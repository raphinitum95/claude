"""The Cancel button on a running test's live card: the route that asks for it, the screen's reducer, and the card in a real browser.
The engine side (the test ending CANCELLED, the worker freed, the run going on) is in test_cancel_one_test.py."""
from __future__ import annotations

import json

import httpx
import pytest

from regrunner.engine.cancel import CANCELLED_BY_USER, marker_path
from regrunner.events import now_iso
from tests.test_web_ui import open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


def plant_running_run(web, run_id: str, *, going=("FlowA",), finished=(), cancelling=False):
    """A run folder that looks like a run in progress (fresh event stream, status RUNNING) with ``going`` tests started and ``finished`` ones done."""
    run_dir = web.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "status": "RUNNING", "workbook": "mock.xlsx", "started_at": now_iso()}))
    tests = [*going, *finished, "FlowLater"]
    events = [{"type": "run_started", "run_id": run_id, "workbook": "mock.xlsx", "environment": "UAT", "workers": 2, "headless": True, "browser": {},
               "warnings": [], "params": {}, "shares": [], "scenarios": [],
               "tests": [{"id": t, "title": t, "description": "", "scenario": "", "total_steps": 4, "waits_for": []} for t in tests]}]
    for n, t in enumerate(going, start=1):
        events += [{"type": "test_started", "test": t, "title": t, "total_steps": 4, "worker": n, "attempt": 1},
                   {"type": "step_started", "test": t, "step": 1, "total_steps": 4, "row": 2, "name": "Open", "action": "OPEN"}]
    for t in finished:
        events += [{"type": "test_started", "test": t, "title": t, "total_steps": 4, "worker": 2, "attempt": 1},
                   {"type": "test_finished", "test": t, "status": "PASSED", "passed": 4, "failed": 0, "skipped": 0, "duration_s": 1.0, "review_counts": []}]
    (run_dir / "events.jsonl").write_text("".join(json.dumps({"ts": now_iso(), "run_id": run_id, **e}) + "\n" for e in events))
    if cancelling:
        (run_dir / "cancel").write_text("cancel")
    return run_dir


def test_cancelling_a_running_test_leaves_a_marker_for_that_test_only(web):
    run_dir = plant_running_run(web, "planted-cancel-1", going=("FlowA", "FlowB"))
    with web.client() as c:
        assert c.post("/api/runs/planted-cancel-1/tests/FlowA/cancel").json() == {"ok": True}
    assert marker_path(run_dir, "FlowA").is_file() and not marker_path(run_dir, "FlowB").exists()
    assert not (run_dir / "cancel").exists()                                                       # the run itself was not asked to stop


def test_a_test_id_with_odd_characters_travels_in_the_url_and_is_found(web):
    run_dir = plant_running_run(web, "planted-cancel-2", going=("Two agents · A#1",))
    with web.client() as c:
        assert c.post("/api/runs/planted-cancel-2/tests/Two%20agents%20%C2%B7%20A%231/cancel").status_code == 200
    assert marker_path(run_dir, "Two agents · A#1").is_file()


def test_only_a_test_that_is_running_in_a_running_run_can_be_cancelled(web):
    plant_running_run(web, "planted-cancel-3", going=("FlowA",), finished=("FlowB",))
    with web.client() as c:
        assert c.post("/api/runs/no-such-run/tests/FlowA/cancel").status_code == 404
        done = c.post("/api/runs/planted-cancel-3/tests/FlowB/cancel")
        assert done.status_code == 409 and done.json()["kind"] == "test_not_running"                  # already finished
        later = c.post("/api/runs/planted-cancel-3/tests/FlowLater/cancel")
        assert later.status_code == 409 and later.json()["kind"] == "test_not_running"                # not started yet
        assert c.post("/api/runs/planted-cancel-3/tests/Nothing/cancel").status_code == 409
    plant_running_run(web, "planted-cancel-4", going=("FlowA",), cancelling=True)
    with web.client() as c:
        assert c.post("/api/runs/planted-cancel-4/tests/FlowA/cancel").json()["kind"] == "run_cancelling"
    over = plant_running_run(web, "planted-cancel-5", going=("FlowA",))
    (over / "run.json").write_text(json.dumps({"run_id": "planted-cancel-5", "status": "PASSED"}))
    with web.client() as c:
        assert c.post("/api/runs/planted-cancel-5/tests/FlowA/cancel").json()["kind"] == "not_running"


def test_the_request_must_come_from_the_page(web):
    plant_running_run(web, "planted-cancel-6", going=("FlowA",))
    with httpx.Client(base_url=web.base) as bare:
        assert bare.post("/api/runs/planted-cancel-6/tests/FlowA/cancel").status_code == 403


async def test_the_screen_shows_a_test_as_cancelling_and_then_cancelled_and_the_views_load(web):
    async with open_ui(web) as page:
        summary = await page.evaluate("""async () => {
            await import('/static/js/views/live.js');                                   // (the card's markup parses)
            const { newRun, applyAll } = await import('/static/js/runstate.js');
            const run = newRun('r1');
            const ts = new Date().toISOString();
            const start = { type: 'run_started', ts, run_id: 'r1', workbook: 'w.xlsx', environment: 'UAT', workers: 2, tests: [
              { id: 'A', title: 'A', total_steps: 4 }, { id: 'B', title: 'B', total_steps: 4 }] };
            applyAll(run, [start, { type: 'test_started', ts, test: 'A', worker: 1, total_steps: 4 }, { type: 'test_started', ts, test: 'B', worker: 2, total_steps: 4 },
              { type: 'test_cancel_requested', ts, test: 'A', reason: 'Cancelled by user' }]);
            const asked = { a: run.tests.A.cancelling, b: run.tests.B.cancelling, log: run.log[run.log.length - 1].m };
            applyAll(run, [{ type: 'test_finished', ts, test: 'A', status: 'CANCELLED', passed: 1, failed: 0, skipped: 3, duration_s: 2, error: 'Cancelled by user', review_counts: [] }]);
            return { asked, status: run.tests.A.status, error: run.tests.A.error, cancelling: run.tests.A.cancelling, other: run.tests.B.status };
        }""")
        assert summary["asked"]["a"] is True and summary["asked"]["b"] is False and "Cancelled by user" in summary["asked"]["log"]
        assert summary["status"] == "CANCELLED" and summary["error"] == CANCELLED_BY_USER and summary["cancelling"] is False
        assert summary["other"] == "RUNNING"                                                        # the other test is not touched
        assert not page.errors, page.errors


async def test_the_cancel_test_button_is_on_each_running_card_and_asks_for_that_test_only(web):
    run_dir = plant_running_run(web, "planted-cancel-7", going=("FlowA", "FlowB"))
    async with open_ui(web, path="/#/run/planted-cancel-7") as page:
        await page.wait_for_selector('[data-act="cancel-test"]')
        assert await page.locator('[data-act="cancel-test"]').count() == 2
        await page.locator('[data-act="cancel-test"][data-test="FlowB"]').click()
        for _ in range(100):
            if marker_path(run_dir, "FlowB").exists():
                break
            await page.wait_for_timeout(100)
        assert marker_path(run_dir, "FlowB").is_file() and not marker_path(run_dir, "FlowA").exists()
        assert not (run_dir / "cancel").exists()
        assert not page.errors, page.errors
