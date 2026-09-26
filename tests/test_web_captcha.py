"""A captcha in a run started from the web UI: the run screen says so, the test carries on when it is solved, or ends when the person skips it."""
from __future__ import annotations

import pytest

from tests.test_captcha import build_captcha_workbook
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


def start(web, name: str, query: str) -> str:
    build_captcha_workbook(web.root / "workbooks" / name, web.site, query)
    with web.client() as c:
        res = c.post("/api/runs", json={"workbook": name, "tests": ["Flow"]})
        assert res.status_code == 200, res.text
        return res.json()["run_id"]


async def test_the_banner_appears_while_the_captcha_waits_and_goes_when_it_is_solved(web):
    run_id = start(web, "captcha-solved.xlsx", "?person=9000")
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await js_until(page, "document.body.innerText.includes('Captcha detected')", timeout=90)
        text = await page.locator(".bn").first.inner_text()
        assert "Captcha detected in Flow." in text and 'reCAPTCHA is asking "Select all images with a fire hydrant"' in text
        assert "Solve it in the browser window that opened" in text
        assert "s left" in text and await page.locator('[data-act="ask-skip"]').count() == 1
        assert (await page.title()).startswith("● Input needed")                            # visible from another tab
        await js_until(page, "!document.body.innerText.includes('Captcha detected')", timeout=60)
        detail = web.wait_finished(run_id, timeout=120)
        assert detail["meta"]["status"] == "PASSED", detail["meta"]
        assert page.errors == []
    (test,) = detail["results"]["tests"]
    assert test["status"] == "PASSED" and test["attempts"][0]["captcha"] is True


async def test_skipping_from_the_banner_ends_the_test_with_the_reason(web):
    run_id = start(web, "captcha-skip.xlsx", "")                                             # nobody solves it
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await js_until(page, "document.body.innerText.includes('Captcha detected')", timeout=90)
        await page.locator('[data-act="ask-skip"]').click()
        await js_until(page, "!document.body.innerText.includes('Captcha detected')")
        detail = web.wait_finished(run_id, timeout=120)
        assert page.errors == []
    (test,) = detail["results"]["tests"]
    assert test["status"] == "ERROR" and "It was skipped, so the test was stopped here" in test["error"]
    assert len(test["steps"]) == 3 and test["steps"][-1]["status"] == "FAILED"
