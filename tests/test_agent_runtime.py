import pytest

from src.agent.runtime import AgentRuntime, RuntimeState


class DummyProcess:
    pid = 12345

    def poll(self):
        return None


class TestAgentRuntime:
    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_start_rejects_reserved_child_env_override(self, monkeypatch):
        started = False

        def fail_if_started(*args, **kwargs):
            nonlocal started
            started = True

        monkeypatch.setattr("subprocess.Popen", fail_if_started)

        with pytest.raises(ValueError, match="AO_AGENT_ID"):
            self.runtime.start(
                "real-agent",
                ["python", "-c", "print('sandbox')"],
                env={"AO_AGENT_ID": "spoofed-agent"},
            )

        assert not started
        assert self.runtime.get_state("real-agent") == RuntimeState.STOPPED

    def test_start_injects_runtime_owned_agent_id(self, monkeypatch):
        captured_env = {}

        def fake_popen(*args, **kwargs):
            captured_env.update(kwargs["env"])
            return DummyProcess()

        monkeypatch.setattr("subprocess.Popen", fake_popen)

        assert self.runtime.start(
            "real-agent",
            ["python", "-c", "print('sandbox')"],
            env={"CUSTOM_ENV": "allowed"},
        )

        assert captured_env["AO_AGENT_ID"] == "real-agent"
        assert captured_env["CUSTOM_ENV"] == "allowed"
        assert self.runtime.get_state("real-agent") == RuntimeState.RUNNING
