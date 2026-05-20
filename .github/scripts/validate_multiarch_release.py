"""Validate per-architecture release digests before publishing a manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


DEFAULT_REQUIRED_ARCHES = ("linux/amd64", "linux/arm64")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PASSING_STATUSES = {"pass", "passed", "success", "successful", "ok", "true"}


class ReleaseValidationError(ValueError):
    """Raised when a release digest manifest is unsafe to publish."""


def _normalize_status(value: Any) -> str:
    if isinstance(value, bool):
        return "passed" if value else "failed"
    return str(value or "").strip().lower()


def _is_passing(value: Any) -> bool:
    return _normalize_status(value) in PASSING_STATUSES


def _entry_platform(entry: Dict[str, Any]) -> str:
    return str(
        entry.get("platform") or entry.get("architecture") or entry.get("arch") or ""
    ).strip()


def _entry_test_status(entry: Dict[str, Any]) -> Any:
    return entry.get("test_status", entry.get("tests", entry.get("test")))


def _entry_scan_status(entry: Dict[str, Any]) -> Any:
    return entry.get("scan_status", entry.get("scan"))


def _normalize_entries(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("architectures"), list):
        return [dict(entry) for entry in payload["architectures"]]

    if isinstance(payload, dict):
        entries = []
        for platform, details in payload.items():
            if not isinstance(details, dict):
                raise ReleaseValidationError(f"{platform} entry must be an object")
            entry = dict(details)
            entry.setdefault("platform", platform)
            entries.append(entry)
        return entries

    raise ReleaseValidationError(
        "digest manifest must be an object or contain an architectures list"
    )


def validate_digest_manifest(
    payload: Any,
    required_arches: Sequence[str] = DEFAULT_REQUIRED_ARCHES,
) -> List[Dict[str, str]]:
    """Return validated digest entries or raise before manifest publication."""
    required = list(required_arches)
    allowed = set(required)
    entries = _normalize_entries(payload)
    validated: Dict[str, Dict[str, str]] = {}
    errors: List[str] = []

    for entry in entries:
        platform = _entry_platform(entry)
        digest = str(entry.get("digest") or "").strip()
        test_status = _entry_test_status(entry)
        scan_status = _entry_scan_status(entry)

        if not platform:
            errors.append("entry is missing platform")
            continue
        if platform not in allowed:
            errors.append(f"{platform} is not part of the release architecture set")
            continue
        if platform in validated:
            errors.append(f"{platform} appears more than once")
            continue
        if not DIGEST_RE.match(digest):
            errors.append(f"{platform} has an invalid image digest")
        if not _is_passing(test_status):
            errors.append(f"{platform} is missing passing tests")
        if not _is_passing(scan_status):
            errors.append(f"{platform} is missing a passing scan")

        if not errors or not any(error.startswith(platform) for error in errors):
            validated[platform] = {
                "platform": platform,
                "digest": digest,
                "test_status": "passed",
                "scan_status": "passed",
            }

    for platform in required:
        if platform not in validated:
            errors.append(f"{platform} is missing from the digest manifest")

    if errors:
        raise ReleaseValidationError("; ".join(errors))

    return [validated[platform] for platform in required]


def render_summary(entries: Iterable[Dict[str, str]]) -> str:
    lines = [
        "## Multi-architecture image validation",
        "",
        "| Architecture | Digest | Tests | Scan |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        lines.append(
            f"| {entry['platform']} | `{entry['digest']}` | "
            f"{entry['test_status']} | {entry['scan_status']} |"
        )
    return "\n".join(lines) + "\n"


def write_github_summary(summary: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        type=Path,
        help="Path to the per-architecture digest manifest JSON",
    )
    parser.add_argument("--output", type=Path, help="Write the validated digest manifest JSON")
    parser.add_argument(
        "--required",
        nargs="+",
        default=list(DEFAULT_REQUIRED_ARCHES),
        help="Required platform strings, for example linux/amd64 linux/arm64",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        entries = validate_digest_manifest(payload, args.required)
    except (OSError, json.JSONDecodeError, ReleaseValidationError) as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1

    summary = render_summary(entries)
    print(summary, end="")
    write_github_summary(summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"architectures": entries}, indent=2) + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
