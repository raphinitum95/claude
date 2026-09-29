"""The recorder's plain logic (build/recorder.py, P09), no browser: variable names from labels, the check kinds an element gets and what they
are prefilled with, the step each check becomes, secrets.env writes, fingerprint names.  The browser side is tests/test_build_recording.py."""
from __future__ import annotations

import os

import pytest

from regrunner.build import recorder as R
from regrunner.workbook.builder import BuildError

TOTAL = {"tag": "span", "kind": "text", "id": "total", "classes": ["price"], "text": "Total: $1,234.50", "current": {"visible": True}}
FIELD = {"tag": "input", "kind": "field", "id": "firstName", "label": "First name", "current": {"value": "Jane", "enabled": True}}
BOX = {"tag": "input", "kind": "checkbox", "id": "offers", "type": "checkbox", "current": {"checked": True, "enabled": True}}
PLAN = {"tag": "select", "kind": "dropdown", "id": "plan", "label": "Plan", "current": {"value": "Plus", "selected": "Plus", "enabled": True}}
LOC = {"findBy": "BY_ID", "value": "total", "index": 0, "backups": ["css=span.price"]}


def by_id(kinds: list[dict]) -> dict[str, dict]:
    return {k["id"]: k for k in kinds}


def test_a_variable_name_comes_from_the_fields_label_and_never_repeats_a_column_or_the_steps_own_locator():
    assert R.token_for("First name", set()) == "FIRST_NAME"
    assert R.token_for("First name", {"FIRST_NAME", "FIRST_NAME_2"}) == "FIRST_NAME_3"
    assert R.token_for("", set(), "PASSWORD") == "PASSWORD"
    assert R.token_for("city", set(), avoid={"city"}) == "CITY_VALUE"             # a Params header CITY would replace the locator "city"
    assert R.field_label({"id": "firstName"}) == "first Name" and R.field_label({"placeholder": "DD/MM/YYYY", "id": "when"}) == "when"
    assert R.field_label({"id": "ember1234"}) == ""                                  # (a generated id is no name)


def test_a_saved_value_is_named_from_its_card_and_class_not_from_the_number_it_shows():
    assert R.save_token_for(TOTAL, set()) == "PRICE"
    assert R.save_token_for({**TOTAL, "context": {"heading": "Max"}}, set()) == "MAX_PRICE"
    assert R.save_token_for(FIELD, {"FIRST_NAME"}) == "FIRST_NAME_2"


def test_check_this_offers_what_fits_the_element_prefilled_from_the_live_page():
    text = by_id(R.check_kinds(TOTAL, similar=None))
    assert [k["id"] for k in R.check_kinds(TOTAL)] == [k for k, _, _ in R.CHECK_KINDS]
    assert text["text_is"]["expected"] == "Total: $1,234.50" and text["gt"]["expected"] == "1234.5" and text["between"]["expected"] == "1234.5;1234.5"
    assert not text["value"]["enabled"] and text["value"]["why"] == "not a field" and not text["count"]["enabled"]
    assert not text["date_format"]["enabled"] and text["regex"]["expected"] == r"^Total:\ \$\d+,\d+\.\d+$"
    field = by_id(R.check_kinds(FIELD, similar=4))
    assert field["value"]["expected"] == "Jane" and field["text_is"]["expected"] == "Jane" and field["enabled"]["expected"] == "Y"
    assert field["count"]["expected"] == "4" and not field["ticked"]["enabled"]
    assert by_id(R.check_kinds(BOX))["ticked"]["expected"] == "Y"
    assert by_id(R.check_kinds(PLAN))["selected"]["expected"] == "Plus"
    assert by_id(R.check_kinds({**TOTAL, "text": "15/03/2027"}))["date_format"]["expected"] == "dd/mm/yyyy"
    assert [k["id"] for k in R.check_kinds(TOTAL, "wait")] == ["wait_shown", "wait_gone", "wait_text"]
    assert [k["id"] for k in R.check_kinds(TOTAL, "save")] == ["save"]


@pytest.mark.parametrize("kind, expected, want", [
    ("text_is", "Total: $1,234.50", {"method": "OUTPUT", "outputProperty": "INNERTEXT", "match": "exact"}),
    ("text_contains", "1,234", {"method": "OUTPUT", "match": "contains"}),
    ("shown", "", {"method": "EXIST"}),
    ("gone", "", {"method": "NOT_EXIST"}),
    ("value", "Jane", {"method": "CHECK_VALUE", "expected": "Jane"}),
    ("ticked", "no", {"method": "CHECK_CHECKED", "expected": "N"}),
    ("selected", "Plus", {"method": "CHECK_SELECTED"}),
    ("enabled", "Y", {"method": "CHECK_ENABLED", "expected": "Y"}),
    ("gt", "1000", {"method": "CHECK_COMPARE", "outputProperty": "GT"}),
    ("lt", "2000", {"method": "CHECK_COMPARE", "outputProperty": "LT"}),
    ("between", "1000;2000", {"method": "CHECK_COMPARE", "outputProperty": "BETWEEN"}),
    ("regex", r"^REF-\d+$", {"method": "CHECK_REGEX"}),
    ("date_format", "dd/mm/yyyy", {"method": "CHECK_DATE_FORMAT"}),
    ("count", "3", {"method": "CHECK_COUNT", "locator": "li.item", "findBy": "BY_CSSSELECTOR", "backups": []}),
    ("wait_shown", "", {"method": "WAIT_UNTIL", "outputProperty": "SHOWN"}),
    ("wait_gone", "", {"method": "WAIT_UNTIL", "outputProperty": "GONE"}),
    ("wait_text", "Ready", {"method": "WAIT_UNTIL", "outputProperty": "TEXT", "match": "contains"}),
])
def test_every_check_kind_becomes_the_engines_own_step(kind, expected, want):
    fields = R.check_step(kind, TOTAL, LOC, expected, similar={"findBy": "BY_CSSSELECTOR", "value": "li.item", "matches": 3})
    assert {k: fields[k] for k in want} == want
    if kind != "count":
        assert (fields["findBy"], fields["locator"], fields["backups"]) == ("BY_ID", "total", ["css=span.price"])


def test_a_check_refuses_what_the_engine_would_refuse_and_only_text_checks_also_save():
    with pytest.raises(BuildError, match="expect"):
        R.check_step("text_is", TOTAL, LOC, " ")
    with pytest.raises(BuildError, match="not a number|number"):
        R.check_step("gt", TOTAL, LOC, "lots")
    with pytest.raises(BuildError, match="regular expression"):
        R.check_step("regex", TOTAL, LOC, "(")
    with pytest.raises(BuildError, match="date parts"):
        R.check_step("date_format", TOTAL, LOC, "soon")
    with pytest.raises(BuildError, match="Only a text check"):
        R.check_step("shown", TOTAL, LOC, "", token="SEEN")
    assert R.check_step("text_is", TOTAL, LOC, "x", token="{TOTAL_SHOWN}")["saveAs"] == "{TOTAL_SHOWN}"
    assert R.check_step("save", FIELD, LOC, "", token="FIRST")["outputProperty"] == "VALUE"
    with pytest.raises(BuildError, match="name"):
        R.check_step("save", TOTAL, LOC, "")


def test_secrets_env_gets_the_line_once_and_another_value_is_never_overwritten(tmp_path):
    path = tmp_path / "secrets.env"
    path.write_text("# mine\nRR_VAR_X=1\n", encoding="utf-8")
    key = "RR_SECRET_UAT_PW_TEST_ONLY"
    try:
        assert R.store_secret(path, key, " spaced ") == "added" and os.environ[key] == " spaced "
        assert R.store_secret(path, key, " spaced ") == "same"
        assert R.store_secret(path, key, "other") == "differs"
        assert path.read_text(encoding="utf-8") == f'# mine\nRR_VAR_X=1\n{key}=" spaced "\n'
        with pytest.raises(BuildError):
            R.store_secret(path, key + "_2", "two\nlines")
    finally:
        os.environ.pop(key, None)
        os.environ.pop("RR_VAR_X", None)


def test_a_new_pages_fingerprint_is_named_from_its_heading_and_its_path():
    assert R.fingerprint_name("Payment details", "/purchase/payment", set()) == "Payment details page"
    assert R.fingerprint_name("Payment details", "/p", {"PAYMENT DETAILS PAGE"}) == "Payment details page 2"
    assert R.fingerprint_name("", "/purchase/traveler-info/", set()) == "traveler info page"
    assert R.url_path("https://uat.example.test/purchase/payment?step=2#top") == "/purchase/payment" and R.url_path("http://x.test") == "/"
    assert R.pattern_of("REF-12345") == r"^REF\-\d+$" and R.guess_date_format("2027-03-15") == "yyyy-mm-dd" and R.guess_date_format("soon") == ""


def test_a_date_near_today_is_kept_as_days_from_today_and_a_far_one_stays_fixed():
    from datetime import date
    from regrunner.build.recorder import relative_date
    today = date(2026, 9, 29)
    assert relative_date("04/10/2026", today) == '=TEXT(TODAY()+5,"dd/mm/yyyy")'
    assert relative_date("29/09/2026", today) == '=TEXT(TODAY(),"dd/mm/yyyy")'
    assert relative_date("2026-10-04", today) == '=TEXT(TODAY()+5,"yyyy-mm-dd")'
    assert relative_date("14/03/1990", today) == "" and relative_date("not a date", today) == ""


def test_a_list_check_needs_the_list_showing_and_writes_check_list_item():
    from regrunner.build.recorder import check_kinds, check_step
    desc = {"tag": "ul", "kind": "element", "text": "Albania\nAlgeria", "current": {}}
    assert next(k for k in check_kinds(desc) if k["id"] == "list_item")["enabled"]
    step = check_step("list_item", desc, {"findBy": "BY_CSSSELECTOR", "value": "ul.results"}, "Albania")
    assert step["method"] == "CHECK_LIST_ITEM" and step["outputProperty"] == "1" and step["expected"] == "Albania"
