"""Deployment gate for database migrations."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional


MigrationHandler = Callable[[], object]


@dataclass(frozen=True)
class MigrationSpec:
    """Metadata required before a migration can participate in rollout."""

    name: str
    owner: str
    backward_compatible: bool
    required_before_traffic: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("migration name is required")
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise ValueError(f"migration {self.name} must declare an owner")
        if not isinstance(self.backward_compatible, bool):
            raise ValueError(
                f"migration {self.name} must declare backward_compatible as a boolean"
            )
        if not isinstance(self.required_before_traffic, bool):
            raise ValueError(
                f"migration {self.name} must declare required_before_traffic as a boolean"
            )


@dataclass(frozen=True)
class MigrationResult:
    name: str
    status: str
    error: Optional[str] = None


@dataclass(frozen=True)
class MigrationGateResult:
    rollout_allowed: bool
    prior_version_serving: bool
    traffic_shift_started: bool
    migration_results: List[MigrationResult] = field(default_factory=list)
    compatibility_errors: List[str] = field(default_factory=list)


class MigrationRolloutGate:
    """Runs migration checks before any application traffic shift."""

    def __init__(
        self,
        migrations: Iterable[MigrationSpec],
        handlers: Optional[Dict[str, MigrationHandler]] = None,
    ):
        self._migrations = list(migrations)
        self._handlers = handlers or {}
        if not self._migrations:
            raise ValueError("at least one migration is required")

    def check_release_compatibility(
        self, require_backward_compatible: bool = True
    ) -> List[str]:
        errors: List[str] = []
        seen = set()
        for migration in self._migrations:
            if migration.name in seen:
                errors.append(f"{migration.name}: duplicate migration")
            seen.add(migration.name)
            if not migration.required_before_traffic:
                errors.append(f"{migration.name}: must run before traffic shift")
            if require_backward_compatible and not migration.backward_compatible:
                errors.append(f"{migration.name}: not backward compatible")
        return errors

    def run_before_traffic_shift(
        self,
        traffic_shift: Optional[Callable[[], object]] = None,
        require_backward_compatible: bool = True,
    ) -> MigrationGateResult:
        compatibility_errors = self.check_release_compatibility(
            require_backward_compatible=require_backward_compatible
        )
        if compatibility_errors:
            return MigrationGateResult(
                rollout_allowed=False,
                prior_version_serving=True,
                traffic_shift_started=False,
                compatibility_errors=compatibility_errors,
            )

        results: List[MigrationResult] = []
        for migration in self._migrations:
            handler = self._handlers.get(migration.name)
            if handler is None:
                results.append(
                    MigrationResult(migration.name, "failed", "missing migration handler")
                )
                return self._blocked(results)

            try:
                handler_result = handler()
            except Exception as exc:
                results.append(MigrationResult(migration.name, "failed", type(exc).__name__))
                return self._blocked(results)

            if handler_result is False:
                results.append(MigrationResult(migration.name, "failed", "handler returned false"))
                return self._blocked(results)

            results.append(MigrationResult(migration.name, "succeeded"))

        if traffic_shift is not None:
            traffic_shift()

        return MigrationGateResult(
            rollout_allowed=True,
            prior_version_serving=False,
            traffic_shift_started=traffic_shift is not None,
            migration_results=results,
        )

    @staticmethod
    def _blocked(results: List[MigrationResult]) -> MigrationGateResult:
        return MigrationGateResult(
            rollout_allowed=False,
            prior_version_serving=True,
            traffic_shift_started=False,
            migration_results=results,
        )


def load_migration_manifest(path: str) -> List[MigrationSpec]:
    data = json.loads(Path(path).read_text())
    migrations = data.get("migrations")
    if not isinstance(migrations, list):
        raise ValueError("migration manifest must include a migrations list")

    return [
        MigrationSpec(
            name=item.get("name"),
            owner=item.get("owner"),
            backward_compatible=item.get("backward_compatible"),
            required_before_traffic=item.get("required_before_traffic", True),
        )
        for item in migrations
    ]
