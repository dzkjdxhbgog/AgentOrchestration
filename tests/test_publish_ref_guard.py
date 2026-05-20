import json

from tools.validate_publish_ref import PublishRefContext, validate_publish_ref


def _signed(_tag_name):
    return True, "good signature"


def _unsigned(_tag_name):
    return False, "no signature"


def test_protected_main_branch_is_accepted():
    ctx = PublishRefContext(
        event_name="workflow_dispatch",
        ref="refs/heads/main",
        ref_name="main",
        ref_type="branch",
        ref_protected=True,
    )

    valid, message = validate_publish_ref(ctx)

    assert valid
    assert "accepted" in message


def test_unprotected_release_branch_is_rejected():
    ctx = PublishRefContext(
        event_name="workflow_dispatch",
        ref="refs/heads/release/2.4",
        ref_name="release/2.4",
        ref_type="branch",
        ref_protected=False,
    )

    valid, message = validate_publish_ref(ctx)

    assert not valid
    assert "not protected" in message


def test_protected_non_release_branch_is_rejected():
    ctx = PublishRefContext(
        event_name="workflow_dispatch",
        ref="refs/heads/feature/publish",
        ref_name="feature/publish",
        ref_type="branch",
        ref_protected=True,
    )

    valid, message = validate_publish_ref(ctx)

    assert not valid
    assert "not a release ref" in message


def test_signed_semver_tag_is_accepted():
    ctx = PublishRefContext(
        event_name="push",
        ref="refs/tags/v2.4.1",
        ref_name="v2.4.1",
        ref_type="tag",
        ref_protected=False,
    )

    valid, message = validate_publish_ref(ctx, tag_verifier=_signed)

    assert valid
    assert "signed release tag" in message


def test_unsigned_semver_tag_is_rejected():
    ctx = PublishRefContext(
        event_name="push",
        ref="refs/tags/v2.4.1",
        ref_name="v2.4.1",
        ref_type="tag",
        ref_protected=False,
    )

    valid, message = validate_publish_ref(ctx, tag_verifier=_unsigned)

    assert not valid
    assert "signature" in message


def test_manual_dispatch_ref_override_input_is_rejected(tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"inputs": {"source_ref": "main", "version": "2.4.1"}}),
        encoding="utf-8",
    )
    ctx = PublishRefContext(
        event_name="workflow_dispatch",
        ref="refs/heads/main",
        ref_name="main",
        ref_type="branch",
        ref_protected=True,
        event_path=str(event_path),
    )

    valid, message = validate_publish_ref(ctx)

    assert not valid
    assert "override inputs" in message


def test_manual_dispatch_version_input_does_not_override_ref(tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"inputs": {"version": "2.4.1"}}),
        encoding="utf-8",
    )
    ctx = PublishRefContext(
        event_name="workflow_dispatch",
        ref="refs/heads/release/2.4",
        ref_name="release/2.4",
        ref_type="branch",
        ref_protected=True,
        event_path=str(event_path),
    )

    valid, message = validate_publish_ref(ctx)

    assert valid
    assert "accepted" in message
