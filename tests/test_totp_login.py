"""Several tests logging in at the same time with ONE account and ONE authenticator secret, against a login page that - like Okta - accepts each
code once and checks it only when Verify is clicked."""
from __future__ import annotations

import asyncio
import base64
import json

import pytest
from playwright.async_api import async_playwright

from regrunner import totp
from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from tests.site import server as mock_server
from tests.test_page_ready import opened
from tests.workbook_factory import build_steps_workbook

pytestmark = pytest.mark.browser

SECRET = base64.b32encode(b"one-account-many-tests").decode().rstrip("=")


@pytest.fixture(autouse=True)
def okta():
    mock_server.OKTA.update(secret=SECRET, used=set(), seen=[])
    yield
    mock_server.OKTA.update(secret="", used=set(), seen=[])


def login(sheet) -> None:
    sheet.add("Open", "Open", Value="DT_URL")
    code = sheet.add("GET_GOOGLE_TOKEN", "Get Okta code", Value="DT_Key")
    sheet.add("Set", "Enter code", FindBy="xpath", FindBy_Value="//input[@id='code']", Index=0, Value=f"=S{code}")
    sheet.add("Click", "Verify", FindBy="xpath", FindBy_Value="//button[@id='verify']", Index=0)
    sheet.add("Output", "Signed in", FindBy="xpath", FindBy_Value="//p[@id='msg']", Index=0, Output_Property="innertext",
              Expected_Value="Welcome", Exact_Match="Y")
    sheet.add("Quit", "Quit")


async def test_five_tests_one_secret_all_log_in_with_visible_waits(site, make_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(totp, "STEP_S", 10)                                  # 10 s code windows (Okta's are 30 s): the same rules, a shorter test
    names = [f"Login{i}" for i in range(1, 6)]
    wb = tmp_path / "wb.xlsx"
    build_steps_workbook(wb, {n: login for n in names}, params={n: {"DT_URL": site + "okta.html", "DT_Key": SECRET} for n in names})
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    cfg = make_cfg(**{"runner.stagger_s": 0, "runner.min_page_load_gap_s": 0})
    result = await asyncio.wait_for(execute(RunOptions(workbook=wb, seed=1, tests=names, workers=5), cfg, bus), 240)
    assert {t.id: t.status for t in result.tests} == {n: "PASSED" for n in names}, [(t.id, [(s.name, s.error, s.actual) for s in t.steps if s.status != "PASSED"]) for t in result.tests]
    assert len(mock_server.OKTA["used"]) == 5 and len(mock_server.OKTA["seen"]) == 5         # five different codes, each accepted the first time
    waits = [e for e in events if e["type"] == "worker_waiting" and e["code"] == "login_code"]
    assert len(waits) >= 4 and all(e.get("seconds") for e in waits)                          # the ones that queued for a code said so, with a countdown
    for t in result.tests:
        verify = next(s for s in t.steps if s.name == "Verify")
        assert any("was submitted" in n and "before it expired" in n for n in verify.notes), verify.notes     # the code-to-Verify gap, measured
    text = json.dumps(events) + (result.tests[0].steps[0].actual or "")
    assert not any(code in text for code in mock_server.OKTA["used"]) and SECRET not in text               # never a code or the key in events
    stored = json.loads((tmp_path / ".auth" / "totp_last.json").read_text())
    assert len(stored["gaps"][totp.fingerprint(SECRET)]) == 5                                 # what the next run's safety margin is based on


async def test_the_margin_follows_the_measured_gap(tmp_path):
    store = tmp_path / "totp_last.json"
    assert totp.safe_margin(SECRET, store) == totp.UNMEASURED_MARGIN_S                       # nothing measured yet: the conservative margin
    totp.record_gap(totp.fingerprint(SECRET), 2.0, store)
    assert totp.safe_margin(SECRET, store) == totp.EXPIRY_MARGIN_S + 1.0                      # 2 s measured -> 5 s
    totp.record_gap(totp.fingerprint(SECRET), 14.0, store)                                   # a slow login: the next codes need more time left
    totp._gaps.clear()                                                                       # (a new run reads it back from the file)
    assert totp.safe_margin(SECRET, store) == 17.0
    totp.record_gap(totp.fingerprint(SECRET), 40.0, store)
    assert totp.safe_margin(SECRET, store) == 25.0                                           # never more than 25 s of 30


async def test_a_refused_login_is_explained_in_network_jsonl_without_the_code(site):
    """Okta's answers are not first-party calls; a 4xx from a sign-in service is kept, with its body, secrets and codes masked."""
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "okta.html")
        try:
            await session.page.fill("#code", "246810")
            await session.page.click("#verify")
            await session.page.wait_for_function("document.getElementById('msg').textContent !== ''")
            await asyncio.sleep(0.5)
            (entry,) = [n for n in session.network if n.get("auth")]
            assert entry["status"] == 403 and "Invalid Passcode" in entry["body"] and "246810" not in json.dumps(entry)
            assert '"passCode": "***"' in entry["body"]
        finally:
            await session.close()
            await browser.close()
