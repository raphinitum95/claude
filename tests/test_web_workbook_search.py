"""A folder with dozens of workbooks: searching, ordering, paging and the always-visible selection, in a real browser."""
from __future__ import annotations

import os
import shutil
import threading
import time

import pytest
import uvicorn
import yaml

from regrunner.config import load_config
from regrunner.web.app import create_app
from tests.test_web_ui import js_until, open_ui, pick_only, until
from tests.web_fixtures import Web, web  # noqa: F401
from tests.workbook_factory import build_workbook

pytestmark = pytest.mark.browser
FAMILIES = ["Regression_UAT", "QA_Smoke", "Owner_Advantage", "PostDeparture"]


@pytest.fixture(scope="module")
def many(site, tmp_path_factory):
    """60 workbooks (15 per family) - a real, readable one copied under different names, newest = highest number."""
    root = tmp_path_factory.mktemp("many")
    (root / "workbooks").mkdir()
    template = root / "template.xlsx"
    build_workbook(template, flows=["FlowA"], base_url=site, enabled=["FlowA"])
    now = time.time()
    for n in range(1, 16):
        for k, fam in enumerate(FAMILIES):
            path = root / "workbooks" / f"{fam}_v{n}.xlsx"
            shutil.copy(template, path)
            os.utime(path, (now - (100 - n * 4 - k), now - (100 - n * 4 - k)))       # v15 is the newest of its family
    cfg_file = root / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({"runner": {"workers": 1}, "timeouts": {"element_s": 6}, "auth": {"headless": True}}))
    cfg = load_config(cfg_file, base_dir=root)
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, str(cfg_file)), host="127.0.0.1", port=0, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield Web(f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}", root, cfg_file, site)
    server.should_exit = True


def rows(page):
    return page.locator('[role=group][aria-label="Workbooks"] label.trow')


async def label(page) -> str:
    return (await page.locator(".lbl", has_text="In workbooks/").inner_text()).strip().lower()


async def ready(page):
    await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 0")


async def test_a_long_folder_is_capped_and_searchable(many):
    async with open_ui(many) as page:
        await ready(page)
        assert await rows(page).count() == 7 or await rows(page).count() == 6            # 6 shown (+ the remembered one may be pinned above)
        assert "60" in await label(page)
        search = page.locator("#wb-search")
        assert await search.count() == 1 and "60 workbooks" in (await search.get_attribute("placeholder"))
        more = page.get_by_role("button", name="Show 10 more")
        assert await more.count() == 1 and "54 left" in await more.inner_text()
        await more.click()
        await js_until(page, "document.querySelectorAll('[role=group][aria-label=Workbooks] label.trow').length === 16")
        assert "44 left" in await page.get_by_role("button", name="Show 10 more").inner_text()

        await search.fill("owner v1")                                    # several words, any order of appearance
        await js_until(page, "document.querySelectorAll('[role=group][aria-label=Workbooks] label.trow').length <= 7")
        assert "of 60" in await label(page)
        names = [await rows(page).nth(i).locator("div[style*='font-weight: 650']").inner_text() for i in range(await rows(page).count())]
        assert names and all("Owner_Advantage_v1" in n for n in names)          # v1, v10..v15
        assert await page.locator("mark.hl").count() >= 1                          # the typed text is highlighted
        assert page.errors == []


async def test_enter_picks_the_best_match_escape_clears_and_the_choice_stays_visible(many):
    async with open_ui(many) as page:
        await ready(page)
        search = page.locator("#wb-search")
        await search.fill("postdep v12")
        await search.press("Enter")                                      # type a few letters, press Enter
        await js_until(page, "Array.from(document.querySelectorAll('input[name=workbook]:checked')).map(e => e.value).includes('PostDeparture_v12.xlsx')")
        await pick_only(page, "PostDeparture_v12.xlsx")                  # (the page opened with the newest workbook ticked: leave just this one)
        await search.fill("qa_smoke")                                    # a search that no longer includes the choice
        await js_until(page, "document.body.innerText.toLowerCase().includes('not in this search')")
        pinned = page.locator('[role=group][aria-label="Selected workbooks"] label.trow')
        assert await pinned.count() == 1 and "PostDeparture_v12.xlsx" in await pinned.inner_text()
        await search.press("Escape")                                     # Escape clears the search
        await js_until(page, "document.getElementById('wb-search').value === ''")
        await js_until(page, "![...document.querySelectorAll('.lbl')].some(e => / of 60/i.test(e.innerText))")
        assert page.errors == []


async def test_sorting_and_an_empty_search(many):
    async with open_ui(many) as page:
        await ready(page)
        search = page.locator("#wb-search")
        await search.fill("smoke")
        await page.get_by_role("button", name="A–Z").click()             # natural order: v1, v2 ... v10, not v1, v10, v11
        await js_until(page, "document.querySelector('[role=group][aria-label=Workbooks] label.trow').innerText.includes('QA_Smoke_v1.xlsx')")
        first = [await rows(page).nth(i).locator("div[style*='font-weight: 650']").inner_text() for i in range(3)]
        assert first == ["QA_Smoke_v1.xlsx", "QA_Smoke_v2.xlsx", "QA_Smoke_v3.xlsx"]
        await page.get_by_role("button", name="Newest").click()          # newest first: v15 leads
        await js_until(page, "document.querySelector('[role=group][aria-label=Workbooks] label.trow').innerText.includes('QA_Smoke_v15.xlsx')")
        await search.fill("no such thing")
        await js_until(page, "document.body.innerText.includes('No workbook matches')")
        assert await rows(page).count() == 0
        await page.get_by_role("button", name="clear the search").click()
        await js_until(page, "document.getElementById('wb-search').value === ''")
        await js_until(page, "document.querySelectorAll('[role=group][aria-label=Workbooks] label.trow').length >= 6")


async def test_recently_run_workbooks_are_one_click_away(many):
    with many.client() as c:                                             # a run of one workbook, then look at the New run screen
        run_id = c.post("/api/runs", json={"workbook": "QA_Smoke_v7.xlsx", "tests": ["FlowA"]}).json()["run_id"]
        many.wait_finished(run_id, timeout=150)
    async with open_ui(many) as page:
        await ready(page)
        chip = page.locator("button.chip", has_text="QA_Smoke_v7.xlsx")
        assert await chip.count() == 1
        await page.locator("#wb-search").fill("owner")
        await js_until(page, "!document.body.innerText.toLowerCase().includes('recently run')")       # hidden while searching
        await page.locator("#wb-search").fill("")
        await js_until(page, "document.body.innerText.toLowerCase().includes('recently run')")
        await page.locator("button.chip", has_text="QA_Smoke_v7.xlsx").click()
        await js_until(page, "Array.from(document.querySelectorAll('input[name=workbook]:checked')).map(e => e.value).includes('QA_Smoke_v7.xlsx')")
        assert page.errors == []


async def test_a_small_folder_has_no_search_box(web):                    # the two-workbook project used everywhere else
    async with open_ui(web) as page:
        await js_until(page, "document.querySelectorAll('[role=group] label.trow').length > 0")
        assert await page.locator("#wb-search").count() == 0
        assert await page.locator("button.chip", has_text=".xlsx").count() == 0
