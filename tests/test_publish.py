"""The shared copy of a finished run (``publish.dir``): report + pass/fail summary, never the screenshots folder, never a failed run."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from regrunner import publish
from regrunner.cli import main
from regrunner.config import Config, load_config
from regrunner.reporting.results import RunResult, StepRecord, TestResult
from regrunner.runmeta import read_meta, update_meta
from tests.workbook_factory import build_workbook


def make_run(runs: Path, run_id: str = "20260924-101500-UAT", status: str = "FAILED") -> Path:
    """A finished run folder: one passing test, one failing test, a screenshot for every step."""
    run_dir = runs / run_id
    shots = run_dir / "tests" / "Owner_CRVD" / "screenshots"
    shots.mkdir(parents=True)
    steps = []
    for i, (name, ok) in enumerate([("Open", True), ("Click submit", True), ("Zip error gone", False)], start=1):
        shot = shots / f"{i:04d}.jpg"
        shot.write_bytes(b"\xff\xd8\xff" + bytes([i]) * 40)
        steps.append(StepRecord(seq=i, row=10 + i, name=name, action="Click", status="PASSED" if ok else "FAILED",
                                error="" if ok else "Expected the zip error to go away", screenshot=f"tests/Owner_CRVD/screenshots/{i:04d}.jpg"))
    good = TestResult(id="CW", title="Comprehensive Coverage", status="PASSED", total_steps=1, passed=1, duration_s=53.4,
                      steps=[StepRecord(seq=1, row=2, name="Open", action="Open", status="PASSED")])
    bad = TestResult(id="Owner_CRVD", title="Owner CRVD", status="FAILED", total_steps=200, passed=2, failed=1, duration_s=190, steps=steps)
    RunResult(run_id=run_id, workbook="/somewhere/UAT Regression.xlsx", environment="UAT", started_at="2026-09-24T10:15:00",
              duration_s=754, workers=3, status=status, tests=[good, bad], warnings=["one warning"]).save(run_dir / "results.json")
    update_meta(run_dir, run_id=run_id, status=status)
    return run_dir


def cfg_for(tmp_path: Path, share: Path | None, **publish_cfg) -> Config:
    cfg = Config(base_dir=tmp_path)
    cfg.publish.dir = str(share) if share else ""
    for key, value in publish_cfg.items():
        setattr(cfg.publish, key, value)
    return cfg


def test_the_summary_says_who_passed_who_failed_and_why():
    run_dir = Path("unused")
    data = {"run_id": "R1", "status": "FAILED", "environment": "UAT", "started_at": "2026-09-24T10:15:00", "duration_s": 754, "workers": 3,
            "workbook": "/x/UAT Regression.xlsx", "warnings": ["Note A"],
            "summary": {"tests": 2, "passed": 1, "failed": 1, "errored": 0, "steps": 4, "steps_failed": 1, "review_items": 5},
            "tests": [{"id": "CW", "title": "Comprehensive Coverage", "status": "PASSED", "steps": [{}], "total_steps": 1, "duration_s": 53},
                      {"id": "Owner_CRVD", "title": "Owner CRVD", "status": "FAILED", "total_steps": 200, "duration_s": 190, "error": "",
                       "steps": [{"seq": 3, "row": 13, "name": "Zip error gone", "status": "FAILED", "error": "still showing"}]}]}
    text = publish.summary_text(data)
    assert "Result:       FAILED  (1 of 2 tests passed, 1 did not)" in text
    assert "Environment:  UAT" in text and "took 12m 34s, 3 at a time" in text and "Workbook:     UAT Regression.xlsx" in text
    assert "PASSED    CW" in text and "FAILED    Owner_CRVD" in text
    assert 'step 3 (row 13) Zip error gone: still showing' in text
    assert "Note A" in text and "report.html" in text
    assert run_dir  # (silence linters)


def test_only_the_report_and_the_summary_are_copied_and_failed_steps_keep_their_screenshot(tmp_path):
    run_dir, share = make_run(tmp_path / "runs"), tmp_path / "share"
    dest = publish.publish_run(run_dir, share)
    assert dest == share / run_dir.name
    assert sorted(p.name for p in dest.iterdir()) == ["report.html", "summary.txt"]        # no screenshots folder, no results.json, no events
    html = (dest / "report.html").read_text(encoding="utf-8")
    assert html.count("data:image/jpeg;base64,") == 1                                       # the failed step only
    assert "Expected the zip error to go away" in html
    assert "FAILED" in (dest / "summary.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("mode,embedded", [("failures", 1), ("all", 3), ("none", 0)])
def test_screenshots_in_the_shared_report_follow_publish_screenshots(tmp_path, mode, embedded):
    run_dir = make_run(tmp_path / "runs")
    dest = publish.publish_run(run_dir, tmp_path / "share", mode)
    assert (dest / "report.html").read_text(encoding="utf-8").count("data:image/jpeg;base64,") == embedded


def test_copying_again_replaces_the_files_and_leaves_no_temp_files(tmp_path):
    run_dir = make_run(tmp_path / "runs")
    publish.publish_run(run_dir, tmp_path / "share")
    dest = publish.publish_run(run_dir, tmp_path / "share", "none")
    assert sorted(p.name for p in dest.iterdir()) == ["report.html", "summary.txt"]
    assert "data:image" not in (dest / "report.html").read_text(encoding="utf-8")


def test_a_finished_run_is_copied_and_noted_and_recorded(tmp_path):
    run_dir, share, notes = make_run(tmp_path / "runs"), tmp_path / "share", []
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, share), run_dir, "FAILED", lambda m, level="warning": notes.append((level, m))))
    assert (share / run_dir.name / "summary.txt").is_file()
    assert notes and notes[0][0] == "info" and str(share / run_dir.name) in notes[0][1]
    meta = read_meta(run_dir)
    assert meta["published"]["to"] == str(share / run_dir.name) and not meta.get("publish_error")
    assert (run_dir / "results.json").is_file() and (run_dir / "tests").is_dir()              # the local run is untouched


def test_nothing_happens_without_publish_dir_or_for_a_cancelled_run_unless_forced(tmp_path):
    run_dir, share, notes = make_run(tmp_path / "runs", status="CANCELLED"), tmp_path / "share", []
    note = lambda m, level="warning": notes.append(m)                                            # noqa: E731
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, None), run_dir, "FAILED", note))
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, share), run_dir, "CANCELLED", note))
    assert not share.exists() and not notes
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, share), run_dir, "CANCELLED", note, force=True))
    assert (share / run_dir.name / "report.html").is_file()


def test_an_unreachable_share_is_a_warning_not_a_failure_and_the_run_is_copied_after_the_next_one(tmp_path):
    runs, notes = tmp_path / "runs", []
    note = lambda m, level="warning": notes.append((level, m))                                   # noqa: E731
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file, so nothing can be created below it")
    first = make_run(runs, "20260924-090000-UAT")
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, blocker / "share"), first, "FAILED", note))
    assert notes[0][0] == "warning" and "Could not copy this run to the shared folder" in notes[0][1]
    assert f"python -m regrunner publish {first.name}" in notes[0][1]                            # what to do about it
    assert read_meta(first)["publish_error"] and not read_meta(first).get("published")

    share, notes[:] = tmp_path / "share", []                                                     # the share is back for the next run
    second = make_run(runs, "20260924-100000-UAT")
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, share), second, "PASSED", note))
    assert (share / second.name / "summary.txt").is_file() and (share / first.name / "summary.txt").is_file()
    assert any("earlier run" in m for _, m in notes)
    assert not read_meta(first).get("publish_error") and read_meta(first)["published"]["to"] == str(share / first.name)


def test_a_share_that_hangs_delays_the_end_of_the_run_by_the_timeout_and_no_longer(tmp_path, monkeypatch):
    run_dir, notes = make_run(tmp_path / "runs"), []
    release = __import__("threading").Event()
    monkeypatch.setattr(publish, "publish_run", lambda *a, **k: release.wait(30))               # a file call stuck on a dead share
    started = time.monotonic()
    asyncio.run(publish.publish_finished_run(cfg_for(tmp_path, tmp_path / "share", timeout_s=0.4), run_dir, "FAILED",
                                             lambda m, level="warning": notes.append((level, m))))
    release.set()
    assert time.monotonic() - started < 5
    assert notes and notes[0][0] == "warning" and "no answer within 0.4s" in notes[0][1]
    assert read_meta(run_dir)["publish_error"]


def test_probe_tells_a_writable_share_from_one_that_is_not(tmp_path):
    assert asyncio.run(publish.probe(tmp_path / "share")) == ""
    assert list((tmp_path / "share").iterdir()) == []                                            # the probe file is removed again
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert asyncio.run(publish.probe(blocker / "share"))


def test_doctor_and_the_ui_card_show_the_shared_folder_only_when_it_is_configured(tmp_path):
    assert asyncio.run(publish.publish_status(cfg_for(tmp_path, None))) is None
    ok = asyncio.run(publish.publish_status(cfg_for(tmp_path, tmp_path / "share")))
    assert ok["status"] == "ok" and ok["label"] == "Shared folder" and str(tmp_path / "share") in ok["detail"]
    blocker = tmp_path / "file"
    blocker.write_text("x")
    bad = asyncio.run(publish.publish_status(cfg_for(tmp_path, blocker / "share")))
    assert bad["status"] == "warn" and "cannot be written to" in bad["detail"]


def test_paths_may_start_with_a_tilde_or_use_an_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("QA_SHARE", str(tmp_path / "via-env"))
    assert Config().path("~/QA") == tmp_path / "QA"
    (tmp_path / "config.yaml").write_text("publish:\n  dir: ${QA_SHARE}/runs\n  screenshots: all\n")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.path(cfg.publish.dir) == tmp_path / "via-env" / "runs" and cfg.publish.screenshots == "all"


def test_the_publish_command_copies_a_run_by_id_and_can_force_a_cancelled_one(tmp_path, capsys):
    run_dir = make_run(tmp_path / "runs", status="CANCELLED")
    share = tmp_path / "share"
    (tmp_path / "config.yaml").write_text(f"publish:\n  dir: {share}\n")
    assert main(["--config", str(tmp_path / "config.yaml"), "publish", run_dir.name]) == 0
    assert (share / run_dir.name / "report.html").is_file() and str(share / run_dir.name) in capsys.readouterr().out
    assert read_meta(run_dir)["published"]["to"] == str(share / run_dir.name)
    other = tmp_path / "other"
    assert main(["--config", str(tmp_path / "config.yaml"), "publish", run_dir.name, "--to", str(other), "--screenshots", "none"]) == 0
    assert "data:image" not in (other / run_dir.name / "report.html").read_text(encoding="utf-8")


def test_the_publish_command_explains_what_is_missing(tmp_path, capsys):
    (tmp_path / "config.yaml").write_text("runner: {workers: 1}\n")
    make_run(tmp_path / "runs")
    assert main(["--config", str(tmp_path / "config.yaml"), "publish", "20260924-101500-UAT"]) == 2
    assert "Set publish.dir" in capsys.readouterr().err
    assert main(["--config", str(tmp_path / "config.yaml"), "publish", "nope", "--to", str(tmp_path / "s")]) == 2
    assert "no results.json" in capsys.readouterr().err
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert main(["--config", str(tmp_path / "config.yaml"), "publish", "20260924-101500-UAT", "--to", str(blocker / "s")]) == 1
    assert "could not copy" in capsys.readouterr().err


@pytest.mark.browser
def test_a_real_run_leaves_its_report_and_summary_in_the_shared_folder_and_everything_in_runs(site, tmp_path):
    wb, share = tmp_path / "wb.xlsx", tmp_path / "share"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    (tmp_path / "config.yaml").write_text(
        "timeouts: {element_s: 6, optional_s: 1.5}\noutput: {match_timeout_s: 3}\ncaptcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\n"
        f"publish: {{dir: '{share}'}}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(tmp_path / "config.yaml"), "run", str(wb), "--plain", "--seed", "1"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (run_dir,) = list((tmp_path / "runs").iterdir())
    (shared,) = list(share.iterdir())
    assert shared.name == run_dir.name and sorted(p.name for p in shared.iterdir()) == ["report.html", "summary.txt"]
    assert "PASSED" in (shared / "summary.txt").read_text(encoding="utf-8")
    assert "data:image" not in (shared / "report.html").read_text(encoding="utf-8")           # all passed: nothing to embed
    assert (run_dir / "report.html").is_file() and list((run_dir / "tests").rglob("*.jpg"))       # the UI's copy is complete
    assert read_meta(run_dir)["published"]["to"] == str(shared)
    log = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "Copied the report and summary to" in log


@pytest.mark.browser
def test_a_run_finishes_normally_when_the_shared_folder_is_not_available(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    (tmp_path / "config.yaml").write_text(
        "timeouts: {element_s: 6, optional_s: 1.5}\noutput: {match_timeout_s: 3}\ncaptcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\n"
        f"publish: {{dir: '{blocker / 'share'}'}}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(tmp_path / "config.yaml"), "run", str(wb), "--plain", "--seed", "1"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr                                       # the run passed; the share is not its business
    assert "cannot be written to right now" in proc.stdout                                       # told up front
    (run_dir,) = list((tmp_path / "runs").iterdir())
    assert (run_dir / "report.html").is_file()
    assert read_meta(run_dir)["publish_error"]
    assert json.loads((run_dir / "results.json").read_text())["status"] == "PASSED"
