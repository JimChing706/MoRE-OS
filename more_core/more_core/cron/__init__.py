"""Cron/Trigger module for QNMing MoRE OS.

This module provides scheduled task execution and event-driven trigger capabilities,
similar to Hermes cron jobs and OpenFang trigger engine.

Features:
- Cron-style scheduling
- Event-based triggers
- One-time and recurring tasks
- Task result delivery via channels
"""

from .manager import TaskManager
from .scheduler import CronJob, CronScheduler, JobResult, JobStatus
from .trigger import EventPattern, Trigger, TriggerEngine, TriggerEvent

__all__ = [
    "CronJob",
    "CronScheduler",
    "EventPattern",
    "JobResult",
    "JobStatus",
    "TaskManager",
    "Trigger",
    "TriggerEngine",
    "TriggerEvent",
]
