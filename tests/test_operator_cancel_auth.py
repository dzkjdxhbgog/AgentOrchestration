import asyncio
import time

import pytest

from src.agent.executor import AgentExecutor
from src.common.auth import (
    AuthorizationService,
    OperatorPrincipal,
    PermissionDenied,
    RUN_CANCEL_SCOPE,
)


def operator_principal(**overrides):
    data = {
        "subject": "user-1",
        "workspace_id": "workspace-a",
        "role": "operator",
        "scopes": {RUN_CANCEL_SCOPE},
        "expires_at": time.time() + 60,
        "revoked": False,
    }
    data.update(overrides)
    return OperatorPrincipal(**data)


class TestRunCancellationAuthorization:
    def test_denies_anonymous_principal(self):
        service = AuthorizationService()

        with pytest.raises(PermissionDenied, match="anonymous"):
            service.require_run_cancellation(None, workspace_id="workspace-a")

    def test_denies_stale_operator_token(self):
        service = AuthorizationService()
        principal = operator_principal(expires_at=time.time() - 1)

        with pytest.raises(PermissionDenied, match="stale"):
            service.require_run_cancellation(principal, workspace_id="workspace-a")

    def test_denies_revoked_operator_token(self):
        service = AuthorizationService()
        principal = operator_principal(revoked=True)

        with pytest.raises(PermissionDenied, match="revoked"):
            service.require_run_cancellation(principal, workspace_id="workspace-a")

    def test_denies_insufficient_scope(self):
        service = AuthorizationService()
        principal = operator_principal(scopes={"runs:read"})

        with pytest.raises(PermissionDenied, match=RUN_CANCEL_SCOPE):
            service.require_run_cancellation(principal, workspace_id="workspace-a")

    def test_denies_wrong_workspace_role(self):
        service = AuthorizationService()
        principal = operator_principal(workspace_id="workspace-b")

        with pytest.raises(PermissionDenied, match="workspace"):
            service.require_run_cancellation(principal, workspace_id="workspace-a")

    def test_authorized_operator_can_cancel_active_execution(self):
        async def run_case():
            executor = AgentExecutor()
            task = asyncio.create_task(asyncio.sleep(60))
            executor._active_tasks["exec-1"] = task
            executor._execution_workspaces["exec-1"] = "workspace-a"

            assert executor.cancel("exec-1", principal=operator_principal())
            await asyncio.sleep(0)
            assert task.cancelled()

        asyncio.run(run_case())

    def test_cancel_rejects_insufficient_principal_before_touching_task(self):
        async def run_case():
            executor = AgentExecutor()
            task = asyncio.create_task(asyncio.sleep(60))
            executor._active_tasks["exec-1"] = task
            executor._execution_workspaces["exec-1"] = "workspace-a"

            with pytest.raises(PermissionDenied):
                executor.cancel("exec-1", principal=operator_principal(scopes=set()))

            assert not task.cancelled()
            task.cancel()
            await asyncio.sleep(0)

        asyncio.run(run_case())
