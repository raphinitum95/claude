"""ASK_USER in the web UI: the run screen shows the question, the person types the answer, the run carries on."""
from __future__ import annotations

import json
import time

import pytest

from tests.test_ask_user import SECRET, build_ask_workbook
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


def start(web, style: str, name: str) -> str:
    build_ask_workbook(web.root / "workbooks" / name, web.site, style)
    with web.client() as c:
        res = c.post("/api/runs", json={"workbook": name, "tests": ["Flow"]})
        assert res.status_code == 200, res.text
        return res.json()["run_id"]


def everything(web, run_id: str) -> str:
    text = ""
    for path in (web.root / "runs" / run_id).rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".html", ".log", ".txt"):
            text += path.read_text(errors="ignore")
    return text


async def test_the_question_appears_on_the_run_screen_and_the_answer_reaches_the_field(web):
    run_id = start(web, "into_field", "ask-ui.xlsx")
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await js_until(page, "document.body.innerText.includes('Waiting for you')")
        box = page.locator('input[aria-label="Enter the code from your phone"]')
        assert await box.get_attribute("type") == "password"                                # Output_Property SECRET: hidden while typed
        assert (await page.title()).startswith("● Input needed")                            # visible from another tab
        await js_until(page, "document.activeElement && document.activeElement.tagName === 'INPUT' && document.activeElement.type === 'password'")   # cursor is already there
        await page.keyboard.type(SECRET)
        await page.keyboard.press("Enter")
        await js_until(page, "!document.body.innerText.includes('Waiting for you')")
        assert not (await page.title()).startswith("● Input needed")
        detail = web.wait_finished(run_id, timeout=120)
        assert detail["meta"]["status"] == "PASSED", detail["meta"]
        assert page.errors == []
    steps = detail["results"]["tests"][0]["steps"]
    assert [s["status"] for s in steps] == ["PASSED"] * len(steps)
    assert SECRET not in everything(web, run_id)                                            # not in results, events, report or the run's log
    assert not (web.root / "runs" / run_id / "answers").exists()


def test_the_answer_endpoint_refuses_what_it_should(web):
    run_id = start(web, "then_set", "ask-api.xlsx")
    with web.client() as c:
        assert c.post(f"/api/runs/{run_id}/answer", json={"ask": "nonsense", "answer": "x"}).status_code == 400
        assert c.post("/api/runs/20200101-000000-UAT/answer", json={"ask": "a1-abcdef", "answer": "x"}).status_code == 404
        assert c.post(f"/api/runs/{run_id}/answer", json={"ask": "a1-abcdef", "answer": "x" * 3000}).status_code == 422       # a code, not a document
        events_url = f"/api/runs/{run_id}/events"
        ask = None
        for _ in range(200):
            ask = next((e["ask"] for e in c.get(events_url).json()["events"] if e["type"] == "user_input_needed"), None)
            if ask:
                break
            time.sleep(0.2)
        assert ask, "the run never asked"
        assert c.post(f"/api/runs/{run_id}/answer", json={"ask": "a9-abcdef", "answer": "x"}).status_code in (404, 200)      # not a question of this run
        ok = c.post(f"/api/runs/{run_id}/answer", json={"ask": ask, "answer": SECRET})
        assert ok.status_code == 200 and ok.json() == {"ok": True}
    detail = web.wait_finished(run_id, timeout=120)
    assert detail["meta"]["status"] == "PASSED"
    with web.client() as c:
        late = c.post(f"/api/runs/{run_id}/answer", json={"ask": ask, "answer": "again"})
        assert late.status_code == 409 and late.json()["kind"] == "closed"                  # the run is over: nothing is waiting
    assert SECRET not in everything(web, run_id)
