"""Deleting runs and batches from the UI: a confirm dialog first, the run folders go to runs/.trash, and a run can be removed from inside its batch."""
from __future__ import annotations

import json

import pytest

from tests.test_web_batches import fake_run
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)


def finished(web, run_id, *, workbook="mock.xlsx", status="PASSED", started_at, batch_id=None, batch_label=None):
    """A fabricated finished run with a results.json, enough for the run page and the batch page to read."""
    fake_run(web, run_id, workbook=workbook, status=status, started_at=started_at, batch_id=batch_id, batch_label=batch_label)
    (web.run_dir(run_id) / "results.json").write_text(json.dumps({"environment": "UAT", "workbook": workbook, "status": status, "duration_s": 1.0,
        "tests": [{"id": "FlowA", "sheet": "FlowA", "status": status, "duration_s": 1.0,
                  "steps": [{"row": 3, "seq": 1, "status": status, "name": "Open Browser", "action": "OPEN"}]}]}), encoding="utf-8")


def trashed(web, run_id) -> list[str]:
    trash = web.root / "runs" / ".trash"
    return sorted(p.name for p in trash.iterdir() if p.name.endswith(run_id)) if trash.is_dir() else []


@pytest.mark.browser
async def test_a_run_can_be_deleted_from_inside_its_batch_and_then_the_whole_batch(web):
    finished(web, "ud1-mock", started_at="2026-04-01T00:00:00", batch_id="ud1", batch_label="Delete me")
    finished(web, "ud1-bad", workbook="bad.xlsx", status="FAILED", started_at="2026-04-01T00:00:01", batch_id="ud1")
    async with open_ui(web, path="/#/results/batch/ud1") as page:
        await page.wait_for_selector("text=Delete batch")
        chip = page.locator('[data-key="run-ud1-bad"]')
        await chip.locator("button[data-act=ask-delete-run]").click()                              # the trash button on that run's chip
        dialog = page.locator("[role=dialog]")
        await dialog.wait_for()
        text = await dialog.inner_text()
        assert "ud1-bad" in text and "keeps its other 1 run" in text and "runs/.trash" in text
        await dialog.get_by_role("button", name="Keep it").click()
        await js_until(page, "!document.querySelector('[role=dialog]')")
        assert (web.root / "runs" / "ud1-bad").is_dir()                                            # asking is not deleting

        await chip.locator("button[data-act=ask-delete-run]").click()
        await dialog.get_by_role("button", name="Delete run").click()
        await js_until(page, "!document.querySelector('[role=dialog]') && !document.querySelector('[data-key=\"run-ud1-bad\"]')")
        assert page.url.endswith("#/results/batch/ud1")                                            # still on the batch, with one run fewer
        assert await page.locator('[data-key="run-ud1-mock"]').count() == 1
        assert not (web.root / "runs" / "ud1-bad").exists() and len(trashed(web, "ud1-bad")) == 1

        await page.get_by_role("button", name="Delete batch").click()
        await dialog.wait_for()
        assert "Delete me" in await dialog.inner_text() and "All 1 run" in await dialog.inner_text()
        await dialog.get_by_role("button", name="Delete batch (1 run)").click()
        await js_until(page, "location.hash === '#/results'")                                      # the batch is gone: back to the history
        assert not (web.root / "runs" / "ud1-mock").exists() and len(trashed(web, "ud1-mock")) == 1
        assert await page.locator('a[href="#/results/batch/ud1"]').count() == 0
        assert not page.errors, page.errors


@pytest.mark.browser
async def test_deleting_a_run_from_its_own_page_leaves_for_its_batch_or_the_history(web):
    finished(web, "ud2-a", started_at="2026-04-02T00:00:00", batch_id="ud2")
    finished(web, "ud2-b", workbook="bad.xlsx", started_at="2026-04-02T00:00:01", batch_id="ud2")
    finished(web, "ud2-solo", started_at="2026-04-02T00:00:02")
    async with open_ui(web, path="/#/results/run/ud2-a") as page:
        await page.get_by_role("button", name="Delete run").click()
        await page.locator("[role=dialog]").get_by_role("button", name="Delete run").click()
        await js_until(page, "location.hash === '#/results/batch/ud2'")                            # it was in a batch that still has ud2-b
        await page.wait_for_selector('[data-key="run-ud2-b"]')
        assert not (web.root / "runs" / "ud2-a").exists()

        await page.goto(web.base + "/#/results/run/ud2-solo")
        await page.get_by_role("button", name="Delete run").click()
        await page.locator("[role=dialog]").get_by_role("button", name="Delete run").click()
        await js_until(page, "location.hash === '#/results'")                                      # a solo run: nothing left to show but the history
        assert not (web.root / "runs" / "ud2-solo").exists() and (web.root / "runs" / "ud2-b").is_dir()
        assert not page.errors, page.errors


@pytest.mark.browser
async def test_the_batch_view_on_the_run_tab_deletes_a_finished_batch(web):
    finished(web, "ud3-a", started_at="2026-04-03T00:00:00", batch_id="ud3")
    finished(web, "ud3-b", workbook="bad.xlsx", started_at="2026-04-03T00:00:01", batch_id="ud3")
    async with open_ui(web, path="/#/batch/ud3") as page:
        await page.get_by_role("button", name="Delete batch").click()
        dialog = page.locator("[role=dialog]")
        assert "All 2 runs" in await dialog.inner_text()
        await dialog.get_by_role("button", name="Delete batch (2 runs)").click()
        await js_until(page, "location.hash === '#/'")
        assert not (web.root / "runs" / "ud3-a").exists() and not (web.root / "runs" / "ud3-b").exists()
        assert not page.errors, page.errors
