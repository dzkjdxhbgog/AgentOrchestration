#!/usr/bin/env python3
"""Validate CI runner image provenance before build steps run."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DEFAULT_MAX_IMAGE_AGE_HOURS = 168


def split_csv(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    normalized = value.replace("\n", ",").replace(";", ",")
    return {part.strip().lower() for part in normalized.split(",") if part.strip()}


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bool_env(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def validate_provenance(
    env: Mapping[str, str],
    *,
    now: Optional[datetime] = None,
) -> tuple[bool, list[str], list[str]]:
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    details: list[str] = []

    strict = bool_env(env.get("AO_STRICT_RUNNER_PREFLIGHT"))
    runner_labels = split_csv(env.get("AO_RUNNER_LABELS"))
    required_labels = split_csv(env.get("AO_APPROVED_RUNNER_LABELS"))
    digest = (env.get("AO_RUNNER_IMAGE_DIGEST") or "").strip().lower()
    approved_digests = split_csv(env.get("AO_APPROVED_RUNNER_DIGESTS"))
    built_at_raw = env.get("AO_RUNNER_IMAGE_BUILT_AT")

    if not strict and "self-hosted" not in runner_labels:
        details.append("non-strict GitHub-hosted runner preflight")
        return True, errors, details

    if not digest:
        errors.append("AO_RUNNER_IMAGE_DIGEST is required")
    elif not DIGEST_RE.match(digest):
        errors.append("runner image digest must use sha256:<64 hex>")
    elif approved_digests and digest not in approved_digests:
        errors.append("runner image digest is not in the approved list")
    details.append(f"runner_image_digest={digest or '<missing>'}")

    try:
        built_at = parse_timestamp(built_at_raw)
    except ValueError:
        built_at = None
        errors.append("AO_RUNNER_IMAGE_BUILT_AT is not a valid timestamp")
    if built_at is None:
        errors.append("AO_RUNNER_IMAGE_BUILT_AT is required")
        details.append("runner_image_built_at=<missing>")
    else:
        max_age = int(
            env.get("AO_RUNNER_MAX_IMAGE_AGE_HOURS")
            or DEFAULT_MAX_IMAGE_AGE_HOURS
        )
        age_seconds = (now - built_at).total_seconds()
        if age_seconds < -300:
            errors.append("runner image build timestamp is in the future")
        if age_seconds > max_age * 3600:
            errors.append("runner image is older than the approved max age")
        details.append(f"runner_image_built_at={built_at.isoformat()}")
        details.append(f"runner_image_age_hours={age_seconds / 3600:.2f}")

    missing_labels = required_labels - runner_labels
    if missing_labels:
        errors.append(
            "runner labels missing approved labels: "
            + ", ".join(sorted(missing_labels))
        )
    details.append(
        "runner_labels="
        + (",".join(sorted(runner_labels)) if runner_labels else "<missing>")
    )

    return not errors, errors, details


def write_summary(
    summary_path: Optional[str],
    ok: bool,
    errors: Iterable[str],
    details: Iterable[str],
) -> None:
    if not summary_path:
        return
    status = "passed" if ok else "failed"
    lines = [f"## Runner provenance preflight {status}", ""]
    lines.extend(f"- {detail}" for detail in details)
    errors = list(errors)
    if errors:
        lines.append("")
        lines.append("### Blocking errors")
        lines.extend(f"- {error}" for error in errors)
    Path(summary_path).open("a", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default=os.getenv("GITHUB_STEP_SUMMARY"))
    args = parser.parse_args()

    ok, errors, details = validate_provenance(os.environ)
    write_summary(args.summary, ok, errors, details)
    if not ok:
        for error in errors:
            print(f"runner provenance preflight failed: {error}", file=sys.stderr)
        return 1
    print("runner provenance preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
