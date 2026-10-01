"""A live picture of a test that runs where nobody can see it (the run screen's "Watch live").

A headless browser cannot be turned into a visible one while it runs, so the run screen asks for pictures instead.  The web server (another process)
touches a marker file ``<run folder>/watch/<frame name>`` every few seconds while somebody is watching that test; while the marker is fresh the test
writes a small picture of its page to ``<run folder>/live/<frame name>`` every ``runner.live_view_frame_s`` seconds, and the screen shows the newest one.
Nobody watching = nothing is taken: the test is not slowed down and nothing is written.  The pictures are only the page as a person would see it (the
same as a step's screenshot); the last one is removed when the test ends.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import zlib
from pathlib import Path

WATCH_DIR = "watch"                 # inside the run folder: one file per test somebody is watching
LIVE_DIR = "live"                   # inside the run folder: the newest picture of each watched test
FRESH_S = 15.0                      # a marker touched longer ago than this means nobody is watching any more


def frame_name(test_id: str) -> str:
    """A file name that is safe in a URL and different for every test id (ids hold '#', spaces and ' · ')."""
    return f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', test_id)[:60]}-{zlib.crc32(test_id.encode('utf-8')):08x}.jpg"


def watch_marker(run_dir: Path, test_id: str) -> Path:
    return run_dir / WATCH_DIR / frame_name(test_id)


def frame_file(run_dir: Path, test_id: str) -> Path:
    return run_dir / LIVE_DIR / frame_name(test_id)


def is_watched(run_dir: Path, test_id: str, fresh_s: float = FRESH_S) -> bool:
    try:
        return time.time() - watch_marker(run_dir, test_id).stat().st_mtime < fresh_s
    except OSError:
        return False


async def stream(session, run_dir: Path, test_id: str, every_s: float, cancel) -> None:
    """Write a picture of the test's page while somebody watches it, until the test ends (the caller cancels this task).  Never raises."""
    target = frame_file(run_dir, test_id)
    every_s = max(0.25, float(every_s))
    try:
        while not cancel.is_set():
            await asyncio.sleep(every_s)
            if not is_watched(run_dir, test_id) or not session.is_open or session.pending_dialog is not None:   # an open dialog blocks the page
                continue
            try:
                data = await session.page.screenshot(type="jpeg", quality=55, timeout=3000, animations="allow", caret="hide")
            except Exception:
                continue                                       # the page was navigating or closing: the next picture will do
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)                            # the screen never reads half a picture
    except asyncio.CancelledError:
        raise
    except Exception:
        return


def forget(run_dir: Path, test_id: str) -> None:
    """The test ended: its last picture and marker go."""
    for path in (frame_file(run_dir, test_id), watch_marker(run_dir, test_id)):
        try:
            path.unlink()
        except OSError:
            pass
