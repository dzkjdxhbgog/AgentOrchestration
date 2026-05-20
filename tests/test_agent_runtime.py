import signal
import subprocess

from src.agent.runtime import AgentRuntime, RuntimeState


class FakeProcess:
    def __init__(self, returncode=None, on_signal=None, timeout_on_wait=False):
        self.returncode = returncode
        self.on_signal = on_signal
        self.timeout_on_wait = timeout_on_wait
        self.signals = []
        self.killed = False
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.signals.append(value)
        if self.on_signal:
            self.on_signal(value)

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.timeout_on_wait and not self.killed:
            raise subprocess.TimeoutExpired(cmd="agent", timeout=timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_failure_reason_is_recorded_before_shutdown_signal():
    runtime = AgentRuntime()
    observed = {}

    def on_signal(value):
        observed["signal"] = value
        observed["outcome"] = runtime.get_terminal_outcome("agent-1")

    runtime._processes["agent-1"] = FakeProcess(on_signal=on_signal)
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.stop("agent-1", failure_reason="worker heartbeat lost")

    outcome = runtime.get_terminal_outcome("agent-1")
    assert observed["signal"] == signal.SIGTERM
    assert observed["outcome"] is outcome
    assert outcome.state == RuntimeState.CRASHED
    assert outcome.reason == "worker heartbeat lost"
    assert runtime.get_state("agent-1") == RuntimeState.CRASHED


def test_failure_terminal_outcome_is_not_overwritten_by_clean_exit():
    runtime = AgentRuntime()
    proc = FakeProcess()
    runtime._processes["agent-1"] = proc
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.stop("agent-1", failure_reason="shutdown after task failure")
    proc.returncode = 0

    assert runtime.get_state("agent-1") == RuntimeState.CRASHED
    outcome = runtime.get_terminal_outcome("agent-1")
    assert outcome.reason == "shutdown after task failure"
    assert outcome.exit_code is None


def test_nonzero_process_exit_records_durable_failure_reason_once():
    runtime = AgentRuntime()
    runtime._processes["agent-1"] = FakeProcess(returncode=7)
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.get_state("agent-1") == RuntimeState.CRASHED
    first = runtime.get_terminal_outcome("agent-1")
    assert first.reason == "process exited with code 7"
    assert first.exit_code == 7

    runtime._processes["agent-1"].returncode = 0
    assert runtime.get_state("agent-1") == RuntimeState.CRASHED
    assert runtime.get_terminal_outcome("agent-1") is first


def test_forced_shutdown_preserves_failure_reason():
    runtime = AgentRuntime()
    proc = FakeProcess(timeout_on_wait=True)
    runtime._processes["agent-1"] = proc
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.stop("agent-1", timeout=0, failure_reason="cancellation requested")

    outcome = runtime.get_terminal_outcome("agent-1")
    assert proc.killed
    assert outcome.state == RuntimeState.CRASHED
    assert outcome.reason == "cancellation requested"
