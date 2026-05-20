import pytest

from src.cli.main import main


def test_missing_command_writes_usage_to_stderr(capsys):
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "No command provided." in captured.err
    assert "usage:" in captured.err
    assert captured.out == ""


def test_parser_validation_errors_stay_on_stderr(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["logs"])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "error:" in captured.err
    assert "agent_id" in captured.err
    assert captured.out == ""


def test_deploy_validation_errors_stay_on_stderr(capsys, tmp_path):
    missing_manifest = tmp_path / "missing.yml"

    exit_code = main(["deploy", str(missing_manifest)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Manifest not found:" in captured.err
    assert str(missing_manifest) in captured.err
    assert captured.out == ""


def test_successful_commands_write_data_to_stdout(capsys):
    exit_code = main(["status"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "Checking agent status...\n"
    assert captured.err == ""
