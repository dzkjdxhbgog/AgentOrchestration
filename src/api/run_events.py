"""Run event stream service with bounded pagination."""

from typing import Any, Dict, List, Optional


MAX_RUN_EVENT_WINDOW = 1000
MAX_RUN_EVENT_LIMIT = 100
DEFAULT_RUN_EVENT_LIMIT = 100


class RunEventsPaginationError(ValueError):
    """Raised when run event pagination parameters are malformed or unsafe."""


class RunEventStreamService:
    def __init__(self, max_window: int = MAX_RUN_EVENT_WINDOW):
        self.max_window = max_window
        self._events: Dict[str, List[Dict[str, Any]]] = {}
        self.lookup_count = 0

    def reset(self) -> None:
        self._events.clear()
        self.lookup_count = 0

    def add_event(self, run_id: str, event: Dict[str, Any]) -> None:
        self._events.setdefault(run_id, []).append(dict(event))

    def list_events(
        self,
        run_id: str,
        limit: Optional[str] = None,
        offset: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_limit, parsed_offset = self._validate_window(limit, offset)

        self.lookup_count += 1
        events = self._events.get(run_id, [])
        page = events[parsed_offset:parsed_offset + parsed_limit]
        return {
            "run_id": run_id,
            "events": page,
            "pagination": {
                "limit": parsed_limit,
                "offset": parsed_offset,
                "count": len(page),
                "total": len(events),
            },
        }

    def _validate_window(
        self,
        limit: Optional[str],
        offset: Optional[str],
    ) -> tuple[int, int]:
        parsed_limit = self._parse_int("limit", limit, DEFAULT_RUN_EVENT_LIMIT)
        parsed_offset = self._parse_int("offset", offset, 0)

        if parsed_limit < 1:
            raise RunEventsPaginationError("limit must be at least 1")
        if parsed_limit > MAX_RUN_EVENT_LIMIT:
            raise RunEventsPaginationError(
                f"limit must not exceed {MAX_RUN_EVENT_LIMIT}"
            )
        if parsed_offset < 0:
            raise RunEventsPaginationError("offset must be non-negative")
        if parsed_offset + parsed_limit > self.max_window:
            raise RunEventsPaginationError(
                f"pagination window must not exceed {self.max_window}"
            )
        return parsed_limit, parsed_offset

    @staticmethod
    def _parse_int(name: str, value: Optional[str], default: int) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RunEventsPaginationError(
                f"{name} must be an integer"
            ) from exc
