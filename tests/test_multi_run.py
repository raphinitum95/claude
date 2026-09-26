"""Several workbooks at once: one run per workbook (own folder, events, results, report) on one set of workers.

The pool hands a free worker to the run with the fewest tests going, a run can join a process that is already going (the web UI's "New run" while a
run is in progress), and the command line takes ``regrunner run A.xlsx --tests X B.xlsx --all``.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from regrunner.cli import build_parser, split_workbooks
from regrunner.engine import inbox as inbox_mod
from regrunner.engine.pool import Pool
from regrunner.engine.runner import RunOptions, SelectionError, execute_many
from regrunner.engine.schedule import Schedule
from regrunner.events import EventBus
from tests.site import server as mock_server
from tests.workbook_factory import build_workbook


# -- the pool, without a browser ---------------------------------------------------------------------------------------------------------------------
class Case:
    def __init__(self, id):
        self.id = id


class FakeRun:
    def __init__(self, name: str, ids: list[str]):
        self.name = name
        self.schedule = Schedule([Case(i) for i in ids], {})
        self.cancel = asyncio.Event()
        self.ended = False


async def test_a_free_worker_goes_to_the_run_with_the_fewest_tests_going():
    a, b = FakeRun("a", ["a1", "a2", "a3"]), FakeRun("b", ["b1", "b2"])
    pool = Pool(asyncio.Event())
    pool.add(a)
    pool.add(b)
    taken = [await pool.take() for _ in range(4)]
    assert [(run.name, case.id) for run, case in taken] == [("a", "a1"), ("b", "b1"), ("a", "a2"), ("b", "b2")]      # they take turns: the workers split evenly
    await pool.finished(taken[1][0], "b1")                                                  # b has one going, a has two: the next worker goes to b... which has nothing left
    run, case = await pool.take()
    assert (run.name, case.id) == ("a", "a3")                                               # ...so a gets it: an idle share is never wasted
    assert await pool.take() is None                                                        # nothing left anywhere: the worker goes home


async def test_a_cancelled_run_is_skipped_and_its_waiting_tests_are_never_started():
    a, b = FakeRun("a", ["a1", "a2"]), FakeRun("b", ["b1", "b2"])
    pool = Pool(asyncio.Event())
    pool.add(a)
    pool.add(b)
    a.cancel.set()
    assert [case.id for _, case in [await pool.take(), await pool.take()]] == ["b1", "b2"]
    assert await pool.take() is None


async def test_a_run_whose_tests_wait_for_each_other_leaves_the_workers_to_the_others():
    a = FakeRun("a", ["a2"])
    a.schedule = Schedule([Case("a2")], {"a2": ["a1"]})                                     # a2 waits for a1, which is not in the queue and not done
    a.schedule._running = 1                                                                 # (a1 is going)
    b = FakeRun("b", ["b1"])
    pool = Pool(asyncio.Event())
    pool.add(a)
    pool.add(b)
    run, case = await pool.take()
    assert (run.name, case.id) == ("b", "b1")


async def test_an_open_pool_keeps_its_workers_until_it_is_closed_so_a_run_can_still_join():
    pool = Pool(asyncio.Event(), joinable=True)
    waiter = asyncio.ensure_future(pool.take())
    await asyncio.sleep(0.7)
    assert not waiter.done() and not pool.drained()                                         # nothing to run, but somebody may still join
    late = FakeRun("late", ["l1"])
    pool.add(late)
    await pool.wake()
    run, case = await asyncio.wait_for(waiter, 2)
    assert (run.name, case.id) == ("late", "l1")
    waiter = asyncio.ensure_future(pool.take())
    await pool.close()
    assert await asyncio.wait_for(waiter, 2) is None and pool.drained()


# -- the inbox handshake ----------------------------------------------------------------------------------------------------------------------------
def test_a_request_is_taken_once_and_a_closed_inbox_hands_the_run_back(tmp_path):
    folder = tmp_path / "inbox"
    box = inbox_mod.Inbox(folder)
    assert inbox_mod.post(folder, "r1", {"workbook": "x.xlsx"}) is True
    assert inbox_mod.answer(folder, "r1") == "waiting"
    assert box.claim() == [("r1", {"workbook": "x.xlsx"})] and box.claim() == []            # taken once
    assert inbox_mod.answer(folder, "r1") == "claimed"
    box.close()
    assert inbox_mod.post(folder, "r2", {}) is False                                        # the process is going home: start one of your own
    assert not (folder / "r2.json").exists()
    box2 = inbox_mod.Inbox(tmp_path / "gone")
    (tmp_path / "gone" / "junk.json").write_text("[1, 2]")
    assert box2.claim() == [] and inbox_mod.answer(tmp_path / "gone", "junk").startswith("rejected:")     # an unreadable request is answered, not lost
    assert inbox_mod.post(tmp_path / "never-made", "r3", {}) is False


def test_a_request_that_slips_in_as_the_door_closes_is_either_taken_or_retracted_never_lost(tmp_path):
    folder = tmp_path / "inbox"
    box = inbox_mod.Inbox(folder)
    (folder / inbox_mod.CLOSED).write_text("closed")                                        # the process closed the door...
    (folder / "late.json").write_text('{"workbook": "x"}')                                  # ...just after a request was written
    assert inbox_mod.retract(folder, "late") is True and box.claim() == []                  # the server took it back: nobody runs it, nobody loses it
    (folder / "late2.json").write_text('{"workbook": "x"}')
    assert [i for i, _ in box.claim()] == ["late2"] and inbox_mod.retract(folder, "late2") is False      # the process got it first: the server must wait for that run


# -- the command line -------------------------------------------------------------------------------------------------------------------------------
def test_each_workbook_on_the_command_line_keeps_its_own_tests_and_the_rest_is_shared():
    parser = build_parser()
    one = ["run", "a.xlsx", "--all", "--workers", "4"]
    assert split_workbooks(parser, one) is None                                             # one workbook: exactly as before
    assert split_workbooks(parser, ["run", "--all", "a.xlsx"]) is None
    groups = split_workbooks(parser, ["--config", "c.yaml", "run", "a.xlsx", "--tests", "X,Y", "--chain", "X,Y", "b.xlsx", "--all",
                                      "--workers", "4", "--env", "UAT", "--no-pdf"])
    assert groups == [["--config", "c.yaml", "run", "a.xlsx", "--tests", "X,Y", "--chain", "X,Y", "--workers", "4", "--env", "UAT", "--no-pdf"],
                      ["--config", "c.yaml", "run", "b.xlsx", "--all", "--workers", "4", "--env", "UAT", "--no-pdf"]]
    parsed = [parser.parse_args(g) for g in groups]
    assert [(p.workbook, p.tests, p.all, p.chain, p.workers, p.env, p.pdf) for p in parsed] == [
        ("a.xlsx", "X,Y", False, ["X,Y"], 4, "UAT", False), ("b.xlsx", None, True, None, 4, "UAT", False)]
    early = split_workbooks(parser, ["run", "--tag", "smoke", "a.xlsx", "b.xlsx"])
    assert early[0] == ["run", "a.xlsx", "--tag", "smoke"] and early[1] == ["run", "b.xlsx"]        # options before the first workbook belong to it
    assert split_workbooks(parser, ["run", "a.xlsx", "--test", "X", "b.xlsx"])[0] == ["run", "a.xlsx", "--test", "X"]     # an abbreviation is still that option


# -- real runs --------------------------------------------------------------------------------------------------------------------------------------
def two_workbooks(tmp_path: Path, site: str):
    a, b = tmp_path / "alpha.xlsx", tmp_path / "beta.xlsx"
    build_workbook(a, flows=["A1", "A2"], base_url=site, enabled=["A1", "A2"])
    build_workbook(b, flows=["B1", "B2"], base_url=site, enabled=["B1", "B2"])
    return a, b


def quick(make_cfg, **extra):
    return make_cfg(**{"runner.stagger_s": 0, "runner.min_page_load_gap_s": 0, **extra})


@pytest.mark.browser
async def test_two_workbooks_are_two_runs_that_share_the_workers(site, make_cfg, tmp_path):
    a, b = two_workbooks(tmp_path, site)
    cfg = quick(make_cfg, **{"runner.workers": 2})
    timeline: list[tuple[str, dict]] = []
    buses = [EventBus(), EventBus()]
    for name, bus in zip("ab", buses):
        bus.subscribe(lambda e, name=name: timeline.append((name, e)))
    results = await execute_many([RunOptions(workbook=a, tests=["A1", "A2"], seed=1), RunOptions(workbook=b, tests=["B1", "B2"], seed=1)], cfg, buses)
    ra, rb = results
    assert ra.run_id != rb.run_id and ra.status == rb.status == "PASSED", (ra.status, rb.status)
    assert [t.id for t in ra.tests] == ["A1", "A2"] and [t.id for t in rb.tests] == ["B1", "B2"]      # each run has only its own tests
    for r, wb in ((ra, a), (rb, b)):                                                                   # own folder, results, report, events, copy of the workbook
        folder = tmp_path / "runs" / r.run_id
        assert (folder / "results.json").is_file() and (folder / "report.html").is_file() and (folder / "events.jsonl").is_file()
        assert (folder / "workbook.xlsx").read_bytes() == wb.read_bytes()
        meta = json.loads((folder / "run.json").read_text())
        assert meta["status"] == "PASSED" and meta["workbook"] == str(wb) and meta["tests"] == 2
    starts = [name for name, e in timeline if e["type"] == "test_started"]
    assert starts[:2] == ["a", "b"]                                                                    # the two workers began one on each workbook
    running = peak = 0
    for _, e in timeline:
        running += e["type"] == "test_started"
        running -= e["type"] == "test_finished"
        peak = max(peak, running)
    assert peak == 2                                                                                   # never more tests going than workers
    started = {name: next(e for n, e in timeline if n == name and e["type"] == "run_started") for name in "ab"}
    assert [s["workbook"] for s in started["a"]["shares"]] == ["beta.xlsx"]
    assert [s["run_id"] for s in started["b"]["shares"]] == [ra.run_id]                                # each run knows who it shares the workers with
    assert started["a"]["workers"] == started["b"]["workers"] == 2


@pytest.mark.browser
async def test_cancelling_one_run_leaves_the_other_running(site, make_cfg, tmp_path):
    a, b = two_workbooks(tmp_path, site)
    cfg = quick(make_cfg, **{"runner.workers": 2})
    bus_a, bus_b = EventBus(), EventBus()

    def cancel_a_when_it_starts(e):
        if e["type"] == "test_started":
            (tmp_path / "runs" / "run-a" / "cancel").write_text("cancel")                              # what the web UI's Cancel button does
    bus_a.subscribe(cancel_a_when_it_starts)
    ra, rb = await asyncio.wait_for(execute_many([RunOptions(workbook=a, tests=["A1", "A2"], seed=1, run_id="run-a"),
                                                  RunOptions(workbook=b, tests=["B1", "B2"], seed=1, run_id="run-b")], cfg, [bus_a, bus_b]), 180)
    assert ra.status == "CANCELLED" and rb.status == "PASSED"
    assert {t.id for t in rb.tests} == {"B1", "B2"} and all(t.status == "PASSED" for t in rb.tests)     # b did not notice
    assert len(ra.tests) < 2 or {t.status for t in ra.tests} == {"CANCELLED"}                          # a stopped: its second test was never started


@pytest.mark.browser
async def test_a_run_can_join_workers_that_are_going_and_a_finished_process_hands_the_next_one_back(site, make_cfg, tmp_path):
    a, b = two_workbooks(tmp_path, site)
    cfg = quick(make_cfg, **{"runner.workers": 3})
    folder = tmp_path / "runs" / ".pools" / "p1"
    events_a: list[dict] = []
    bus_a = EventBus()
    bus_a.subscribe(events_a.append)
    main = asyncio.ensure_future(execute_many([RunOptions(workbook=a, tests=["A1"], seed=1, run_id="run-a", extra={"ask": "ui"})], cfg, [bus_a], inbox_dir=folder))
    for _ in range(100):
        if any(e["type"] == "test_started" for e in events_a):
            break
        await asyncio.sleep(0.1)
    request = {"workbook": str(b), "tests": ["B1", "B2"], "seed": 1}
    assert inbox_mod.post(folder, "run-b", request) is True
    ra, = await asyncio.wait_for(main, 180)
    assert ra.status == "PASSED" and ra.workers == 1                                                    # it began with one test, so one worker
    run_b = tmp_path / "runs" / "run-b"
    assert json.loads((run_b / "run.json").read_text())["status"] == "PASSED"                          # the joined run finished too, before the process left
    joined = json.loads((run_b / "results.json").read_text())
    assert [t["id"] for t in joined["tests"]] == ["B1", "B2"] and {t["status"] for t in joined["tests"]} == {"PASSED"}
    assert joined["workers"] == 3                                                                      # the pool grew to what was asked for, not beyond
    assert (run_b / "report.html").is_file()
    changed = [e for e in events_a if e["type"] == "pool_changed"]
    assert changed and changed[-1]["shares"][0]["run_id"] == "run-b"                                    # a run that was going hears that another joined
    assert events_a[0]["type"] == "run_started"                                                        # (and never before its own start)
    assert json.loads((tmp_path / "runs" / "run-a" / "run.json").read_text())["shares"][0]["run_id"] == "run-b"
    assert inbox_mod.post(folder, "run-c", request) is False                                            # the process is over: a new one has to be started


@pytest.mark.browser
async def test_a_request_that_cannot_join_is_refused_and_the_run_going_is_not_disturbed(site, make_cfg, tmp_path):
    a, _b = two_workbooks(tmp_path, site)
    cfg = quick(make_cfg, **{"runner.workers": 2})
    folder = tmp_path / "runs" / ".pools" / "p2"
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    main = asyncio.ensure_future(execute_many([RunOptions(workbook=a, tests=["A1"], seed=1, run_id="run-a", browser="chromium", extra={"ask": "ui"})], cfg, [bus],
                                              inbox_dir=folder))
    for _ in range(100):
        if any(e["type"] == "test_started" for e in events):
            break
        await asyncio.sleep(0.1)
    assert inbox_mod.post(folder, "r-missing", {"workbook": str(tmp_path / "nope.xlsx"), "tests": ["X"]})
    assert inbox_mod.post(folder, "r-safari", {"workbook": str(a), "tests": ["A2"], "browser": "safari"})
    assert inbox_mod.post(folder, "r-headed", {"workbook": str(a), "tests": ["A2"], "headed": True})
    assert inbox_mod.post(folder, "r-tests", {"workbook": str(a), "tests": ["Nope"]})
    for _ in range(100):
        if all(inbox_mod.answer(folder, r).startswith("rejected:") for r in ("r-missing", "r-safari", "r-headed", "r-tests")):
            break
        await asyncio.sleep(0.2)
    said = {r: inbox_mod.answer(folder, r) for r in ("r-missing", "r-safari", "r-headed", "r-tests")}
    assert "Workbook not found" in said["r-missing"] and "share their browser" in said["r-safari"]
    assert "run headless" in said["r-headed"] and "Unknown test" in said["r-tests"]
    ra, = await asyncio.wait_for(main, 180)
    assert ra.status == "PASSED" and not (tmp_path / "runs" / "r-safari").exists()                      # nothing half-made was left behind


@pytest.mark.browser
def test_the_command_line_runs_several_workbooks_at_once_and_says_which_line_is_whose(site, tmp_path):
    a, b = two_workbooks(tmp_path, site)
    (tmp_path / "config.yaml").write_text("runner: {workers: 2, stagger_s: 0, min_page_load_gap_s: 0}\ntimeouts: {element_s: 6, optional_s: 1.5}\n"
                                          "output: {match_timeout_s: 3}\ncaptcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(tmp_path / "config.yaml"), "run", str(a), "--tests", "A1",
                           str(b), "--all", "--plain", "--seed", "1"], cwd=tmp_path, capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    out = proc.stdout
    assert "[alpha.xlsx] Run " in out and "[beta.xlsx] Run " in out and "1 test(s)" in out and "2 test(s)" in out            # a run per workbook, its own tests
    assert all(line.startswith(("[alpha.xlsx]", "[beta.xlsx]")) for line in out.splitlines() if line.strip())
    runs = sorted(p.name for p in (tmp_path / "runs").iterdir() if p.is_dir())
    assert len(runs) == 2
    summaries = [json.loads((tmp_path / "runs" / r / "results.json").read_text()) for r in runs]
    assert sorted(len(s["tests"]) for s in summaries) == [1, 2] and all(s["status"] == "PASSED" for s in summaries)


async def test_a_selection_error_in_any_workbook_stops_everything_before_anything_is_created(site, make_cfg, tmp_path):
    a, b = two_workbooks(tmp_path, site)
    cfg = quick(make_cfg)
    with pytest.raises(SelectionError, match="Unknown test"):
        await execute_many([RunOptions(workbook=a, tests=["A1"]), RunOptions(workbook=b, tests=["Nope"])], cfg)
    assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())                    # no half-made run folder for the workbook that was fine
    with pytest.raises(SelectionError, match="share their browser"):
        await execute_many([RunOptions(workbook=a, tests=["A1"], browser="chromium"), RunOptions(workbook=b, tests=["B1"], browser="safari")], cfg)


@pytest.mark.browser
async def test_a_forced_stop_ends_the_tests_of_one_run_only(site, make_cfg, tmp_path):
    """The web UI writes ``stop`` in a run's folder when a cancel takes too long and other runs still depend on the process."""
    a, b = two_workbooks(tmp_path, site)
    cfg = quick(make_cfg, **{"runner.workers": 2, "runner.close_timeout_s": 5})
    bus_a, bus_b = EventBus(), EventBus()
    stopped_at: list[float] = []

    def stop_a_when_a_step_runs(e):
        if e["type"] == "step_started" and e["step"] == 5 and not stopped_at:
            stopped_at.append(asyncio.get_running_loop().time())
            (tmp_path / "runs" / "run-a" / "stop").write_text("stop")
    bus_a.subscribe(stop_a_when_a_step_runs)
    ra, rb = await asyncio.wait_for(execute_many([RunOptions(workbook=a, tests=["A1", "A2"], seed=1, run_id="run-a"),
                                                  RunOptions(workbook=b, tests=["B1", "B2"], seed=1, run_id="run-b")], cfg, [bus_a, bus_b]), 180)
    assert ra.status == "CANCELLED" and rb.status == "PASSED"
    assert {t.id for t in rb.tests} == {"B1", "B2"} and {t.status for t in rb.tests} == {"PASSED"}
    assert ra.tests and ra.tests[0].status == "CANCELLED" and ra.tests[0].passed >= 3                     # what it had done is kept, and it says how it ended
    assert "Stopped by force" in ra.tests[0].error
    meta = json.loads((tmp_path / "runs" / "run-a" / "run.json").read_text())
    assert meta["status"] == "CANCELLED"


async def test_a_site_that_a_block_has_reduced_leaves_its_workers_to_the_other_runs():
    a, b = FakeRun("a", ["a1", "a2", "a3"]), FakeRun("b", ["b1", "b2"])
    full = {"a": False}
    pool = Pool(asyncio.Event(), gate=lambda run: full.get(run.name, False))
    pool.add(a)
    pool.add(b)
    (run, case) = await pool.take()
    assert (run.name, case.id) == ("a", "a1")
    full["a"] = True                                                                        # a's site was blocked and may only have the test that is going
    assert [case.id for _, case in [await pool.take(), await pool.take()]] == ["b1", "b2"]      # the other workers go to b
    full["a"] = False
    assert (await pool.take())[1].id == "a2"                                                # room again: a carries on


def test_a_block_takes_workers_away_from_the_site_only_as_far_as_it_was_using_them():
    from regrunner.engine.throttle import Throttle
    site = Throttle(min_gap_s=0, workers=4)                                                # (4 = what may be asked for; the site is using 2 of them)
    assert site.cool_down(0, reduce=True, running=2) and site.limit == 1                   # one fewer than it had going, not one fewer than the pool has
    site = Throttle(min_gap_s=0, workers=4)
    assert site.cool_down(0, reduce=True, running=1) is False and site.limit == 1          # a single test cannot be reduced further: it is only paused


@pytest.mark.browser
async def test_a_block_by_one_sites_waf_does_not_stall_a_run_on_another_site(site, make_cfg, tmp_path):
    """Two workbooks on shared workers, each against its own host.  The first host answers 403 to the first page load (a rate limit): only pages of
    that host wait out the cool-down, the other run carries on (before: the pause and the worker taken out of service were the whole process's)."""
    a, b = tmp_path / "alpha.xlsx", tmp_path / "beta.xlsx"
    build_workbook(a, flows=["A1"], base_url=site + "flaky/", enabled=["A1"])                            # http://127.0.0.1:<port>/flaky/
    build_workbook(b, flows=["B1"], base_url=site.replace("127.0.0.1", "localhost"), enabled=["B1"])       # http://localhost:<port>/  (another host: another site)
    cfg = quick(make_cfg, **{"runner.workers": 2, "runner.block_cooldown_s": 40, "runner.block_retries": 1})
    timeline: list[tuple[str, dict]] = []
    buses = [EventBus(), EventBus()]
    for name, bus in zip("ab", buses):
        bus.subscribe(lambda e, name=name: timeline.append((name, e)))
    mock_server.FLAKY.update(block=1, seen=0)
    try:
        ra, rb = await asyncio.wait_for(execute_many([RunOptions(workbook=a, tests=["A1"], seed=1), RunOptions(workbook=b, tests=["B1"], seed=1)], cfg, buses), 240)
    finally:
        mock_server.FLAKY.update(block=0, seen=0)
    assert rb.status == "PASSED" and ra.status == "PASSED", (ra.status, ra.tests[0].error, rb.status)
    assert [e["type"] for n, e in timeline if n == "a" and e["type"] == "run_paused"] == ["run_paused"]     # a was blocked and waited
    assert not [1 for n, e in timeline if n == "b" and e["type"] == "run_paused"]                           # b never was told to wait
    assert ra.duration_s >= 40 and rb.duration_s < 35                                                      # a sat out its 40 s cool-down; b did not wait for it
