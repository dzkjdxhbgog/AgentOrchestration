import pytest

from src.cli.main import MAX_LOG_TAIL_LINES, cli


def test_logs_rejects_tail_above_documented_maximum(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli(["logs", "agent-1", "--tail", str(MAX_LOG_TAIL_LINES + 1)])

    assert exc_info.value.code == 2
    assert f"--tail must be at most {MAX_LOG_TAIL_LINES} lines" in capsys.readouterr().err


def test_logs_allows_documented_maximum_tail(capsys):
    cli(["logs", "agent-1", "--tail", str(MAX_LOG_TAIL_LINES)])

    assert "Fetching logs for agent: agent-1" in capsys.readouterr().out
