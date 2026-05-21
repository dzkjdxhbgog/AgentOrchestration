from fastapi.testclient import TestClient

from src.api.server import create_app


class TestProtectedRouteAuthorization:
    def setup_method(self):
        self.client = TestClient(create_app())

    def test_anonymous_principal_is_denied_before_route_handling(self):
        response = self.client.get("/api/v2/agents")

        assert response.status_code == 401
        assert response.text == "anonymous"

    def test_malformed_token_is_denied(self):
        response = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer not-registered"},
        )

        assert response.status_code == 401
        assert response.text == "malformed_or_unknown"

    def test_stale_token_is_denied(self):
        response = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer stale-token"},
        )

        assert response.status_code == 401
        assert response.text == "stale_or_revoked"

    def test_revoked_token_is_denied_on_trailing_slash_route(self):
        response = self.client.get(
            "/api/v2/agents/",
            headers={"Authorization": "Bearer revoked-token"},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert response.text == "stale_or_revoked"

    def test_insufficient_scope_is_denied_before_mutation(self):
        response = self.client.post(
            "/api/v2/agents",
            params={"name": "worker-a", "agent_type": "worker.processor"},
            headers={"Authorization": "Bearer read-token"},
        )

        assert response.status_code == 403
        assert response.text == "insufficient_scope"

    def test_insufficient_workspace_role_is_denied_before_route_handling(self):
        response = self.client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer no-role-token"},
        )

        assert response.status_code == 403
        assert response.text == "insufficient_role"

    def test_stale_browser_session_is_denied(self):
        self.client.cookies.set("ao_session", "stale-session")
        response = self.client.get("/api/v2/agents")

        assert response.status_code == 401
        assert response.text == "stale_or_revoked"

    def test_revoked_browser_session_is_denied_on_trailing_slash_route(self):
        self.client.cookies.set("ao_session", "revoked-session")
        response = self.client.get(
            "/api/v2/agents/",
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert response.text == "stale_or_revoked"

    def test_authorized_token_client_can_complete_same_workflow(self):
        response = self.client.post(
            "/api/v2/agents",
            params={"name": "worker-a", "agent_type": "worker.processor"},
            headers={"Authorization": "Bearer valid-token"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "registered"

    def test_authorized_browser_session_can_access_protected_route(self):
        self.client.cookies.set("ao_session", "valid-session")
        response = self.client.get("/api/v2/agents")

        assert response.status_code == 200
        assert "agents" in response.json()
