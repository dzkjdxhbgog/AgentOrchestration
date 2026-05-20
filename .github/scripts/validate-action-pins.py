#!/usr/bin/env python3
"""Fail CI when external GitHub Actions are not pinned to full commit SHAs."""

from pathlib import Path
import re
import sys


WORKFLOW_DIR = Path(".github/workflows")
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
USES_LINE = re.compile(r"^\s*uses:\s*['\"]?([^'\"\s#]+)")


def is_local_action(ref: str) -> bool:
    return ref.startswith("./") or ref.startswith("../")


def is_docker_action(ref: str) -> bool:
    return ref.startswith("docker://")


def find_mutable_refs() -> list[str]:
    failures: list[str] = []
    for workflow in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            match = USES_LINE.match(line)
            if not match:
                continue

            ref = match.group(1)
            if is_local_action(ref) or is_docker_action(ref):
                continue

            if "@" not in ref:
                failures.append(f"{workflow}:{line_number}: missing @ref in {ref}")
                continue

            version = ref.rsplit("@", 1)[1]
            if not FULL_SHA.fullmatch(version):
                failures.append(f"{workflow}:{line_number}: pin {ref} to a full 40-character commit SHA")

    return failures


def main() -> int:
    failures = find_mutable_refs()
    if not failures:
        print("All external GitHub Actions are pinned to full commit SHAs.")
        return 0

    print("Mutable GitHub Actions references found:")
    for failure in failures:
        print(f"- {failure}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
