"""Integration endpoint registration service."""

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Dict
from urllib.parse import urlparse
from uuid import uuid4


class UnsafeCallbackUrlError(ValueError):
    """Raised when an integration callback URL is unsafe."""


@dataclass(frozen=True)
class IntegrationEndpoint:
    endpoint_id: str
    name: str
    callback_url: str


class IntegrationEndpointService:
    def __init__(self):
        self._endpoints: Dict[str, IntegrationEndpoint] = {}

    @property
    def endpoint_count(self) -> int:
        return len(self._endpoints)

    def register(self, name: str, callback_url: str) -> IntegrationEndpoint:
        safe_callback_url = validate_callback_url(callback_url)
        endpoint = IntegrationEndpoint(
            endpoint_id=str(uuid4()),
            name=name,
            callback_url=safe_callback_url,
        )
        self._endpoints[endpoint.endpoint_id] = endpoint
        return endpoint


def validate_callback_url(callback_url: str) -> str:
    if not isinstance(callback_url, str):
        raise UnsafeCallbackUrlError("callback_url must be a string")

    candidate = callback_url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme != "https":
        raise UnsafeCallbackUrlError("callback_url must use https")
    if not parsed.hostname:
        raise UnsafeCallbackUrlError("callback_url must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeCallbackUrlError("callback_url must not include credentials")
    if parsed.fragment:
        raise UnsafeCallbackUrlError("callback_url must not include a fragment")

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeCallbackUrlError("callback_url host is not allowed")

    try:
        host_ip = ip_address(hostname)
    except ValueError:
        host_ip = None

    if host_ip and (
        host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_multicast
        or host_ip.is_reserved
        or host_ip.is_unspecified
    ):
        raise UnsafeCallbackUrlError("callback_url IP range is not allowed")

    return candidate


integration_endpoint_service = IntegrationEndpointService()
