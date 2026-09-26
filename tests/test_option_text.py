"""Output/InnerText of an <option> in a closed dropdown (Travelkore row 70: //option[@data-cmp-claimantid='3']).

The element was found, but its text was read as "": in a closed <select> the options have no box of their own, so Chromium's
checkVisibility() calls every one of them hidden.  Selenium counts an option as shown when its <select> is; so do we.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.config import Config
from regrunner.engine.actions import _read_output

PAGE = """
<select id="amount">
  <option data-cmp-claimantid="1">$500,000</option>
  <option data-cmp-claimantid="3" selected>$1,000,000</option>
  <option data-cmp-claimantid="3">$2,000,000</option>
</select>
<select id="gone" style="display:none"><option data-cmp-claimantid="9">from a hidden select</option></select>
<select id="list" multiple size="3"><option data-cmp-claimantid="7">in an open list</option></select>
<div id="shown">plain text</div><div id="hidden" style="display:none">hidden text</div>
<select><optgroup label="Group"><option data-cmp-claimantid="5">grouped</option></optgroup></select>
"""


async def inner_text(selector: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(PAGE)
            ctx = SimpleNamespace(step=SimpleNamespace(output_property="INNERTEXT"), value_text="", cfg=Config())
            read = await _read_output(ctx, SimpleNamespace(locator=page.locator(selector).first))
            return await read()
        finally:
            await browser.close()


@pytest.mark.browser
async def test_the_text_of_an_option_in_a_closed_dropdown_is_read():
    assert await inner_text("xpath=//option[@data-cmp-claimantid='3']") == "$1,000,000"      # the workbook's locator, first match
    assert await inner_text("css=option[data-cmp-claimantid=\"3\"]") == "$1,000,000"          # what selectors.yaml turns it into
    assert await inner_text("option[data-cmp-claimantid='1']") == "$500,000"
    assert await inner_text("option[data-cmp-claimantid='5']") == "grouped"                  # inside an optgroup


@pytest.mark.browser
async def test_an_option_of_a_hidden_dropdown_and_other_hidden_things_still_read_as_empty():
    assert await inner_text("option[data-cmp-claimantid='9']") == ""
    assert await inner_text("#hidden") == ""
    assert await inner_text("#shown") == "plain text"
    assert await inner_text("option[data-cmp-claimantid='7']") == "in an open list"
