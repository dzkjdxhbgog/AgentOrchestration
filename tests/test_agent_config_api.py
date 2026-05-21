from fastapi.testclient import TestClient

from src.api.routes import registry
from src.api.server import create_app


def setup_function():
    registry._agents.clear()
    registry._index.clear()


def test_authorized_agent_config_update_requires_current_etag():
    agent_id = registry.register("test-agent", "worker.processor", {"limit": 1})
    current_etag = registry.get(agent_id)["config_etag"]
    client = TestClient(create_app())

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"limit": 2},
        headers={"Authorization": "Bearer token", "If-Match": current_etag},
    )

    assert response.status_code == 200
    assert response.json()["config"] == {"limit": 2}
    assert response.headers["etag"] != current_etag
    assert registry.get(agent_id)["config"] == {"limit": 2}


def test_unauthorized_agent_config_update_never_mutates_state():
    agent_id = registry.register("test-agent", "worker.processor", {"limit": 1})
    current_etag = registry.get(agent_id)["config_etag"]
    client = TestClient(create_app())

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"limit": 2},
        headers={"If-Match": current_etag},
    )

    assert response.status_code == 401
    assert registry.get(agent_id)["config"] == {"limit": 1}
    assert registry.get(agent_id)["config_etag"] == current_etag


def test_missing_if_match_fails_before_config_mutation():
    agent_id = registry.register("test-agent", "worker.processor", {"limit": 1})
    current_etag = registry.get(agent_id)["config_etag"]
    client = TestClient(create_app())

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"limit": 2},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 428
    assert response.json()["detail"] == "If-Match header is required"
    assert registry.get(agent_id)["config"] == {"limit": 1}
    assert registry.get(agent_id)["config_etag"] == current_etag


def test_malformed_if_match_fails_before_config_mutation():
    agent_id = registry.register("test-agent", "worker.processor", {"limit": 1})
    current_etag = registry.get(agent_id)["config_etag"]
    client = TestClient(create_app())

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"limit": 2},
        headers={"Authorization": "Bearer token", "If-Match": "not-quoted"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "If-Match header is malformed"
    assert registry.get(agent_id)["config"] == {"limit": 1}
    assert registry.get(agent_id)["config_etag"] == current_etag


def test_stale_if_match_fails_without_overwriting_newer_config():
    agent_id = registry.register("test-agent", "worker.processor", {"limit": 1})
    stale_etag = registry.get(agent_id)["config_etag"]
    client = TestClient(create_app())
    first = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"limit": 2},
        headers={"Authorization": "Bearer token", "If-Match": stale_etag},
    )

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"limit": 3},
        headers={"Authorization": "Bearer token", "If-Match": stale_etag},
    )

    assert first.status_code == 200
    assert response.status_code == 412
    assert response.json()["detail"] == "Agent config ETag is stale"
    assert registry.get(agent_id)["config"] == {"limit": 2}
    assert registry.get(agent_id)["config_etag"] == first.headers["etag"]
