"""Regression tests for CLI client injection."""

import pytest

from unittest.mock import Mock

from src.cli.main import cli


def test_init_does_not_build_client(capsys):
    factory = Mock()

    cli(["init", "demo"], client_factory=factory)

    factory.assert_not_called()
    assert "Initializing project: demo" in capsys.readouterr().out


def test_deploy_uses_injected_client(capsys):
    client = Mock()
    client.register_agent.return_value = {"id": "agent-1"}
    factory = Mock()

    cli(["deploy", "manifest.yaml"], client=client, client_factory=factory)

    factory.assert_not_called()
    client.register_agent.assert_called_once_with("manifest.yaml", "custom")
    assert "Agent registered" in capsys.readouterr().out


def test_status_builds_client_from_factory_only_when_needed(capsys):
    client = Mock()
    client.list_agents.return_value = {"agents": []}
    factory = Mock(return_value=client)

    cli(["status"], client_factory=factory)

    factory.assert_called_once_with()
    client.list_agents.assert_called_once_with()
    assert "Active agents" in capsys.readouterr().out


def test_logs_uses_injected_client(capsys):
    client = Mock()
    client.get_agent.return_value = {"id": "agent-123"}

    cli(["logs", "agent-123"], client=client)

    client.get_agent.assert_called_once_with("agent-123")
    assert "Agent info" in capsys.readouterr().out


def test_missing_command_exits_without_building_client(capsys):
    factory = Mock()

    with pytest.raises(SystemExit) as exc_info:
        cli([], client_factory=factory)

    assert exc_info.value.code == 1
    factory.assert_not_called()
    assert "Available commands" in capsys.readouterr().out
