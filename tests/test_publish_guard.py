import pytest

from src.ci.publish_guard import (
    PublishRefContext,
    PublishRefError,
    validate_publish_ref,
)


def test_protected_branch_is_accepted():
    validate_publish_ref(PublishRefContext(ref="refs/heads/main", ref_protected=True))


def test_unprotected_branch_is_rejected_before_publish_auth():
    with pytest.raises(PublishRefError, match="protected branch"):
        validate_publish_ref(PublishRefContext(ref="refs/heads/feature/package-test"))


def test_signed_release_tag_is_accepted():
    validate_publish_ref(PublishRefContext(ref="refs/tags/v2.4.1", signed_tag=True))


def test_unsigned_release_tag_is_rejected():
    with pytest.raises(PublishRefError, match="signed release tag"):
        validate_publish_ref(PublishRefContext(ref="refs/tags/v2.4.1", signed_tag=False))


def test_non_release_tag_is_rejected_even_when_signed():
    with pytest.raises(PublishRefError, match="vX.Y.Z"):
        validate_publish_ref(PublishRefContext(ref="refs/tags/latest", signed_tag=True))


def test_manual_dispatch_input_cannot_override_actual_ref():
    with pytest.raises(PublishRefError, match="cannot override"):
        validate_publish_ref(
            PublishRefContext(
                ref="refs/heads/feature/package-test",
                ref_protected=False,
                event_name="workflow_dispatch",
                manual_ref_input="refs/heads/main",
            )
        )
