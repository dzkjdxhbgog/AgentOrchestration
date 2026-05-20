"""Feature flag rollout validation."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


class FeatureFlagValidationError(ValueError):
    """Raised when feature flag rollout validation fails."""

    def __init__(self, violations: Sequence[str]):
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


@dataclass(frozen=True)
class FeatureFlagSpec:
    name: str
    default: Any
    owner: str
    description: str
    services: Tuple[str, ...] = ("scheduler", "worker")
    required: bool = True


def _coerce_spec(entry: Mapping[str, Any]) -> FeatureFlagSpec:
    violations: List[str] = []
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        violations.append("feature flag entry is missing name")

    if "default" not in entry:
        label = name if isinstance(name, str) and name else "<unnamed>"
        violations.append(f"feature flag '{label}' is missing documented default")

    owner = entry.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        label = name if isinstance(name, str) and name else "<unnamed>"
        violations.append(f"feature flag '{label}' is missing owner")

    description = entry.get("description")
    if not isinstance(description, str) or not description.strip():
        label = name if isinstance(name, str) and name else "<unnamed>"
        violations.append(f"feature flag '{label}' is missing description")

    services = entry.get("services")
    if services is None:
        services = ["scheduler", "worker"]

    if not isinstance(services, (list, tuple)) or not all(
        isinstance(item, str) and item for item in services
    ):
        label = name if isinstance(name, str) and name else "<unnamed>"
        violations.append(f"feature flag '{label}' must list target services")

    if violations:
        raise FeatureFlagValidationError(violations)

    return FeatureFlagSpec(
        name=name.strip(),
        default=entry["default"],
        owner=owner.strip(),
        description=description.strip(),
        services=tuple(services),
        required=bool(entry.get("required", True)),
    )


def load_feature_flag_manifest(path: Union[str, Path]) -> Tuple[FeatureFlagSpec, ...]:
    with open(path, encoding="utf-8") as file:
        raw_manifest = json.load(file)

    if not isinstance(raw_manifest, list):
        raise FeatureFlagValidationError(["feature flag manifest must be a list"])

    return tuple(_coerce_spec(entry) for entry in raw_manifest)


def load_rendered_feature_flags(path: Union[str, Path]) -> Dict[str, Dict[str, Any]]:
    with open(path, encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise FeatureFlagValidationError(["rendered feature flags must be a service mapping"])

    services = data.get("services", data)
    if not isinstance(services, dict):
        raise FeatureFlagValidationError(["rendered feature flags must contain service mappings"])

    normalized: Dict[str, Dict[str, Any]] = {}
    for service, values in services.items():
        if not isinstance(service, str) or not service:
            raise FeatureFlagValidationError(["rendered feature flag service name is invalid"])

        if isinstance(values, dict) and isinstance(values.get("feature_flags"), dict):
            values = values["feature_flags"]

        if not isinstance(values, dict):
            raise FeatureFlagValidationError(
                [f"rendered feature flags for '{service}' must be a mapping"]
            )

        normalized[service] = dict(values)

    return normalized


def validate_feature_flag_manifest(
    manifest: Iterable[Union[Mapping[str, Any], FeatureFlagSpec]],
) -> Tuple[FeatureFlagSpec, ...]:
    specs: List[FeatureFlagSpec] = []
    seen: set[str] = set()
    violations: List[str] = []

    for entry in manifest:
        spec = entry if isinstance(entry, FeatureFlagSpec) else _coerce_spec(entry)
        if not spec.name.strip():
            violations.append("feature flag entry is missing name")
        if not spec.owner.strip():
            violations.append(f"feature flag '{spec.name}' is missing owner")
        if not spec.description.strip():
            violations.append(f"feature flag '{spec.name}' is missing description")
        if not spec.services:
            violations.append(f"feature flag '{spec.name}' must list target services")
        if spec.name in seen:
            violations.append(f"feature flag '{spec.name}' is duplicated")
        seen.add(spec.name)
        specs.append(spec)

    if violations:
        raise FeatureFlagValidationError(violations)

    return tuple(specs)


def validate_rendered_feature_flags(
    rendered_by_service: Mapping[str, Mapping[str, Any]],
    manifest: Iterable[Union[Mapping[str, Any], FeatureFlagSpec]],
) -> None:
    specs = validate_feature_flag_manifest(manifest)
    violations: List[str] = []

    for spec in specs:
        if not spec.required:
            continue

        expected_owner = f"owner={spec.owner}"
        observed_services: List[str] = []
        first_service: Optional[str] = None
        first_value: Any = None
        first_value_set = False

        for service in spec.services:
            values = rendered_by_service.get(service)
            if values is None:
                violations.append(
                    f"service '{service}' is missing rendered feature flags "
                    f"for '{spec.name}' ({expected_owner})"
                )
                continue

            if spec.name not in values:
                violations.append(
                    f"service '{service}' is missing required feature flag "
                    f"'{spec.name}' ({expected_owner})"
                )
                continue

            observed_services.append(service)
            value = values[spec.name]
            if value != spec.default:
                violations.append(
                    f"service '{service}' feature flag '{spec.name}' does not "
                    f"match documented default ({expected_owner})"
                )

            if not first_value_set:
                first_service = service
                first_value = value
                first_value_set = True
            elif value != first_value:
                violations.append(
                    f"feature flag '{spec.name}' differs between "
                    f"'{first_service}' and '{service}' ({expected_owner})"
                )

        if not observed_services and spec.services:
            violations.append(
                f"required feature flag '{spec.name}' was not rendered by any "
                f"target service ({expected_owner})"
            )

    if violations:
        raise FeatureFlagValidationError(violations)
