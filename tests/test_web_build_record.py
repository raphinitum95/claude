"""Recording and Check / Save this through the server and the Build tab (P09): ``/api/build/session/{name}/record|check|save|prompt`` and the
editor's Rec / Check / Save / Wait until buttons and check card.  Picks go through "which one?" (the build window runs in the server's own
loop); recording a person's actions in the window is tests/test_build_recording.py."""
from __future__ import annotations

import pytest

from tests.test_build_recording import record_book
from tests.test_web_build import js_until, open_ui
from tests.test_web_build_session import wait_state
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


@pytest.fixture
def rec(web, request):
    name = f"rec_{request.node.name}"[:60] + ".xlsx"
    record_book(web.root / "workbooks" / name, web.site)
    return name


async def opened(c, name: str) -> dict:
    r = await c.post(f"/api/build/session/{name}/start", json={"test": "Rec", "headless": True})
    assert r.status_code == 200, r.text
    return await wait_state(c, name, lambda s: s["status"] == "ready" and s.get("replay") and not s["replay"]["running"])


async def test_the_record_check_save_and_prompt_routes(web, rec):
    async with web.aclient() as c:
        r = await c.post(f"/api/build/session/{rec}/record", json={"on": True})
        assert r.status_code == 409 and r.json()["kind"] == "closed"
        await opened(c, rec)
        r = await c.post(f"/api/build/session/{rec}/record", json={"on": True, "after": 99})
        assert r.status_code == 400 and r.json()["kind"] == "step"
        state = (await c.post(f"/api/build/session/{rec}/record", json={"on": True, "after": 2})).json()
        assert state["record"]["on"] and state["record"]["cursor"]["n"] == 1
        assert not (await c.post(f"/api/build/session/{rec}/record", json={"on": False})).json()["record"]["on"]
        await c.post(f"/api/build/session/{rec}/pick", json={"mode": "check", "row": 2})
        await c.post(f"/api/build/session/{rec}/which", json={"text": "Continue", "kind": "button"})
        pick = (await c.post(f"/api/build/session/{rec}/choose", json={"i": 0})).json()["pick"]
        form = pick["card"]["form"]
        assert form["purpose"] == "check" and form["n"] == 2 and {k["id"]: k["enabled"] for k in form["kinds"]}["enabled"] is True
        r = await c.post(f"/api/build/session/{rec}/check", json={"kind": "gt", "expected": "lots"})
        assert r.status_code == 400
        r = await c.post(f"/api/build/session/{rec}/check", json={"kind": "enabled", "expected": "Y"})
        assert r.status_code == 200, r.text
        steps = next(t for t in r.json()["model"]["tests"] if t["id"] == "Rec")["steps"]
        assert [s["method"] for s in steps] == ["OPEN", "CHECK_ENABLED"] and steps[1]["locator"]["value"] == "continue"
        await c.post(f"/api/build/session/{rec}/pick", json={"mode": "save"})
        await c.post(f"/api/build/session/{rec}/which", json={"text": "$1,234.50"})
        pick = (await c.post(f"/api/build/session/{rec}/choose", json={"i": 0})).json()["pick"]
        assert pick["card"]["form"]["token"] == "PRICE"
        r = await c.post(f"/api/build/session/{rec}/save", json={"token": "TOTAL"})
        steps = next(t for t in r.json()["model"]["tests"] if t["id"] == "Rec")["steps"]
        assert [s["method"] for s in steps] == ["OPEN", "CHECK_ENABLED", "OUTPUT"] and steps[2]["saveAs"] == "TOTAL"
        r = await c.post(f"/api/build/session/{rec}/prompt", json={"id": "nope", "choice": "keep"})
        assert r.status_code == 409 and r.json()["kind"] == "prompt"
        await c.post(f"/api/build/session/{rec}/close")


async def test_the_editor_has_rec_check_save_and_wait_and_adds_a_check_from_its_card(web, rec):
    pw, browser, page = await open_ui(web, f"/#/build/{rec}/test/Rec")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length === 1")
        async with web.aclient() as c:
            await opened(c, rec)
        await js_until(page, "!!document.querySelector('[data-act=\"build-rec-toggle\"]')")
        assert [await b.inner_text() for b in await page.locator('[data-act="build-rec-mode"]').all()] == ["Check", "Save", "Wait until"]
        await page.locator('.scard [data-act="build-pick-step"]').first.click()
        await js_until(page, "document.querySelector('aside:not(.b-rail)').textContent.includes('Step 1')")
        await page.locator('[data-act="build-rec-toggle"]').first.click()
        await js_until(page, "document.querySelector('[data-act=\"build-rec-toggle\"]').textContent.includes('Recording')")
        assert "Recording after step 1" in await page.locator("aside:not(.b-rail)").inner_text()
        await page.locator('[data-act="build-rec-toggle"]').first.click()
        await js_until(page, "!document.querySelector('.sess-bar [data-act=\"build-rec-toggle\"]').textContent.includes('Recording')")
        await page.locator('[data-act="build-rec-mode"][data-mode="check"]').click()
        await page.locator('input[data-input="build-sess-which-text"]').fill("$1,234.50")
        await page.locator('[data-act="build-sess-which"]').click()
        await js_until(page, "document.querySelectorAll('[data-act=\"build-sess-choose\"]').length === 1")
        await page.locator('[data-act="build-sess-choose"]').click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-rec-add\"]')")
        assert await page.locator('input[data-input="build-rec-expected"]').input_value() == "$1,234.50"
        assert await page.locator('[data-act="build-rec-kind"][data-kind="ticked"]').is_disabled()
        await page.locator('[data-act="build-rec-kind"][data-kind="gt"]').click()
        await page.locator('input[data-input="build-rec-expected"]').fill("1000")
        await page.locator('[data-act="build-rec-add"]').click()
        await js_until(page, "document.querySelectorAll('.scard').length === 2")
        assert "1000" in await page.locator(".scard").nth(1).inner_text()
        async with web.aclient() as c:
            await c.post(f"/api/build/session/{rec}/close")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
