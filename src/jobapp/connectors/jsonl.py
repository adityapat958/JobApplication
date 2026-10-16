"""Reference connector: appends one JSON line per event to output/events.jsonl."""
from __future__ import annotations

import json
from pathlib import Path

from ..db import now

KEYS = ("id", "source", "company", "title", "location", "url", "status", "match_pct")


class JsonlConnector:
    name = "jsonl"

    def __init__(self, path: Path):
        self.path = Path(path)

    def _write(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def on_job_added(self, job: dict) -> None:
        self._write({"at": now(), "event": "added", "job": {k: job.get(k) for k in KEYS}})

    def on_job_updated(self, job: dict, changes: dict) -> None:
        self._write({"at": now(), "event": "updated", "job": {k: job.get(k) for k in KEYS}, "changes": changes})

    def pull(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
