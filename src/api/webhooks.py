"""Webhook endpoint dispatch controls."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse


router = APIRouter(prefix="/workspaces/{workspace_id}/webhooks", tags=["webhooks"])


class EndpointCreate(BaseModel):
    url: str
    events: List[str] = Field(default_factory=list)
    enabled: bool = True
    rate_limit: int = Field(default=10, ge=1, le=1000)
    rate_window_seconds: int = Field(default=60, ge=1, le=3600)


class EndpointUpdate(BaseModel):
    enabled: Optional[bool] = None


class EndpointRotate(BaseModel):
    url: str


class FanoutRequest(BaseModel):
    event_id: str = Field(min_length=1)
    event_type: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    events: List[str]
    enabled: bool
    rate_limit: int
    rate_window_seconds: int
    generation: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class DeliveryRecord:
    id: str
    workspace_id: str
    endpoint_id: str
    event_id: str
    event_type: Optional[str]
    status: str
    reason: Optional[str]
    created_at: float = field(default_factory=time.time)


class WebhookDispatchController:
    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[Tuple[str, str, int, str], DeliveryRecord] = {}
        self._rate_windows: Dict[Tuple[str, str], List[float]] = {}

    def reset(self) -> None:
        self._endpoints.clear()
        self._deliveries.clear()
        self._rate_windows.clear()

    def register(self, workspace_id: str, request: EndpointCreate) -> Dict[str, Any]:
        self._validate_url(request.url)
        endpoint = WebhookEndpoint(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            url=request.url,
            events=list(dict.fromkeys(request.events)),
            enabled=request.enabled,
            rate_limit=request.rate_limit,
            rate_window_seconds=request.rate_window_seconds,
        )
        self._endpoints[endpoint.id] = endpoint
        return self._public_endpoint(endpoint)

    def update(
        self, workspace_id: str, endpoint_id: str, request: EndpointUpdate
    ) -> Dict[str, Any]:
        endpoint = self._endpoint_for_workspace(workspace_id, endpoint_id)
        if request.enabled is not None:
            endpoint.enabled = request.enabled
            endpoint.updated_at = time.time()
        return self._public_endpoint(endpoint)

    def rotate(
        self, workspace_id: str, endpoint_id: str, request: EndpointRotate
    ) -> Dict[str, Any]:
        self._validate_url(request.url)
        endpoint = self._endpoint_for_workspace(workspace_id, endpoint_id)
        endpoint.url = request.url
        endpoint.generation += 1
        endpoint.enabled = True
        endpoint.updated_at = time.time()
        self._rate_windows.pop((workspace_id, endpoint_id), None)
        return self._public_endpoint(endpoint)

    def fanout(
        self, workspace_id: str, endpoint_id: str, request: FanoutRequest
    ) -> JSONResponse:
        endpoint = self._endpoint_for_workspace(workspace_id, endpoint_id)
        if not endpoint.enabled:
            return self._rejected(status.HTTP_409_CONFLICT, "endpoint_disabled")
        if (
            endpoint.events
            and request.event_type
            and request.event_type not in endpoint.events
        ):
            return self._rejected(status.HTTP_409_CONFLICT, "event_not_allowed")

        delivery_key = (
            workspace_id,
            endpoint_id,
            endpoint.generation,
            request.event_id,
        )
        existing = self._deliveries.get(delivery_key)
        if existing:
            body = self._public_delivery(existing)
            body["idempotent"] = True
            return JSONResponse(status_code=status.HTTP_200_OK, content=body)

        retry_after = self._retry_after(endpoint)
        if retry_after is not None:
            return self._rejected(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate_limited",
                retry_after,
            )

        record = DeliveryRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            endpoint_id=endpoint_id,
            event_id=request.event_id,
            event_type=request.event_type,
            status="queued",
            reason=None,
        )
        self._deliveries[delivery_key] = record
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=self._public_delivery(record),
        )

    def _endpoint_for_workspace(
        self, workspace_id: str, endpoint_id: str
    ) -> WebhookEndpoint:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint or endpoint.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Webhook endpoint not found")
        return endpoint

    def _retry_after(self, endpoint: WebhookEndpoint) -> Optional[int]:
        key = (endpoint.workspace_id, endpoint.id)
        now = time.time()
        window = self._rate_windows.setdefault(key, [])
        window[:] = [
            seen_at
            for seen_at in window
            if now - seen_at < endpoint.rate_window_seconds
        ]
        if len(window) >= endpoint.rate_limit:
            oldest = min(window)
            return max(1, int(endpoint.rate_window_seconds - (now - oldest)))
        window.append(now)
        return None

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(
                status_code=422,
                detail="Webhook endpoint URL must be http or https",
            )

    @staticmethod
    def _public_endpoint(endpoint: WebhookEndpoint) -> Dict[str, Any]:
        return {
            "id": endpoint.id,
            "workspace_id": endpoint.workspace_id,
            "url": endpoint.url,
            "events": endpoint.events,
            "enabled": endpoint.enabled,
            "rate_limit": endpoint.rate_limit,
            "rate_window_seconds": endpoint.rate_window_seconds,
        }

    @staticmethod
    def _public_delivery(record: DeliveryRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "workspace_id": record.workspace_id,
            "endpoint_id": record.endpoint_id,
            "event_id": record.event_id,
            "event_type": record.event_type,
            "status": record.status,
        }

    @staticmethod
    def _rejected(
        status_code: int, reason: str, retry_after: Optional[int] = None
    ) -> JSONResponse:
        body: Dict[str, Any] = {"status": "rejected", "reason": reason}
        if retry_after is not None:
            body["retry_after"] = retry_after
        return JSONResponse(status_code=status_code, content=body)


webhook_dispatch = WebhookDispatchController()


@router.post("/endpoints", status_code=status.HTTP_201_CREATED)
async def register_endpoint(workspace_id: str, request: EndpointCreate):
    return webhook_dispatch.register(workspace_id, request)


@router.patch("/endpoints/{endpoint_id}")
async def update_endpoint(workspace_id: str, endpoint_id: str, request: EndpointUpdate):
    return webhook_dispatch.update(workspace_id, endpoint_id, request)


@router.post("/endpoints/{endpoint_id}/rotate")
async def rotate_endpoint(workspace_id: str, endpoint_id: str, request: EndpointRotate):
    return webhook_dispatch.rotate(workspace_id, endpoint_id, request)


@router.post("/endpoints/{endpoint_id}/fanout")
async def fanout_endpoint(workspace_id: str, endpoint_id: str, request: FanoutRequest):
    return webhook_dispatch.fanout(workspace_id, endpoint_id, request)
