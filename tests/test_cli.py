from src.cli import main as cli_main


def test_status_without_watch_returns_success(capsys):
    exit_code = cli_main.cli(["status"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Checking agent status..." in captured.out
    assert captured.err == ""


def test_status_watch_interrupt_returns_documented_code(monkeypatch, capsys):
    def raise_keyboard_interrupt(_interval):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main.time, "sleep", raise_keyboard_interrupt)

    exit_code = cli_main.cli(["status", "--watch"])

    captured = capsys.readouterr()
    assert exit_code == cli_main.STATUS_INTERRUPT_EXIT_CODE
    assert "Checking agent status..." in captured.out
    assert "Status watch interrupted." in captured.err
    assert "Traceback" not in captured.err
