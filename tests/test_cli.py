from argparse import Namespace

from src.cli import main


def test_cli_returns_zero_for_successful_deploy(capsys):
    exit_code = main.cli(["deploy", "agent.yaml"])

    assert exit_code == 0
    assert "Deploying agent from manifest: agent.yaml" in capsys.readouterr().out


def test_deploy_handler_returns_nonzero_when_backend_fails(capsys):
    def failing_backend(manifest):
        raise ConnectionError(f"orchestrator unavailable for {manifest}")

    exit_code = main.handle_deploy(Namespace(manifest="agent.yaml"), failing_backend)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Deploy failed: orchestrator unavailable for agent.yaml" in captured.err


def test_cli_returns_nonzero_when_no_command_is_selected(capsys):
    exit_code = main.cli([])

    assert exit_code == 1
    assert "Agent Orchestrator CLI" in capsys.readouterr().out


def test_command_handlers_return_explicit_success_codes(capsys):
    assert main.handle_init(Namespace(name="demo")) == 0
    assert main.handle_status(Namespace(watch=False)) == 0
    assert main.handle_logs(Namespace(agent_id="agent-1", tail=20)) == 0

    output = capsys.readouterr().out
    assert "Initializing project: demo" in output
    assert "Checking agent status..." in output
    assert "Fetching logs for agent: agent-1" in output
