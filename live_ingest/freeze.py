from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class FreezeController:
    def __init__(self, *, root_dir: Path) -> None:
        self.path = Path(root_dir) / "outputs" / "live" / "freeze.flag"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def freeze(self, *, reason: str) -> None:
        payload = f"frozen_at={datetime.now(timezone.utc).isoformat()} reason={reason}\n"
        self.path.write_text(payload, encoding="utf-8")

    def unfreeze(self) -> None:
        if self.path.exists():
            self.path.unlink()
