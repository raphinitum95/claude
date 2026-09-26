"""Phase 0 of "the same speed at 1 or 20 tests": a run measures itself (where each step's time went, the queue, the computer, third-party
hosts, the site's code version) without changing how any test runs, and without ever recording a secret."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from regrunner.engine.resources import LoopLag, machine_info, read_resources, read_sample, CpuMeter, summarize
from regrunner.engine.schedule import Schedule
from regrunner.engine.timing import PARTS, Timing, describe, fingerprint_site_code, run_summary
from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from tests.workbook_factory import build_steps_workbook


class _Case:
    def __init__(self, id_):
        self.id = id_


# ---- the time split (no browser) -----------------------------------------------------------------------------
def test_a_steps_split_adds_up_to_its_wall_time_and_never_double_counts():
    timing = Timing()
    timing.step_started()
    timing.site.started("page")                                  # the site answers for 0.2 s...
    time.sleep(0.2)
    timing.site.ended("page")
    with timing.span("wait", "pacing"):                          # ...then a deliberate wait of 0.15 s
        time.sleep(0.15)
    with timing.span("runner", "screenshots"):                   # ...then the runner's own work, 0.1 s, the site busy for part of it
        timing.site.started("xhr")
        time.sleep(0.05)
        timing.site.ended("xhr")
        with timing.span("runner", "nested"):                    # (a span inside a span is not counted twice)
            time.sleep(0.05)
    time.sleep(0.05)                                             # nothing the runner can name: the browser acting (with a late heartbeat in it)
    timing.lagged(0.02)
    split = timing.step_ended()
    total = sum(split[f"{p}_ms"] for p in PARTS)
    assert abs(total - 500) < 60, split
    assert 180 <= split["site_ms"] <= 300 and 130 <= split["wait_ms"] <= 200 and 30 <= split["runner_ms"] <= 90, split
    assert split["computer_ms"] == 20 and split["wait_kinds_ms"].keys() == {"pacing"} and split["runner_kinds_ms"].keys() == {"screenshots"}


def test_the_site_answering_during_a_deliberate_wait_counts_as_the_wait_not_the_site():
    timing = Timing()
    timing.step_started()
    with timing.span("wait", "login_code"):
        timing.site.started("poll")
        time.sleep(0.1)
        timing.site.ended("poll")
    split = timing.step_ended()
    assert split["site_ms"] < 20 and split["wait_ms"] >= 90


def test_requests_of_a_closed_window_stop_counting_as_the_site_working():
    timing = Timing()
    timing.site.started("never answers")
    time.sleep(0.05)
    timing.site.forget(["never answers"])
    busy = timing.site.busy_s()
    time.sleep(0.05)
    assert timing.site.busy_s() == busy


def test_the_run_summary_and_its_sentence_name_every_part_and_the_queue_separately():
    tests = [{"timing": {"site_s": 60, "wait_s": 30, "runner_s": 10, "computer_s": 0, "other_s": 20, "queue_s": 45,
                         "wait_kinds_s": {"login_code": 30}, "runner_kinds_s": {"screenshots": 10}}},
             {"timing": {}}, {"no": "timing"}]
    summary = run_summary(tests)
    assert summary["tests"] == 1 and summary["site_s"] == 60 and summary["queue_s"] == 45 and summary["wait_kinds_s"] == {"login_code": 30}
    line = describe(summary)
    assert "the site 60 s (50%)" in line and "deliberate waits 30 s (25%)" in line and "in the queue" in line and "busy computer" not in line


def test_the_site_version_changes_when_a_code_file_changes_and_only_then():
    one = fingerprint_site_code({"/etc.clientlibs/site.min.js": '"abc"', "/etc.clientlibs/vendor.js": "123"})
    same = fingerprint_site_code({"/etc.clientlibs/vendor.js": "123", "/etc.clientlibs/site.min.js": '"abc"'})
    new = fingerprint_site_code({"/etc.clientlibs/site.min.js": '"abd"', "/etc.clientlibs/vendor.js": "123"})
    assert one == same and one["fingerprint"] != new["fingerprint"] and one["files"] == 2 and fingerprint_site_code({}) == {}


def test_queue_time_counts_from_when_a_test_could_start_not_from_when_the_run_did():
    schedule = Schedule([_Case("A"), _Case("B")], {"B": ["A"]})
    time.sleep(0.1)
    schedule.start(schedule.next_ready())                         # A waited 0.1 s for a worker
    queued, deps = schedule.queued_s("A")
    assert queued >= 0.09 and deps < 0.01
    schedule.finish("A")                                          # B could start from here...
    time.sleep(0.05)
    schedule.start(schedule.next_ready())
    queued, deps = schedule.queued_s("B")
    assert 0.04 <= queued < 0.09 and deps >= 0.09                 # ...its wait for A is not queue time


# ---- the computer (no browser) ---------------------------------------------------------------------------------
def test_a_resource_sample_reads_this_computer_without_psutil_and_never_raises():
    meter = CpuMeter()
    meter.read()
    time.sleep(0.2)
    sample = read_sample(meter)
    assert set(sample) == {"cpu_pct", "mem_free_mb", "mem_total_mb", "swap_used_mb", "browsers_mb", "processes"}
    assert sample["mem_total_mb"] and sample["mem_free_mb"] is not None
    info = machine_info()
    assert info["runner_version"].startswith("src-") and info["cpus"] and "node" not in json.dumps(info).lower()


async def test_the_loop_lag_heartbeat_notices_a_blocked_event_loop():
    lag = LoopLag()
    beat = asyncio.ensure_future(lag.run())
    await asyncio.sleep(0.15)
    time.sleep(0.3)                                               # something blocks the loop that every test shares
    await asyncio.sleep(0.15)
    beat.cancel()
    worst, total = lag.take()
    assert worst >= 0.2 and total >= 0.2


def test_resource_peaks_skip_missing_numbers(tmp_path):
    path = tmp_path / "resources.jsonl"
    path.write_text('{"mem_free_mb": 900, "swap_used_mb": null, "loop_lag_ms": 12}\n{"mem_free_mb": 700, "loop_lag_ms": 40}\n{"cut', encoding="utf-8")
    peaks = summarize(read_resources(path))
    assert peaks["samples"] == 2 and peaks["min_mem_free_mb"] == 700 and peaks["max_loop_lag_ms"] == 40 and peaks["max_swap_used_mb"] is None


# ---- a real run on the mock site --------------------------------------------------------------------------------
@pytest.mark.browser
async def test_a_run_records_where_its_time_went_the_queue_the_computer_third_parties_and_the_site_version(site, make_cfg, tmp_path):
    def flow(sheet) -> None:
        sheet.add("Open", "Open", Value="DT_URL")
        sheet.add("Open", "Open again", Value="DT_URL")          # a second page load: spaced by runner.min_page_load_gap_s = a deliberate wait
        sheet.add("Click", "Go", FindBy="xpath", FindBy_Value="//button[@id='go']")
        sheet.add("Quit", "Quit")
    wb = tmp_path / "wb.xlsx"
    params = {"DT_URL": site + "tracked.html"}
    build_steps_workbook(wb, {"One": flow, "Two": flow}, params={"One": params, "Two": params})
    cfg = make_cfg(**{"runner.stagger_s": 0, "runner.min_page_load_gap_s": 1.5, "measure.sample_s": 0.5})
    result = await execute(RunOptions(workbook=wb, seed=1, tests=["One", "Two"], workers=1), cfg, EventBus())
    assert [t.status for t in result.tests] == ["PASSED", "PASSED"]
    run_dir = cfg.path(cfg.runs_dir) / result.run_id
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))

    for test in data["tests"]:
        for step in test["steps"]:                                # every step's parts add up to its own time
            split = step["timing"]
            assert abs(sum(split[f"{p}_ms"] for p in PARTS) - step["duration_ms"]) <= max(50, step["duration_ms"] * 0.05), step
        assert test["timing"]["wait_kinds_s"].get("pacing", 0) >= 1.0            # the second Open waited for the page-load spacing
        assert test["timing"]["site_s"] > 0 and "screenshots" in test["timing"]["runner_kinds_s"]
        assert [h["host"] for h in test["third_party"]] == ["localhost"] and set(test["third_party"][0]) == {"host", "requests", "bytes"}
        assert test["site_version"]["files"] == 1 and len(test["site_version"]["fingerprint"]) == 12
    one, two = data["tests"]
    assert one["timing"]["queue_s"] < 1 and two["timing"]["queue_s"] >= one["duration_s"] - 1     # one worker: Two queued while One ran
    assert data["tests"][0]["site_version"] == data["tests"][1]["site_version"]
    assert data["timing"]["tests"] == 2 and data["machine"]["runner_version"].startswith("src-")

    samples = read_resources(run_dir / "resources.jsonl")
    assert samples and all({"mem_free_mb", "browsers_mb", "loop_lag_ms", "tests_running"} <= set(s) for s in samples)
    assert any(s["tests_running"] == 1 for s in samples) and data["resources"]["samples"] == len(samples)
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Where the time went" in report and "The computer" in report and "queued" in report
    measured = (run_dir / "resources.jsonl").read_text(encoding="utf-8") + json.dumps([t["third_party"] for t in data["tests"]])
    assert "http" not in measured and "tracker.js" not in measured and "/" not in json.dumps([t["third_party"] for t in data["tests"]])   # hosts only, never an address
