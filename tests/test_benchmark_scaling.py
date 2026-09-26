"""The target of "the same speed at 1 or 20 tests": a test's own time in a run of N stays within 1.6 x its time alone.

Slow (several minutes) and opt-in: it only runs with ``RR_BENCHMARK=1`` (never part of the default subset).  It prints, per N, each test's
time against the solo time and where the time went, and the queue time separately (a crowded run may take longer as a whole: that is the
accepted trade-off; the tests that run must stay fast).  On this mock site pages are light: it measures the runner, not a real site's
JavaScript (memory comparisons come from real runs: ``resources.jsonl``).

    RR_BENCHMARK=1 .venv/bin/pytest -s tests/test_benchmark_scaling.py
    RR_BENCHMARK=1 RR_BENCHMARK_N=5,10 .venv/bin/pytest -s tests/test_benchmark_scaling.py
"""
from __future__ import annotations

import json
import os
import statistics

import pytest

from regrunner.engine.runner import RunOptions, execute
from regrunner.engine.timing import describe, run_summary
from regrunner.events import EventBus
from tests.workbook_factory import build_workbook

pytestmark = [pytest.mark.browser, pytest.mark.benchmark,
              pytest.mark.skipif(os.environ.get("RR_BENCHMARK") != "1", reason="slow benchmark: set RR_BENCHMARK=1 to run it")]

TARGET = 1.6


async def _run(site, make_cfg, tmp_path, n: int):
    flows = [f"F{i:02d}" for i in range(1, n + 1)]
    wb = tmp_path / f"wb{n}.xlsx"
    build_workbook(wb, flows=flows, base_url=site + "index.html")
    cfg = make_cfg(**{"runner.max_workers": max(n, 1), "measure.sample_s": 2})
    result = await execute(RunOptions(workbook=wb, seed=1, tests=flows, workers=n), cfg, EventBus())
    data = json.loads((cfg.path(cfg.runs_dir) / result.run_id / "results.json").read_text(encoding="utf-8"))
    return data


async def test_a_tests_own_time_stays_within_the_target_as_the_number_of_tests_grows(site, make_cfg, tmp_path):
    sizes = [int(x) for x in os.environ.get("RR_BENCHMARK_N", "5,10,20").split(",") if x.strip()]
    solo = await _run(site, make_cfg, tmp_path, 1)
    assert solo["tests"][0]["status"] == "PASSED"
    base = solo["tests"][0]["duration_s"]
    lines = [f"solo: {base:.1f} s  ({describe(run_summary(solo['tests']))})"]
    worst: dict[int, float] = {}
    for n in sizes:
        data = await _run(site, make_cfg, tmp_path, n)
        durations = [t["duration_s"] for t in data["tests"]]
        assert all(t["status"] == "PASSED" for t in data["tests"]), [(t["id"], t["status"], t["error"]) for t in data["tests"]]
        worst[n] = max(durations) / base
        res = data.get("resources") or {}
        lines.append(f"N={n:>2}: per test median {statistics.median(durations):.1f} s, max {max(durations):.1f} s = {worst[n]:.2f} x solo; "
                     f"run {data['duration_s']:.0f} s; least free memory {res.get('min_mem_free_mb')} MB, browsers up to {res.get('max_browsers_mb')} MB, "
                     f"loop lag up to {res.get('max_loop_lag_ms')} ms\n       {describe(run_summary(data['tests']))}")
    print("\n" + "\n".join(lines))
    assert all(ratio <= TARGET for ratio in worst.values()), f"per-test time above {TARGET} x solo: {worst}"
