"""Confidence–accuracy calibrator (Mirror-style)."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(slots=True)
class CalibrationPoint:
    timestamp: float
    confidence: float
    accuracy: float


class Calibrator:
    def __init__(self, window: int = 128) -> None:
        self._history: Deque[CalibrationPoint] = deque(maxlen=window)
        self._last_alignment: float = 1.0

    def observe(self, confidence: float, accuracy: float) -> float:
        self._history.append(
            CalibrationPoint(timestamp=time.time(), confidence=confidence, accuracy=accuracy)
        )
        alignment = 1 - abs(confidence - accuracy)
        self._last_alignment = alignment
        return alignment

    def report(self) -> dict[str, object]:
        if not self._history:
            return {"confidence": 0.0, "accuracy": 0.0, "alignment": 1.0, "n": 0}
        avg_conf = sum(p.confidence for p in self._history) / len(self._history)
        avg_acc = sum(p.accuracy for p in self._history) / len(self._history)
        return {
            "confidence": avg_conf,
            "accuracy": avg_acc,
            "alignment": 1 - abs(avg_conf - avg_acc),
            "n": len(self._history),
        }
