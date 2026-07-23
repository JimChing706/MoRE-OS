"""JSONL audit log producing who-did-what-why records (AOW-compatible)."""

from __future__ import annotations

import io
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AuditRecord:
    id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:10]}")
    timestamp: float = field(default_factory=time.time)
    actor: str = "system"
    action: str = ""
    entity: str = ""
    payload: dict[str, object] = field(default_factory=dict)


class AuditLogger:
    """Thread-safe JSONL audit logger for AOW compliance."""

    def __init__(self, path: str | Path) -> None:
        """Initialize audit logger.

        Args:
            path: Path to the audit log file
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: AuditRecord) -> None:
        """Write a single audit record to the log file.

        Args:
            record: AuditRecord to write
        """
        line = json.dumps(asdict(record), ensure_ascii=False) + os.linesep
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def log(self, actor: str, action: str, entity: str, **payload: object) -> AuditRecord:
        """Log an audit event.

        Args:
            actor: Who performed the action (user, system, agent)
            action: What was done (create, update, delete, execute)
            entity: What was affected (task, file, config)
            **payload: Additional context data

        Returns:
            The created AuditRecord
        """
        record = AuditRecord(actor=actor, action=action, entity=entity, payload=payload)
        self.write(record)
        return record

    def read_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read the most recent audit records from the JSONL file.

        Uses reverse-chunked reading to avoid loading the entire file
        into memory — safe for multi-GB audit logs.
        """
        records: list[dict[str, Any]] = []
        try:
            if not self._path.exists():
                return records
            with self._lock, self._path.open("rb") as fh:
                chunk_size = max(8192, limit * 256)
                fh.seek(0, io.SEEK_END)
                file_size = fh.tell()
                if file_size == 0:
                    return records

                buf = bytearray()
                remaining = file_size
                while remaining > 0 and len(records) < limit:
                    read_size = min(chunk_size, remaining)
                    remaining -= read_size
                    fh.seek(remaining)
                    chunk = fh.read(read_size)
                    buf = bytearray(chunk) + buf
                    raw = buf.decode("utf-8", errors="replace")
                    lines = raw.split(os.linesep)
                    buf = bytearray(lines[0].encode("utf-8", errors="replace"))
                    for line in reversed(lines[1:]):
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                            if len(records) >= limit:
                                break
                leftover = buf.decode("utf-8", errors="replace").strip()
                if leftover and len(records) < limit:
                    try:
                        records.append(json.loads(leftover))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return records[:limit]
