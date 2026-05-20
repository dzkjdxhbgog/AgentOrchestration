"""Digest-based container image signing and promotion gate."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Dict, List, Optional, Set


_DIGEST_RE = re.compile(r"^(?P<name>.+)@(?P<algorithm>[A-Za-z0-9_+.-]+):(?P<digest>[A-Fa-f0-9]{32,})$")


class ImagePublishError(ValueError):
    """Raised when an image cannot pass the publish gate."""


@dataclass(frozen=True)
class ScanApproval:
    image_digest: str
    scanner: str
    approved_at: str
    report_id: Optional[str] = None


@dataclass(frozen=True)
class ImageSignature:
    image_digest: str
    signer: str
    signed_at: str
    scan_report_id: Optional[str] = None


@dataclass(frozen=True)
class ImagePromotion:
    source_digest: str
    target_ref: str
    promoted_at: str


def normalize_image_digest(image_ref: str) -> str:
    """Return an immutable digest reference, rejecting mutable tag-only refs."""
    if not image_ref or not image_ref.strip():
        raise ImagePublishError("image reference is required")

    ref = image_ref.strip()
    if "@" not in ref:
        raise ImagePublishError("image reference must include an immutable digest")

    match = _DIGEST_RE.match(ref)
    if not match:
        raise ImagePublishError("image reference digest must be algorithm:hex")

    name = match.group("name")
    if ":" in name.rsplit("/", 1)[-1]:
        name = name.rsplit(":", 1)[0]

    return f"{name}@{match.group('algorithm').lower()}:{match.group('digest').lower()}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImagePublishGate:
    """Requires scan approval before signing or promoting image digests."""

    def __init__(self):
        self._scan_approvals: Dict[str, ScanApproval] = {}
        self._signatures: Dict[str, ImageSignature] = {}
        self._promotions: List[ImagePromotion] = []

    def approve_scan(
        self,
        image_ref: str,
        scanner: str = "vulnerability-scan",
        report_id: Optional[str] = None,
        approved: bool = True,
    ) -> ScanApproval:
        image_digest = normalize_image_digest(image_ref)
        if not approved:
            self._scan_approvals.pop(image_digest, None)
            raise ImagePublishError("scan approval failed")

        approval = ScanApproval(
            image_digest=image_digest,
            scanner=scanner,
            approved_at=_now(),
            report_id=report_id,
        )
        self._scan_approvals[image_digest] = approval
        return approval

    def sign_image(self, image_ref: str, signer: str = "cosign") -> ImageSignature:
        image_digest = normalize_image_digest(image_ref)
        approval = self._require_scan_approval(image_digest)
        signature = ImageSignature(
            image_digest=image_digest,
            signer=signer,
            signed_at=_now(),
            scan_report_id=approval.report_id,
        )
        self._signatures[image_digest] = signature
        return signature

    def promote_image(self, image_ref: str, target_ref: str) -> ImagePromotion:
        image_digest = normalize_image_digest(image_ref)
        self._require_scan_approval(image_digest)
        if image_digest not in self._signatures:
            raise ImagePublishError("image digest must be signed before promotion")

        promotion = ImagePromotion(
            source_digest=image_digest,
            target_ref=target_ref,
            promoted_at=_now(),
        )
        self._promotions.append(promotion)
        return promotion

    def is_scan_approved(self, image_ref: str) -> bool:
        return normalize_image_digest(image_ref) in self._scan_approvals

    def approved_digests(self) -> Set[str]:
        return set(self._scan_approvals)

    def signatures(self) -> Dict[str, ImageSignature]:
        return dict(self._signatures)

    def promotions(self) -> List[ImagePromotion]:
        return list(self._promotions)

    def _require_scan_approval(self, image_digest: str) -> ScanApproval:
        approval = self._scan_approvals.get(image_digest)
        if approval is None:
            raise ImagePublishError("image digest does not have scan approval")
        return approval
