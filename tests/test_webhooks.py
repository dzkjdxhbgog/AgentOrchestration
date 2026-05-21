import pytest

from src.orchestrator.webhooks import (
    WebhookDeliveryError,
    WebhookService,
    WebhookValidationError,
)


def test_production_registration_rejects_non_tls_before_persistence():
    service = WebhookService(production=True)

    with pytest.raises(WebhookValidationError, match="HTTPS"):
        service.register_endpoint(
            "workspace-a",
            "endpoint-1",
            "http://example.com/hook",
        )

    assert service.endpoint_count == 0


def test_valid_delivery_sanitizes_payload_and_records_idempotently():
    callbacks = []
    service = WebhookService(
        production=True,
        delivery_callback=callbacks.append,
    )
    service.register_endpoint(
        "workspace-a",
        "endpoint-1",
        "https://example.com/hook",
    )

    record = service.deliver(
        "workspace-a",
        "endpoint-1",
        "event-1",
        {
            "type": "run.completed",
            "trace_id": "internal-trace",
            "_debug": "hidden",
            "internal_metadata": {"node": "worker-1"},
        },
    )
    retry_record = service.retry(
        "workspace-a",
        "endpoint-1",
        "event-1",
        {"type": "run.completed", "trace_id": "second-trace"},
    )

    assert retry_record is record
    assert len(callbacks) == 1
    assert record.status == "delivered"
    assert record.payload == {"type": "run.completed"}
    assert callbacks[0]["payload"] == {"type": "run.completed"}


def test_workspace_isolation_prevents_cross_workspace_delivery():
    callbacks = []
    service = WebhookService(
        production=True,
        delivery_callback=callbacks.append,
    )
    service.register_endpoint(
        "workspace-a",
        "endpoint-1",
        "https://example.com/hook",
    )

    with pytest.raises(WebhookDeliveryError, match="not found"):
        service.deliver(
            "workspace-b",
            "endpoint-1",
            "event-1",
            {"type": "run"},
        )

    assert callbacks == []


def test_disabled_endpoint_rejects_delivery_before_callback():
    callbacks = []
    service = WebhookService(
        production=True,
        delivery_callback=callbacks.append,
    )
    service.register_endpoint(
        "workspace-a",
        "endpoint-1",
        "https://example.com/hook",
    )
    service.disable_endpoint("workspace-a", "endpoint-1")

    with pytest.raises(WebhookDeliveryError, match="disabled"):
        service.deliver(
            "workspace-a",
            "endpoint-1",
            "event-1",
            {"type": "run"},
        )

    assert callbacks == []


def test_rotated_endpoint_rejects_stale_delivery_version():
    callbacks = []
    service = WebhookService(
        production=True,
        delivery_callback=callbacks.append,
    )
    endpoint = service.register_endpoint(
        "workspace-a",
        "endpoint-1",
        "https://example.com/hook",
    )
    rotated = service.rotate_endpoint(
        "workspace-a",
        "endpoint-1",
        "https://hooks.example.com/new",
    )

    with pytest.raises(WebhookDeliveryError, match="rotated"):
        service.deliver(
            "workspace-a",
            "endpoint-1",
            "event-1",
            {"type": "run"},
            endpoint_version=endpoint.version,
        )

    record = service.deliver(
        "workspace-a",
        "endpoint-1",
        "event-1",
        {"type": "run"},
        endpoint_version=rotated.version,
    )

    assert callbacks[0]["url"] == "https://hooks.example.com/new"
    assert record.endpoint_version == rotated.version
