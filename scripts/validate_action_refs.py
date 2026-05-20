#!/usr/bin/env python3
"""Validate that external GitHub Actions are pinned to immutable SHAs."""

from __future__ import annotations

import re
import sys
from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")
USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#\s]+)")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files(root: Path) -> list[Path]:
    workflow_dir = root / WORKFLOW_DIR
    if not workflow_dir.exists():
        return []
    return sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")])


def _strip_yaml_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _is_external_github_action(action_ref: str) -> bool:
    if action_ref.startswith(("./", "../", "docker://")):
        return False
    return "/" in action_ref


def mutable_action_refs(root: Path) -> list[tuple[Path, int, str]]:
    problems: list[tuple[Path, int, str]] = []

    for workflow in _workflow_files(root):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = USES_PATTERN.match(line)
            if not match:
                continue

            action_ref = _strip_yaml_quotes(match.group(1))
            if not _is_external_github_action(action_ref):
                continue

            if "@" not in action_ref:
                problems.append((workflow, line_number, action_ref))
                continue

            _, ref = action_ref.rsplit("@", 1)
            if not FULL_SHA_PATTERN.fullmatch(ref):
                problems.append((workflow, line_number, action_ref))

    return problems


def main() -> int:
    problems = mutable_action_refs(Path.cwd())
    if not problems:
        print("All external GitHub Actions references are pinned to full commit SHAs.")
        return 0

    print("Mutable GitHub Actions references found:")
    for workflow, line_number, action_ref in problems:
        print(f"- {workflow}:{line_number}: {action_ref}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
