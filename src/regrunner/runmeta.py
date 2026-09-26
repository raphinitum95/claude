"""``run.json``: the small per-run summary the UI lists.  Written by the runner and the web supervisor."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def new_batch_id(existing: set[str]) -> str:
    """A label tying together the individual runs started from one "New run" screen (or "Add tests to this batch").

    A batch is only a label (dev/plan/CONTRACT.md, engineering doc section 5): it never changes how a run executes or where it is
    stored, so unlike a run id this needs no folder of its own - callers pass the batch ids already in use (from the runs on disk)
    so two batches started in the same second still get different ids."""
    stamp = datetime.now().strftime("%m%d-%H%M")
    candidate, n = stamp, 1
    while candidate in existing:
        n += 1
        candidate = f"{stamp}-{n}"
    return candidate


def read_meta(run_dir: Path) -> dict[str, Any] | None:
    f = run_dir / "run.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def update_meta(run_dir: Path, **fields: Any) -> dict[str, Any]:
    """Merge ``fields`` into run.json (keeps what other writers stored) and replace it atomically."""
    meta = {**(read_meta(run_dir) or {}), **fields}
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f"run.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(run_dir / "run.json")
    return meta
