"""The build window through the server and the Build tab (P08): ``/api/build/session/{name}/*`` and the editor's session strip / pick panel /
side-effect dialog.  The workbook points only at the mock site; the window is headless (``headless: true`` in the start body is for tests)."""
from __future__ import annotations

import asyncio
import re

import pytest

from tests.test_build_session import plans_book
from tests.test_web_build import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


@pytest.fixture
def plans(web, request):
    name = f"sess_{request.node.name}"[:60] + ".xlsx"
    plans_book(web.root / "workbooks" / name, web.site)
    return name


async def wait_state(c, name: str, check, timeout: float = 30) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        state = (await c.get(f"/api/build/session/{name}")).json()
        if check(state):
            return state
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"session state not reached: {state}")
        await asyncio.sleep(0.2)


def replayed(state: dict) -> list[tuple[int, str]]:
    return [(r["n"], r["status"]) for r in (state.get("replay") or {}).get("results", [])]


async def test_the_session_routes_open_run_pick_and_close_a_build_window(web, plans):
    async with web.aclient() as c:
        assert (await c.get(f"/api/build/session/{plans}")).json()["open"] is False
        r = await c.post(f"/api/build/session/{plans}/pick", json={"mode": "pick"})
        assert r.status_code == 409 and r.json()["kind"] == "closed"
        r = await c.post(f"/api/build/session/{plans}/start", json={"test": "Plans", "headless": True})
        assert r.status_code == 200, r.text
        state = await wait_state(c, plans, lambda s: s["status"] == "ready" and s.get("replay") and not s["replay"]["running"])
        assert replayed(state) == [(1, "PASSED")] and state["environment"] == "UAT" and state["dataRow"] == 2
        r = await c.post(f"/api/build/session/{plans}/which", json={"text": "Choose", "kind": "button", "row": 3})
        assert [m["context"] for m in r.json()["which"]["matches"]] == ["Basic", "Plus", "Max"]
        r = await c.post(f"/api/build/session/{plans}/choose", json={"i": 2})
        assert r.json()["pick"]["forN"] == 2 and "'Max'" in r.json()["pick"]["locator"]["value"]
        r = await c.post(f"/api/build/session/{plans}/variable", json={"role": "context", "token": "PLAN"})
        assert "{PLAN}" in r.json()["pick"]["locator"]["value"]
        r = await c.post(f"/api/build/session/{plans}/use", json={})
        assert r.status_code == 200, r.text
        step = next(s for t in r.json()["model"]["tests"] if t["id"] == "Plans" for s in t["steps"] if s["row"] == 3)
        assert "{PLAN}" in step["locator"]["value"] and step["locator"]["plainWords"][-1]["variable"] == "PLAN"
        r = await c.post(f"/api/build/session/{plans}/run-to-here", json={"row": 5})
        assert r.status_code == 200
        question = (await wait_state(c, plans, lambda s: s.get("question")))["question"]
        assert question["sideEffect"]["name"] == "pay"
        assert (await c.post(f"/api/build/session/{plans}/run-next", json={})).json()["kind"] == "busy"
        assert (await c.post(f"/api/build/session/{plans}/answer", json={"id": question["id"], "answer": "yes"})).json() == {"ok": True}
        state = await wait_state(c, plans, lambda s: not s["replay"]["running"])
        assert replayed(state) == [(1, "PASSED"), (2, "PASSED"), (3, "PASSED"), (4, "PASSED")]
        assert (await c.post(f"/api/build/session/{plans}/answer", json={"id": question["id"], "answer": "yes"})).status_code == 409
        runs = (await c.get("/api/runs")).json()
        assert not any(".build" in str(x) for x in runs)                  # a build window is not a run
        assert (await c.post(f"/api/build/session/{plans}/close")).json()["open"] is False
        assert (await c.get(f"/api/build/session/{plans}")).json()["open"] is False


async def test_a_production_environment_needs_a_typed_confirmation_before_the_window_opens(web, plans):
    async with web.aclient() as c:
        r = await c.post(f"/api/build/session/{plans}/start", json={"test": "Plans", "env": "PROD", "headless": True})
        assert r.status_code == 400 and r.json()["kind"] == "prod_confirm"
        assert (await c.get(f"/api/build/session/{plans}")).json()["open"] is False
        r = await c.post(f"/api/build/session/{plans}/start", json={"test": "Plans", "env": "PROD", "confirmProd": "PROD", "headless": True})
        assert r.status_code == 200 and r.json()["environment"] == "PROD"
        await c.post(f"/api/build/session/{plans}/close")


async def test_the_build_window_coexists_with_a_run_of_the_same_workbook(web, plans):
    async with web.aclient() as c:
        r = await c.post(f"/api/build/session/{plans}/start", json={"test": "Plans", "headless": True})
        assert r.status_code == 200, r.text
        run = await c.post("/api/runs", json={"workbook": plans, "tests": ["Plans"]})
        assert run.status_code == 200, run.text                          # the run reads the saved file in its own process and browser
        detail = await asyncio.to_thread(web.wait_finished, run.json()["run_id"])
        assert detail["meta"]["status"] in ("PASSED", "FAILED")
        assert (await c.get(f"/api/build/session/{plans}")).json()["open"] is True
        await c.post(f"/api/build/session/{plans}/close")


async def test_the_editor_opens_the_site_runs_up_to_a_step_and_asks_before_a_side_effect(web, plans):
    pw, browser, page = await open_ui(web, f"/#/build/{plans}/test/Plans")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length === 4")
        async with web.aclient() as c:                                    # (opened through the API: the button only differs by headless)
            r = await c.post(f"/api/build/session/{plans}/start", json={"test": "Plans", "headless": True})
            assert r.status_code == 200
        await js_until(page, "!!document.querySelector('[data-act=\"build-sess-run-to\"]')")
        assert "Build window" in await page.locator(".sess-bar").inner_text()
        await page.locator('.scard [data-act="build-pick-step"]').nth(3).click()          # step 4: paid once
        await page.locator('[data-act="build-sess-run-to"]').click()
        await js_until(page, "!!document.querySelector('[role=dialog][aria-label=\"Run it for real?\"]')")
        await page.get_by_role("button", name=re.compile("Don't run it")).click()
        await js_until(page, "document.querySelector('.sess-bar').textContent.includes('chose not to run it')")
        marks = await page.locator(".scard .tag").evaluate_all("els => els.map(e => e.textContent.trim())")
        assert marks.count("ran") == 2 and "failed" in marks
        await page.locator('.scard [data-act="build-pick-step"]').nth(1).click()          # step 2: choose
        await page.locator('input[data-input="build-sess-which-text"]').fill("Choose")
        await page.locator('[data-act="build-sess-which"]').click()
        await js_until(page, "document.querySelectorAll('[data-act=\"build-sess-choose\"]').length === 3")
        await page.locator('[data-act="build-sess-choose"]').nth(2).click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-sess-use\"]')")
        assert "Use for step 2" in await page.locator('[data-act="build-sess-use"]').inner_text()
        await page.locator('[data-act="build-sess-use"]').click()
        await js_until(page, "document.querySelector('aside:not(.b-rail)').textContent.includes('inside card')")
        await page.locator('[data-act="build-sess-close"]').click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-sess-open\"]')")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
