# Runtime Compose Configuration

Sidecar containers run with read-only root filesystems. Any path that must remain writable is declared in the service label `com.agent-orchestration.writable-paths` and must be backed by a matching `tmpfs` mount.

Current sidecar writable paths:

- `/tmp`: transient scratch space for helper tools.
- `/var/run/agent-orchestration`: runtime sockets and short-lived coordination files.

Run `python scripts/validate_sidecar_compose.py infra/docker-compose.yml` before changing sidecar services.
