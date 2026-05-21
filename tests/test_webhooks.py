import pytest

from src.orchestrator.webhooks import (
    REDACTED,
    WebhookError,
    WebhookRegistry,
    shape_public_webhook_payload,
)


def test_public_payload_removes_internal_run_metadata_and_redacts_secrets():
    shaped = shape_public_webhook_payload(
        {
            "event": "run.completed",
            "run_id": "public-run-1",
            "run_metadata": {"worker_id": "worker-7", "lease_id": "lease-9"},
            "nested": {
                "internal_trace": "trace-1",
                "authorization": "Bearer secret",
                "items": [{"token": "abc"}, {"value": 3}],
            },
        }
    )

    assert shaped == {
        "event": "run.completed",
        "run_id": "public-run-1",
        "nested": {
            "authorization": REDACTED,
            "items": [{"token": REDACTED}, {"value": 3}],
        },
    }


def test_valid_delivery_and_callback_store_only_shaped_payloads():
    registry = WebhookRegistry()
    endpoint = registry.register_endpoint("workspace-a", "https://example.com/hooks")

    delivery = registry.deliver(
        endpoint.id,
        "workspace-a",
        "event-1",
        {
            "type": "task.finished",
            "run_metadata": {"attempt": 2, "trace_id": "trace-1"},
            "secret": "not-public",
        },
    )
    callback = registry.record_callback(
        delivery.id,
        {
            "status": "ok",
            "worker_id": "worker-1",
            "api_key": "private",
        },
    )

    assert delivery.payload == {"type": "task.finished", "secret": REDACTED}
    assert callback.payload == {"status": "ok", "api_key": REDACTED}


def test_delivery_rejects_disabled_endpoint_before_persisting_records():
    registry = WebhookRegistry()
    endpoint = registry.register_endpoint("workspace-a", "https://example.com/hooks")
    registry.disable_endpoint(endpoint.id, "workspace-a")

    with pytest.raises(WebhookError):
        registry.deliver(endpoint.id, "workspace-a", "event-1", {"type": "task.finished"})

    assert registry.deliveries == {}
    assert registry.callbacks == {}


def test_delivery_rejects_cross_workspace_access_before_persisting_records():
    registry = WebhookRegistry()
    endpoint = registry.register_endpoint("workspace-a", "https://example.com/hooks")

    with pytest.raises(WebhookError):
        registry.deliver(endpoint.id, "workspace-b", "event-1", {"type": "task.finished"})

    assert registry.deliveries == {}


def test_delivery_retries_and_callbacks_are_idempotent():
    registry = WebhookRegistry()
    endpoint = registry.register_endpoint("workspace-a", "https://example.com/hooks")

    first = registry.deliver(endpoint.id, "workspace-a", "event-1", {"type": "task.finished"})
    retry = registry.deliver(endpoint.id, "workspace-a", "event-1", {"type": "task.finished"})
    first_callback = registry.record_callback(first.id, {"status": "ok"})
    second_callback = registry.record_callback(first.id, {"status": "duplicate"})

    assert retry is first
    assert first_callback is second_callback
    assert len(registry.deliveries) == 1
    assert len(registry.callbacks) == 1


def test_rotated_endpoint_uses_new_delivery_idempotency_scope():
    registry = WebhookRegistry()
    endpoint = registry.register_endpoint("workspace-a", "https://example.com/hooks")
    first = registry.deliver(endpoint.id, "workspace-a", "event-1", {"type": "task.finished"})

    registry.rotate_endpoint(endpoint.id, "workspace-a", "https://example.com/new-hooks")
    after_rotation = registry.deliver(
        endpoint.id,
        "workspace-a",
        "event-1",
        {"type": "task.finished"},
    )
    retry_after_rotation = registry.deliver(
        endpoint.id,
        "workspace-a",
        "event-1",
        {"type": "task.finished"},
    )

    assert after_rotation is retry_after_rotation
    assert first.id != after_rotation.id
    assert first.endpoint_version == 1
    assert after_rotation.endpoint_version == 2
    assert len(registry.deliveries) == 2


def test_endpoint_registration_requires_https_urls():
    registry = WebhookRegistry()

    with pytest.raises(WebhookError):
        registry.register_endpoint("workspace-a", "http://example.com/hooks")
