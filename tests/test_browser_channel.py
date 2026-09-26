"""Running on the browser already installed on the machine (Chrome / Edge) instead of the downloaded Chromium: launch options and the preflight check."""
from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from regrunner import browsers, preflight
from regrunner.config import BrowserCfg, Config
from tests.workbook_factory import build_workbook


def test_launch_options_carry_the_channel_only_when_one_is_set():
    assert BrowserCfg().launch_kwargs(True) == {"headless": True}
    assert BrowserCfg(channel="chrome").launch_kwargs(False) == {"headless": False, "channel": "chrome"}
    assert BrowserCfg(name="msedge").launch_kwargs(True) == {"headless": True, "channel": "msedge"}


def test_the_install_hint_is_a_command_that_works_without_activating_the_venv():
    cmd = preflight.install_command()
    assert cmd.endswith("-m playwright install chromium") and sys.executable in cmd.replace('"', "").replace("'", "")
    assert preflight.install_command("webkit").endswith("-m playwright install webkit")


def _probe(monkeypatch, working: set):
    """Pretend only the browsers in ``working`` (ids) can start and are installed."""
    async def fake_probe(kind, *, headless=True, timeout_s=60.0, cached=False):
        if kind.id not in working:
            raise browsers.BrowserUnavailable(kind, f"BrowserType.launch: Executable doesn't exist ({kind.id})")
        return {"version": "9.9.9", "user_agent": "UA"}

    async def fake_installed(deep=False):
        return {b.id: b.id in working for b in browsers.ORDER}
    monkeypatch.setattr(browsers, "probe", fake_probe)
    monkeypatch.setattr(preflight, "installed_map", fake_installed)
    preflight._BROWSER_CACHE.clear()


def test_missing_chromium_but_working_chrome_says_so(monkeypatch):
    _probe(monkeypatch, {"chrome"})
    check = asyncio.run(preflight.browser_check(deep=True))
    assert check.status == "err"                                   # runs would fail as configured
    assert "Chromium" in check.detail and "-m playwright install chromium" in check.detail
    assert "Available on this computer instead: Google Chrome" in check.detail


def test_edge_is_offered_when_chrome_is_not_there(monkeypatch):
    _probe(monkeypatch, {"msedge"})
    assert "Available on this computer instead: Microsoft Edge" in asyncio.run(preflight.browser_check(deep=True)).detail


def test_nothing_installed_falls_back_to_the_download_instruction(monkeypatch):
    _probe(monkeypatch, set())
    detail = asyncio.run(preflight.browser_check(deep=True)).detail
    assert "not downloaded" in detail and "-m playwright install chromium" in detail and "Available on this computer" not in detail and detail.split("Run: ")[1].endswith("install chromium")


def test_a_chosen_browser_that_works_is_ok_and_one_that_is_missing_says_so(monkeypatch):
    _probe(monkeypatch, {"chrome"})
    ok = asyncio.run(preflight.browser_check(deep=True, browser="chrome"))
    assert ok.status == "ok" and ok.label == "Google Chrome" and "Google Chrome 9.9.9 launches headless" in ok.detail
    bad = asyncio.run(preflight.browser_check(deep=True, browser="msedge"))
    assert bad.status == "err" and "Microsoft Edge is not installed on this computer" in bad.detail


def test_the_cache_is_per_browser(monkeypatch):
    _probe(monkeypatch, {"chromium"})
    assert asyncio.run(preflight.browser_check(deep=True)).status == "ok"
    assert asyncio.run(preflight.browser_check(browser="chrome")).status == "err"     # not served from the chromium entry


def test_preflight_uses_the_configured_browser_unless_the_form_picked_one(monkeypatch, tmp_path):
    _probe(monkeypatch, {"chrome", "safari"})
    cfg = Config(base_dir=tmp_path)
    cfg.browser.channel = "chrome"                                 # the older spelling still selects it
    pre = asyncio.run(preflight.run_preflight(cfg, deep=True))
    assert pre["browser"]["status"] == "ok" and pre["browser"]["label"] == "Google Chrome"
    picked = asyncio.run(preflight.run_preflight(cfg, deep=True, browser="safari"))
    assert picked["browser"]["label"] == "Safari (WebKit)" and "Safari (WebKit 9.9.9)" in picked["browser"]["detail"]
    by_id = {o["id"]: o for o in picked["browsers"]}
    assert by_id["safari"]["selected"] and by_id["chrome"]["configured"] and not by_id["chrome"]["selected"]
    assert by_id["msedge"]["installed"] is False and "not installed" in by_id["msedge"]["detail"]
    assert by_id["chromium"]["installed"] is False and "-m playwright install chromium" in by_id["chromium"]["detail"]


def _chrome_installed() -> bool:
    return browsers.installed_executable(browsers.CHROME) is not None


@pytest.mark.browser
def test_a_whole_run_works_on_the_installed_chrome(site, tmp_path):
    if not _chrome_installed():
        pytest.skip("Google Chrome is not installed here")
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("timeouts: {element_s: 6, optional_s: 1.5}\noutput: {match_timeout_s: 3}\n"
                   "captcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\nbrowser: {channel: chrome}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain", "--seed", "1"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASSED: 1/1 tests passed" in proc.stdout
    assert "browser Google Chrome " in proc.stdout and ", headless" in proc.stdout        # the terminal says which browser ran
