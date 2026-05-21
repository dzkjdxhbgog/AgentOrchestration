import socket

import pytest

from src.orchestrator import healthcheck


def test_scheduler_dependency_checks_parse_queue_and_storage_urls(monkeypatch):
    monkeypatch.setenv("SCHEDULER_QUEUE_URL", "redis://queue.local/0")
    monkeypatch.setenv("SCHEDULER_STORAGE_DSN", "postgresql://user:pass@db.local/app")

    checks = healthcheck.scheduler_dependency_checks()

    assert checks == [
        healthcheck.DependencyCheck("queue", "queue.local", 6379),
        healthcheck.DependencyCheck("storage", "db.local", 5432),
    ]


def test_scheduler_healthcheck_fails_when_dependencies_are_missing(monkeypatch):
    monkeypatch.delenv("SCHEDULER_QUEUE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("SCHEDULER_STORAGE_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    healthy, failures = healthcheck.scheduler_is_healthy()

    assert healthy is False
    assert failures == ["no scheduler dependency URLs configured"]


def test_scheduler_healthcheck_reports_queue_dependency_failure(monkeypatch):
    monkeypatch.setenv("SCHEDULER_QUEUE_URL", "redis://queue.local:6380/0")

    def fail_connection(address, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(socket, "create_connection", fail_connection)

    healthy, failures = healthcheck.scheduler_is_healthy()

    assert healthy is False
    assert "queue unavailable at queue.local:6380" in failures[0]


def test_scheduler_healthcheck_succeeds_when_dependencies_accept_connections(monkeypatch):
    monkeypatch.setenv("SCHEDULER_QUEUE_URL", "redis://queue.local:6379/0")
    monkeypatch.setenv("SCHEDULER_STORAGE_DSN", "postgresql://db.local:5432/app")
    opened = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def connect(address, timeout):
        opened.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr(socket, "create_connection", connect)

    healthy, failures = healthcheck.scheduler_is_healthy(timeout=1.5)

    assert healthy is True
    assert failures == []
    assert opened == [(("queue.local", 6379), 1.5), (("db.local", 5432), 1.5)]


def test_scheduler_docker_assets_declare_healthcheck_and_startup_grace():
    dockerfile = open("infra/scheduler.Dockerfile", encoding="utf-8").read()
    compose = open("infra/docker-compose.yml", encoding="utf-8").read()

    assert "HEALTHCHECK" in dockerfile
    assert "python -m src.orchestrator.healthcheck" in dockerfile
    assert "python\", \"-m\", \"src.orchestrator.scheduler_service" in dockerfile
    assert "healthcheck:" in compose
    assert "start_period: 45s" in compose
    assert "condition: service_healthy" in compose
