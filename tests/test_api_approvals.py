from fastapi.testclient import TestClient

from src.api.approvals import ApprovalRunState, approval_service
from src.api.server import create_app


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def setup_function():
    approval_service.reset()


def test_approve_human_step_when_run_is_waiting():
    approval_service.register_run(
        "run-1",
        state=ApprovalRunState.WAITING_FOR_HUMAN,
        steps={"step-1": {"kind": "human_approval"}},
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/runs/run-1/human-steps/step-1/approve",
        headers=AUTH_HEADERS,
        json={"approved": True, "actor": "reviewer"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "step_id": "step-1",
        "approved": True,
        "state": "approved",
    }
    assert approval_service.protected_lookup_count == 1
    assert approval_service.mutation_count == 1


def test_approve_human_step_requires_authorization():
    approval_service.register_run(
        "run-1",
        state=ApprovalRunState.WAITING_FOR_HUMAN,
        steps={"step-1": {"kind": "human_approval"}},
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/runs/run-1/human-steps/step-1/approve",
        json={"approved": True},
    )

    assert response.status_code == 401
    assert approval_service.protected_lookup_count == 0
    assert approval_service.mutation_count == 0


def test_approve_human_step_rejects_malformed_request_before_lookup():
    approval_service.register_run(
        "run-1",
        state=ApprovalRunState.WAITING_FOR_HUMAN,
        steps={"step-1": {"kind": "human_approval"}},
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/runs/run-1/human-steps/step-1/approve",
        headers=AUTH_HEADERS,
        json={"actor": "reviewer"},
    )

    assert response.status_code == 422
    assert approval_service.protected_lookup_count == 0
    assert approval_service.mutation_count == 0


def test_approve_human_step_checks_run_state_before_protected_lookup():
    approval_service.register_run(
        "run-1",
        state=ApprovalRunState.COMPLETED,
        steps={"step-1": {"kind": "human_approval"}},
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/runs/run-1/human-steps/step-1/approve",
        headers=AUTH_HEADERS,
        json={"approved": True},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Run is not waiting for human approval"}
    assert approval_service.protected_lookup_count == 0
    assert approval_service.mutation_count == 0
