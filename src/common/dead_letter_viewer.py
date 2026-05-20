"""Dead-letter queue inspection helpers."""

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional


SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "email",
    "password",
    "secret",
    "ssn",
    "token",
}


class DeadLetterQueueViewer:
    def __init__(self):
        self._audit_records: List[Dict[str, str]] = []

    def list_messages(self, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.summarize(message) for message in messages]

    def summarize(self, message: Dict[str, Any]) -> Dict[str, Any]:
        payload = message.get("payload", {})
        return {
            "id": message.get("id"),
            "task_type": message.get("type"),
            "failed_at": message.get("failed_at"),
            "attempts": message.get("retries", message.get("attempts", 0)),
            "error": message.get("error"),
            "payload_redacted": True,
            "payload_summary": self._redact(payload),
        }

    def raw_payload(self, message: Dict[str, Any], actor: str, reason: str) -> Dict[str, Any]:
        if not actor or not actor.strip():
            raise ValueError("actor is required for raw dead-letter access")
        if not reason or not reason.strip():
            raise ValueError("reason is required for raw dead-letter access")

        self._audit_records.append(
            {
                "event": "dead_letter_raw_payload_accessed",
                "message_id": str(message.get("id")),
                "actor": actor.strip(),
                "reason": reason.strip(),
            }
        )
        return deepcopy(message.get("payload", {}))

    def audit_records(self) -> List[Dict[str, str]]:
        return list(self._audit_records)

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._redact_value(key, child) for key, child in value.items()}
        if isinstance(value, list):
            return [self._redact(child) for child in value]
        if isinstance(value, str):
            return self._summarize_string(value)
        return value

    def _redact_value(self, key: str, value: Any) -> Any:
        if self._is_sensitive_key(key):
            return "[REDACTED]"
        return self._redact(value)

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return any(name in normalized for name in SENSITIVE_FIELD_NAMES)

    def _summarize_string(self, value: str) -> str:
        if len(value) <= 16:
            return value
        return f"{value[:8]}...[{len(value)} chars]"

