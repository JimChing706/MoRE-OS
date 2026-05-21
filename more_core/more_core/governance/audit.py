"""JSONL audit log producing who-did-what-why records (AOW-compatible)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


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
