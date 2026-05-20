import pytest

from src.common.image_publish import ImagePublishError, ImagePublishGate, normalize_image_digest


GOOD_DIGEST = "registry.example.com/ao/agent-orchestrator@sha256:" + "a" * 64
TAG_AND_DIGEST = "registry.example.com/ao/agent-orchestrator:1.2.3@sha256:" + "b" * 64
TAG_ONLY = "registry.example.com/ao/agent-orchestrator:latest"


def test_signing_requires_scan_approval():
    gate = ImagePublishGate()

    with pytest.raises(ImagePublishError, match="scan approval"):
        gate.sign_image(GOOD_DIGEST)

    approval = gate.approve_scan(GOOD_DIGEST, report_id="scan-123")
    signature = gate.sign_image(GOOD_DIGEST, signer="cosign-keyless")

    assert approval.image_digest == GOOD_DIGEST
    assert signature.image_digest == GOOD_DIGEST
    assert signature.scan_report_id == "scan-123"


def test_signatures_use_immutable_digest_not_mutable_tag():
    gate = ImagePublishGate()
    normalized = normalize_image_digest(TAG_AND_DIGEST)

    gate.approve_scan(TAG_AND_DIGEST)
    signature = gate.sign_image(TAG_AND_DIGEST)

    assert normalized == "registry.example.com/ao/agent-orchestrator@sha256:" + "b" * 64
    assert signature.image_digest == normalized
    assert ":1.2.3" not in signature.image_digest


def test_mutable_tag_only_reference_is_rejected_before_signing():
    gate = ImagePublishGate()

    with pytest.raises(ImagePublishError, match="immutable digest"):
        gate.approve_scan(TAG_ONLY)

    with pytest.raises(ImagePublishError, match="immutable digest"):
        gate.sign_image(TAG_ONLY)


def test_promotion_requires_scan_approval_and_signature():
    gate = ImagePublishGate()

    with pytest.raises(ImagePublishError, match="scan approval"):
        gate.promote_image(GOOD_DIGEST, "prod")

    gate.approve_scan(GOOD_DIGEST)
    with pytest.raises(ImagePublishError, match="signed"):
        gate.promote_image(GOOD_DIGEST, "prod")

    gate.sign_image(GOOD_DIGEST)
    promotion = gate.promote_image(GOOD_DIGEST, "prod")

    assert promotion.source_digest == GOOD_DIGEST
    assert promotion.target_ref == "prod"


def test_rejected_scan_cannot_be_signed_or_promoted():
    gate = ImagePublishGate()

    with pytest.raises(ImagePublishError, match="scan approval failed"):
        gate.approve_scan(GOOD_DIGEST, approved=False)

    with pytest.raises(ImagePublishError, match="scan approval"):
        gate.sign_image(GOOD_DIGEST)
