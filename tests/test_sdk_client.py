import json
from unittest.mock import patch

from src.sdk.client import OrchestratorClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"ok": True}).encode()


def test_base_url_trailing_slash_does_not_duplicate_api_prefix():
    captured_urls = []

    def fake_urlopen(req):
        captured_urls.append(req.full_url)
        return FakeResponse()

    client = OrchestratorClient(
        base_url="https://api.example.test/",
        api_key="token",
    )

    with patch("src.sdk.client.urlopen", side_effect=fake_urlopen):
        assert client.list_agents() == {"ok": True}

    assert captured_urls == ["https://api.example.test/api/v2/agents"]


def test_base_url_multiple_trailing_slashes_are_normalized():
    captured_urls = []

    def fake_urlopen(req):
        captured_urls.append(req.full_url)
        return FakeResponse()

    client = OrchestratorClient(
        base_url="https://api.example.test///",
        api_key="token",
    )

    with patch("src.sdk.client.urlopen", side_effect=fake_urlopen):
        client.get_agent("agent-1")

    assert captured_urls == ["https://api.example.test/api/v2/agents/agent-1"]


def test_request_accepts_paths_without_leading_slash():
    captured_urls = []

    def fake_urlopen(req):
        captured_urls.append(req.full_url)
        return FakeResponse()

    client = OrchestratorClient(
        base_url="https://api.example.test/",
        api_key="token",
    )

    with patch("src.sdk.client.urlopen", side_effect=fake_urlopen):
        client._request("GET", "agents?status=running")

    assert captured_urls == [
        "https://api.example.test/api/v2/agents?status=running",
    ]
