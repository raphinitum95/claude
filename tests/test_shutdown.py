"""A run must always be able to end: a browser that will not close cannot stall it, and Cancel really stops a wedged runner."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from regrunner.web import app as web_app
from tests.web_fixtures import web  # noqa: F401  (module fixture: a live UI + backend on a scratch project)
from tests.workbook_factory import build_workbook

# Run the CLI with every browser/window close made to hang forever, like a Chromium that has wedged on a pop-up.
NEVER_CLOSES = '''
import asyncio, sys
from playwright.async_api import Browser, BrowserContext
async def never(self, *a, **k):
    await asyncio.sleep(3600)
BrowserContext.close = never
Browser.close = never
from regrunner.cli import main
sys.exit(main(sys.argv[1:]))
'''

# Loaded by every runner subprocess (via PYTHONPATH) when RR_TEST_WEDGE is set: the test itself never finishes and ignores cancel.
WEDGE = '''
import asyncio, os, time
mode = os.environ.get("RR_TEST_WEDGE")
if mode:
    from regrunner.engine.test_runner import TestRunner
    if mode == "async":
        async def stuck(self):
            await asyncio.sleep(3600)          # waiting forever on something; the event loop is alive
    else:
        async def stuck(self):
            time.sleep(3600)                   # the whole event loop is blocked
    TestRunner.run = stuck
'''


@pytest.mark.browser
def test_a_browser_that_never_closes_cannot_stall_the_run(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("runner: {close_timeout_s: 2}\ntimeouts: {element_s: 6, optional_s: 1.5}\noutput: {match_timeout_s: 3}\n"
                   "captcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-c", NEVER_CLOSES, "--config", str(cfg), "run", str(wb), "--plain", "--seed", "1"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASSED: 1/1 tests passed" in proc.stdout
    assert time.monotonic() - started < 100
    (run_dir,) = list((tmp_path / "runs").iterdir())
    logs = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    said = " ".join(e.get("message", "") for e in logs if e["type"] == "log")
    assert "did not close within 2s" in said and "closing the browsers" in said            # and it says what it skipped
    assert logs[-1]["type"] == "run_finished"


@pytest.mark.browser
def test_sigterm_stops_a_runner_that_ignores_cancel(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    (tmp_path / "config.yaml").write_text("reports: {html: false}\n")
    (tmp_path / "wedge").mkdir()
    (tmp_path / "wedge" / "sitecustomize.py").write_text(WEDGE)
    env = {**os.environ, "RR_TEST_WEDGE": "async", "PYTHONPATH": str(tmp_path / "wedge")}
    proc = subprocess.Popen([sys.executable, "-m", "regrunner", "--config", str(tmp_path / "config.yaml"), "run", str(wb), "--plain"],
                            cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        events = tmp_path / "runs"
        for _ in range(100):                                               # wait until the run really started
            found = list(events.glob("*/events.jsonl"))
            if found and "run_started" in found[0].read_text():
                break
            time.sleep(0.2)
        time.sleep(2)                                                      # the wedged test is running (cancel-before-start would just exit)
        proc.send_signal(signal.SIGTERM)
        started = time.monotonic()
        code = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert code == 130 and time.monotonic() - started < 20
    assert "hard stop" in proc.stderr.read()                              # and it wrote down what everything was waiting on


@pytest.mark.browser
@pytest.mark.parametrize("mode,limit", [("async", 25), ("blocked", 12)])
def test_cancel_ends_a_wedged_run_instead_of_leaving_it_running(web, monkeypatch, tmp_path, mode, limit):  # noqa: F811
    (tmp_path / "sitecustomize.py").write_text(WEDGE)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("RR_TEST_WEDGE", mode)
    monkeypatch.setattr(web_app, "CANCEL_GRACE_S", 1)
    monkeypatch.setattr(web_app, "KILL_AFTER_S", 2)
    with web.client() as c:
        run_id = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"]}).json()["run_id"]
        time.sleep(3)                                                      # the runner is up and the test is wedged
        assert c.get(f"/api/runs/{run_id}").json()["meta"]["status"] == "RUNNING"
        asked = time.monotonic()
        assert c.post(f"/api/runs/{run_id}/cancel").json() == {"ok": True}
        detail = web.wait_finished(run_id, timeout=limit + 15)
        assert time.monotonic() - asked < limit, "cancel took too long"
        assert detail["meta"]["status"] == "CANCELLED"
        events = c.get(f"/api/runs/{run_id}/events").json()["events"]
        assert events[-1]["type"] == "run_finished" and events[-1]["status"] == "CANCELLED"
        assert next(r for r in c.get("/api/runs").json() if r["run_id"] == run_id)["active"] is False
