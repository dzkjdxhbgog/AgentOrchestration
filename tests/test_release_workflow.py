from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"


def load_release_workflow():
    return yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_release_workflow_runs_for_immutable_tags():
    workflow = load_release_workflow()

    assert "v*" in workflow["on"]["push"]["tags"]
    assert (
        workflow["on"]["workflow_dispatch"]["inputs"]["tag"]["required"]
        == "true"
    )


def test_release_signing_concurrency_is_tag_specific_and_non_canceling():
    workflow = load_release_workflow()
    concurrency = workflow["jobs"]["sign-release-artifacts"]["concurrency"]

    assert "github.ref_name" in concurrency["group"]
    assert "inputs.tag" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "false"


def test_release_workflow_fails_on_partial_signing_summary():
    workflow = load_release_workflow()
    steps = workflow["jobs"]["sign-release-artifacts"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)

    assert "scripts/check_release_signing.py" in commands
    assert "dist/release/signing-manifest.json" in commands
