"""Webhook endpoint registration and public payload shaping."""

from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)

REDACTED = "[redacted]"

DROP_KEYS = {
    "_internal",
    "attempt",
    "debug",
    "lease_id",
    "retry",
    "retry_count",
    "run_metadata",
    "runtime",
    "scheduler_state",
    "stack",
    "trace",
    "trace_id",
    "worker_id",
}

SECRET_KEY_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)


class WebhookError(ValueError):
    """Raised when a webhook operation is invalid."""


@dataclass
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    active: bool = True
    version: int = 1


@dataclass
class WebhookDelivery:
    id: str
    endpoint_id: str
    workspace_id: str
    endpoint_version: int
    event_id: str
    payload: Dict[str, Any]
    status: str = "queued"


@dataclass
class WebhookCallback:
    id: str
    delivery_id: str
    payload: Dict[str, Any]


def _normalized_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _should_drop_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return (
        normalized in DROP_KEYS
        or normalized.startswith("internal_")
        or normalized.endswith("_internal")
        or normalized.startswith("_")
    )


def _should_redact_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in SECRET_KEY_PARTS)


def shape_public_webhook_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy safe for public webhook delivery and persistence."""

    return _sanitize_value(payload)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        shaped: Dict[str, Any] = {}
        for key, nested in value.items():
            if _should_drop_key(key):
                continue
            if _should_redact_key(key):
                shaped[str(key)] = REDACTED
                continue
            shaped[str(key)] = _sanitize_value(nested)
        return shaped

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]

    return copy.deepcopy(value)


class WebhookRegistry:
    """Stores webhook endpoints and idempotent delivery records in-process."""

    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[str, WebhookDelivery] = {}
        self._callbacks: Dict[str, WebhookCallback] = {}
        self._idempotency: Dict[Tuple[str, int, str], str] = {}
        self._audit_events: List[Dict[str, Any]] = []

    @property
    def deliveries(self) -> Dict[str, WebhookDelivery]:
        return self._deliveries

    @property
    def callbacks(self) -> Dict[str, WebhookCallback]:
        return self._callbacks

    @property
    def audit_events(self) -> List[Dict[str, Any]]:
        return self._audit_events

    def register_endpoint(
        self,
        workspace_id: str,
        url: str,
        endpoint_id: Optional[str] = None,
    ) -> WebhookEndpoint:
        self._validate_workspace(workspace_id)
        self._validate_endpoint_url(url)
        endpoint = WebhookEndpoint(
            id=endpoint_id or str(uuid4()),
            workspace_id=workspace_id,
            url=url,
        )
        self._endpoints[endpoint.id] = endpoint
        self._record_audit("webhook_endpoint_registered", endpoint, None)
        return endpoint

    def disable_endpoint(self, endpoint_id: str, workspace_id: str) -> WebhookEndpoint:
        endpoint = self._require_endpoint(endpoint_id, workspace_id)
        endpoint.active = False
        self._record_audit("webhook_endpoint_disabled", endpoint, None)
        return endpoint

    def rotate_endpoint(self, endpoint_id: str, workspace_id: str, url: str) -> WebhookEndpoint:
        endpoint = self._require_endpoint(endpoint_id, workspace_id)
        self._validate_endpoint_url(url)
        endpoint.url = url
        endpoint.version += 1
        endpoint.active = True
        self._record_audit("webhook_endpoint_rotated", endpoint, None)
        return endpoint

    def deliver(
        self,
        endpoint_id: str,
        workspace_id: str,
        event_id: str,
        payload: Mapping[str, Any],
    ) -> WebhookDelivery:
        endpoint = self._require_endpoint(endpoint_id, workspace_id)
        self._validate_event_id(event_id)
        if not endpoint.active:
            self._record_audit("webhook_delivery_rejected", endpoint, {"reason": "disabled_endpoint"})
            raise WebhookError("Webhook endpoint is disabled")

        idempotency_key = (endpoint.id, endpoint.version, event_id)
        existing_delivery_id = self._idempotency.get(idempotency_key)
        if existing_delivery_id:
            return self._deliveries[existing_delivery_id]

        shaped_payload = shape_public_webhook_payload(payload)
        delivery = WebhookDelivery(
            id=str(uuid4()),
            endpoint_id=endpoint.id,
            workspace_id=workspace_id,
            endpoint_version=endpoint.version,
            event_id=event_id,
            payload=shaped_payload,
        )
        self._deliveries[delivery.id] = delivery
        self._idempotency[idempotency_key] = delivery.id
        self._record_audit("webhook_delivery_queued", endpoint, {"event_id": event_id})
        return delivery

    def record_callback(self, delivery_id: str, payload: Mapping[str, Any]) -> WebhookCallback:
        delivery = self._deliveries.get(delivery_id)
        if delivery is None:
            raise WebhookError("Unknown webhook delivery")
        existing = self._callbacks.get(delivery_id)
        if existing:
            return existing

        callback = WebhookCallback(
            id=str(uuid4()),
            delivery_id=delivery_id,
            payload=shape_public_webhook_payload(payload),
        )
        self._callbacks[delivery_id] = callback
        return callback

    def _require_endpoint(self, endpoint_id: str, workspace_id: str) -> WebhookEndpoint:
        self._validate_workspace(workspace_id)
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise WebhookError("Unknown webhook endpoint")
        if endpoint.workspace_id != workspace_id:
            raise WebhookError("Webhook endpoint does not belong to this workspace")
        return endpoint

    @staticmethod
    def _validate_workspace(workspace_id: str) -> None:
        if not workspace_id:
            raise WebhookError("workspace_id is required")

    @staticmethod
    def _validate_event_id(event_id: str) -> None:
        if not event_id:
            raise WebhookError("event_id is required")

    @staticmethod
    def _validate_endpoint_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise WebhookError("Webhook endpoints must use https URLs")

    def _record_audit(
        self,
        action: str,
        endpoint: WebhookEndpoint,
        details: Optional[MutableMapping[str, Any]],
    ) -> None:
        event = {
            "action": action,
            "endpoint_hash": _hash_identifier(endpoint.id),
            "workspace_hash": _hash_identifier(endpoint.workspace_id),
            "endpoint_version": endpoint.version,
            "details": shape_public_webhook_payload(details or {}),
        }
        self._audit_events.append(event)
        logger.info("webhook audit event recorded", extra={"webhook_audit": event})


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
