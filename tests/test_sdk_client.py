import pytest

from src.sdk import AuthenticationError as ExportedAuthenticationError
from src.sdk import OrchestratorClient as ExportedOrchestratorClient
from src.sdk.client import AuthenticationError, OrchestratorClient


def test_client_requires_api_key_when_env_missing(monkeypatch):
    monkeypatch.delenv("AO_API_KEY", raising=False)

    with pytest.raises(AuthenticationError, match="requires an API key"):
        OrchestratorClient()


def test_client_rejects_blank_api_key_argument(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", "env-token")

    with pytest.raises(AuthenticationError, match="requires an API key"):
        OrchestratorClient(api_key="   ")


def test_client_rejects_non_string_api_key_argument(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", "env-token")

    with pytest.raises(AuthenticationError, match="requires an API key"):
        OrchestratorClient(api_key=123)


def test_client_uses_stripped_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", "  env-token  ")

    client = OrchestratorClient()

    assert client.api_key == "env-token"


def test_sdk_exports_authentication_error():
    assert ExportedAuthenticationError is AuthenticationError
    assert ExportedOrchestratorClient is OrchestratorClient
