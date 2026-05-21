"""Container entry point for scheduler deployments."""

import signal
import time

from src.orchestrator.scheduler import TaskScheduler


def main() -> int:
    running = True
    scheduler = TaskScheduler()

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        time.sleep(1.0)

    return 0 if scheduler is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
