"""Choosing the browser on the New run screen, and seeing which one a run used - while it runs and in its results."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from regrunner import browsers, preflight
from regrunner.runmeta import update_meta
from tests.test_browsers import needs_webkit
from tests.test_web_api import make_interrupted_copy
from tests.test_web_ui import command, command_has, js_until, open_ui
from tests.web_fixtures import bad_run, web  # noqa: F401  (fixtures)

pytestmark = pytest.mark.browser


@pytest.fixture
def machine(monkeypatch):
    """Pretend which browsers this computer has: Chromium, Chrome (but broken) and Safari's WebKit are here, Edge is not.
    The web fixture's server runs in this process, so patching the module changes what the UI is told."""
    state = {"here": {"chrome": True, "msedge": False, "safari": True, "chromium": True}, "broken": set()}

    async def fake_installed(deep=False):
        return dict(state["here"])

    async def fake_probe(kind, *, headless=True, timeout_s=60.0, cached=False):
        if not state["here"][kind.id] or kind.id in state["broken"]:
            raise browsers.BrowserUnavailable(kind, "BrowserType.launch: Executable doesn't exist" if not state["here"][kind.id] else "the process crashed")
        return {"version": "9.9.9", "user_agent": "UA"}
    monkeypatch.setattr(preflight, "installed_map", fake_installed)
    monkeypatch.setattr(browsers, "probe", fake_probe)
    monkeypatch.setattr(browsers, "downloaded", lambda b: bool(b.download and state["here"][b.id]))          # what is "here" also decides the default
    monkeypatch.setattr(browsers, "installed_executable", lambda b: Path("/fake") if b.channel and state["here"][b.id] else None)
    preflight._BROWSER_CACHE.clear()
    yield state
    preflight._BROWSER_CACHE.clear()


# ---- the API ------------------------------------------------------------------------------------------------------
def test_the_ui_is_told_which_browsers_exist_and_which_one_config_yaml_selects(web, machine):
    with web.client() as c:
        cfg = c.get("/api/config").json()
        pre = c.get("/api/preflight").json()
    assert cfg["browser"] == "chromium" and [b["id"] for b in cfg["browsers"]] == ["chrome", "msedge", "safari", "chromium"]
    assert next(b for b in cfg["browsers"] if b["id"] == "safari")["approximate"] is True
    assert pre["browser"]["status"] == "ok" and pre["browser"]["label"] == "Chromium"
    have = {b["id"]: b for b in pre["browsers"]}
    assert have["msedge"]["installed"] is False and "not installed" in have["msedge"]["detail"]
    assert have["safari"]["installed"] is True and have["chromium"]["selected"] is True


def test_the_preflight_can_be_asked_about_the_browser_picked_on_the_form(web, machine):
    machine["here"]["safari"] = False
    with web.client() as c:
        safari = c.get("/api/preflight", params={"browser": "safari"}).json()
        edge = c.get("/api/preflight", params={"browser": "msedge"}).json()
        bogus = c.get("/api/preflight", params={"browser": "netscape"})
    assert safari["browser"]["status"] == "err" and "Safari (WebKit) is not downloaded on this computer yet" in safari["browser"]["detail"]
    assert "-m playwright install webkit" in safari["browser"]["detail"] and "Available on this computer instead: Google Chrome, Chromium" in safari["browser"]["detail"]
    assert next(b for b in safari["browsers"] if b["id"] == "safari")["selected"] is True
    assert edge["browser"]["status"] == "err" and "Microsoft Edge is not installed" in edge["browser"]["detail"]
    assert bogus.status_code == 422 and "Unknown browser 'netscape'" in bogus.json()["error"]
    machine["here"]["safari"] = True
    with web.client() as c:
        ok = c.get("/api/preflight", params={"browser": "safari", "deep": "true"}).json()["browser"]
    assert ok["status"] == "ok" and ok["data"]["text"] == "Safari (WebKit 9.9.9)"


def test_the_command_shows_the_browser_only_when_it_differs_from_config_yaml(web, machine):
    with web.client() as c:
        def preview(**extra):
            return c.post("/api/runs/command", json={"workbook": "mock.xlsx", "all": True, **extra})
        assert "--browser" not in preview().json()["text"]
        assert "--browser" not in preview(browser="chromium").json()["text"]                  # the configured one: nothing to say
        assert preview(browser="safari").json()["text"].endswith("--browser safari")
        assert "--browser msedge" in preview(browser="Edge").json()["text"]                     # spelled the way a person would
        bad = preview(browser="netscape")
        assert bad.status_code == 422 and bad.json()["kind"] == "browser"
        assert c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "browser": "netscape"}).status_code == 422


# ---- the New run screen ------------------------------------------------------------------------------------------
async def test_the_browser_choice_is_on_the_run_settings_and_greys_out_what_is_not_here(web, machine):
    async with open_ui(web) as page:
        await js_until(page, "document.querySelectorAll('[data-browser]').length >= 4 && document.querySelector('#browser-note').innerText.includes('starts fine')")
        buttons = page.locator(".seg button[data-browser]")
        assert await buttons.all_inner_texts() == ["Chrome", "Edge", "Safari", "Chromium"]
        assert await page.locator('button[data-browser="chromium"]').get_attribute("aria-pressed") == "true"      # config.yaml's choice is the starting point
        edge = page.locator('button[data-browser="msedge"]')
        assert await edge.is_disabled() and "not installed" in await edge.get_attribute("title")
        assert await page.locator('button[data-browser="safari"]').is_enabled()
        text = await page.locator("body").inner_text()
        assert "Microsoft Edge is not installed on this computer" in text                                     # not only in a tooltip
        assert "--browser" in text and page.errors == []


async def test_picking_safari_says_it_is_webkit_updates_the_command_and_checks_that_browser(web, machine):
    async with open_ui(web) as page:
        await js_until(page, "document.querySelector('#browser-note') && document.querySelector('#browser-note').innerText.includes('starts fine')")
        assert "--browser" not in await command(page)
        await page.locator('button[data-browser="safari"]').click()
        await command_has(page, "--browser safari")
        await js_until(page, "document.querySelector('#browser-note').innerText.includes('Safari (WebKit 9.9.9) starts fine')")
        body = await page.locator("body").inner_text()
        assert "Safari here means WebKit" in body and "not Safari.app" in body                                 # never passes the engine off as the app
        assert "Safari (WebKit 9.9.9)" in await page.locator("#launch-browser").inner_text()
        assert await page.locator('button[data-act="launch"]').is_enabled()
        assert await page.locator('button[data-browser="safari"]').get_attribute("aria-pressed") == "true"
        await page.locator('button[data-browser="chromium"]').click()                                          # back to the configured one
        await js_until(page, "!document.body.innerText.includes('Safari here means WebKit')")
        await js_until(page, "!document.querySelector('[aria-label=\"Command line for this run\"]').innerText.includes('--browser')")     # the preview follows a moment later
        assert page.errors == []


async def test_a_browser_that_will_not_start_blocks_the_run_and_says_why(web, machine):
    machine["broken"].add("chrome")
    async with open_ui(web) as page:
        await js_until(page, "document.querySelector('#browser-note') && document.querySelector('#browser-note').innerText.includes('starts fine')")
        await page.locator('button[data-browser="chrome"]').click()
        await js_until(page, "(function () { const t = document.querySelector('#browser-note').innerText; return t.includes('Google Chrome') && !t.includes('Checking'); })()")
        note = await page.locator("#browser-note").inner_text()
        assert "did not start" in note or "not installed" in note
        launch = page.locator('button[data-act="launch"]')
        assert await launch.is_disabled()                                                                     # nothing to press until it is fixed
        await page.locator('button[data-browser="chromium"]').click()
        await js_until(page, "document.querySelector('#browser-note').innerText.includes('starts fine')")
        assert await launch.is_enabled()


async def test_a_browser_that_is_not_downloaded_shows_the_command_that_fixes_it(web, machine):
    machine["here"]["safari"] = False
    async with open_ui(web) as page:
        await js_until(page, "document.querySelector('[data-key=\"missing-safari\"]')")
        line = await page.locator('[data-key="missing-safari"]').inner_text()
        assert "Safari:" in line and "Not downloaded yet" in line and "-m playwright install webkit" in line
        assert await page.locator('button[data-browser="safari"]').is_disabled()


async def test_the_form_starts_from_the_browser_config_yaml_selects_even_when_chrome_is_picked_last_time(web, machine):
    async with open_ui(web) as page:
        await js_until(page, "document.querySelector('#browser-note') && document.querySelector('#browser-note').innerText.includes('starts fine')")
        await page.locator('button[data-browser="safari"]').click()
        await command_has(page, "--browser safari")
        await page.reload()
        await js_until(page, "document.querySelector('#browser-note') && document.querySelector('#browser-note').innerText.includes('starts fine')")
        assert await page.locator('button[data-browser="chromium"]').get_attribute("aria-pressed") == "true"   # a run is never launched with a stale choice


async def test_a_computer_that_cannot_download_chromium_starts_on_the_installed_chrome_and_does_not_offer_chromium(web, machine):
    machine["here"]["chromium"] = False                                                   # the download is blocked; Chrome is installed
    with web.client() as c:
        assert c.get("/api/config").json()["browser"] == "chrome"                         # nothing configured: whatever is here, no config.yaml edit needed
        pre = c.get("/api/preflight").json()
    assert pre["browser"]["status"] == "ok" and pre["browser"]["label"] == "Google Chrome"
    info = next(c for c in pre["checks"] if c["id"] == "browsers")["detail"]
    assert "config.yaml names no browser and Chromium is not downloaded here, so the installed Google Chrome is used" in info
    async with open_ui(web) as page:
        await js_until(page, "document.querySelector('#browser-note') && document.querySelector('#browser-note').innerText.includes('starts fine')")
        assert await page.locator(".seg button[data-browser]").all_inner_texts() == ["Chrome", "Edge", "Safari"]      # no Chromium button
        assert await page.locator('button[data-browser="chrome"]').get_attribute("aria-pressed") == "true"
        body = await page.locator("body").inner_text()
        assert "playwright install chromium" not in body and "Chromium" not in await page.locator('[aria-labelledby="lbl-browser"]').inner_text()
        assert "--browser" not in await command(page)                                     # Chrome is the default here: nothing to add
        assert await page.locator('button[data-act="launch"]').is_enabled() and page.errors == []


async def test_with_no_browser_at_all_the_form_still_says_what_is_wrong(web, machine):
    machine["here"].update(chromium=False, chrome=False)                                  # only Safari's WebKit is here
    async with open_ui(web) as page:
        await js_until(page, "document.querySelector('#browser-note') && !document.querySelector('#browser-note').innerText.includes('Checking')")
        assert await page.locator(".seg button[data-browser]").all_inner_texts() == ["Chrome", "Edge", "Safari", "Chromium"]     # the default stays visible, so the error has a place
        assert await page.locator('button[data-browser="chromium"]').get_attribute("aria-pressed") == "true"
        note = await page.locator("#browser-note").inner_text()
        assert "not downloaded" in note and "Available on this computer instead: Safari (WebKit)" in note
        assert await page.locator('button[data-act="launch"]').is_disabled()


# ---- which browser a run used -------------------------------------------------------------------------------------
def fabricate_live_run(web, run_id: str, identity: dict) -> None:
    run_dir = web.root / "runs" / run_id
    run_dir.mkdir(parents=True)
    now = datetime.now().astimezone().isoformat(timespec="milliseconds")
    base = {"ts": now, "run_id": run_id}
    events = [
        {**base, "type": "run_started", "workbook": "wb.xlsx", "environment": "UAT", "workers": 1, "headless": True, "warnings": [], "browser": identity,
         "params": {"browser": identity["id"], "headless": True}, "tests": [{"id": "FlowA", "title": "FlowA", "description": "", "scenario": "", "total_steps": 20}]},
        {**base, "type": "test_started", "test": "FlowA", "title": "FlowA", "total_steps": 20, "worker": 1, "attempt": 1},
    ]
    (run_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    update_meta(run_dir, run_id=run_id, status="RUNNING", environment="UAT", started_at=now, workbook="wb.xlsx", tests=1, test_ids=["FlowA"], browser=identity)


async def test_a_run_in_progress_says_which_browser_it_is_using(web):
    fabricate_live_run(web, "20260924-990001-UAT", browsers.identity(browsers.SAFARI, version="26.6", headless=True, user_agent="AppleWebKit"))
    async with open_ui(web, path="/#/run/20260924-990001-UAT") as page:
        await js_until(page, "document.querySelector('[data-browser=\"safari\"]')")
        chip = page.locator('.chip[data-browser="safari"]')
        assert " ".join((await chip.inner_text()).split()) == "Safari (WebKit 26.6)"
        assert "not Safari.app" in await chip.get_attribute("title")
        await js_until(page, "document.body.innerText.includes('Safari')")                                     # and the run list beside it
        assert "· Safari" in await page.locator('.side-run[data-key="20260924-990001-UAT"]').inner_text()
        assert page.errors == []


async def test_a_finished_run_shows_its_browser_in_the_header_the_parameters_and_the_run_list(web, bad_run):
    async with open_ui(web, path=f"/#/run/{bad_run}") as page:
        await js_until(page, "document.querySelector('#run-browser')")
        chip = " ".join((await page.locator('.chip[data-browser="chromium"]').first.inner_text()).split())
        assert re.fullmatch(r"Chromium \d+\.\d+\.\d+\.\d+", chip), chip
        assert re.fullmatch(r"Chromium \d+\.\d+\.\d+\.\d+, headless", (await page.locator("#run-browser").inner_text()).strip())
        assert "· Chromium" in await page.locator(f'.side-run[data-key="{bad_run}"]').inner_text()
        assert page.errors == []
    with web.client() as c:
        detail = c.get(f"/api/runs/{bad_run}").json()
    assert detail["meta"]["browser"]["id"] == "chromium" and detail["results"]["browser"]["text"] == detail["meta"]["browser"]["text"]
    report = (web.run_dir(bad_run) / "report.html").read_text(encoding="utf-8")
    assert detail["meta"]["browser"]["text"] in report


async def test_a_run_from_before_browsers_were_recorded_says_so_instead_of_guessing_a_version(web, bad_run):
    old = "20260101-000001-UAT"
    shutil.copytree(web.run_dir(bad_run), web.run_dir(old))
    for name in ("run.json", "results.json"):
        path = web.run_dir(old) / name
        data = json.loads(path.read_text())
        data.pop("browser", None)
        data.get("params", {}).pop("browser", None)
        data["run_id"] = old
        path.write_text(json.dumps(data))
    async with open_ui(web, path=f"/#/run/{old}") as page:
        await js_until(page, "document.querySelector('#run-browser')")
        assert " ".join((await page.locator('.chip[data-browser]').first.inner_text()).split()) == "Chromium (version not recorded)"
        assert "did not record its browser" in await page.locator("body").inner_text()
        assert page.errors == []


def test_a_run_rebuilt_from_its_event_log_keeps_its_browser(web, bad_run):
    run_id = make_interrupted_copy(web, bad_run, "20260101-000002-UAT")
    with web.client() as c:
        assert c.post(f"/api/runs/{run_id}/report", json={"from_events": True}).status_code == 200
        results = c.get(f"/api/runs/{run_id}").json()["results"]
    assert results["partial"] is True and results["browser"]["id"] == "chromium" and results["browser"]["version"]


@needs_webkit
async def test_a_run_started_in_safari_from_the_ui_runs_in_webkit_and_the_results_say_so(web):
    with web.client() as c:
        started = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"], "browser": "safari"})
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        assert started.json()["command"].endswith("--browser safari")                                       # the command shown is the command run
    detail = web.wait_finished(run_id)
    failed = [(s["row"], s["name"], s["error"]) for t in detail["results"]["tests"] for s in t["steps"] if s["status"] != "PASSED"]
    assert detail["meta"]["status"] == "PASSED", failed
    b = detail["results"]["browser"]
    assert b["id"] == "safari" and b["engine"] == "webkit" and b["text"].startswith("Safari (WebKit ") and "Version/" in b["user_agent"]
    assert detail["meta"]["params"]["browser"] == "safari" and detail["meta"]["browser"] == b
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await js_until(page, "document.querySelector('#run-browser')")
        chip = " ".join((await page.locator('.chip[data-browser="safari"]').first.inner_text()).split())
        assert chip == b["text"] and "not Safari.app" in await page.locator("body").inner_text()
        assert " ".join((await page.locator("#run-browser").inner_text()).split()) == f"{b['text']}, headless"
        assert "· Safari" in await page.locator(f'.side-run[data-key="{run_id}"]').inner_text()
        assert page.errors == []
    assert b["text"] in (web.run_dir(run_id) / "report.html").read_text(encoding="utf-8")                  # and so does the report
