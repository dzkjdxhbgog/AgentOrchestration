"""Plugin runtime guard for manifest validation and hook loading."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

HookMap = Mapping[str, List[Callable]]


class PluginManifestState(Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    LOADING = "loading"
    REJECTED = "rejected"
    LOADED = "loaded"
    FAILED = "failed"


@dataclass(frozen=True)
class PluginTerminalOutcome:
    plugin_id: str
    state: PluginManifestState
    error: Optional[str]
    timestamp: float


class PluginManifestError(ValueError):
    """Raised when a plugin manifest cannot be safely loaded."""


class PluginRuntime:
    """Validates plugin manifests before any hook-loading side effects run."""

    REQUIRED_FIELDS = ("name", "version", "hooks")

    def __init__(
        self,
        allowed_hook_events: Optional[Iterable[str]] = None,
        max_validation_retries: int = 3,
    ):
        self.allowed_hook_events = set(
            allowed_hook_events
            or ("pre_execute", "post_execute", "on_error", "on_complete")
        )
        self.max_validation_retries = max_validation_retries
        self._lock = threading.RLock()
        self._states: Dict[str, PluginManifestState] = {}
        self._attempts: Dict[str, int] = {}
        self._loaded_hooks: Dict[str, Dict[str, List[Callable]]] = {}
        self._terminal_outcomes: Dict[str, PluginTerminalOutcome] = {}

    def load_manifest(
        self,
        manifest: Mapping[str, Any],
        hook_loader: Optional[Callable[[Mapping[str, Any]], HookMap]] = None,
    ) -> PluginTerminalOutcome:
        plugin_id = self._plugin_id(manifest)
        with self._lock:
            existing = self._terminal_outcomes.get(plugin_id)
            if existing:
                return existing

            self._attempts[plugin_id] = self._attempts.get(plugin_id, 0) + 1
            if self._attempts[plugin_id] > self.max_validation_retries:
                return self._record_terminal(
                    plugin_id,
                    PluginManifestState.FAILED,
                    "manifest validation retry limit exceeded",
                )

            try:
                validated = self.validate_manifest(manifest)
            except PluginManifestError as exc:
                return self._record_terminal(
                    plugin_id,
                    PluginManifestState.REJECTED,
                    str(exc),
                )

            self._states[plugin_id] = PluginManifestState.VALIDATED
            self._states[plugin_id] = PluginManifestState.LOADING

            loaded_hooks: Mapping[str, List[Callable]] = {}
            try:
                if hook_loader:
                    loaded_hooks = hook_loader(validated)
                self._validate_loaded_hooks(plugin_id, loaded_hooks)
            except Exception as exc:
                return self._record_terminal(
                    plugin_id,
                    PluginManifestState.FAILED,
                    str(exc),
                )

            self._loaded_hooks[plugin_id] = {
                event: list(callbacks)
                for event, callbacks in loaded_hooks.items()
            }
            return self._record_terminal(
                plugin_id,
                PluginManifestState.LOADED,
                None,
            )

    def validate_manifest(
        self,
        manifest: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if not isinstance(manifest, Mapping):
            raise PluginManifestError("manifest must be an object")

        missing = [
            field
            for field in self.REQUIRED_FIELDS
            if field not in manifest
        ]
        if missing:
            raise PluginManifestError(
                "manifest missing required fields: "
                f"{', '.join(missing)}"
            )

        name = manifest["name"]
        version = manifest["version"]
        hooks = manifest["hooks"]

        if not isinstance(name, str) or not name.strip():
            raise PluginManifestError(
                "manifest name must be a non-empty string"
            )
        if not isinstance(version, str) or not version.strip():
            raise PluginManifestError(
                "manifest version must be a non-empty string"
            )
        if not isinstance(hooks, Mapping):
            raise PluginManifestError("manifest hooks must be an object")

        for event, hook_specs in hooks.items():
            if event not in self.allowed_hook_events:
                raise PluginManifestError(f"unsupported hook event: {event}")
            if not isinstance(hook_specs, list):
                raise PluginManifestError(
                    f"hook list for {event} must be a list"
                )
            for hook_spec in hook_specs:
                if not isinstance(hook_spec, str) or not hook_spec.strip():
                    raise PluginManifestError(
                        f"hook spec for {event} must be a non-empty string"
                    )

        return manifest

    def get_state(self, manifest: Mapping[str, Any]) -> PluginManifestState:
        plugin_id = self._plugin_id(manifest)
        with self._lock:
            return self._states.get(plugin_id, PluginManifestState.PENDING)

    def get_terminal_outcome(
        self,
        manifest: Mapping[str, Any],
    ) -> Optional[PluginTerminalOutcome]:
        plugin_id = self._plugin_id(manifest)
        with self._lock:
            return self._terminal_outcomes.get(plugin_id)

    def get_loaded_hooks(
        self,
        manifest: Mapping[str, Any],
    ) -> Dict[str, List[Callable]]:
        plugin_id = self._plugin_id(manifest)
        with self._lock:
            hooks = self._loaded_hooks.get(plugin_id, {})
            return {
                event: list(callbacks)
                for event, callbacks in hooks.items()
            }

    def _validate_loaded_hooks(
        self,
        plugin_id: str,
        loaded_hooks: HookMap,
    ) -> None:
        if not isinstance(loaded_hooks, Mapping):
            raise PluginManifestError(
                f"loaded hooks for {plugin_id} must be an object"
            )
        for event, callbacks in loaded_hooks.items():
            if event not in self.allowed_hook_events:
                raise PluginManifestError(
                    f"unsupported loaded hook event: {event}"
                )
            if not isinstance(callbacks, list):
                raise PluginManifestError(
                    f"loaded hooks for {event} must be a list"
                )
            if any(not callable(callback) for callback in callbacks):
                raise PluginManifestError(
                    f"loaded hooks for {event} must be callable"
                )

    def _record_terminal(
        self,
        plugin_id: str,
        state: PluginManifestState,
        error: Optional[str],
    ) -> PluginTerminalOutcome:
        self._states[plugin_id] = state
        outcome = PluginTerminalOutcome(
            plugin_id=plugin_id,
            state=state,
            error=error,
            timestamp=time.time(),
        )
        self._terminal_outcomes[plugin_id] = outcome
        return outcome

    def _plugin_id(self, manifest: Mapping[str, Any]) -> str:
        if isinstance(manifest, Mapping):
            name = manifest.get("name", "<unknown>")
            version = manifest.get("version", "<unknown>")
            return f"{name}:{version}"
        return "<invalid>:<invalid>"
