"""Fail package publishing unless the GitHub ref is release-approved."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
RELEASE_BRANCH_PREFIX = "release/"
REF_OVERRIDE_INPUTS = {
    "branch",
    "commit",
    "github_ref",
    "ref",
    "sha",
    "source_ref",
    "tag",
}


@dataclass(frozen=True)
class PublishRefContext:
    event_name: str
    ref: str
    ref_name: str
    ref_type: str
    ref_protected: bool
    event_path: str | None = None

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> "PublishRefContext":
        env = environ or os.environ
        return cls(
            event_name=env.get("GITHUB_EVENT_NAME", ""),
            ref=env.get("GITHUB_REF", ""),
            ref_name=env.get("GITHUB_REF_NAME", ""),
            ref_type=env.get("GITHUB_REF_TYPE", ""),
            ref_protected=env.get("GITHUB_REF_PROTECTED", "").lower()
            == "true",
            event_path=env.get("GITHUB_EVENT_PATH") or None,
        )


def _workflow_dispatch_inputs(event_path: str | None) -> set[str]:
    if not event_path:
        return set()

    path = Path(event_path)
    if not path.is_file():
        return set()

    payload = json.loads(path.read_text(encoding="utf-8"))
    inputs = payload.get("inputs") or {}
    return {str(name).lower() for name in inputs}


def _verify_signed_tag(tag_name: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "tag", "-v", tag_name],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0, result.stderr or result.stdout


def _is_release_branch(ref_name: str) -> bool:
    return ref_name == "main" or ref_name.startswith(RELEASE_BRANCH_PREFIX)


def validate_publish_ref(
    ctx: PublishRefContext,
    tag_verifier: Callable[[str], tuple[bool, str]] = _verify_signed_tag,
) -> tuple[bool, str]:
    if ctx.event_name == "workflow_dispatch":
        overrides = _workflow_dispatch_inputs(ctx.event_path)
        blocked = sorted(overrides.intersection(REF_OVERRIDE_INPUTS))
        if blocked:
            return (
                False,
                "workflow_dispatch ref override inputs are not allowed: "
                + ", ".join(blocked),
            )

    if ctx.ref_type == "branch":
        if not _is_release_branch(ctx.ref_name):
            return False, f"branch {ctx.ref_name!r} is not a release ref"
        if not ctx.ref_protected:
            return False, f"branch {ctx.ref_name!r} is not protected"
        return True, f"protected release branch {ctx.ref_name!r} accepted"

    if ctx.ref_type == "tag":
        if not RELEASE_TAG.fullmatch(ctx.ref_name):
            return False, f"tag {ctx.ref_name!r} does not match release policy"

        verified, output = tag_verifier(ctx.ref_name)
        if not verified:
            return (
                False,
                "release tag signature could not be verified: " + output,
            )
        return True, f"signed release tag {ctx.ref_name!r} accepted"

    return False, f"unsupported GitHub ref type {ctx.ref_type!r}"


def main() -> int:
    valid, message = validate_publish_ref(PublishRefContext.from_env())
    print(message)
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
