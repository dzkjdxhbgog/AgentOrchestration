import sys

import pytest

from src.cli.main import cli


def test_deploy_dry_run_validates_manifest_without_deploying(tmp_path, capsys, monkeypatch):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("name: dry-run-agent\nimage: example/agent:latest\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["ao", "deploy", "--dry-run", str(manifest)])

    cli()

    captured = capsys.readouterr()
    assert "Dry run passed" in captured.out
    assert str(manifest) in captured.out
    assert "Deploying agent" not in captured.out
    assert captured.err == ""


def test_deploy_dry_run_rejects_missing_manifest(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", "--dry-run", "missing.yaml"])

    with pytest.raises(SystemExit) as exc:
        cli()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert captured.out == ""
    assert "Deploy validation failed: manifest does not exist" in captured.err
