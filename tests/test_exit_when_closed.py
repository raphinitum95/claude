"""`serve --exit-when-closed`: the launchers stop QA Regression (and close their terminal window) once the UI window is closed."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from regrunner.web.presence import GOODBYE_GRACE_S, SILENT_GONE_S, UiPresence

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-Requested-With": "regrunner"}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_nothing_counts_as_closed_before_the_first_window_has_said_hello():
    assert UiPresence(FakeClock()).all_closed() is False


def test_a_goodbye_counts_as_closed_only_after_the_reload_grace():
    clock = FakeClock()
    ui = UiPresence(clock)
    ui.hello("a")
    ui.goodbye("a")
    assert ui.all_closed() is False
    clock.now += GOODBYE_GRACE_S
    assert ui.all_closed() is True


def test_a_reload_says_goodbye_then_hello_and_is_never_taken_for_a_closed_window():
    clock = FakeClock()
    ui = UiPresence(clock)
    ui.hello("old")
    ui.goodbye("old")
    clock.now += 1
    ui.hello("new")
    clock.now += GOODBYE_GRACE_S * 10
    assert ui.all_closed() is False


def test_closing_one_of_two_windows_keeps_it_running():
    clock = FakeClock()
    ui = UiPresence(clock)
    ui.hello("a")
    ui.hello("b")
    ui.goodbye("a")
    clock.now += GOODBYE_GRACE_S * 2
    assert ui.all_closed() is False


def test_a_window_that_went_silent_without_goodbye_counts_as_closed_only_after_a_long_silence():
    clock = FakeClock()
    ui = UiPresence(clock)
    ui.hello("a")
    clock.now += 60                                  # a minimised window's heartbeat can be this slow
    assert ui.all_closed() is False
    clock.now += SILENT_GONE_S
    assert ui.all_closed() is True


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(tmp_path: Path, *flags: str) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "regrunner", "serve", "--port", str(port), *flags], cwd=tmp_path,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(url + "/api/config", timeout=1)
            return proc, url
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise AssertionError(proc.stdout.read())


def test_the_server_stops_by_itself_a_few_seconds_after_the_last_window_says_goodbye(tmp_path):
    proc, url = _serve(tmp_path, "--exit-when-closed")
    try:
        httpx.post(url + "/api/ui/hello", json={"page": "p1"}, headers=HEADERS).raise_for_status()
        httpx.post(url + "/api/ui/goodbye", json={"page": "p1"}, headers=HEADERS).raise_for_status()
        assert proc.wait(timeout=GOODBYE_GRACE_S + 10) == 0
        assert "window was closed: stopping" in proc.stdout.read()
    finally:
        proc.kill()


def test_without_the_flag_closing_the_window_leaves_the_server_running(tmp_path):
    proc, url = _serve(tmp_path)
    try:
        httpx.post(url + "/api/ui/hello", json={"page": "p1"}, headers=HEADERS).raise_for_status()
        httpx.post(url + "/api/ui/goodbye", json={"page": "p1"}, headers=HEADERS).raise_for_status()
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=GOODBYE_GRACE_S + 3)
    finally:
        proc.kill()


def test_a_window_closed_while_a_run_is_going_waits_for_the_run(monkeypatch):
    """The server's busy check (runs, workers, sign-in window) keeps it up; checked through the app with a fake run."""
    from fastapi.testclient import TestClient

    from regrunner.config import Config
    from regrunner.web import app as app_mod

    clock = FakeClock()
    monkeypatch.setattr(app_mod, "UiPresence", lambda: UiPresence(clock))
    monkeypatch.setattr(app_mod.RunManager, "active_runs", lambda self: ["run-1"])
    stopped = []
    app = app_mod.create_app(Config(), on_all_windows_closed=lambda: stopped.append(True))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post("/api/ui/hello", json={"page": "p"}, headers={**HEADERS, "Origin": "http://127.0.0.1"})
        client.post("/api/ui/goodbye", json={"page": "p"}, headers={**HEADERS, "Origin": "http://127.0.0.1"})
        clock.now += GOODBYE_GRACE_S * 3
        time.sleep(2.5)                              # the watcher looks once a second
        assert stopped == []
        monkeypatch.setattr(app_mod.RunManager, "active_runs", lambda self: [])
        for _ in range(50):
            time.sleep(0.2)
            if stopped:
                break
        assert stopped == [True]


@pytest.mark.browser
def test_closing_the_real_page_in_a_browser_stops_the_server(tmp_path):
    from playwright.sync_api import sync_playwright

    proc, url = _serve(tmp_path, "--exit-when-closed")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(url)
            page.wait_for_timeout(1500)              # the page says hello as it boots
            page.reload()                            # a reload is not a closed window
            page.wait_for_timeout(GOODBYE_GRACE_S * 1000 + 2000)
            assert proc.poll() is None
            page.close(run_before_unload=True)
            assert proc.wait(timeout=GOODBYE_GRACE_S + 10) == 0
            browser.close()
    finally:
        proc.kill()
