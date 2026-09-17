# -*- coding: utf-8 -*-
"""Small, durable run store for local background jobs.

The store intentionally keeps one JSON document per run. It avoids a database,
survives process restarts, and makes every formal run inspectable on disk.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
import uuid
from pathlib import Path


class RunStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.RLock()

    def _kind_dir(self, kind: str) -> Path:
        safe = "".join(c for c in str(kind) if c.isalnum() or c in "-_") or "run"
        return self.root / safe

    def _path(self, kind: str, run_id: str) -> Path:
        safe_id = Path(str(run_id)).name
        return self._kind_dir(kind) / f"{safe_id}.json"

    @staticmethod
    def _now() -> str:
        return _dt.datetime.now().isoformat(timespec="seconds")

    def _atomic_write(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def create(self, kind: str, *, request: dict | None = None, message: str = "") -> dict:
        now = self._now()
        run_id = f"{now[:10].replace('-', '')}-{now[11:19].replace(':', '')}-{uuid.uuid4().hex[:8]}"
        record = {
            "schema_version": 1,
            "run_id": run_id,
            "kind": kind,
            "state": "queued",
            "progress": 0,
            "done": 0,
            "total": 0,
            "message": message,
            "request": request or {},
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._atomic_write(self._path(kind, run_id), record)
        return record

    def update(self, kind: str, run_id: str, **changes) -> dict:
        with self._lock:
            record = self.get(kind, run_id) or {
                "schema_version": 1,
                "run_id": run_id,
                "kind": kind,
                "created_at": self._now(),
            }
            record.update(changes)
            record["updated_at"] = self._now()
            self._atomic_write(self._path(kind, run_id), record)
            return record

    def get(self, kind: str, run_id: str) -> dict | None:
        path = self._path(kind, run_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def latest(self, kind: str, *, states: tuple[str, ...] | None = None) -> dict | None:
        folder = self._kind_dir(kind)
        if not folder.is_dir():
            return None
        records = []
        for path in folder.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if states and item.get("state") not in states:
                continue
            records.append(item)
        return max(records, key=lambda item: item.get("updated_at", ""), default=None)

    def recover_interrupted(self, kind: str) -> dict | None:
        """Startup only: expose the newest run and reconcile abandoned workers."""
        with self._lock:
            records = self.list(kind, limit=None)
            latest = max(records, key=lambda r: r.get("created_at") or r.get("updated_at", ""), default=None)
            for record in records:
                if record.get("state") not in {"queued", "running"}:
                    continue
                message = "服务重启导致评测中断；请检查最后进度后手动重试"
                changes = dict(state="error", message=message, error={"type": "InterruptedRun", "message": message})
                try:
                    recovered = self.update(kind, record["run_id"], **changes)
                except OSError as exc:
                    logging.getLogger(__name__).error("Cannot persist interrupted run %s: %s", record["run_id"], exc)
                    recovered = dict(record, state="error", message=f"中断状态保存失败：{exc}", error={"type": "PersistenceError", "message": str(exc)})
                if record is latest:
                    latest = recovered
            return latest

    def list(self, kind: str, limit: int | None = 20) -> list[dict]:
        folder = self._kind_dir(kind)
        if not folder.is_dir():
            return []
        rows = []
        for path in folder.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append(item)
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return rows if limit is None else rows[: max(1, int(limit))]
