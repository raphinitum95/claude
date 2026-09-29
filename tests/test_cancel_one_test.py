"""Cancelling ONE test of a running run (the Cancel button on its live card): it ends CANCELLED "Cancelled by user", frees its worker at once, and the
run, the other tests and their workers are not touched.  The web UI asks with a marker file in the run's folder; these tests write it the same way."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from regrunner.engine import actions
from regrunner.engine import runner as runner_mod
from regrunner.engine.cancel import CANCELLED_BY_USER, OneTestCancel, marker_path, requested_tests
from regrunner.engine.runner import Engine, RunCtx, RunOptions, execute
from regrunner.events import EventBus
from regrunner.reporting.from_events import results_from_events
from tests.workbook_factory import build_steps_workbook


@actions.action("TEST_HOLD_FOREVER")
async def _hold_forever(ctx) -> None:
    """(tests only) A step that never comes back and does not look at the cancel: only ending its task can free the worker."""
    await asyncio.sleep(3600)


@actions.action("TEST_WAIT_FOR_CANCEL")
async def _wait_for_cancel(ctx) -> None:
    """(tests only) A patient wait: it looks at the cancel the way ``Patience`` does (``session.cancel.is_set()``) and ends when it is set."""
    for _ in range(600):
        if ctx.session.cancel.is_set():
            return
        await asyncio.sleep(0.1)


@actions.action("TEST_TAKE_A_MOMENT")
async def _take_a_moment(ctx) -> None:
    """(tests only) A step that just takes two seconds."""
    await asyncio.sleep(2)


def flow(hold: str):
    def fill(sheet) -> None:
        sheet.add("Open", "Open", Value="DT_URL")
        sheet.add(hold, "Hold on")
        sheet.add("Output", "Heading", FindBy="xpath", FindBy_Value="//h1", Index=0, Output_Property="innertext")
        sheet.add("Quit", "Quit")
    return fill


def fine(sheet) -> None:
    sheet.add("Open", "Open", Value="DT_URL")
    sheet.add("Quit", "Quit")


class Going:
    """A run started in the background; ``events`` fills as it goes."""

    def __init__(self, site, make_cfg, tmp_path, flows: dict, workers: int = 1, **cfg):
        wb = tmp_path / "wb.xlsx"
        build_steps_workbook(wb, flows, params={name: {"DT_URL": site + "index.html"} for name in flows})
        self.events: list[dict] = []
        bus = EventBus()
        bus.subscribe(self.events.append)
        self.run_dir = None
        self.tmp = tmp_path
        conf = make_cfg(**{"runner.stagger_s": 0, "runner.min_page_load_gap_s": 0, **cfg})
        self.task = asyncio.ensure_future(execute(RunOptions(workbook=wb, seed=1, tests=list(flows), workers=workers), conf, bus))

    async def until(self, what, timeout: float = 60):
        for _ in range(int(timeout * 20)):
            if any(what(e) for e in self.events):
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"never happened: {[e['type'] for e in self.events][-12:]}")

    def cancel(self, test: str) -> None:
        run_id = next(e["run_id"] for e in self.events if e["type"] == "run_started")
        marker = marker_path(self.tmp / "runs" / run_id, test)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("cancel")

    async def finish(self, timeout: float = 90):
        result = await asyncio.wait_for(self.task, timeout)
        return result, {t.id: t for t in result.tests}

    def of(self, kind: str, test: str) -> list[dict]:
        return [e for e in self.events if e["type"] == kind and e.get("test") == test]


# -- the engine ------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.browser
async def test_cancelling_a_test_stuck_in_a_step_ends_it_at_once_and_the_worker_goes_on_to_the_next_test(site, make_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "TEST_CANCEL_GRACE_S", 0.5)
    run = Going(site, make_cfg, tmp_path, {"Stuck": flow("TEST_HOLD_FOREVER"), "Fine": fine})          # one worker: Fine can only start once Stuck lets go of it
    await run.until(lambda e: e["type"] == "step_started" and e.get("action") == "TEST_HOLD_FOREVER")
    assert not run.of("test_started", "Fine")
    run.cancel("Stuck")
    result, tests = await run.finish()
    assert tests["Stuck"].status == "CANCELLED" and tests["Stuck"].error == CANCELLED_BY_USER
    assert tests["Fine"].status == "PASSED"                                                        # the other test ran, on the very worker Stuck was on
    assert result.status == "INCOMPLETE" and result.summary["passed"] == 1
    (asked,) = run.of("test_cancel_requested", "Stuck")
    assert asked["reason"] == CANCELLED_BY_USER
    assert run.of("test_finished", "Stuck")[-1]["status"] == "CANCELLED" and run.of("test_finished", "Stuck")[-1]["error"] == CANCELLED_BY_USER
    assert run.events[-1]["type"] == "run_finished" and run.events[-1]["status"] == "INCOMPLETE"


@pytest.mark.browser
async def test_a_patient_wait_ends_by_itself_when_its_test_is_cancelled_without_ending_its_task(site, make_cfg, tmp_path):
    run = Going(site, make_cfg, tmp_path, {"Waits": flow("TEST_WAIT_FOR_CANCEL"), "Fine": fine}, workers=2)
    await run.until(lambda e: e["type"] == "step_started" and e.get("action") == "TEST_WAIT_FOR_CANCEL")
    await run.until(lambda e: e["type"] == "test_finished" and e.get("test") == "Fine")            # the other test is not held up by it
    run.cancel("Waits")
    result, tests = await run.finish(30)                                                            # (the 5 s grace never had to end its task)
    assert tests["Waits"].status == "CANCELLED" and tests["Waits"].error == CANCELLED_BY_USER
    assert tests["Waits"].skipped == 2 and tests["Fine"].status == "PASSED"                          # what it had not reached is skipped, not failed
    assert not [e for e in run.events if e["type"] == "step_started" and e.get("test") == "Waits" and e.get("action") == "OUTPUT"]


@pytest.mark.browser
async def test_a_test_cancelled_before_it_gets_a_worker_never_starts_and_the_one_running_is_not_disturbed(site, make_cfg, tmp_path):
    run = Going(site, make_cfg, tmp_path, {"Slow": flow("TEST_TAKE_A_MOMENT"), "Later": fine})
    await run.until(lambda e: e["type"] == "step_started" and e.get("action") == "TEST_TAKE_A_MOMENT")
    run.cancel("Later")
    result, tests = await run.finish()
    assert tests["Slow"].status == "PASSED"                                                         # it carried on to its end
    assert tests["Later"].status == "CANCELLED" and tests["Later"].error == CANCELLED_BY_USER and tests["Later"].skipped == 2
    assert run.of("test_started", "Later") and run.of("test_finished", "Later")[-1]["status"] == "CANCELLED"     # it is in the log, not silently missing
    assert result.status == "INCOMPLETE"


@pytest.mark.browser
async def test_the_event_log_of_a_cancelled_test_replays_to_the_same_result(site, make_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "TEST_CANCEL_GRACE_S", 0.5)
    run = Going(site, make_cfg, tmp_path, {"Stuck": flow("TEST_HOLD_FOREVER"), "Fine": fine})
    await run.until(lambda e: e["type"] == "step_started" and e.get("action") == "TEST_HOLD_FOREVER")
    run.cancel("Stuck")
    result, tests = await run.finish()
    (run_dir,) = list((tmp_path / "runs").iterdir())
    replayed = {t.id: t for t in results_from_events(run_dir).tests}
    assert replayed["Stuck"].status == "CANCELLED" and replayed["Stuck"].error == CANCELLED_BY_USER and replayed["Fine"].status == "PASSED"


# -- the pieces ------------------------------------------------------------------------------------------------------------------------------
async def test_a_tests_cancel_is_set_by_the_run_or_by_the_person_but_the_person_only_reaches_that_test():
    run = asyncio.Event()
    one, other = OneTestCancel(run, "Purchase#1"), OneTestCancel(run, "View#1")
    assert not one.is_set() and not other.is_set()
    one.set()
    assert one.is_set() and one.by_user and not other.is_set() and not run.is_set()
    run.set()
    assert other.is_set() and not other.by_user                                                     # the run's own cancel is not "by the user"


def test_the_marker_of_a_test_survives_the_characters_ids_hold(tmp_path):
    for test_id in ("Purchase#1", "Two agents edit one policy · A", "Flow B"):
        marker = marker_path(tmp_path, test_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("cancel")
        assert marker.parent == tmp_path / "cancel_test" and "/" not in marker.name
    assert sorted(requested_tests(tmp_path)) == ["Flow B", "Purchase#1", "Two agents edit one policy · A"]
    assert requested_tests(tmp_path / "nowhere") == []


def test_a_test_that_needs_what_a_cancelled_test_should_have_set_is_skipped_and_the_reason_says_the_person_cancelled_it():
    order = SimpleNamespace(data={"View": {"DT_URL": ["Purchase"]}}, cells={"View": {"DT_URL": ("Purchase", 3, 9)}})
    flow_of = SimpleNamespace(id="View", reads={"a": {"param": "DT_URL"}})
    cancelled = SimpleNamespace(status="CANCELLED")
    ctx = SimpleNamespace(order=order, flows=[flow_of], shared={}, results={"Purchase": cancelled}, test_cancelled=lambda test: test == "Purchase")
    why = Engine.producer_failed(ctx, SimpleNamespace(id="View"))
    assert why.startswith("Not run: View needs DT_URL, which Purchase should have set") and "Purchase was cancelled by the user" in why
    ctx.test_cancelled = lambda test: False                                                          # (a run-wide cancel keeps the plain wording)
    assert "Purchase ended CANCELLED" in Engine.producer_failed(ctx, SimpleNamespace(id="View"))


async def test_the_context_hands_out_one_switch_per_test_and_only_the_persons_cancel_counts_as_theirs():
    ctx = RunCtx.__new__(RunCtx)
    ctx.cancel, ctx.switches = asyncio.Event(), {}
    assert ctx.switch_of("A") is ctx.switch_of("A") and not ctx.test_cancelled("A")
    ctx.cancel.set()
    assert ctx.switch_of("A").is_set() and not ctx.test_cancelled("A")
    ctx.switch_of("B").set()
    assert ctx.test_cancelled("B")
