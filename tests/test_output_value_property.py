"""Output_Property = value: what a field holds right now (text field, textarea, select, radio group, check box), and `attribute` reading the live
property like Selenium's getAttribute did (a typed-into field's value, not the HTML attribute it started with)."""
from __future__ import annotations

from pathlib import Path

import pytest

from regrunner.lint import lint
from regrunner.workbook import Workbook
from tests.test_click_and_window_rules import at, build, run

pytestmark = pytest.mark.browser


def out(name: str, xpath: str, prop: str, value: str = "", **extra) -> tuple[str, str, dict]:
    cols = {**at(xpath), "Output_Property": prop, **extra}
    if value:
        cols["Value"] = value
    return "Output", name, cols


ROWS = [
    ("Set", "type text", {**at("//input[@id='txt']"), "Value": "hello"}),
    ("Set", "type textarea", {**at("//textarea[@id='ta']"), "Value": "some notes"}),
    ("Select", "pick an amount", {**at("//select[@name='aoad-options']"), "Value": "$1,000,000"}),
    ("JS_Click", "pick No", at("//input[@name='yn' and @value='No']")),
    ("Tick", "tick the box", at("//input[@id='cb']")),
    out("text field", "//input[@id='txt']", "value"),
    out("textarea", "//textarea[@id='ta']", "value"),
    out("select", "//select[@name='aoad-options']", "value"),
    out("radio group via the first button", "//input[@name='yn' and @value='Yes']", "value"),
    out("radio group via the checked button", "//input[@name='yn' and @value='No']", "value"),
    out("checkbox", "//input[@id='cb']", "value"),
    out("attribute value of the typed field", "//input[@id='txt']", "attribute", "value"),
    out("attribute value of the textarea", "//textarea[@id='ta']", "attribute", "value"),
    out("attribute checked", "//input[@id='cb']", "attribute", "checked"),
    out("attribute href", "//a[@id='lnk']", "attribute", "href"),
    out("attribute data-", "//option[@data-cmp-claimantid='3']", "attribute", "data-cmp-claimantid"),
    # the Travelkore flaw: the option's label is the same whether or not it is selected
    out("option label, first option", "//option[@data-cmp-claimantid='1']", "innertext", Expected_Value="$100,000", Exact_Match="Y"),
    # what the row should check
    out("selected amount is right", "//select[@name='aoad-options']", "value", Expected_Value="$1,000,000", Exact_Match="Y"),
    out("selected amount is wrong", "//select[@name='aoad-options']", "value", Expected_Value="$100,000", Exact_Match="Y"),
]


async def test_value_reads_what_a_person_would_say_the_field_holds(site, make_cfg, tmp_path):
    test, _ = await run(make_cfg, build(tmp_path / "a.xlsx", site, "fields.html", ROWS), **{"output.match_timeout_s": 1})
    steps = {s.name: s for s in test.steps}
    assert steps["text field"].actual == "hello" and steps["textarea"].actual == "some notes"
    assert steps["select"].actual == "$1,000,000"                                      # the selected option's text, not its value attribute
    assert steps["radio group via the first button"].actual == "No"                    # the checked button of the group, whichever button was asked
    assert steps["radio group via the checked button"].actual == "No"
    assert steps["checkbox"].actual == "true"
    assert steps["selected amount is right"].status == "PASSED"
    assert steps["selected amount is wrong"].status == "FAILED" and steps["selected amount is wrong"].actual == "$1,000,000"


async def test_attribute_is_the_live_property_like_selenium(site, make_cfg, tmp_path):
    test, _ = await run(make_cfg, build(tmp_path / "a.xlsx", site, "fields.html", ROWS))
    steps = {s.name: s for s in test.steps}
    assert steps["attribute value of the typed field"].actual == "hello"               # not the HTML attribute the field started with ("initial")
    assert steps["attribute value of the textarea"].actual == "some notes"             # a textarea has no such attribute at all
    assert steps["attribute checked"].actual == "true"
    assert steps["attribute href"].actual.endswith("/second.html") and steps["attribute href"].actual.startswith("http")     # Selenium: the full URL
    assert steps["attribute data-"].actual == "3"                                      # no such property: the attribute


async def test_reading_an_option_label_says_it_cannot_show_the_selection(site, make_cfg, tmp_path):
    test, _ = await run(make_cfg, build(tmp_path / "a.xlsx", site, "fields.html", ROWS))
    step = {s.name: s for s in test.steps}["option label, first option"]
    assert step.status == "PASSED" and any("same whether or not it is selected" in n for n in step.notes)      # the flaw, made visible


def test_lint_flags_a_check_on_an_option_label(site, tmp_path):
    wb = Workbook(build(tmp_path / "a.xlsx", site, "fields.html", ROWS), seed=1)
    said = [f.message for f in lint(wb) if f.severity == "warning" and "innerText of an <option>" in f.message]
    assert len(said) == 1 and "Output_Property = value" in said[0]
