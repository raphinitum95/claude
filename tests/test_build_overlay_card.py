"""The check card drawn inside the build window (build/overlay.js): where the Expected value comes from - the page, a variable picked from a list that
can be searched, or typed.  No build session: a bare page gets the overlay with its closed shadow root forced open (so the test can read it), a stub
for the binding that records what the card sends, and a card the way the builder would send it."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from regrunner.build.session import OVERLAY_JS

pytestmark = pytest.mark.browser

FORM = {
    "purpose": "check", "chosen": "text_is", "n": 3, "token": "", "text": "$1,234.50",
    "kinds": [{"id": "text_is", "group": "Text", "label": "Text is", "enabled": True, "expected": "$1,234.50", "why": ""},
              {"id": "shown", "group": "Shown or gone", "label": "It shows", "enabled": True, "expected": "", "why": ""},
              {"id": "gt", "group": "Numbers & patterns", "label": "Greater than", "enabled": True, "expected": "1234.5", "why": ""}],
    "variables": [{"token": "FIRST_NAME", "value": "Jane", "group": "data", "n": None, "match": False},
                  {"token": "LAST_NAME", "value": "Doe", "group": "data", "n": None, "match": False},
                  {"token": "TOTAL_SHOWN", "value": "", "group": "saved", "n": 2, "match": False},
                  {"token": "BALANCE", "value": "$1,234.50", "group": "saved", "n": 2, "match": True},
                  {"token": "DOMAIN", "value": "https://uat.example.com", "group": "environment", "n": None, "match": False}],
}


async def inside(page, expression: str):
    """Evaluate ``expression`` with ``root`` = the overlay's shadow root."""
    return await page.evaluate(f"(() => {{ const root = document.querySelector('rr-build-overlay').shadowRoot; return {expression}; }})()")


async def press(page, selector: str, nth: int = 0) -> None:
    """A real mouse press in the middle of a control of the card (the overlay finds what was pressed by position)."""
    box = await inside(page, f"(() => {{ const r = root.querySelectorAll({selector!r})[{nth}].getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
    await page.mouse.click(*box)
    await asyncio.sleep(0.15)


async def shot(page, name: str) -> None:
    """``RR_SHOTS=<dir>`` keeps a screenshot to look at."""
    if os.environ.get("RR_SHOTS"):
        Path(os.environ["RR_SHOTS"]).mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(Path(os.environ["RR_SHOTS"]) / f"overlay_{name}.png"))


async def sources(page) -> list[str]:
    return await inside(page, "[...root.querySelectorAll('.seg button')].map((b) => b.textContent + (b.classList.contains('on') ? '*' : ''))")


@pytest.fixture
async def card():
    sent: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 1200, "height": 900})
        await context.expose_binding("__rrBuildCall", lambda _src, body: sent.append(body))
        await context.add_init_script("""(() => { const attach = Element.prototype.attachShadow;
          Element.prototype.attachShadow = function (init) { return attach.call(this, { ...init, mode: 'open' }); }; })();""")
        await context.add_init_script(script=OVERLAY_JS.replace("__RR_KEY__", "k"))
        page = await context.new_page()
        await page.goto("data:text/html,<body><h1>Basket</h1><span id=total style='position:absolute;left:60px;top:160px'>$1,234.50</span></body>")
        await page.evaluate("window.__rrBuild.apply({mode: 'check'})")
        await page.click("#total")
        await page.evaluate("(form) => window.__rrBuild.apply({card: {id: 'c1', title: 'Check this: total', ok: true, lines: [], form}})", FORM)
        await asyncio.sleep(0.2)
        yield page, sent
        await browser.close()


async def test_the_expected_value_is_read_from_the_page_by_default_and_says_which_variable_equals_it(card):
    page, _ = card
    await shot(page, "page")
    assert await sources(page) == ["From the page*", "From a variable", "Type my own"]
    assert await inside(page, "root.querySelector('.read').textContent") == "$1,234.50"
    assert await inside(page, "[...root.querySelectorAll('button[data-rr-act=use-var]')].map((b) => b.textContent)") == ["{BALANCE}"]       # "Same as now"


async def test_a_variable_is_found_by_typing_part_of_its_name_or_value_and_enter_takes_the_first(card):
    page, sent = card
    await press(page, ".seg button", 1)
    assert await sources(page) == ["From the page", "From a variable*", "Type my own"]
    assert await inside(page, "root.querySelector('.vopt.on .tk').textContent") == "BALANCE"                       # the one that equals the page is chosen for you
    names = await inside(page, "[...root.querySelectorAll('.vopt .tk')].map((n) => n.textContent)")
    assert names == ["FIRST_NAME", "LAST_NAME", "TOTAL_SHOWN", "BALANCE", "DOMAIN"]
    assert await inside(page, "[...root.querySelectorAll('.vg')].map((n) => n.textContent)") == ["Test data", "Saved by earlier steps", "Environment"]
    await shot(page, "variable")
    await press(page, "input[data-rr-field=vsearch]")
    await page.keyboard.type("last na")                                                                              # words, not the underscore
    assert await inside(page, "[...root.querySelectorAll('.vopt .tk')].map((n) => n.textContent)") == ["LAST_NAME"]
    await page.keyboard.press("Control+A")
    await page.keyboard.type("example")                                                                              # a value matches too
    assert await inside(page, "[...root.querySelectorAll('.vopt .tk')].map((n) => n.textContent)") == ["DOMAIN"]
    await page.keyboard.press("Control+A")
    await page.keyboard.type("zzz")
    assert await inside(page, "root.querySelectorAll('.vopt').length") == 0
    assert "No variable matches" in await inside(page, "root.querySelector('.vlist').textContent")
    await page.keyboard.press("Control+A")
    await page.keyboard.type("last na")
    await page.keyboard.press("Enter")
    assert await inside(page, "root.querySelector('.vopt.on .tk').textContent") == "LAST_NAME"
    assert "Doe" in await inside(page, "root.textContent")                                                          # what it is worth now
    await press(page, "button[data-rr-act=add]")
    assert sent[-1] == {"kind": "check-add", "check": "text_is", "expected": "{LAST_NAME}", "token": "", "key": "k"}


async def test_a_typed_value_can_have_variables_inserted_and_each_kind_reads_its_own_page_value(card):
    page, sent = card
    await press(page, ".seg button", 2)
    assert await inside(page, "root.querySelector('input[data-rr-field=expected]').value") == "$1,234.50"            # typing starts from what was read
    await press(page, "input[data-rr-field=expected]")
    await page.keyboard.press("Control+A")
    await page.keyboard.type("{LOW};")
    await press(page, "button[data-rr-act=insert-list]")
    await press(page, "input[data-rr-field=vsearch]")
    await page.keyboard.type("dom")
    await page.keyboard.press("Enter")
    assert await inside(page, "root.querySelector('input[data-rr-field=expected]').value") == "{LOW};{DOMAIN}"
    await press(page, "button[data-rr-act=kind][data-kind=shown]")                                                  # "It shows" compares nothing: no Expected at all
    assert await inside(page, "root.querySelector('input[data-rr-field=expected]')") is None and await inside(page, "!!root.querySelector('.seg')") is False
    await press(page, "button[data-rr-act=kind][data-kind=gt]")                                                     # (and a kind with a page value goes back to reading it)
    assert await sources(page) == ["From the page*", "From a variable", "Type my own"]
    assert await inside(page, "root.querySelector('.read').textContent") == "1234.5"
    await press(page, "button[data-rr-act=add]")
    assert sent[-1]["expected"] == "1234.5" and sent[-1]["check"] == "gt"
