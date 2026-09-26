"""The run screen lists the values a run set."""
from __future__ import annotations

import pytest

from tests.test_blank_params import build
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


async def test_the_finished_run_shows_the_values_it_set(web):
    build(web.root / "workbooks" / "sets-a-value.xlsx", web.site)
    with web.client() as c:
        run_id = c.post("/api/runs", json={"workbook": "sets-a-value.xlsx", "tests": ["Buy"]}).json()["run_id"]
    detail = web.wait_finished(run_id, timeout=120)
    assert detail["meta"]["status"] == "PASSED"
    async with open_ui(web, path=f"/#/run/{run_id}") as page:
        await js_until(page, "document.body.innerText.includes('Values set')")
        text = await page.locator("body").inner_text()
        assert "DT_Policy_Out" in text and "Google Authenticator" in text and "Buy · step 2 · row 3 · Get Policy Number" in text
        assert page.errors == []
