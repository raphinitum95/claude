"""The new-run screen warns about an empty parameter before anything runs, and the run screen asks for the value when the step is reached."""
from __future__ import annotations

import pytest

from tests.test_blank_params import VALUE, build
from tests.test_web_ui import js_until, open_ui, pick_only
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


async def test_the_new_run_screen_names_the_empty_parameter_before_the_run(web):
    build(web.root / "workbooks" / "blank-param.xlsx", web.site)
    async with open_ui(web) as page:
        await pick_only(page, "blank-param.xlsx")
        await js_until(page, "document.body.innerText.includes('A test uses an empty parameter')")
        text = await page.locator("body").inner_text()
        assert "View uses DT_Policy_Out, which is empty and nothing in this run sets it. Buy does: add it to the run" in text
        assert page.errors == []


async def test_the_run_screen_asks_for_the_value_and_the_step_uses_it(web):
    build(web.root / "workbooks" / "blank-param-run.xlsx", web.site)
    with web.client() as c:
        run_id = c.post("/api/runs", json={"workbook": "blank-param-run.xlsx", "tests": ["View"]}).json()["run_id"]
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await js_until(page, "document.body.innerText.includes('DT_Policy_Out is empty for View')", timeout=90)
        await page.locator('input[aria-label^="DT_Policy_Out is empty"]').fill(VALUE)
        await page.keyboard.press("Enter")
        detail = web.wait_finished(run_id, timeout=120)
        assert detail["meta"]["status"] == "PASSED", detail["meta"]
        assert page.errors == []
    steps = {s["name"]: s for s in detail["results"]["tests"][0]["steps"]}
    assert steps["What the field holds"]["actual"] == VALUE
