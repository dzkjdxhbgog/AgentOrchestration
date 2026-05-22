import pytest

from src.orchestrator.deploy import (
    DeploymentManifestRenderer,
    ReleaseHistory,
    ReleaseIdentityError,
)


def test_manifest_uses_immutable_release_annotations_and_image_digest():
    history = ReleaseHistory()
    renderer = DeploymentManifestRenderer(history)

    manifest = renderer.render(
        name="scheduler",
        image="registry.example.com/ao/scheduler",
        commit_sha="abc123def456",
        package_version="2.4.1",
        image_digest="sha256:deadbeef",
        source_ref="main",
    )

    annotations = manifest["metadata"]["annotations"]
    release_id = annotations["ao.release/id"]
    assert release_id.startswith("rel-")
    assert annotations["ao.release/commit"] == "abc123def456"
    assert annotations["ao.release/package-version"] == "2.4.1"
    assert annotations["ao.release/image-digest"] == "sha256:deadbeef"
    assert annotations["ao.release/source-ref"] == "main"
    assert manifest["metadata"]["labels"]["ao.release.id"] == release_id
    assert manifest["spec"]["template"]["metadata"]["annotations"] == annotations
    assert manifest["spec"]["template"]["spec"]["containers"][0]["image"].endswith("@sha256:deadbeef")
    assert "main" not in release_id


def test_release_history_can_be_queried_by_immutable_release_id():
    history = ReleaseHistory()
    renderer = DeploymentManifestRenderer(history)
    manifest = renderer.render(
        name="api",
        image="registry.example.com/ao/api",
        commit_sha="feedface",
        package_version="2.4.1",
        image_digest="sha256:cafebabe",
        source_ref="release/latest",
    )
    release_id = manifest["metadata"]["annotations"]["ao.release/id"]

    record = history.get(release_id)

    assert record["release_id"] == release_id
    assert record["commit_sha"] == "feedface"
    assert record["image_digest"] == "sha256:cafebabe"
    assert record["source_ref"] == "release/latest"
    assert record["manifest_name"] == "api"


def test_mutable_ref_cannot_replace_required_immutable_identity():
    renderer = DeploymentManifestRenderer()

    with pytest.raises(ReleaseIdentityError):
        renderer.render(
            name="api",
            image="registry.example.com/ao/api",
            commit_sha="",
            package_version="2.4.1",
            image_digest="sha256:cafebabe",
            source_ref="main",
        )
