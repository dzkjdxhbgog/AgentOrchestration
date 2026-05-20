"""Validate sidecar hardening in Docker Compose files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import yaml


ROLE_LABEL = "com.agent-orchestration.role"
WRITABLE_PATHS_LABEL = "com.agent-orchestration.writable-paths"


def _label_map(labels: Any) -> Dict[str, str]:
    if labels is None:
        return {}
    if isinstance(labels, dict):
        return {str(key): str(value) for key, value in labels.items()}
    if isinstance(labels, list):
        mapped: Dict[str, str] = {}
        for label in labels:
            if not isinstance(label, str):
                continue
            key, separator, value = label.partition("=")
            if separator:
                mapped[key] = value
        return mapped
    return {}


def _tmpfs_paths(tmpfs_entries: Any) -> Set[str]:
    if tmpfs_entries is None:
        return set()
    if not isinstance(tmpfs_entries, list):
        return set()

    paths: Set[str] = set()
    for entry in tmpfs_entries:
        if isinstance(entry, str):
            path = entry.split(":", 1)[0].strip()
            if path:
                paths.add(path)
        elif isinstance(entry, dict):
            target = entry.get("target") or entry.get("source")
            if target:
                paths.add(str(target))
    return paths


def _documented_writable_paths(labels: Dict[str, str]) -> Set[str]:
    raw_value = labels.get(WRITABLE_PATHS_LABEL, "")
    return {path.strip() for path in raw_value.split(",") if path.strip()}


def _is_sidecar(service_name: str, service: Dict[str, Any]) -> bool:
    labels = _label_map(service.get("labels"))
    return service_name.endswith("-sidecar") or labels.get(ROLE_LABEL) == "sidecar"


def validate_compose(compose: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    services = compose.get("services", {})
    if not isinstance(services, dict):
        return ["compose file must define a services mapping"]

    for service_name, service in services.items():
        if not isinstance(service, dict) or not _is_sidecar(service_name, service):
            continue

        labels = _label_map(service.get("labels"))
        documented_paths = _documented_writable_paths(labels)
        tmpfs_paths = _tmpfs_paths(service.get("tmpfs"))

        if service.get("read_only") is not True:
            errors.append(f"{service_name}: sidecar must set read_only: true")
        if not documented_paths:
            errors.append(
                f"{service_name}: sidecar must document writable paths in "
                f"{WRITABLE_PATHS_LABEL}"
            )
        missing_tmpfs = sorted(documented_paths - tmpfs_paths)
        if missing_tmpfs:
            errors.append(
                f"{service_name}: documented writable paths missing tmpfs mounts: "
                f"{', '.join(missing_tmpfs)}"
            )

    return errors


def load_compose(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a Compose mapping")
    return data


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose_file", type=Path)
    args = parser.parse_args(argv)

    errors = validate_compose(load_compose(args.compose_file))
    if errors:
        for error in errors:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
