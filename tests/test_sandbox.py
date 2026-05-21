import os
import stat

import pytest

from src.agent.sandbox import AgentSandbox, PRIVATE_DIRECTORY_MODE


pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX permission bits are required for directory mode assertions",
)


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_sandbox_directories_ignore_permissive_umask(tmp_path):
    original_umask = os.umask(0)
    try:
        sandbox = AgentSandbox(str(tmp_path / "sandbox-root"))
        sandbox_path = sandbox.create("agent-1")
    finally:
        os.umask(original_umask)

    assert _mode(sandbox.base_path) == PRIVATE_DIRECTORY_MODE
    assert _mode(sandbox_path) == PRIVATE_DIRECTORY_MODE


def test_existing_sandbox_directories_are_tightened(tmp_path):
    base_path = tmp_path / "sandbox-root"
    sandbox_path = base_path / "agent-1"
    sandbox_path.mkdir(mode=0o777, parents=True)
    base_path.chmod(0o777)
    sandbox_path.chmod(0o777)

    sandbox = AgentSandbox(str(base_path))
    created_path = sandbox.create("agent-1")

    assert created_path == sandbox_path
    assert _mode(base_path) == PRIVATE_DIRECTORY_MODE
    assert _mode(sandbox_path) == PRIVATE_DIRECTORY_MODE
