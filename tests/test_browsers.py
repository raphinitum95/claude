"""Choosing the browser (Chrome / Edge / Safari's engine / Chromium) and recording which one a run used."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from regrunner import browsers, publish
from regrunner.config import BrowserCfg, load_config
from regrunner.engine.runner import RunOptions, SelectionError, execute
from regrunner.events import EventBus
from regrunner.preflight import installed_map
from regrunner.reporting.html_report import build_report, render_html
from tests.workbook_factory import build_workbook


# ---- names ---------------------------------------------------------------------------------------------
def test_every_browser_resolves_by_id_and_by_the_usual_spellings():
    assert [b.id for b in browsers.ORDER] == ["chrome", "msedge", "safari", "chromium"]
    assert browsers.resolve("Chrome").id == "chrome" and browsers.resolve("google_chrome").id == "chrome"
    assert browsers.resolve("edge").id == "msedge" and browsers.resolve("Microsoft Edge").id == "msedge"
    assert browsers.resolve("webkit").id == "safari" and browsers.resolve(" SAFARI ").id == "safari"
    assert browsers.resolve("").id == browsers.resolve(None).id == "chromium"          # a config with no browser line has always meant this


def test_an_unknown_browser_names_the_choices():
    with pytest.raises(browsers.BrowserError, match="Unknown browser 'firefox'.*chrome, msedge, safari, chromium"):
        browsers.resolve("firefox")


def test_safari_is_labelled_as_the_engine_it_is():
    """Playwright cannot drive Safari.app: nothing a person reads may claim it does."""
    safari = browsers.SAFARI
    assert safari.engine == "webkit" and safari.approximate and safari.label == "Safari (WebKit)"
    assert "not Safari.app" in safari.what
    assert browsers.text_of(safari, "26.6") == "Safari (WebKit 26.6)"
    assert browsers.text_of(browsers.CHROME, "141.0.7390.55") == "Google Chrome 141.0.7390.55"
    assert browsers.text_of(browsers.EDGE, "") == "Microsoft Edge"


# ---- configuration -------------------------------------------------------------------------------------------
def test_name_wins_over_the_older_channel_line_and_the_default_is_chromium(monkeypatch):
    monkeypatch.setattr(browsers, "downloaded", lambda b: True)
    assert BrowserCfg().kind.id == "chromium"
    assert BrowserCfg(channel="msedge").kind.id == "msedge"
    assert BrowserCfg(name="safari", channel="chrome").kind.id == "safari"


def _here(monkeypatch, *, chromium=False, chrome=False, edge=False):
    """Pretend which of these are on the computer."""
    monkeypatch.setattr(browsers, "downloaded", lambda b: chromium and b.id == "chromium")
    monkeypatch.setattr(browsers, "installed_executable", lambda b: Path("/fake") if {"chrome": chrome, "msedge": edge}.get(b.id) else None)


def test_nothing_configured_means_the_downloaded_chromium_else_the_chrome_or_edge_that_is_installed(monkeypatch):
    _here(monkeypatch, chromium=True, chrome=True, edge=True)
    assert browsers.pick_default().id == "chromium"                                      # what it has always meant, even with Chrome around
    _here(monkeypatch, chromium=False, chrome=True, edge=True)
    assert browsers.pick_default().id == "chrome" and BrowserCfg().kind.id == "chrome" and BrowserCfg().auto
    _here(monkeypatch, chromium=False, chrome=False, edge=True)
    assert BrowserCfg().kind.id == "msedge"
    _here(monkeypatch)
    assert BrowserCfg().kind.id == "chromium"                                            # nothing here: the error then explains what to do


def test_a_browser_that_was_asked_for_never_falls_back(monkeypatch):
    _here(monkeypatch, chromium=False, chrome=True, edge=True)
    for cfg in (BrowserCfg(name="chromium"), BrowserCfg(channel="chromium")):
        assert cfg.kind.id == "chromium" and not cfg.auto                                # config.yaml said Chromium: it is Chromium or an error, not Chrome
    assert BrowserCfg(name="safari").kind.id == "safari" and BrowserCfg(name="msedge").kind.id == "msedge"


def test_a_download_is_recognised_from_the_files_playwright_leaves(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert not browsers.downloaded(browsers.CHROMIUM) and not browsers.downloaded(browsers.SAFARI)

    def install(part):
        folder = tmp_path / f"{part.replace('-', '_')}-{browsers._revision(part)}"
        folder.mkdir()
        (folder / "INSTALLATION_COMPLETE").write_text("")
    install("chromium")
    assert not browsers.downloaded(browsers.CHROMIUM)                                    # headless runs use the headless shell: half an install is not one
    install("chromium-headless-shell")
    assert browsers.downloaded(browsers.CHROMIUM) and not browsers.downloaded(browsers.SAFARI)
    install("webkit")
    assert browsers.downloaded(browsers.SAFARI)
    assert not browsers.downloaded(browsers.CHROME) and not browsers.downloaded(browsers.EDGE)     # installed apps, not downloads
    (tmp_path / f"webkit-{browsers._revision('webkit')}" / "INSTALLATION_COMPLETE").unlink()      # a download that never finished
    assert not browsers.downloaded(browsers.SAFARI)


def test_launch_options_follow_the_engine():
    assert BrowserCfg(name="safari").launch_kwargs(True) == {"headless": True}          # WebKit: no channel
    chromium = BrowserCfg(name="chrome", args=["--x"])
    assert chromium.launch_kwargs(True) == {"headless": True, "channel": "chrome"}       # switches only where asked for...
    assert chromium.launch_kwargs(False, args=True) == {"headless": False, "channel": "chrome", "args": ["--x"]}
    assert BrowserCfg(name="safari", args=["--x"]).launch_kwargs(True, args=True) == {"headless": True}     # ...and never handed to WebKit


def test_channel_chromium_still_means_the_full_chromium_and_only_for_chromium():
    assert BrowserCfg(channel="chromium").launch_kwargs(True) == {"headless": True, "channel": "chromium"}
    assert BrowserCfg(name="chromium", channel="chromium").launch_kwargs(True) == {"headless": True, "channel": "chromium"}
    assert BrowserCfg(name="chrome", channel="chromium").launch_kwargs(True) == {"headless": True, "channel": "chrome"}
    assert BrowserCfg(name="safari", channel="chromium").launch_kwargs(True) == {"headless": True}


def test_jobs_only_chromium_can_do_never_use_webkit():
    assert [b.id for b in BrowserCfg(name="safari").chromium_family()] == ["chrome", "msedge", "chromium"]      # sign-in window, PDF export
    assert [b.id for b in BrowserCfg(name="msedge").chromium_family()] == ["msedge"]


def test_config_yaml_accepts_a_browser_and_rejects_a_typo(tmp_path):
    (tmp_path / "config.yaml").write_text("browser: {name: safari}\n")
    assert load_config(tmp_path / "config.yaml", base_dir=tmp_path).browser.kind.id == "safari"
    (tmp_path / "bad.yaml").write_text("browser: {name: netscape}\n")
    with pytest.raises(ValueError, match="config.yaml, browser: Unknown browser 'netscape'"):
        load_config(tmp_path / "bad.yaml", base_dir=tmp_path)


# ---- what is installed ------------------------------------------------------------------------------------------
def test_installed_chrome_is_found_where_playwright_looks(tmp_path, monkeypatch):
    fake = tmp_path / "Google Chrome"
    monkeypatch.setattr(browsers, "executable_candidates", lambda b: [fake] if b.id == "chrome" else [])
    assert browsers.installed_executable(browsers.CHROME) is None
    fake.write_text("")
    assert browsers.installed_executable(browsers.CHROME) == fake
    assert browsers.installed_executable(browsers.SAFARI) is None                        # a build Playwright downloads has no fixed install spot


def test_windows_looks_where_playwright_looks_for_chrome_and_edge(monkeypatch):
    monkeypatch.setattr(browsers, "platform_key", lambda: "win32")
    for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE"):
        monkeypatch.delenv(var, raising=False)
    assert browsers.executable_candidates(browsers.EDGE) == []
    monkeypatch.setenv("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
    monkeypatch.setenv("HOMEDRIVE", "D:")                                          # no PROGRAMFILES variables at all: Playwright falls back to <drive>:\Program Files
    got = [str(p).replace("/", "\\") for p in browsers.executable_candidates(browsers.EDGE)]
    assert got[0].endswith("Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe")
    assert any(g.startswith("D:") and "Program Files" in g for g in got) and len(got) == 3
    assert any(str(p).replace("/", "\\").endswith("Google\\Chrome\\Application\\chrome.exe") for p in browsers.executable_candidates(browsers.CHROME))


def test_a_browser_that_is_missing_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(browsers, "executable_candidates", lambda b: [tmp_path / "nowhere"] if b.channel else [])
    edge = browsers.unavailable_message(browsers.EDGE, "Executable doesn't exist")
    assert "Microsoft Edge is not installed on this computer" in edge and "Install it, or choose another browser" in edge
    safari = browsers.unavailable_message(browsers.SAFARI, "BrowserType.launch: Executable doesn't exist at /x/webkit-1/pw_run.sh", ["Google Chrome", "Chromium"])
    assert safari.startswith("Safari (WebKit) is not downloaded on this computer yet") and "Available on this computer instead: Google Chrome, Chromium (choose one under Browser)." in safari
    assert safari.split("Run: ")[1].endswith("-m playwright install webkit")                                   # the command is the last thing, so a UI can show it as code
    crashed = browsers.unavailable_message(browsers.CHROMIUM, "Target page, context or browser has been closed")
    assert "did not start: Target page" in crashed and "-m playwright install chromium" in crashed
    assert browsers.BrowserUnavailable(browsers.SAFARI, "Target closed").reason == "Target closed"


# ---- the record -------------------------------------------------------------------------------------------------
def test_a_run_from_before_browsers_were_recorded_is_worked_out_from_its_saved_config():
    old = {"config": {"browser": {"channel": "chrome"}, "runner": {"headless": False}}}
    got = browsers.identity_of(old)
    assert got["id"] == "chrome" and got["recorded"] is False and got["headless"] is False and got["version"] == ""
    assert browsers.identity_of({})["id"] == "unknown"                   # no browser and no saved settings: nothing is guessed
    assert browsers.identity_of({"config": {"browser": {}}})["id"] == "chromium"      # saved settings that name none: the default they ran with
    recorded = {"browser": browsers.identity(browsers.SAFARI, version="26.6")}
    assert browsers.identity_of(recorded)["text"] == "Safari (WebKit 26.6)"


def test_a_run_with_only_api_tests_says_no_browser_was_used():
    b = browsers.no_browser()
    assert b["id"] == "none" and "API tests only" in b["text"] and browsers.identity_of({"browser": b}) == b


def test_the_report_and_the_shared_summary_name_the_browser(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    data = {"run_id": "r1", "workbook": "wb.xlsx", "environment": "UAT", "status": "PASSED", "summary": {"tests": 0}, "tests": [],
            "browser": browsers.identity(browsers.SAFARI, version="26.6", headless=True, user_agent="Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15")}
    page = render_html(data, run_dir)
    assert "Safari (WebKit 26.6)" in page and "headless" in page and "AppleWebKit/605.1.15" in page
    assert "not Safari.app" in page                                                     # the report never lets Safari's engine pass for Safari
    text = publish.summary_text(data)
    assert "Browser:      Safari (WebKit 26.6) (headless; not Safari itself" in text
    chrome = {**data, "browser": browsers.identity(browsers.CHROME, version="141.0.7390.55", headless=False)}
    assert "Google Chrome 141.0.7390.55" in render_html(chrome, run_dir) and "headed (windows were shown)" in render_html(chrome, run_dir)
    assert "Browser:      Google Chrome 141.0.7390.55 (headed)" in publish.summary_text(chrome)
    unrecorded = {k: v for k, v in data.items() if k != "browser"}
    assert "did not record which browser it used" in render_html(unrecorded, run_dir)
    assert "Browser:      not recorded" in publish.summary_text(unrecorded)
    from_config = {**unrecorded, "config": {"browser": {"channel": "chrome"}}}
    assert "did not record its browser" in render_html(from_config, run_dir) and "Google Chrome" in render_html(from_config, run_dir)


# ---- a run ---------------------------------------------------------------------------------------------------------
async def run(cfg, wb_path, **opts):
    bus = EventBus()
    events: list[dict] = []
    bus.subscribe(events.append)
    result = await execute(RunOptions(workbook=wb_path, **opts), cfg, bus)
    return result, events


@pytest.mark.browser
async def test_a_run_records_its_browser_everywhere_a_person_looks(site, make_cfg, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    cfg = make_cfg(**{"reports.html": True})
    result, events = await run(cfg, wb, tests=["Login flow"], seed=1)
    assert result.status == "PASSED"
    started = next(e for e in events if e["type"] == "run_started")
    b = started["browser"]
    assert b["id"] == "chromium" and b["engine"] == "chromium" and b["headless"] is True
    assert b["version"] and b["text"] == f"Chromium {b['version']}" and "Chrome/" in b["user_agent"]
    assert started["params"]["browser"] == "chromium"
    run_dir = tmp_path / "runs" / result.run_id
    assert json.loads((run_dir / "run.json").read_text())["browser"]["text"] == b["text"]
    assert json.loads((run_dir / "results.json").read_text())["browser"] == b
    assert b["text"] in (run_dir / "report.html").read_text(encoding="utf-8")


@pytest.mark.browser
async def test_the_browser_asked_for_on_the_command_line_beats_config_yaml(site, make_cfg, tmp_path, monkeypatch):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    seen = []
    real = browsers.probe

    async def spy(kind, **kw):
        seen.append(kind.id)
        return await real(browsers.CHROMIUM, **kw)                     # start the browser that is here; only the label is under test
    monkeypatch.setattr(browsers, "probe", spy)
    cfg = make_cfg()
    cfg.browser.name = "msedge"
    result, events = await run(cfg, wb, tests=["Login flow"], seed=1, browser="chrome")
    assert seen == ["chrome"] and result.browser["id"] == "chrome" and cfg.browser.kind.id == "chrome"
    assert result.config["browser"]["name"] == "chrome"                # the saved settings say so too


async def test_a_browser_that_cannot_start_stops_the_run_before_anything_is_created(site, make_cfg, tmp_path, monkeypatch):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)

    async def broken(kind, **kw):
        raise browsers.BrowserUnavailable(kind, "BrowserType.launch: Executable doesn't exist")
    monkeypatch.setattr(browsers, "probe", broken)
    with pytest.raises(SelectionError, match="Safari .WebKit. is not downloaded on this computer yet.*-m playwright install webkit"):
        await execute(RunOptions(workbook=wb, tests=["Login flow"], browser="safari"), make_cfg(), EventBus())
    assert not (tmp_path / "runs").exists() or not list((tmp_path / "runs").iterdir())          # no half-made run folder to puzzle over


async def test_an_unknown_browser_is_a_selection_error(site, make_cfg, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    with pytest.raises(SelectionError, match="Unknown browser 'firefox'"):
        await execute(RunOptions(workbook=wb, tests=["Login flow"], browser="firefox"), make_cfg(), EventBus())


def test_the_command_line_offers_the_browsers_and_refuses_a_typo(tmp_path):
    out = subprocess.run([sys.executable, "-m", "regrunner", "run", "--help"], capture_output=True, text=True, timeout=60)
    assert "--browser {chrome,msedge,safari,chromium}" in " ".join(out.stdout.split())
    bad = subprocess.run([sys.executable, "-m", "regrunner", "run", "x.xlsx", "--browser", "netscape"], capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2 and "invalid choice: 'netscape'" in bad.stderr


# ---- real WebKit (Safari's engine): runs only where Playwright's WebKit has been downloaded ----------------------
def _webkit_here() -> bool:
    return bool(asyncio.run(installed_map(deep=True)).get("safari"))


needs_webkit = pytest.mark.skipif(not _webkit_here(), reason="Playwright's WebKit is not downloaded here: python -m playwright install webkit")


@needs_webkit
@pytest.mark.browser
async def test_a_whole_run_works_in_webkit_and_says_so(site, make_cfg, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    cfg = make_cfg(**{"reports.html": True})
    result, events = await run(cfg, wb, tests=["Login flow"], seed=1, browser="safari")
    failed = [(s.row, s.name, s.error) for t in result.tests for s in t.steps if s.status != "PASSED"]
    assert result.status == "PASSED", failed
    b = next(e for e in events if e["type"] == "run_started")["browser"]
    assert b["id"] == "safari" and b["engine"] == "webkit" and b["approximate"] is True and b["label"] == "Safari (WebKit)"
    assert b["text"] == f"Safari (WebKit {b['version']})" and "AppleWebKit" in b["user_agent"] and "Chrome" not in b["user_agent"]
    page = (tmp_path / "runs" / result.run_id / "report.html").read_text(encoding="utf-8")
    assert b["text"] in page and "not Safari.app" in page


@needs_webkit
@pytest.mark.browser
async def test_the_pdf_of_a_webkit_run_is_still_printed_by_a_chromium_browser(site, make_cfg, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    result, _ = await run(make_cfg(**{"reports.html": True}), wb, tests=["Login flow"], seed=1, browser="safari", pdf=False)
    run_dir = tmp_path / "runs" / result.run_id
    await build_report(run_dir, pdf=True)                                # WebKit cannot page.pdf(); this must not try
    assert (run_dir / "report.pdf").stat().st_size > 1000
