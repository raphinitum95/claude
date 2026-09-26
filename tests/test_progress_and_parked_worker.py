"""Two ways a run looked finished while it was not: progress that counted a retried test twice (100% while a test was about to start over), and a worker
taken out of service after a block that never went home, so the run sat there after its last test until somebody cancelled it."""
from __future__ import annotations

import asyncio
import time

import pytest

from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus, ProgressTracker
from tests.site import server as mock_server
from tests.workbook_factory import build_workbook


def progress_of(events_in) -> list[float]:
    bus = EventBus("r")
    ProgressTracker(bus)
    seen: list[float] = []
    bus.subscribe(lambda e: seen.append(e["percent"]) if e["type"] == "run_progress" else None)
    for kind, fields in events_in:
        bus.emit(kind, **fields)
    return seen


def test_a_test_that_starts_over_is_not_counted_twice_and_the_run_is_not_at_100_percent_while_one_is_waiting_to_retry():
    """The real run: two API tests blocked (HTTP 403), each waiting out a 60 s cool-down before its second attempt: the run said 100%."""
    started = ("run_started", {"tests": [{"id": "A", "total_steps": 7}, {"id": "B", "total_steps": 7}]})
    a1 = [("test_started", {"test": "A", "total_steps": 7, "attempt": 1}), ("step_failed", {"test": "A", "step": 1, "total_steps": 7}),
          ("test_finished", {"test": "A", "status": "ERROR"}), ("run_paused", {"test": "A", "seconds": 60})]
    b1 = [("test_started", {"test": "B", "total_steps": 7, "attempt": 1}), ("step_failed", {"test": "B", "step": 1, "total_steps": 7}),
          ("test_finished", {"test": "B", "status": "ERROR"}), ("run_paused", {"test": "B", "seconds": 60})]
    seen = progress_of([started, *a1, *b1])
    assert max(seen) < 100.0 and seen[-1] == 0.0                                       # both are about to start over: nothing is done
    again = progress_of([started, *a1, *b1, ("test_started", {"test": "A", "total_steps": 7, "attempt": 2}),
                         ("step_failed", {"test": "A", "step": 1, "total_steps": 7}), ("test_finished", {"test": "A", "status": "ERROR"})])
    assert again[-1] == 50.0                                                           # A is done (for good), B has not started its second attempt
    done = progress_of([started, *a1, *b1, ("test_started", {"test": "A", "total_steps": 7, "attempt": 2}), ("test_finished", {"test": "A", "status": "ERROR"}),
                        ("test_started", {"test": "B", "total_steps": 7, "attempt": 2}), ("test_finished", {"test": "B", "status": "ERROR"})])
    assert done[-1] == 100.0                                                           # 100% only when the last attempt of the last test is over


@pytest.fixture(autouse=True)
def waf_off():
    mock_server.FLAKY.update(block=0, seen=0)
    yield
    mock_server.FLAKY.update(block=0, seen=0)


@pytest.mark.browser
async def test_a_worker_taken_out_of_service_by_a_block_does_not_keep_the_run_alive(site, make_cfg, tmp_path):
    """Two workers, the first load of the run is refused (403): one worker is taken out of service for the rest of the run.  The other one runs both tests;
    when they are done the run must end by itself (before: the parked worker waited for a cancel that nobody was going to send)."""
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["A", "B"], base_url=site + "flaky/", enabled=["A", "B"])
    mock_server.FLAKY.update(block=1, seen=0)
    cfg = make_cfg(**{"runner.workers": 2, "runner.stagger_s": 2.5, "runner.block_cooldown_s": 0.5, "runner.block_retries": 1, "runner.min_page_load_gap_s": 0})
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    started = time.monotonic()
    result = await asyncio.wait_for(execute(RunOptions(workbook=wb, seed=1, tests=["A", "B"]), cfg, bus), 120)         # a hang shows up as a timeout here
    assert {t.status for t in result.tests} == {"PASSED"}, [(t.id, t.error) for t in result.tests]
    assert [e for e in events if e["type"] == "run_paused"], "the block never happened, so this did not test what it is for"
    assert time.monotonic() - started < 100
    assert [e for e in events if e["type"] == "run_progress"][-1]["percent"] == 100.0
