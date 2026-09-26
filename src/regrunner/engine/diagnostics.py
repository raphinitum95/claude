"""When a run stops making progress, say where: a snapshot of every pending asyncio task goes to the runner's stderr
(``runner.log`` in the run folder), so a hang can be diagnosed from the run itself instead of guessed at."""
from __future__ import annotations

import asyncio
import io
import sys


def dump_tasks(reason: str, limit: int = 8) -> None:
    tasks = [t for t in asyncio.all_tasks() if not t.done()]
    out = [f"--- {reason}: {len(tasks)} pending task(s) ---"]
    for task in tasks:
        buf = io.StringIO()
        task.print_stack(limit=limit, file=buf)
        out.append(f"{task.get_name()}\n{buf.getvalue().rstrip()}")
    print("\n".join(out), file=sys.stderr, flush=True)
