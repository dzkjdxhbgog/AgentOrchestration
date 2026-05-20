#!/usr/bin/env python3
"""Validate that every release artifact reached a signed state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


class ReleaseSigningError(ValueError):
    """Raised when a release signing summary is incomplete."""


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseSigningError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseSigningError(
            f"manifest is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise ReleaseSigningError("manifest must be a JSON object")
    return data


def _iter_artifacts(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseSigningError("manifest must contain artifacts")

    for index, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, dict):
            raise ReleaseSigningError(f"artifact {index} must be an object")
        yield artifact


def validate_release_signing_summary(path: Path) -> int:
    """Return the signed artifact count or raise for partial states."""

    manifest = _load_manifest(path)
    signed_count = 0

    for index, artifact in enumerate(_iter_artifacts(manifest), start=1):
        name = artifact.get("name") or f"artifact {index}"
        status = artifact.get("status")
        if status != "signed":
            raise ReleaseSigningError(
                f"{name} is not fully signed; status={status!r}"
            )

        digest = artifact.get("digest")
        signature = artifact.get("signature")
        if not isinstance(digest, str) or not digest.strip():
            raise ReleaseSigningError(f"{name} is missing a digest")
        if not isinstance(signature, str) or not signature.strip():
            raise ReleaseSigningError(f"{name} is missing a signature")

        signed_count += 1

    return signed_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if a release signing manifest is incomplete."
    )
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)

    try:
        signed_count = validate_release_signing_summary(args.manifest)
    except ReleaseSigningError as exc:
        print(f"Release signing summary failed: {exc}", file=sys.stderr)
        return 1

    print(f"Release signing summary OK: {signed_count} artifacts signed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
