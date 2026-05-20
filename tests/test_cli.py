import sys

import pytest

from src.cli.main import cli


def test_deploy_missing_manifest_exits_before_reporting_progress(capsys, monkeypatch, tmp_path):
    missing_manifest = tmp_path / "missing.yaml"
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(missing_manifest)])

    with pytest.raises(SystemExit) as exc_info:
        cli()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "manifest not found" in captured.err
    assert str(missing_manifest) in captured.err
    assert "Deploying agent" not in captured.out


def test_deploy_existing_manifest_reports_progress(capsys, monkeypatch, tmp_path):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("name: test-agent\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    cli()

    captured = capsys.readouterr()
    assert f"Deploying agent from manifest: {manifest}" in captured.out
    assert captured.err == ""
