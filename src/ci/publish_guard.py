"""Validate release refs before package registry authentication."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass


RELEASE_TAG = re.compile(r"^refs/tags/v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class PublishRefContext:
    ref: str
    ref_protected: bool = False
    signed_tag: bool = False
    event_name: str = "push"
    manual_ref_input: str = ""


class PublishRefError(ValueError):
    """Raised when a registry publish run is not allowed."""


def validate_publish_ref(context: PublishRefContext) -> None:
    """Require a protected branch or a signed release tag.

    The guard trusts only the actual GitHub ref context. workflow_dispatch inputs
    may document intent, but they cannot replace or loosen the checked ref.
    """

    ref = context.ref.strip()
    manual_ref = context.manual_ref_input.strip()

    if not ref:
        raise PublishRefError("GitHub ref is required for package publishing")

    if context.event_name == "workflow_dispatch" and manual_ref and manual_ref != ref:
        raise PublishRefError("workflow_dispatch input cannot override the running ref")

    if ref.startswith("refs/heads/"):
        if context.ref_protected:
            return
        raise PublishRefError("package publishing requires a protected branch ref")

    if ref.startswith("refs/tags/"):
        if not RELEASE_TAG.match(ref):
            raise PublishRefError("package publishing requires a release tag named vX.Y.Z")
        if context.signed_tag:
            return
        raise PublishRefError("package publishing requires a signed release tag")

    raise PublishRefError("package publishing requires a branch or tag ref")


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate registry publish source ref")
    parser.add_argument("--ref", required=True)
    parser.add_argument("--ref-protected", default="false")
    parser.add_argument("--signed-tag", default="false")
    parser.add_argument("--event", default="push")
    parser.add_argument("--manual-ref-input", default="")
    args = parser.parse_args()

    context = PublishRefContext(
        ref=args.ref,
        ref_protected=_bool(args.ref_protected),
        signed_tag=_bool(args.signed_tag),
        event_name=args.event,
        manual_ref_input=args.manual_ref_input,
    )

    try:
        validate_publish_ref(context)
    except PublishRefError as exc:
        print(f"::error::{exc}")
        return 1

    print("Registry publish ref validated before authentication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
