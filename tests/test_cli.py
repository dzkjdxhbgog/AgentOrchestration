"""Tests for the command line interface."""

import sys

import pytest

from src.cli.main import cli


def test_cli_rejects_unsupported_output_mode(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ao", "--output", "yaml", "status"])

    with pytest.raises(SystemExit) as exc_info:
        cli()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice: 'yaml'" in captured.err


def test_cli_accepts_supported_output_mode(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ao", "--output", "json", "status"])

    cli()

    captured = capsys.readouterr()
    assert "Checking agent status..." in captured.out
