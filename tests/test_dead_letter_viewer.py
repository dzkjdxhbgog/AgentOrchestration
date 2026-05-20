import pytest

from src.common.dead_letter_viewer import DeadLetterQueueViewer


def test_dead_letter_view_defaults_to_redacted_summary():
    viewer = DeadLetterQueueViewer()
    messages = [
        {
            "id": "task-1",
            "type": "email.delivery",
            "retries": 3,
            "failed_at": "2026-05-20T01:20:00Z",
            "error": "handler failed",
            "payload": {
                "recipient_email": "user@example.com",
                "api_key": "sk-live-secret",
                "body": "customer message with debugging details",
                "metadata": {"token": "session-token"},
            },
        }
    ]

    summary = viewer.list_messages(messages)[0]

    assert summary["payload_redacted"] is True
    assert summary["payload_summary"]["recipient_email"] == "[REDACTED]"
    assert summary["payload_summary"]["api_key"] == "[REDACTED]"
    assert summary["payload_summary"]["metadata"]["token"] == "[REDACTED]"
    assert "customer message with debugging details" not in str(summary)
    assert summary["payload_summary"]["body"] == "customer...[39 chars]"


def test_raw_dead_letter_access_requires_audited_actor_and_reason():
    viewer = DeadLetterQueueViewer()
    message = {
        "id": "task-2",
        "payload": {"secret": "raw-secret", "customer_id": "cus_123"},
    }

    raw = viewer.raw_payload(message, actor="ops-user", reason="incident-debug")

    assert raw == {"secret": "raw-secret", "customer_id": "cus_123"}
    assert viewer.audit_records() == [
        {
            "event": "dead_letter_raw_payload_accessed",
            "message_id": "task-2",
            "actor": "ops-user",
            "reason": "incident-debug",
        }
    ]


@pytest.mark.parametrize("actor, reason", [("", "debug"), ("ops-user", "")])
def test_raw_dead_letter_access_rejects_missing_audit_context(actor, reason):
    viewer = DeadLetterQueueViewer()

    with pytest.raises(ValueError):
        viewer.raw_payload({"id": "task-3", "payload": {"token": "secret"}}, actor=actor, reason=reason)

