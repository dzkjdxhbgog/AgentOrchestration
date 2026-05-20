import pytest

from src.sdk.decorators import agent


def test_agent_accepts_semantic_version_string():
    @agent(name="orders", version="2.4.1-beta.1+build.7", description="demo")
    class OrdersAgent:
        pass

    assert OrdersAgent.__agent_config__ == {
        "name": "orders",
        "version": "2.4.1-beta.1+build.7",
        "description": "demo",
    }


@pytest.mark.parametrize(
    "version",
    [
        "1",
        "1.0",
        "01.0.0",
        "1.0.x",
        "v1.0.0",
        "",
        1,
        None,
    ],
)
def test_agent_rejects_malformed_version_before_storing_metadata(version):
    with pytest.raises(ValueError, match="semantic version|MAJOR.MINOR.PATCH"):
        agent(name="orders", version=version)
