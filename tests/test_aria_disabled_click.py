"""Click / Tick / ... on an element that only ``aria-disabled="true"`` marks disabled: the legacy runner (Selenium) clicked it, Playwright waits for it to be
"enabled".  With ``behaviour.click_ignores_aria_disabled`` (on by default) the step clicks like the legacy runner - after checking the element is visible, still
and not covered - and says so on the step.  A control that really is disabled is still waited for."""
from __future__ import annotations

import pytest

from tests.test_failure_capture import build, click, run, step_named

pytestmark = pytest.mark.browser


def text_of(xpath: str, expected: str) -> dict:
    return {"FindBy": "xpath", "FindBy_Value": xpath, "Index": 0, "Output_Property": "innertext", "Expected_Value": expected, "Exact_Match": "Y", "Timeout": 2}


async def test_a_link_inside_an_aria_disabled_container_is_clicked_and_the_step_says_so(site, make_cfg, tmp_path):
    wb = build(tmp_path / "wb.xlsx", site, "/disabled_parent.html", [
        ("SwitchToFrame", "into the frame", {"Value": "aemFormFrame"}),
        ("Click", "click Australia", click("//a[contains(.,'Australia')]", timeout=30)),
        ("SwitchToDefault", "back to the page", {}),
        ("Output", "the link was followed", text_of("//h1[@id='second']", "Second Window")),
    ])
    result, _, _ = await run(make_cfg, wb)
    step = step_named(result, "click Australia")
    assert step.status == "PASSED" and step.duration_ms < 8000                                      # not the 30 s the browser would wait for "enabled"
    assert step.diagnosis is None and step.detail == ""
    note = " ".join(step.notes)
    assert "div#guideContainer-rootPanel.guideContainer" in note and "which contains the element" in note and "legacy runner" in note
    assert "behaviour.click_ignores_aria_disabled" in note and "visible, still and not covered" in note
    assert step_named(result, "the link was followed").status == "PASSED"                          # the click really happened


async def test_the_old_behaviour_is_one_setting_away(site, make_cfg, tmp_path):
    wb = build(tmp_path / "wb.xlsx", site, "/disabled_parent.html", [
        ("SwitchToFrame", "into the frame", {"Value": "aemFormFrame"}),
        ("Click", "click Australia", click("//a[contains(.,'Australia')]")),
    ])
    result, _, _ = await run(make_cfg, wb, **{"behaviour.click_ignores_aria_disabled": False})
    step = step_named(result, "click Australia")
    assert step.status == "FAILED" and "element is not enabled" in step.detail and not [n for n in step.notes if "aria-disabled" in n]


async def test_an_aria_disabled_link_that_is_also_covered_still_fails(site, make_cfg, tmp_path):
    """Only "enabled" is skipped: a layer over the link still stops the click (the hover that comes first finds it)."""
    wb = build(tmp_path / "wb.xlsx", site, "/disabled_covered.html", [
        ("SwitchToFrame", "into the frame", {"Value": "aemFormFrame"}),
        ("Click", "click Australia", click("//a[contains(.,'Australia')]")),
    ])
    result, _, _ = await run(make_cfg, wb)
    step = step_named(result, "click Australia")
    assert step.status == "FAILED" and "intercepts pointer events" in step.detail
    assert any("has aria-disabled" in n for n in step.notes)                                          # it says it tried
    assert "On the main page, above the frame" in " ".join(step.diagnosis["summary"])


async def test_a_control_that_really_is_disabled_is_still_waited_for(site, make_cfg, tmp_path):
    wb = build(tmp_path / "wb.xlsx", site, "/disabled_native.html", [("Click", "click Go", click("//button[@id='b']"))])
    result, _, _ = await run(make_cfg, wb)
    step = step_named(result, "click Go")
    assert step.status == "FAILED" and "element is not enabled" in step.detail and not [n for n in step.notes if "aria-disabled" in n]    # the disabled attribute is respected, aria-disabled around it or not
    assert "disabled attribute" in " ".join(step.diagnosis["summary"])


async def test_tick_click_and_context_click_go_past_it_too(site, make_cfg, tmp_path):
    wb = build(tmp_path / "wb.xlsx", site, "/disabled_controls.html", [
        ("Tick", "tick the radio", click("//input[@id='r']")),
        ("Output", "radio is checked", text_of("//span[@id='radio']", "radio checked")),
        ("Click", "click the button", click("//button[@id='self']")),
        ("Output", "button clicked", text_of("//span[@id='out']", "clicked")),
        ("ContextClick", "right-click the link", click("//a[@id='ctx']")),
        ("Output", "menu asked for", text_of("//span[@id='out']", "context menu")),
    ])
    result, _, _ = await run(make_cfg, wb)
    failed = [(s.name, s.error) for s in result.tests[0].steps if s.status != "PASSED"]
    assert not failed, failed
    assert "the element has aria-disabled" in " ".join(step_named(result, "click the button").notes)     # aria-disabled on the element itself
    assert "<div>" in " ".join(step_named(result, "tick the radio").notes)                                # ... or around it
