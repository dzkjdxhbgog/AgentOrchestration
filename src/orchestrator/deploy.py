"""Deployment manifest rendering with immutable release identity."""

from dataclasses import dataclass, asdict
from hashlib import sha256
from typing import Dict, List, Optional


ANNOTATION_PREFIX = "ao.release"


class ReleaseIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class ReleaseIdentity:
    release_id: str
    commit_sha: str
    package_version: str
    image_digest: str
    source_ref: Optional[str] = None

    def to_record(self) -> Dict[str, Optional[str]]:
        return asdict(self)


class ReleaseHistory:
    def __init__(self):
        self._records: Dict[str, Dict[str, Optional[str]]] = {}

    def record(self, identity: ReleaseIdentity, manifest: Dict) -> Dict[str, Optional[str]]:
        record = identity.to_record()
        record["manifest_name"] = manifest["metadata"]["name"]
        self._records[identity.release_id] = record
        return dict(record)

    def get(self, release_id: str) -> Optional[Dict[str, Optional[str]]]:
        record = self._records.get(release_id)
        return dict(record) if record else None

    def list(self) -> List[Dict[str, Optional[str]]]:
        return [dict(record) for record in self._records.values()]


class DeploymentManifestRenderer:
    def __init__(self, history: Optional[ReleaseHistory] = None):
        self.history = history or ReleaseHistory()

    def render(
        self,
        name: str,
        image: str,
        commit_sha: str,
        package_version: str,
        image_digest: str,
        source_ref: Optional[str] = None,
    ) -> Dict:
        identity = build_release_identity(
            commit_sha=commit_sha,
            package_version=package_version,
            image_digest=image_digest,
            source_ref=source_ref,
        )
        image_ref = image if "@" in image else f"{image}@{image_digest}"
        annotations = {
            f"{ANNOTATION_PREFIX}/id": identity.release_id,
            f"{ANNOTATION_PREFIX}/commit": identity.commit_sha,
            f"{ANNOTATION_PREFIX}/package-version": identity.package_version,
            f"{ANNOTATION_PREFIX}/image-digest": identity.image_digest,
        }
        if source_ref:
            annotations[f"{ANNOTATION_PREFIX}/source-ref"] = source_ref

        manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "labels": {"app": name, "ao.release.id": identity.release_id},
                "annotations": annotations,
            },
            "spec": {
                "template": {
                    "metadata": {"annotations": dict(annotations)},
                    "spec": {"containers": [{"name": name, "image": image_ref}]},
                }
            },
        }
        self.history.record(identity, manifest)
        return manifest


def build_release_identity(
    commit_sha: str,
    package_version: str,
    image_digest: str,
    source_ref: Optional[str] = None,
) -> ReleaseIdentity:
    _require_immutable("commit_sha", commit_sha)
    _require_immutable("package_version", package_version)
    _require_immutable("image_digest", image_digest)
    material = "|".join([commit_sha, package_version, image_digest])
    release_id = f"rel-{sha256(material.encode('utf-8')).hexdigest()[:16]}"
    return ReleaseIdentity(
        release_id=release_id,
        commit_sha=commit_sha,
        package_version=package_version,
        image_digest=image_digest,
        source_ref=source_ref,
    )


def _require_immutable(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseIdentityError(f"{field} is required for immutable release identity")
