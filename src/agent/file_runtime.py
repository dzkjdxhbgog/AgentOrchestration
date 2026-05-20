"""Deterministic file runtime state for agent task executions."""

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional


class RunFileRuntimeError(RuntimeError):
    """Raised when a run cannot safely enter the file runtime."""


class RunFileRuntime:
    def __init__(self, base_path: Optional[str] = None):
        root = Path(base_path or tempfile.mkdtemp(prefix="ao_run_files_"))
        self.base_path = root
        self.runs_path = root / "runs"
        self.outcomes_path = root / "outcomes"
        self.runs_path.mkdir(parents=True, exist_ok=True)
        self.outcomes_path.mkdir(parents=True, exist_ok=True)

    def begin(
        self,
        execution_id: str,
        agent_id: str,
        task_id: Optional[str],
        attempt: int = 0,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        existing = self.get_outcome(execution_id)
        if existing is not None:
            return existing
        if attempt >= max_retries:
            outcome = self._build_outcome(
                execution_id,
                agent_id,
                task_id,
                "failed",
                error="retry limit exceeded before file runtime entry",
                attempt=attempt,
            )
            self._write_outcome(execution_id, outcome)
            raise RunFileRuntimeError(outcome["error"])

        run_path = self._run_path(execution_id)
        run_path.mkdir(parents=True, exist_ok=True)
        lock_path = run_path / "run.lock"
        try:
            with lock_path.open("x", encoding="utf-8") as lock_file:
                lock_file.write(str(time.time()))
        except FileExistsError as exc:
            raise RunFileRuntimeError(f"stale runtime lock for {execution_id}") from exc

        state = {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "status": "running",
            "attempt": attempt,
            "max_retries": max_retries,
            "started_at": time.time(),
        }
        self._atomic_write_json(run_path / "state.json", state)
        return state

    def finalize(
        self,
        execution_id: str,
        agent_id: str,
        task_id: Optional[str],
        status: str,
        result: Any = None,
        error: Optional[str] = None,
        attempt: int = 0,
    ) -> Dict[str, Any]:
        existing = self.get_outcome(execution_id)
        if existing is not None:
            self.cleanup(execution_id)
            return existing

        outcome = self._build_outcome(
            execution_id,
            agent_id,
            task_id,
            status,
            result=result,
            error=error,
            attempt=attempt,
        )
        self._write_outcome(execution_id, outcome)
        self.cleanup(execution_id)
        return outcome

    def cleanup(self, execution_id: str) -> None:
        shutil.rmtree(self._run_path(execution_id), ignore_errors=True)

    def get_outcome(self, execution_id: str) -> Optional[Dict[str, Any]]:
        outcome_path = self._outcome_path(execution_id)
        if not outcome_path.exists():
            return None
        with outcome_path.open("r", encoding="utf-8") as outcome_file:
            return json.load(outcome_file)

    def has_stale_lock(self, execution_id: str) -> bool:
        return (self._run_path(execution_id) / "run.lock").exists()

    def has_run_files(self, execution_id: str) -> bool:
        return self._run_path(execution_id).exists()

    def _run_path(self, execution_id: str) -> Path:
        return self.runs_path / execution_id

    def _outcome_path(self, execution_id: str) -> Path:
        return self.outcomes_path / f"{execution_id}.json"

    def _build_outcome(
        self,
        execution_id: str,
        agent_id: str,
        task_id: Optional[str],
        status: str,
        result: Any = None,
        error: Optional[str] = None,
        attempt: int = 0,
    ) -> Dict[str, Any]:
        return {
            "execution_id": execution_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "status": status,
            "result": result,
            "error": error,
            "attempt": attempt,
            "completed_at": time.time(),
        }

    def _write_outcome(self, execution_id: str, outcome: Dict[str, Any]) -> None:
        self._atomic_write_json(self._outcome_path(execution_id), outcome)

    def _atomic_write_json(self, path: Path, value: Dict[str, Any]) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as tmp_file:
            json.dump(value, tmp_file, sort_keys=True)
        tmp_path.replace(path)
