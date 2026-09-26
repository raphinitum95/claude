"""Phase 1 of "the same speed at 1 or 20 tests": one record across all runs, built from the run folders, with what changed between runs and
what got slower or started failing since - and never a value a step typed or read."""
from __future__ import annotations

import csv
import json
from datetime import datetime

import pytest

from regrunner.cli import main
from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from regrunner.history import compare, export_csv, load_runs, markers, step_error_kind, third_party_hosts
from tests.workbook_factory import build_steps_workbook


def _step(seq, name, status="PASSED", ms=1000, site_ms=None, error="", **extra):
    timing = {"site_ms": site_ms if site_ms is not None else ms // 2, "wait_ms": 0, "runner_ms": ms // 4, "computer_ms": 0,
              "other_ms": ms - (site_ms if site_ms is not None else ms // 2) - ms // 4}
    return {"seq": seq, "row": seq + 1, "name": name, "action": "CLICK", "status": status, "error": error, "duration_ms": ms,
            "ended_at": "2026-09-20T10:00:05.000+00:00", "timing": timing, "value": "typed-secret-value", "actual": "read-value",
            "expected": "wanted-value", **extra}


def _write_run(runs, run_id, started, steps, *, runner="src-aaa", site="fp1", browser="130.0", workers=3, hosts=None, config=None):
    folder = runs / run_id
    folder.mkdir(parents=True)
    test = {"id": "Purchase#1", "status": "FAILED" if any(s["status"] == "FAILED" for s in steps) else "PASSED", "steps": steps,
            "duration_s": sum(s["duration_ms"] for s in steps) / 1000, "attempt": 1, "started_at": started, "ended_at": started,
            "timing": {"site_s": 1.0, "wait_s": 0.0, "runner_s": 0.5, "computer_s": 0.0, "other_s": 0.5, "queue_s": 2.0},
            "third_party": hosts or [], "site_version": {"fingerprint": site, "files": 12} if site else {}}
    data = {"run_id": run_id, "workbook": "/x/qantas-test.xlsx", "environment": "UAT", "started_at": started, "status": test["status"],
            "workers": workers, "tests": [test], "summary": {"tests": 1}, "browser": {"id": "chrome", "version": browser},
            "config": config or {"runner": {"workers": workers, "stagger_s": 4.0}, "screenshots": {"quality": 60}},
            "machine": {"os": "Windows", "cpus": 4, "ram_mb": 16000, "runner_version": runner} if runner else {}}
    (folder / "results.json").write_text(json.dumps(data), encoding="utf-8")
    sampled = datetime.fromisoformat("2026-09-20T10:00:01+00:00").timestamp()          # (before every step of the fixture ended)
    (folder / "resources.jsonl").write_text(json.dumps({"t": sampled, "mem_free_mb": 2100, "tests_running": 3}) + "\n", encoding="utf-8")
    return folder


@pytest.fixture
def runs(tmp_path):
    runs = tmp_path / "runs"
    fast = [_step(1, "Open"), _step(2, "Quote", ms=2000, site_ms=1000), _step(3, "Pay")]
    _write_run(runs, "r1", "2026-09-20T10:00:00+00:00", fast, hosts=[{"host": "www.googletagmanager.com", "requests": 4, "bytes": 90000}])
    _write_run(runs, "r2", "2026-09-21T10:00:00+00:00", fast, hosts=[{"host": "www.googletagmanager.com", "requests": 3, "bytes": 80000},
                                                                      {"host": "cdn.chat.example", "requests": 9, "bytes": 1000}])
    slow = [_step(1, "Open"), _step(2, "Quote", ms=7000, site_ms=6000), _step(3, "Pay", status="FAILED", error="Comparison Failed: expected X")]
    _write_run(runs, "r3", "2026-09-22T10:00:00+00:00", slow, site="fp2")        # the site deployed new code: Quote got slow, Pay fails
    (runs / "not-a-run").mkdir()
    return runs


def test_history_is_built_from_the_run_folders_oldest_first(runs):
    loaded = load_runs(runs)
    assert [r.run_id for r in loaded] == ["r1", "r2", "r3"] and loaded[2].site_version == "fp2" and loaded[0].samples


def test_a_new_site_version_is_a_what_changed_marker_and_compare_names_what_got_slower_and_what_started_failing(runs):
    loaded = load_runs(runs)
    (marker,) = markers(loaded)
    assert (marker.kind, marker.run_id, marker.before, marker.after) == ("site", "r3", "fp1", "fp2")
    lines = compare(loaded)
    text = "\n".join(lines)
    assert "2 run(s) before vs 1 since site version" in lines[0]
    assert 'Purchase#1 step "Quote" (row 3): 3.5 x slower (2.0 s -> 7.0 s); mostly the site (+5.0 s)' in text
    assert 'Purchase#1 step "Pay" (row 4): passed in every run before, fails in every run since (site_said_no)' in text
    assert "Open" not in text


def test_compare_can_split_at_a_chosen_run(runs):
    lines = compare(load_runs(runs), at="r2")
    assert "1 run(s) before vs 2 since run r2" in lines[0] and '"Quote" (row 3): 2.2 x slower (2.0 s -> 4.5 s)' in "\n".join(lines)   # median of r2 + r3
    assert "fails in every run since" not in "\n".join(lines)                                                                            # (Pay passed in r2)


def test_runner_browser_and_setting_changes_are_markers_too(tmp_path):
    runs = tmp_path / "runs"
    _write_run(runs, "a", "2026-09-20T10:00:00+00:00", [_step(1, "Open")], runner="src-1", browser="130")
    _write_run(runs, "b", "2026-09-21T10:00:00+00:00", [_step(1, "Open")], runner="src-2", browser="131", workers=5)
    _write_run(runs, "c", "2026-09-22T10:00:00+00:00", [_step(1, "Open")], runner=None, browser="131", workers=5)   # (an old run: no machine recorded)
    kinds = {(m.kind, m.run_id) for m in markers(load_runs(runs))}
    assert kinds == {("runner", "b"), ("browser", "b"), ("settings", "b")}
    settings = next(m for m in markers(load_runs(runs)) if m.kind == "settings")
    assert "runner.workers=3" in settings.before and "runner.workers=5" in settings.after


def test_the_csv_export_has_times_kinds_and_versions_but_never_what_a_step_typed_or_read(runs, tmp_path):
    paths = export_csv(load_runs(runs), tmp_path / "out")
    assert [p.name for p in paths] == ["runs.csv", "tests.csv", "steps.csv"]
    text = "".join(p.read_text(encoding="utf-8-sig") for p in paths)
    assert "typed-secret-value" not in text and "read-value" not in text and "wanted-value" not in text and "expected X" not in text
    steps = list(csv.DictReader((tmp_path / "out" / "steps.csv").open(encoding="utf-8-sig")))
    assert len(steps) == 9 and {"site_ms", "wait_ms", "runner_ms", "computer_ms", "other_ms", "mem_free_mb", "error_kind"} <= set(steps[0])
    assert steps[-1]["error_kind"] == "site_said_no" and steps[0]["mem_free_mb"] == "2100" and steps[0]["runner_version"] == "src-aaa"
    tests = list(csv.DictReader((tmp_path / "out" / "tests.csv").open(encoding="utf-8-sig")))
    assert tests[0]["queue_s"] == "2.0" and tests[2]["site_version"] == "fp2"


def test_failure_kinds_tell_the_site_the_page_the_machine_and_the_waf_apart():
    assert step_error_kind({"status": "FAILED", "error": "Comparison Failed: expected A, got B"}) == "site_said_no"
    assert step_error_kind({"status": "FAILED", "error": "Object was not found"}) == "element_missing"
    assert step_error_kind({"status": "NOT_RUN", "error": "Not run: the browser crashed"}) == "infra"
    assert step_error_kind({"status": "FAILED", "error": "Blocked by the site: HTTP 403 to the page load"}) == "waf"
    assert step_error_kind({"status": "PASSED"}) == ""


def test_third_party_hosts_are_tallied_over_all_runs(runs):
    hosts = third_party_hosts(load_runs(runs))
    assert hosts[0] == {"host": "cdn.chat.example", "requests": 9, "bytes": 1000, "tests": 1, "runs": 1}
    assert hosts[1]["host"] == "www.googletagmanager.com" and hosts[1]["requests"] == 7 and hosts[1]["runs"] == 2


def test_the_history_command_prints_changes_and_writes_csv(runs, tmp_path, capsys):
    assert main(["history", "--runs", str(runs), "--csv", str(tmp_path / "csv"), "--hosts"]) == 0
    out = capsys.readouterr().out
    assert "3 run(s) of 1 workbook(s)" in out and "site version (its code files) changed in run r3" in out and "3.5 x slower" in out
    assert "www.googletagmanager.com" in out and (tmp_path / "csv" / "steps.csv").is_file()


@pytest.mark.browser
async def test_history_from_real_runs_detects_that_the_site_deployed_new_code(site, make_cfg, tmp_path):
    def flow(sheet) -> None:
        sheet.add("Open", "Open", Value="DT_URL")
        sheet.add("Click", "Go", FindBy="xpath", FindBy_Value="//button[@id='go']")
        sheet.add("Quit", "Quit")
    cfg = make_cfg(**{"runner.stagger_s": 0, "measure.sample_s": 0.5})
    ids = []
    for lib in ("app", "app", "app2"):                               # two runs of the same site, then one after "a deployment"
        wb = tmp_path / "shop.xlsx"
        build_steps_workbook(wb, {"Buy": flow}, params={"Buy": {"DT_URL": f"{site}tracked.html?lib={lib}"}})
        result = await execute(RunOptions(workbook=wb, seed=1, tests=["Buy"], workers=1), cfg, EventBus())
        assert result.tests[0].status == "PASSED"
        ids.append(result.run_id)
    loaded = load_runs(cfg.path(cfg.runs_dir))
    assert [r.run_id for r in loaded] == ids
    site_changes = [m for m in markers(loaded) if m.kind == "site"]
    assert [m.run_id for m in site_changes] == [ids[2]]
    assert loaded[0].site_version == loaded[1].site_version != loaded[2].site_version
    paths = export_csv(loaded, tmp_path / "csv")
    steps = list(csv.DictReader(paths[2].open(encoding="utf-8-sig")))
    assert len(steps) == 9 and all(s["site_ms"] != "" and s["mem_free_mb"] != "" for s in steps if s["step"] == "Go")
