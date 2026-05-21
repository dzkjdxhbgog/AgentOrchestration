from fastapi.testclient import TestClient

from src.api.routes import run_event_service
from src.api.server import create_app


def make_client():
    run_event_service.reset()
    run_event_service.add_event("run-1", {"id": "event-1", "type": "started"})
    run_event_service.add_event(
        "run-1",
        {"id": "event-2", "type": "completed"},
    )
    return TestClient(create_app())


def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_run_events_authorized_request_uses_bounded_page():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=1&offset=1",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["events"] == [
        {"id": "event-2", "type": "completed"}
    ]
    assert response.json()["pagination"] == {
        "limit": 1,
        "offset": 1,
        "count": 1,
        "total": 2,
    }
    assert run_event_service.lookup_count == 1


def test_run_events_unauthorized_request_never_reaches_lookup():
    client = make_client()

    response = client.get("/api/v2/runs/run-1/events?limit=1&offset=0")

    assert response.status_code == 401
    assert run_event_service.lookup_count == 0


def test_run_events_blank_bearer_token_never_reaches_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=1&offset=0",
        headers={"Authorization": "Bearer "},
    )

    assert response.status_code == 401
    assert run_event_service.lookup_count == 0


def test_run_events_rejects_malformed_pagination_before_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=not-a-number&offset=0",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "limit must be an integer"
    assert run_event_service.lookup_count == 0


def test_run_events_rejects_zero_limit_before_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=0&offset=0",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "limit must be at least 1"
    assert run_event_service.lookup_count == 0


def test_run_events_rejects_limit_over_cap_before_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=101&offset=0",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "limit must not exceed 100"
    assert run_event_service.lookup_count == 0


def test_run_events_allows_exact_max_window_boundary():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=100&offset=900",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["events"] == []
    assert response.json()["pagination"] == {
        "limit": 100,
        "offset": 900,
        "count": 0,
        "total": 2,
    }
    assert run_event_service.lookup_count == 1


def test_run_events_rejects_negative_offset_before_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=1&offset=-1",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "offset must be non-negative"
    assert run_event_service.lookup_count == 0


def test_run_events_rejects_blank_offset_before_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=1&offset=",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "offset must be an integer"
    assert run_event_service.lookup_count == 0


def test_run_events_rejects_over_window_pagination_before_lookup():
    client = make_client()

    response = client.get(
        "/api/v2/runs/run-1/events?limit=100&offset=901",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "pagination window must not exceed 1000"
    )
    assert run_event_service.lookup_count == 0
