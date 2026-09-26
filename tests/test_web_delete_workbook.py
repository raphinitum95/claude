"""Deleting a workbook from the UI: it leaves the list, is kept in workbooks/.trash, and never yanks a workbook out from under a run."""
from __future__ import annotations

import shutil
import time

import pytest

from tests.test_web_ui import js_until, open_ui, pick_only
from tests.web_fixtures import HEADERS, bad_run, web  # noqa: F401  (fixtures)


def add_copy(web, name: str):
    path = web.root / "workbooks" / name
    shutil.copy(web.root / "workbooks" / "mock.xlsx", path)
    return path


def trashed(web) -> list[str]:
    trash = web.root / "workbooks" / ".trash"
    return sorted(p.name for p in trash.iterdir()) if trash.is_dir() else []


def test_deleting_moves_the_file_to_the_trash_and_takes_it_off_the_list(web):
    path = add_copy(web, "scratch-api.xlsx")
    with web.client() as c:
        assert "scratch-api.xlsx" in {w["name"] for w in c.get("/api/workbooks").json()}
        res = c.delete("/api/workbooks/scratch-api.xlsx")
        assert res.status_code == 200 and res.json()["deleted"] == "scratch-api.xlsx" and res.json()["kept_as"].startswith(".trash/")
        assert "scratch-api.xlsx" not in {w["name"] for w in c.get("/api/workbooks").json()}
        assert c.get("/api/workbooks/scratch-api.xlsx/tests").status_code == 404
        assert c.delete("/api/workbooks/scratch-api.xlsx").status_code == 404                   # already gone
    assert not path.exists()
    (kept,) = [n for n in trashed(web) if n.endswith("-scratch-api.xlsx")]
    assert (web.root / "workbooks" / ".trash" / kept).stat().st_size > 1000                      # the real file, not an empty shell
    assert (web.root / "workbooks" / "mock.xlsx").is_file()                                      # nothing else was touched


def test_only_a_file_in_the_workbooks_folder_can_be_deleted(web):
    outside = web.root / "outside.xlsx"
    shutil.copy(web.root / "workbooks" / "mock.xlsx", outside)
    with web.client() as c:
        for name in ("..%2Foutside.xlsx", "../outside.xlsx", "%2E%2E%2Foutside.xlsx", ".trash"):
            assert c.delete(f"/api/workbooks/{name}").status_code in (404, 405)
    assert outside.is_file()
    outside.unlink()


def test_the_request_must_come_from_the_page(web):
    add_copy(web, "scratch-csrf.xlsx")
    import httpx
    res = httpx.delete(f"{web.base}/api/workbooks/scratch-csrf.xlsx")                              # no X-Requested-With header
    assert res.status_code == 403
    assert (web.root / "workbooks" / "scratch-csrf.xlsx").is_file()
    (web.root / "workbooks" / "scratch-csrf.xlsx").unlink()


@pytest.mark.browser
def test_a_workbook_that_a_run_is_using_cannot_be_deleted_until_it_finishes(web):
    add_copy(web, "scratch-busy.xlsx")
    with web.client() as c:
        run_id = c.post("/api/runs", json={"workbook": "scratch-busy.xlsx", "tests": ["FlowA"]}).json()["run_id"]
        busy = c.delete("/api/workbooks/scratch-busy.xlsx")
        assert busy.status_code == 409 and busy.json()["kind"] == "busy" and "still going" in busy.json()["error"]
        assert (web.root / "workbooks" / "scratch-busy.xlsx").is_file()
        web.wait_finished(run_id, timeout=150)
        deadline = time.time() + 15                                                             # the run's process has gone shortly after it reports finished
        while (res := c.delete("/api/workbooks/scratch-busy.xlsx")).status_code == 409 and time.time() < deadline:
            time.sleep(0.5)
        assert res.status_code == 200
    assert not (web.root / "workbooks" / "scratch-busy.xlsx").exists()
    assert (web.root / "runs" / run_id / "workbook.xlsx").is_file()                              # the run keeps the workbook it executed


@pytest.mark.browser
async def test_the_delete_button_asks_first_and_then_removes_the_row(web):
    add_copy(web, "scratch-ui.xlsx")
    async with open_ui(web) as page:
        await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 1")
        checked = "document.querySelector('input[name=workbook]:checked') && document.querySelector('input[name=workbook]:checked').value"
        before = await page.evaluate(checked)
        row = page.locator("label.trow", has_text="scratch-ui.xlsx")
        assert await row.count() == 1
        await row.locator("button.wb-del").click()
        dialog = page.locator('[role=dialog]')
        await dialog.wait_for()
        assert "scratch-ui.xlsx" in await dialog.inner_text() and "workbooks/.trash" in await dialog.inner_text()
        assert await page.evaluate(checked) == before                                            # the click did not also pick that workbook
        await dialog.get_by_role("button", name="Keep it").click()
        await js_until(page, "!document.querySelector('[role=dialog]')")
        assert await row.count() == 1 and (web.root / "workbooks" / "scratch-ui.xlsx").is_file()

        await row.locator("button.wb-del").click()
        await dialog.get_by_role("button", name="Delete workbook").click()
        await js_until(page, "!document.querySelector('[role=dialog]') && document.body.innerText.toLowerCase().includes('scratch-ui.xlsx deleted')")
        assert await page.locator("label.trow", has_text="scratch-ui.xlsx").count() == 0
        assert not (web.root / "workbooks" / "scratch-ui.xlsx").exists() and any(n.endswith("-scratch-ui.xlsx") for n in trashed(web))
        assert await page.locator("label.trow", has_text="mock.xlsx").count() == 1
        assert page.errors == []


@pytest.mark.browser
async def test_deleting_the_selected_workbook_clears_the_form(web):
    add_copy(web, "scratch-selected.xlsx")
    async with open_ui(web) as page:
        await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 1")
        row = page.locator("label.trow", has_text="scratch-selected.xlsx")
        await pick_only(page, "scratch-selected.xlsx")                                             # the newest workbook is ticked when the page opens; make it the only one
        await js_until(page, "Array.from(document.querySelectorAll('input[name=workbook]:checked')).map(e => e.value).includes('scratch-selected.xlsx')")
        await js_until(page, "document.body.innerText.toLowerCase().includes('read ok')")
        assert await page.locator('[role=dialog]').count() == 0                                   # clicking the row picks it; only the trash button asks to delete
        await row.locator("button.wb-del").click()
        await page.locator('[role=dialog]').get_by_role("button", name="Delete workbook").click()
        await js_until(page, "!document.querySelector('[role=dialog]') && document.querySelectorAll('input[name=workbook]:checked').length === 0")
        assert await page.locator("label.trow", has_text="scratch-selected.xlsx").count() == 0
        assert "No workbook" in await page.locator("body").inner_text()                            # the readiness list asks for one again
        assert page.errors == []


async def refuse_delete(page, status: int, body: str):
    async def handler(route):
        if route.request.method == "DELETE":
            await route.fulfill(status=status, content_type="application/json", body=body)
        else:
            await route.continue_()
    await page.route("**/api/workbooks/*", handler)


@pytest.mark.browser
async def test_a_server_that_predates_the_button_is_reported_not_treated_as_success(web):
    """An old server answers the unknown DELETE route with a bare 404 ({"detail": "Not Found"}): the UI used to toast 'deleted' and list the file again."""
    path = add_copy(web, "scratch-old-server.xlsx")
    async with open_ui(web) as page:
        await refuse_delete(page, 404, '{"detail":"Not Found"}')
        await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 1")
        row = page.locator("label.trow", has_text="scratch-old-server.xlsx")
        await row.locator("button.wb-del").click()
        await page.locator('[role=dialog]').get_by_role("button", name="Delete workbook").click()
        await js_until(page, "document.querySelector('[role=dialog]') && document.querySelector('[role=dialog]').innerText.toLowerCase().includes('older than this page')")
        assert "deleted" not in (await page.locator("body").inner_text()).lower().replace("delete workbook", "").replace("delete this workbook", "")
        assert await row.count() == 1 and path.is_file()
        await page.locator('[role=dialog]').get_by_role("button", name="Keep it").click()
    path.unlink()


@pytest.mark.browser
async def test_an_answer_of_success_while_the_file_is_still_listed_is_an_error(web):
    path = add_copy(web, "scratch-sticky.xlsx")
    async with open_ui(web) as page:
        await refuse_delete(page, 200, '{"deleted":"scratch-sticky.xlsx","kept_as":".trash/x"}')              # says yes, does nothing
        await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 1")
        row = page.locator("label.trow", has_text="scratch-sticky.xlsx")
        await row.locator("button.wb-del").click()
        await page.locator('[role=dialog]').get_by_role("button", name="Delete workbook").click()
        await js_until(page, "document.querySelector('[role=dialog]') && document.querySelector('[role=dialog]').innerText.includes('is still in workbooks/')")
        assert await row.count() == 1 and path.is_file()
        assert "deleted. a copy" not in (await page.locator("body").inner_text()).lower()
    path.unlink()


@pytest.mark.browser
async def test_a_file_the_server_already_lost_just_leaves_the_list(web):
    path = add_copy(web, "scratch-gone.xlsx")
    async with open_ui(web) as page:
        await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 1")
        row = page.locator("label.trow", has_text="scratch-gone.xlsx")
        path.unlink()                                                                            # removed behind the page's back
        await row.locator("button.wb-del").click()
        await page.locator('[role=dialog]').get_by_role("button", name="Delete workbook").click()
        await js_until(page, "!document.querySelector('[role=dialog]') && document.querySelectorAll('label.trow').length > 0")
        assert await page.locator("label.trow", has_text="scratch-gone.xlsx").count() == 0


@pytest.mark.parametrize("name", ["a b (1).xlsx", "a#b.xlsx", "a%20b.xlsx", "a+b&c.xlsx", "x'y.xlsx",
                                  "UAT DT_Qantas StandAlone_Staff Daily Regression_v1.1.xlsx"])
def test_awkward_file_names_are_deleted_like_any_other(web, name):
    from urllib.parse import quote
    path = add_copy(web, name)
    with web.client() as c:
        assert c.delete("/api/workbooks/" + quote(name, safe="")).status_code == 200            # what the page sends (encodeURIComponent)
    assert not path.exists()
