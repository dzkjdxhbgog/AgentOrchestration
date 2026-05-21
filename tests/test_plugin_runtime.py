from concurrent.futures import ThreadPoolExecutor
import time

from src.agent.plugin_runtime import PluginManifestState, PluginRuntime


def _valid_manifest():
    return {
        "name": "audit-plugin",
        "version": "1.0.0",
        "hooks": {"pre_execute": ["audit.before"]},
    }


def test_invalid_manifest_rejects_before_loading_hooks():
    runtime = PluginRuntime()
    calls = []

    def loader(manifest):
        calls.append(manifest)
        return {"pre_execute": [lambda task: task]}

    outcome = runtime.load_manifest(
        {
            "name": "bad-plugin",
            "version": "1.0.0",
            "hooks": {"before": ["bad.hook"]},
        },
        loader,
    )

    assert outcome.state is PluginManifestState.REJECTED
    assert calls == []
    assert runtime.get_loaded_hooks(
        {"name": "bad-plugin", "version": "1.0.0"}
    ) == {}


def test_valid_manifest_records_terminal_outcome_before_hooks_are_available():
    runtime = PluginRuntime()

    def pre_execute(task):
        return task

    outcome = runtime.load_manifest(
        _valid_manifest(),
        lambda manifest: {"pre_execute": [pre_execute]},
    )

    assert outcome.state is PluginManifestState.LOADED
    assert outcome.error is None
    assert runtime.get_state(_valid_manifest()) is PluginManifestState.LOADED
    assert runtime.get_loaded_hooks(_valid_manifest()) == {
        "pre_execute": [pre_execute],
    }


def test_concurrent_manifest_load_is_idempotent_with_one_terminal_outcome():
    runtime = PluginRuntime()
    calls = []

    def loader(manifest):
        calls.append(manifest["name"])
        time.sleep(0.01)
        return {"pre_execute": [lambda task: task]}

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(
            executor.map(
                lambda _: runtime.load_manifest(_valid_manifest(), loader),
                range(16),
            )
        )

    assert len({id(outcome) for outcome in outcomes}) == 1
    assert len(calls) == 1
    assert outcomes[0].state is PluginManifestState.LOADED


def test_loader_failure_records_failed_terminal_outcome_without_hooks():
    runtime = PluginRuntime()

    outcome = runtime.load_manifest(
        _valid_manifest(),
        lambda manifest: {"pre_execute": ["not-callable"]},
    )

    assert outcome.state is PluginManifestState.FAILED
    assert "callable" in outcome.error
    assert runtime.get_loaded_hooks(_valid_manifest()) == {}
