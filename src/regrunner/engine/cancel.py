"""Cancelling one test of a run (the Cancel button on a test's live card) without touching the run or the other tests.

Everything that watches for a cancel (the step loop, ``Patience``, the throttle, ASK_USER, scenario syncs) asks ``cancel.is_set()``.  A test therefore
gets an ``OneTestCancel``: it answers "yes" when the whole run is cancelled (the run's own event) *or* when this test alone was cancelled, so none of
those places had to change and a patient wait ends at its next look, like it does for a run-wide cancel.

The web UI asks by writing a marker file ``<run folder>/cancel_test/<quoted test id>`` (the engine runs in another process); ``Engine.watch_markers``
turns it into ``Engine.cancel_test``.  Whole-test re-runs never apply: a cancelled test is not tried again.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote, unquote

CANCELLED_BY_USER = "Cancelled by user"
MARKER_DIR = "cancel_test"                   # inside the run folder: one empty file per test the person cancelled


def marker_path(run_dir: Path, test_id: str) -> Path:
    """The file whose existence means "the person cancelled this test" (the id is quoted: ids hold '#', spaces and ' · ')."""
    return run_dir / MARKER_DIR / quote(test_id, safe="")


def requested_tests(run_dir: Path) -> list[str]:
    """Ids of the tests the person asked to cancel so far."""
    try:
        return [unquote(p.name) for p in (run_dir / MARKER_DIR).iterdir()]
    except OSError:
        return []


class OneTestCancel:
    """``asyncio.Event`` look-alike for one test: set when the run is cancelled, or when this test alone is."""

    def __init__(self, run_cancel: asyncio.Event, test_id: str):
        self.run_cancel, self.test = run_cancel, test_id
        self.by_user = False                                 # this test alone was cancelled (not the whole run)

    def is_set(self) -> bool:
        return self.by_user or self.run_cancel.is_set()

    def set(self) -> None:
        self.by_user = True

    async def wait(self) -> bool:
        while not self.is_set():
            await asyncio.sleep(0.1)
        return True


def cancel_reason(cancel, default: str = "cancelled") -> str:
    """How a test that stopped because of ``cancel`` says why: "Cancelled by user" when its own Cancel button was pressed."""
    return CANCELLED_BY_USER if getattr(cancel, "by_user", False) else default
