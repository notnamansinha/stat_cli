from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class GapLogger:
    def __init__(self, *, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.path = self.root_dir / "outputs" / "live" / "gaps.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
