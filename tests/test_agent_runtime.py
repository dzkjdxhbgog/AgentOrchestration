import sys

from src.agent.runtime import AgentRuntime, RuntimeState


class TestAgentRuntime:
    def test_start_and_stop_drains_stdout_stderr(self):
        runtime = AgentRuntime()
        command = [
            sys.executable,
            "-c",
            "import sys, time\n"
            "for _ in range(20000):\n"
            "    print('stdout' * 100)\n"
            "    print('stderr' * 100, file=sys.stderr)\n"
            "    time.sleep(0.002)\n",
        ]

        assert runtime.start("agent-1739", command)
        assert runtime.stop("agent-1739", timeout=3)
        assert runtime.get_state("agent-1739") == RuntimeState.STOPPED

    def test_double_stop_returns_false(self):
        runtime = AgentRuntime()
        command = [
            sys.executable,
            "-c",
            "import time\nwhile True:\n    time.sleep(0.2)",
        ]
        assert runtime.start("agent-double-stop", command)
        assert runtime.stop("agent-double-stop", timeout=3)
        assert not runtime.stop("agent-double-stop", timeout=3)
