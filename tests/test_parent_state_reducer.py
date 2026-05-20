from dataclasses import asdict

from src.orchestrator.parent_state import (
    ChildEvent,
    LifecycleState,
    ParentRunState,
    ParentStateReducer,
)


def test_failed_parent_rejects_late_child_success_without_private_audit_data():
    parent = ParentRunState(
        run_id="run-1",
        lifecycle=LifecycleState.FAILED,
        attempt=2,
        revision=7,
        children={"child-a": LifecycleState.FAILED},
    )
    event = ChildEvent(
        child_id="child-b",
        lifecycle=LifecycleState.SUCCEEDED,
        attempt=2,
        revision=8,
        runtime_context={
            "authorization": "secret-token",
            "payload": {"customer": "private"},
        },
    )

    decision = ParentStateReducer.apply_child_event(parent, event)

    assert not decision.accepted
    assert decision.reason == "parent_failed_late_child_success"
    assert decision.state.lifecycle == LifecycleState.FAILED
    assert decision.state.revision == parent.revision
    assert decision.state.children == parent.children
    assert "child-b" not in decision.state.children

    audit_text = str(asdict(decision.state.audit[-1]))
    assert "secret-token" not in audit_text
    assert "authorization" not in audit_text
    assert "private" not in audit_text


def test_reducer_rejects_stale_attempt_and_revision_before_commit():
    parent = ParentRunState(
        run_id="run-2",
        lifecycle=LifecycleState.RUNNING,
        attempt=3,
        revision=10,
        children={"child-a": LifecycleState.RUNNING},
    )

    stale_attempt = ParentStateReducer.apply_child_event(
        parent,
        ChildEvent(
            child_id="child-a",
            lifecycle=LifecycleState.SUCCEEDED,
            attempt=2,
            revision=11,
        ),
    )
    stale_revision = ParentStateReducer.apply_child_event(
        parent,
        ChildEvent(
            child_id="child-a",
            lifecycle=LifecycleState.SUCCEEDED,
            attempt=3,
            revision=10,
        ),
    )

    assert not stale_attempt.accepted
    assert stale_attempt.reason == "attempt_mismatch"
    assert stale_attempt.state.lifecycle == LifecycleState.RUNNING
    assert stale_attempt.state.children == parent.children

    assert not stale_revision.accepted
    assert stale_revision.reason == "stale_revision"
    assert stale_revision.state.lifecycle == LifecycleState.RUNNING
    assert stale_revision.state.children == parent.children


def test_reducer_accepts_next_revision_child_event_for_active_parent():
    parent = ParentRunState(
        run_id="run-3",
        lifecycle=LifecycleState.RUNNING,
        attempt=1,
        revision=4,
    )
    event = ChildEvent(
        child_id="child-a",
        lifecycle=LifecycleState.SUCCEEDED,
        attempt=1,
        revision=5,
    )

    decision = ParentStateReducer.apply_child_event(parent, event)

    assert decision.accepted
    assert decision.reason == "child_event_committed"
    assert decision.state.lifecycle == LifecycleState.RUNNING
    assert decision.state.revision == 5
    assert decision.state.children == {"child-a": LifecycleState.SUCCEEDED}
