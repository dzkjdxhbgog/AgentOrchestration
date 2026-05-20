import importlib.util
from pathlib import Path


runtime_path = Path(__file__).resolve().parents[1] / "src" / "agent" / "runtime.py"
runtime_spec = importlib.util.spec_from_file_location("agent_runtime", runtime_path)
agent_runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(agent_runtime)

AgentRuntime = agent_runtime.AgentRuntime
RuntimeState = agent_runtime.RuntimeState


class CompletedProcess:
    def __init__(self, exit_code):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


def test_get_state_treats_zero_exit_as_stopped():
    runtime = AgentRuntime()
    runtime._processes["agent-1"] = CompletedProcess(0)
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.get_state("agent-1") == RuntimeState.STOPPED


def test_get_state_treats_nonzero_exit_as_crashed():
    runtime = AgentRuntime()
    runtime._processes["agent-1"] = CompletedProcess(2)
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.get_state("agent-1") == RuntimeState.CRASHED
