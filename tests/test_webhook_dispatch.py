from fastapi.testclient import TestClient

from src.api.server import create_app
from src.api.webhooks import webhook_dispatch


class TestWebhookDispatch:
    def setup_method(self):
        webhook_dispatch.reset()
        self.client = TestClient(create_app())
        self.headers = {"Authorization": "Bearer test-token"}

    def register_endpoint(self, workspace="workspace-a", **overrides):
        payload = {
            "url": "https://example.com/webhook",
            "events": ["agent.created"],
            "rate_limit": 2,
            "rate_window_seconds": 60,
        }
        payload.update(overrides)
        response = self.client.post(
            f"/api/v2/workspaces/{workspace}/webhooks/endpoints",
            json=payload,
            headers=self.headers,
        )
        assert response.status_code == 201
        return response.json()

    def fanout(
        self, workspace, endpoint_id, event_id, event_type="agent.created", payload=None
    ):
        return self.client.post(
            f"/api/v2/workspaces/{workspace}/webhooks/endpoints/{endpoint_id}/fanout",
            json={
                "event_id": event_id,
                "event_type": event_type,
                "payload": payload or {"secret": "must-not-be-returned", "value": 1},
            },
            headers=self.headers,
        )

    def test_valid_delivery_returns_minimal_public_record(self):
        endpoint = self.register_endpoint()

        response = self.fanout("workspace-a", endpoint["id"], "event-1")

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["workspace_id"] == "workspace-a"
        assert body["endpoint_id"] == endpoint["id"]
        assert body["event_id"] == "event-1"
        assert "payload" not in body
        assert "url" not in body
        assert "generation" not in body

    def test_rejects_new_fanout_before_work_when_endpoint_rate_limit_is_exhausted(self):
        endpoint = self.register_endpoint(rate_limit=1)

        first = self.fanout("workspace-a", endpoint["id"], "event-1")
        second = self.fanout("workspace-a", endpoint["id"], "event-2")

        assert first.status_code == 202
        assert second.status_code == 429
        body = second.json()
        assert body["status"] == "rejected"
        assert body["reason"] == "rate_limited"
        assert body["retry_after"] > 0

    def test_retries_are_idempotent_even_after_rate_limit_is_full(self):
        endpoint = self.register_endpoint(rate_limit=1)

        first = self.fanout("workspace-a", endpoint["id"], "event-1")
        retry = self.fanout("workspace-a", endpoint["id"], "event-1")

        assert first.status_code == 202
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]
        assert retry.json()["idempotent"] is True

    def test_workspace_isolation_hides_foreign_endpoint(self):
        endpoint = self.register_endpoint(workspace="workspace-a")

        response = self.fanout("workspace-b", endpoint["id"], "event-1")

        assert response.status_code == 404

    def test_disabled_endpoint_rejects_and_rotation_reenables_new_generation(self):
        endpoint = self.register_endpoint()
        first = self.fanout("workspace-a", endpoint["id"], "event-1")

        disabled = self.client.patch(
            "/api/v2/workspaces/workspace-a/webhooks/endpoints/"
            f"{endpoint['id']}",
            json={"enabled": False},
            headers=self.headers,
        )
        rejected = self.fanout("workspace-a", endpoint["id"], "event-2")
        rotated = self.client.post(
            f"/api/v2/workspaces/workspace-a/webhooks/endpoints/{endpoint['id']}/rotate",
            json={"url": "https://example.com/rotated"},
            headers=self.headers,
        )
        after_rotate = self.fanout("workspace-a", endpoint["id"], "event-1")

        assert first.status_code == 202
        assert disabled.status_code == 200
        assert rejected.status_code == 409
        assert rejected.json()["reason"] == "endpoint_disabled"
        assert rotated.status_code == 200
        assert after_rotate.status_code == 202
        assert after_rotate.json()["id"] != first.json()["id"]
