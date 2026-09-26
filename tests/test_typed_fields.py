"""Typed text has to stay: a page that is still loading can wipe a field (or an earlier one) a moment after it was typed."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.config import Config
from regrunner.engine.actions import ends_typing_run, type_into
from regrunner.engine.session import ActionError

pytestmark = pytest.mark.browser
async def _ready(*args) -> None:
    return None                                     # the real ensure_ready is covered by tests/test_page_ready.py


FIELDS = "<input id='fn'><input id='ln'><input id='ph' inputmode='numeric'>"


async def typing(html: str, steps):
    """Load ``html`` and run ``steps`` = [(step name, selector, text)] through type_into like consecutive SET steps.
    Returns (values by id, the ActionError that ended it or None, seconds)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html)
            ctx = SimpleNamespace(act_timeout_s=6.0, cfg=Config(), step=SimpleNamespace(name=""), session=SimpleNamespace(page=page, typed=[], ensure_ready=_ready, settle_after_input=_ready, calls_snapshot=lambda: (0, frozenset(), 0)),
                                  review=SimpleNamespace(flag=lambda *a, **k: None), out=SimpleNamespace(notes=[]))
            started = time.monotonic()
            error = None
            try:
                for name, selector, text in steps:
                    ctx.step.name = name
                    await type_into(ctx, SimpleNamespace(locator=page.locator(selector)), text, clear_first=True)
            except ActionError as err:
                error = err
            seconds = time.monotonic() - started
            values = {i: await page.locator(f"#{i}").input_value() for i in ("fn", "ln") if await page.locator(f"#{i}").count()}
            return values, error, seconds
        finally:
            await browser.close()


STEPS = [("First Name", "#fn", "Ada"), ("Last Name", "#ln", "Lovelace")]


async def test_fields_that_keep_their_text_pass_untouched():
    values, error, _ = await typing(FIELDS, STEPS)
    assert values == {"fn": "Ada", "ln": "Lovelace"} and error is None


async def test_typing_the_last_name_that_empties_the_first_name_fails_the_step_and_is_not_typed_again():
    """Row 54 sets First Name, row 55 sets Last Name, and the page empties First Name: a defect must be reported, not repaired."""
    html = FIELDS + "<script>let wiped = false; ln.addEventListener('input', () => { if (!wiped) { wiped = true; setTimeout(() => { fn.value = ''; }, 120); } });</script>"
    values, error, _ = await typing(html, STEPS)
    assert error is not None and "'First Name' was typed earlier and is now empty" in str(error) and "'Last Name'" in str(error)
    assert values == {"fn": "", "ln": "Lovelace"}                           # left exactly as the page left it


async def test_a_field_emptied_right_after_it_was_typed_fails_the_step():
    html = FIELDS + "<script>let once = false; fn.addEventListener('input', () => { if (!once) { once = true; setTimeout(() => { fn.value = ''; }, 100); } });</script>"
    values, error, _ = await typing(html, STEPS)
    assert error is not None and "Typed 'First Name' but the field is empty" in str(error)
    assert values["fn"] == ""                                               # not typed again


async def test_input_the_page_rejects_outright_is_not_mistaken_for_a_wipe():
    html = FIELDS + "<script>ph.addEventListener('input', () => { ph.value = ph.value.replace(/\\D/g, ''); });</script>"
    values, error, seconds = await typing(html, [("Phone", "#ph", "abc")])             # letters into a digits-only field
    assert error is None and seconds < 0.6


async def test_a_masked_value_is_fine():
    html = FIELDS + "<script>ph.addEventListener('input', () => { ph.value = ph.value.replace(/\\D/g, '').replace(/^(\\d{3})(\\d+)/, '($1) $2'); });</script>"
    _, error, _ = await typing(html, [("Phone", "#ph", "5551234567")])
    assert error is None


async def test_a_field_the_page_removed_is_not_chased():
    html = FIELDS + "<script>ln.addEventListener('input', () => { fn.remove(); });</script>"
    _, error, _ = await typing(html, STEPS)                                 # the page moved on: nothing to check, nothing to fail
    assert error is None


def test_only_typing_style_steps_keep_the_protected_run():
    assert not any(ends_typing_run(a) for a in ("SET", "WRITE", "WAIT", "OUTPUT", "EXIST", "SCREENSHOT", "SWITCHTOFRAME"))
    assert all(ends_typing_run(a) for a in ("CLICK", "JS_CLICK", "SELECT", "OPEN", "TICK", "CLEAR", "NAVIGATE"))
