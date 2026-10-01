"""A browser the person chose to watch ("Show browsers" / --headed) and a headless one they want to look at anyway ("Watch live").

* a blocked (HTTP 403) shown browser stays on the page the site blocked while the cool-down runs, instead of closing and a blank window waiting;
* a shown browser fills the screen (no fixed 1920x1080 sheet that a smaller screen crops), does not freeze/restore the page's animations at every
  step, and is not run at low priority;
* a headless test can be watched live: a picture every second while somebody asks for it, nothing otherwise.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.capture.review import ReviewCollector
from regrunner.config import Config
from regrunner.engine import live
from regrunner.engine.session import BrowserSession
from regrunner.engine.test_runner import TestRunner
from tests.site import server as mock_server
from tests.test_web_cancel_test import plant_running_run
from tests.test_web_ui import open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)
from tests.workbook_factory import build_workbook

pytestmark = pytest.mark.browser
needs_a_display = pytest.mark.skipif(not shutil.which("xvfb-run"), reason="a shown browser needs a display (xvfb-run)")


@pytest.fixture(autouse=True)
def waf_off():
    mock_server.WAF.update(until=0.0, pages=False)
    mock_server.FLAKY.update(block=0, seen=0)
    yield
    mock_server.WAF.update(until=0.0, pages=False)
    mock_server.FLAKY.update(block=0, seen=0)


async def open_session(pw, site: str, path: str, *, headed: bool, **runner):
    browser = await pw.chromium.launch()

    async def getter():
        return browser
    cfg = Config()
    for key, value in runner.items():
        setattr(cfg.runner, key, value)
    session = BrowserSession(getter, cfg, ReviewCollector("t", lambda *a, **k: None), "t", "UAT")
    session.headed = headed
    await session.open(site + path)
    return browser, session


# -- the window ------------------------------------------------------------------------------------------------------------------
async def test_a_shown_browser_uses_the_whole_window_but_a_headless_one_keeps_the_fixed_size(site):
    async with async_playwright() as pw:
        browser, session = await open_session(pw, site, "nav_button.html", headed=False)
        try:
            assert session.page.viewport_size == {"width": 1920, "height": 1080}
            assert await session.view_size() == (1920.0, 1080.0)
        finally:
            await session.close()
            await browser.close()
        browser, session = await open_session(pw, site, "nav_button.html", headed=True)
        try:
            assert session.page.viewport_size is None                      # no emulated sheet: the page lays out in the window it is in
            width, height = await session.view_size()                      # ...and the steps still know how big that is (box in the screenshot, mouse centre)
            assert width > 100 and height > 100
        finally:
            await session.close()
            await browser.close()


async def test_the_fixed_size_comes_back_when_the_fit_to_screen_setting_is_off(site):
    async with async_playwright() as pw:
        browser, session = await open_session(pw, site, "nav_button.html", headed=True, headed_fit_window=False)
        try:
            assert session.page.viewport_size == {"width": 1920, "height": 1080}
        finally:
            await session.close()
            await browser.close()


def test_a_shown_browser_leaves_the_pages_animations_alone_when_it_takes_a_screenshot():
    assert TestRunner._shot_animations(SimpleNamespace(_visible=True)) == "allow"
    assert TestRunner._shot_animations(SimpleNamespace(_visible=False)) == "disabled"       # the evidence picture of a headless test stays frozen and clean


# -- a block in a shown browser --------------------------------------------------------------------------------------------------
def run_shown(site, tmp_path, runner_cfg: str, *flags: str):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site + "flaky/")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"runner: {{{runner_cfg}}}\ntimeouts: {{element_s: 6, optional_s: 1.5}}\noutput: {{match_timeout_s: 3}}\n"
                   "captcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    cmd = [sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain", "--seed", "1", *flags]
    if "--headed" in flags:
        cmd = ["xvfb-run", "-a", *cmd]
    proc = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=240, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    (run_dir,) = list((tmp_path / "runs").iterdir())
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    return proc, json.loads((run_dir / "results.json").read_text())["tests"][0], events, json.loads((run_dir / "run.json").read_text())


@needs_a_display
def test_a_blocked_shown_browser_stays_on_the_blocked_page_while_the_cool_down_runs(site, tmp_path):
    mock_server.FLAKY.update(block=1, seen=0)                                  # the first load is refused, the second is let in
    proc, test, events, meta = run_shown(site, tmp_path, "block_cooldown_s: 2, block_retries: 2, stagger_s: 0, min_page_load_gap_s: 0", "--headed")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert test["status"] == "PASSED" and test["attempt"] == 2
    kinds = [e["type"] for e in events]
    (held,) = [e for e in events if e["type"] == "worker_waiting" and e["code"] == "site_block_hold"]
    (resumed,) = [e for e in events if e["type"] == "worker_resumed" and e["code"] == "site_block_hold"]
    assert "stays on the page it blocked" in held["message"] and held["seconds"] == 2.0
    assert resumed["waited_s"] >= 1.5                                          # it really stayed for the cool-down
    paused = kinds.index("run_paused")                                         # the cool-down started while the window was still showing the block...
    assert kinds.index("worker_waiting") < kinds.index("worker_resumed") and paused < kinds.index("worker_resumed")
    assert kinds.count("run_paused") == 1                                      # ...and was not started a second time afterwards
    assert meta["params"]["nice"] is False                                     # a window somebody watches is not run at low priority


@needs_a_display
def test_the_old_behaviour_comes_back_when_holding_on_a_block_is_switched_off(site, tmp_path):
    mock_server.FLAKY.update(block=1, seen=0)
    proc, test, events, _ = run_shown(site, tmp_path, "block_cooldown_s: 1, block_retries: 2, stagger_s: 0, min_page_load_gap_s: 0, headed_hold_on_block: false", "--headed")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert test["status"] == "PASSED" and test["attempt"] == 2
    assert not [e for e in events if e.get("code") == "site_block_hold"]


def test_a_headless_blocked_test_never_holds_a_window_and_keeps_low_priority(site, tmp_path):
    mock_server.FLAKY.update(block=1, seen=0)
    proc, test, events, meta = run_shown(site, tmp_path, "block_cooldown_s: 1, block_retries: 2, stagger_s: 0, min_page_load_gap_s: 0")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert test["status"] == "PASSED" and test["attempt"] == 2
    assert not [e for e in events if e.get("code") == "site_block_hold"]
    assert [e["type"] for e in events].count("run_paused") == 1
    assert meta["params"]["nice"] is True


# -- Watch live ------------------------------------------------------------------------------------------------------------------
def test_a_frame_name_is_safe_in_a_url_and_different_for_every_test_id():
    names = {live.frame_name(t) for t in ("Purchase#1", "Purchase#2", "Two agents · A#1", "Two agents · A#2", "a/b", "a_b")}
    assert len(names) == 6
    assert all(name.endswith(".jpg") and all(c.isalnum() or c in "_.-" for c in name) for name in names)


async def test_a_picture_of_the_page_is_written_only_while_somebody_watches_and_goes_when_the_test_ends(site, tmp_path):
    async with async_playwright() as pw:
        browser, session = await open_session(pw, site, "nav_button.html", headed=False)
        cancel = asyncio.Event()
        task = asyncio.ensure_future(live.stream(session, tmp_path, "Flow#1", 0.25, cancel))
        try:
            await asyncio.sleep(1.2)
            assert not live.frame_file(tmp_path, "Flow#1").exists()                         # nobody asked: nothing is taken
            marker = live.watch_marker(tmp_path, "Flow#1")
            marker.parent.mkdir(parents=True)
            marker.write_text("watch")
            deadline = time.monotonic() + 8
            while not live.frame_file(tmp_path, "Flow#1").exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            frame = live.frame_file(tmp_path, "Flow#1").read_bytes()
            assert frame[:2] == b"\xff\xd8" and len(frame) > 500                            # a real JPEG of the page
            old = time.time() - live.FRESH_S - 5
            os.utime(marker, (old, old))                                                    # the screen stopped asking
            assert not live.is_watched(tmp_path, "Flow#1")
            live.frame_file(tmp_path, "Flow#1").unlink()
            await asyncio.sleep(1.0)
            assert not live.frame_file(tmp_path, "Flow#1").exists()                         # ...and no more pictures are taken
            live.forget(tmp_path, "Flow#1")
            assert not marker.exists()
        finally:
            task.cancel()
            await session.close()
            await browser.close()


def test_watching_a_running_test_leaves_a_marker_and_says_where_the_picture_will_be(web):
    run_dir = plant_running_run(web, "planted-watch-1", going=("FlowA", "Two agents · A#1"), finished=("FlowB",))
    with web.client() as c:
        first = c.post("/api/runs/planted-watch-1/tests/FlowA/watch").json()
        again = c.post("/api/runs/planted-watch-1/tests/Two%20agents%20%C2%B7%20A%231/watch").json()
        assert c.post("/api/runs/planted-watch-1/tests/FlowB/watch").json()["kind"] == "test_not_running"     # already finished
        assert c.post("/api/runs/no-such-run/tests/FlowA/watch").status_code == 404
    assert first == {"frame": f"live/{live.frame_name('FlowA')}"} and again["frame"].endswith(live.frame_name("Two agents · A#1"))
    assert live.is_watched(run_dir, "FlowA") and live.is_watched(run_dir, "Two agents · A#1") and not live.is_watched(run_dir, "FlowB")
    assert not (run_dir / "cancel").exists()


def test_watching_needs_the_page_and_a_run_that_is_still_going(web):
    import httpx
    plant_running_run(web, "planted-watch-2", going=("FlowA",))
    with httpx.Client(base_url=web.base) as bare:
        assert bare.post("/api/runs/planted-watch-2/tests/FlowA/watch").status_code == 403
    over = plant_running_run(web, "planted-watch-3", going=("FlowA",))
    (over / "run.json").write_text(json.dumps({"run_id": "planted-watch-3", "status": "PASSED"}))
    with web.client() as c:
        assert c.post("/api/runs/planted-watch-3/tests/FlowA/watch").json()["kind"] == "not_running"


async def test_the_watch_live_button_shows_the_picture_the_engine_writes_and_goes_back_when_pressed_again(web):
    run_dir = plant_running_run(web, "planted-watch-4", going=("FlowA", "FlowB"))
    async with open_ui(web, path="/#/run/planted-watch-4") as page:
        await page.wait_for_selector('[data-act="watch-test"]')
        assert await page.locator('[data-act="watch-test"]').count() == 2                  # one per running card, beside Cancel test
        await page.locator('[data-act="watch-test"][data-test="FlowA"]').click()
        for _ in range(100):
            if live.is_watched(run_dir, "FlowA"):
                break
            await page.wait_for_timeout(100)
        assert live.is_watched(run_dir, "FlowA") and not live.is_watched(run_dir, "FlowB")      # only the test that is looked at is asked for
        frame = live.frame_file(run_dir, "FlowA")
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9"))
        for _ in range(120):                                                                   # (the card waits 2.5 s before it trusts there is a picture)
            if await page.locator(f'img[src*="live/{live.frame_name("FlowA")}"]').count():
                break
            await page.wait_for_timeout(100)
        assert await page.locator(f'img[src*="live/{live.frame_name("FlowA")}"]').count() == 1
        assert "Stop watching" in await page.locator('[data-act="watch-test"][data-test="FlowA"]').inner_text()
        await page.locator('[data-act="watch-test"][data-test="FlowA"]').click()
        for _ in range(50):
            if not await page.locator(f'img[src*="live/"]').count():
                break
            await page.wait_for_timeout(100)
        assert await page.locator('img[src*="live/"]').count() == 0                            # back to the screenshot after the last step
        assert not page.errors, page.errors
