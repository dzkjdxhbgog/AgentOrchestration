from pathlib import Path

from scripts.validate_sidecar_compose import load_compose, validate_compose


def sidecar_service(**overrides):
    service = {
        "image": "busybox:1.36",
        "read_only": True,
        "tmpfs": ["/tmp", "/var/run/agent-orchestration"],
        "labels": {
            "com.agent-orchestration.role": "sidecar",
            "com.agent-orchestration.writable-paths": (
                "/tmp,/var/run/agent-orchestration"
            ),
        },
    }
    service.update(overrides)
    return service


def test_repository_sidecar_compose_is_hardened():
    compose = load_compose(Path("infra/docker-compose.yml"))

    assert validate_compose(compose) == []


def test_sidecar_without_read_only_filesystem_is_rejected():
    compose = {"services": {"metrics-sidecar": sidecar_service(read_only=False)}}

    errors = validate_compose(compose)

    assert errors == ["metrics-sidecar: sidecar must set read_only: true"]


def test_sidecar_without_documented_writable_paths_is_rejected():
    service = sidecar_service(labels={"com.agent-orchestration.role": "sidecar"})
    compose = {"services": {"metrics-sidecar": service}}

    errors = validate_compose(compose)

    assert errors == [
        "metrics-sidecar: sidecar must document writable paths in "
        "com.agent-orchestration.writable-paths"
    ]


def test_sidecar_documented_paths_must_have_tmpfs_mounts():
    compose = {"services": {"metrics-sidecar": sidecar_service(tmpfs=["/tmp"])}}

    errors = validate_compose(compose)

    assert errors == [
        "metrics-sidecar: documented writable paths missing tmpfs mounts: "
        "/var/run/agent-orchestration"
    ]


def test_non_sidecar_services_do_not_require_sidecar_hardening():
    compose = {"services": {"agent-worker": {"image": "python:3.11-slim"}}}

    assert validate_compose(compose) == []
