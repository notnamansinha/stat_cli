from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class LatencyWindow:
    maxlen: int = 600

    def __post_init__(self) -> None:
        self._values: deque[float] = deque(maxlen=self.maxlen)

    def add(self, value: float) -> None:
        self._values.append(float(value))

    def p95(self) -> float | None:
        if not self._values:
            return None
        arr = sorted(self._values)
        idx = int(round((len(arr) - 1) * 0.95))
        return arr[idx]
