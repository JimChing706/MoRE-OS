"""JSONL audit log producing who-did-what-why records (AOW-compatible).

Writes are queued to a background writer thread so the async event loop is
never blocked on file I/O. Reads flush the queue first for consistency.
"""

from __future__ import annotations

import io
import json
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class AuditRecord:
    id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:10]}")
    timestamp: float = field(default_factory=time.time)
    actor: str = "system"
    action: str = ""
    entity: str = ""
    payload: dict[str, object] = field(default_factory=dict)


class AuditLogger:
    """Thread-safe JSONL audit logger for AOW compliance.

    ``log()``/``write()`` enqueue records (O(1), non-blocking); a daemon
    writer thread drains the queue in batches and appends to the file via a
    persistent file handle. ``read_recent()`` and ``flush()`` block until all
    queued records are on disk.
    """

    _SENTINEL: AuditRecord | None = None

    def __init__(self, path: str | Path) -> None:
        """Initialize audit logger.

        Args:
            path: Path to the audit log file
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: "queue.Queue[AuditRecord | None]" = queue.Queue()
        self._fh: io.TextIOBase | None = None
        self._io_lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._writer_loop, name="audit-writer", daemon=True
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, record: AuditRecord) -> None:
        """Enqueue a single audit record (never blocks on I/O)."""
        if self._closed:
            return
        self._queue.put(record)

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

    def flush(self) -> None:
        """Block until all currently queued records are written to disk."""
        if self._closed:
            return
        self._queue.join()

    def close(self) -> None:
        """Flush pending records and stop the writer thread."""
        if self._closed:
            return
        self._closed = True
        self._queue.put(self._SENTINEL)
        self._queue.join()
        with self._io_lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None

    def read_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read the most recent audit records from the JSONL file.

        Uses reverse-chunked reading to avoid loading the entire file
        into memory — safe for multi-GB audit logs.
        """
        records: list[dict[str, Any]] = []
        try:
            if not self._path.exists():
                return records
            self.flush()
            with self._io_lock, self._path.open("rb") as fh:
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
        except Exception as exc:
            _log.error("Failed to read recent audit records: %s", exc)
        return records[:limit]

    # ------------------------------------------------------------------
    # Writer thread
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        while True:
            record = self._queue.get()
            if record is None:
                self._queue.task_done()
                return
            batch: list[AuditRecord] = [record]
            # Drain the queue in batches to amortize the write syscall cost.
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    batch.append(item)
            self._write_batch(batch)
            for _ in batch:
                self._queue.task_done()

    def _write_batch(self, records: list[AuditRecord]) -> None:
        try:
            with self._io_lock:
                if self._fh is None:
                    self._fh = self._path.open("a", encoding="utf-8")
                for rec in records:
                    self._fh.write(json.dumps(asdict(rec), ensure_ascii=False) + os.linesep)
                self._fh.flush()
        except OSError as exc:
            _log.error("Failed to write %d audit records: %s", len(records), exc)
