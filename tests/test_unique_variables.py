"""Unique variables (brief: dev/claude/CONTEXT_unique_variables.md): ``{NAME#2}`` is copy number 2 of a variable marked Unique in
``_rr_variables`` - its base value plus random characters, made by the first step that types it and the same value for every step and test
of the run after that.  A check only reads a copy (and fails when the run never made it); ``#first`` / ``#last`` read the lowest / highest
copy made so far.  Most of this needs no browser; the last test runs two tests of one run against the mock site."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from regrunner.engine.order import Flow, plan_order
from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from regrunner.workbook.model import Workbook
from regrunner.workbook.variables import VariablePool, default_unique_format, unique_spec
from tests.flow_books import at, book

FIELD = "//input[@name='display_tripCost']"
VARIABLES = [["Token", "Label", "Secret", "EnvSpecific", "Notes", "Unique", "UniqueBase", "UniqueFormat", "UniqueLength"],
             ["LASTNAME", "Last name", "", "", "", "Y", "qalast", "", ""],
             ["REF", "Reference", "", "", "", "Y", "", "digits", "4"],
             ["PLAIN", "Not unique", "", "", "", "", "", "", ""]]


def runtime_of(wb_path: Path, test: str, pool: VariablePool | None = None):
    wb = Workbook(wb_path)
    case = next(c for c in wb.discover() if c.id == test)
    return wb.runtime(case, pool=pool)


def a_book(tmp_path: Path, tests: dict, **kw) -> Path:
    return book(tmp_path / "u.xlsx", tests, sheets={"_rr_variables": VARIABLES}, **kw)


def test_a_typing_step_makes_the_copy_from_the_base_value_and_every_later_step_gets_the_same_one(tmp_path):
    path = a_book(tmp_path, {"T": [("Set", "traveller 2", {**at(FIELD), "Value": "{LASTNAME#2}"}),
                                   ("Set", "traveller 2 again", {**at(FIELD), "Value": "{lastname#2}"})]})
    pool = VariablePool()
    rt = runtime_of(path, "T", pool)
    first, again = rt.prepare_row(2), rt.prepare_row(3)
    made = first.text("VALUE")
    assert re.fullmatch(r"qalast[a-z]{8}", made)                       # letters only: LASTNAME looks like a name
    assert first.made_copies == [{"name": "LASTNAME#2", "value": made}] and first.copy_makes == ["LASTNAME#2"]
    assert again.text("VALUE") == made and again.made_copies == []      # made once, then reused
    assert pool.copy("LASTNAME", 2) == made and pool.copy_made_by[("LASTNAME", 2)] == "T"


def test_a_new_run_makes_new_values(tmp_path):
    path = a_book(tmp_path, {"T": [("Set", "type it", {**at(FIELD), "Value": "{LASTNAME#1}"})]})
    one = runtime_of(path, "T", VariablePool()).prepare_row(2).text("VALUE")
    two = runtime_of(path, "T", VariablePool()).prepare_row(2).text("VALUE")
    assert one != two and one.startswith("qalast") and two.startswith("qalast")


def test_without_a_base_of_its_own_a_copy_starts_with_the_variables_value_for_the_test(tmp_path):
    variables = [VARIABLES[0], ["FIRSTNAME", "", "", "", "", "Y", "", "", "6"]]
    path = book(tmp_path / "u.xlsx", {"T": [("Set", "type it", {**at(FIELD), "Value": "{FIRSTNAME#1}"})]},
                params={"T": [{"FIRSTNAME": "qafirst"}]}, sheets={"_rr_variables": variables})
    assert re.fullmatch(r"qafirst[a-z]{6}", runtime_of(path, "T").prepare_row(2).text("VALUE"))


def test_the_format_and_length_say_what_the_random_part_is_made_of():
    assert default_unique_format("LASTNAME") == "letters" and default_unique_format("FIRST_NAME") == "letters"
    assert default_unique_format("EMAIL_PREFIX") == "mixed"
    assert re.fullmatch(r"x\d{4}", unique_spec("REF", "", "digits", "4").make("x"))
    assert re.fullmatch(r"[a-z0-9]{8}", unique_spec("CODE").make(""))
    assert unique_spec("CODE", fmt="nonsense", length="999").length == 64


def test_a_check_only_reads_a_copy_and_says_plainly_when_the_run_never_made_it(tmp_path):
    path = a_book(tmp_path, {"T": [("Output", "shows traveller 2", {**at(FIELD), "Output_Property": "value", "Expected_Value": "{LASTNAME#2}",
                                                                    "Exact_Match": "Y"}),
                                   ("CHECK_VALUE", "check by value", {**at(FIELD), "Value": "{LASTNAME#2}"})]})
    pool = VariablePool()
    rt = runtime_of(path, "T", pool)
    check, other = rt.prepare_row(2), rt.prepare_row(3)
    assert check.copy_problems == ["LASTNAME #2 was never created in this run"] and check.made_copies == []
    assert other.copy_problems == ["LASTNAME #2 was never created in this run"]          # (a CHECK_ step's Value is what it compares with)
    assert pool.copy("LASTNAME", 2) is None and check.copy_reads == ["LASTNAME#2"]


def test_first_and_last_read_the_lowest_and_highest_copy_made_so_far_even_with_gaps(tmp_path):
    path = a_book(tmp_path, {"T": [("Output", "first", {**at(FIELD), "Expected_Value": "{LASTNAME#first}"}),
                                   ("Set", "type last", {**at(FIELD), "Value": "{LASTNAME#last}"})]})
    pool = VariablePool()
    rt = runtime_of(path, "T", pool)
    assert rt.prepare_row(2).copy_problems == ["no LASTNAME was created in this run, so there is no first one"]
    pool.make_copy("LASTNAME", 1, lambda: "qalastone")
    pool.make_copy("LASTNAME", 3, lambda: "qalastthree")                 # (#2 was deleted from the steps: the numbers keep their gap)
    assert rt.prepare_row(2).values["EXPECTED_VALUE"] == "qalastone"
    typed = rt.prepare_row(3)
    assert typed.text("VALUE") == "qalastthree" and typed.made_copies == []   # "last" never makes a copy, even in a typing step


def test_a_number_on_a_variable_that_is_not_unique_is_an_error_not_a_guess(tmp_path):
    path = a_book(tmp_path, {"T": [("Set", "type it", {**at(FIELD), "Value": "{PLAIN#1}"})]}, params={"T": [{"PLAIN": "x"}]})
    step = runtime_of(path, "T").prepare_row(2)
    assert step.text("VALUE") == "{PLAIN#1}" and "PLAIN is not a unique variable" in step.copy_problems[0]


def test_a_check_of_a_copy_waits_for_the_test_that_makes_it_and_first_or_last_waits_for_every_maker(tmp_path):
    path = a_book(tmp_path, {
        "Check": [("Output", "shows traveller 1", {**at(FIELD), "Expected_Value": "{LASTNAME#1}"}),
                  ("Output", "shows the last one", {**at(FIELD), "Expected_Value": "{LASTNAME#last}"})],
        "Buy": [("Set", "traveller 1", {**at(FIELD), "Value": "{LASTNAME#1}"}), ("Set", "traveller 2", {**at(FIELD), "Value": "{LASTNAME#2}"})],
        "Self": [("Set", "makes its own", {**at(FIELD), "Value": "{LASTNAME#3}"}), ("Output", "reads it", {**at(FIELD), "Expected_Value": "{LASTNAME#last}"})],
    })
    wb = Workbook(path)
    flows = []
    for i, case in enumerate(wb.discover()):
        rt = wb.runtime(case)
        rt.plan()
        flows.append(Flow.of(case, i, rt))
    by_id = {f.id: f for f in flows}
    assert by_id["Check"].needs == {"LASTNAME#1", "LASTNAME#*"}
    assert by_id["Buy"].provides == {"LASTNAME#1", "LASTNAME#2", "LASTNAME#*"} and by_id["Buy"].needs == set()
    assert by_id["Self"].needs == set()                                  # it made a copy before it reads the last one
    order = plan_order(flows, ["Check", "Buy"])
    assert order.deps["Check"] == ["Buy"]
    assert any("a copy of {LASTNAME}" in n["message"] for n in order.notes)


def test_an_api_request_reads_the_copies_a_ui_test_made_and_never_makes_one(tmp_path):
    path = a_book(tmp_path, {"T": [("Wait", "nothing", {"Value": "1"})]})
    wb = Workbook(path)
    pool = VariablePool()
    pool.make_copy("LASTNAME", 1, lambda: "qalastabc")
    from regrunner.workbook.api import ApiRuntime
    rt = wb.runtime(next(iter(wb.discover())), pool=pool)
    api = ApiRuntime(rt.book, rt.case, {}, {}, pool=pool, unique=wb.unique_variables())
    filled = api.fill("/policies?surname={LASTNAME#1}&other={LASTNAME#2}")
    assert filled.text == "/policies?surname=qalastabc&other={LASTNAME#2}" and filled.missing == ["LASTNAME#2"]
    assert pool.copy("LASTNAME", 2) is None


@pytest.mark.browser
async def test_one_test_makes_the_copies_and_another_types_and_checks_them_in_the_same_run(site, make_cfg, tmp_path):
    envs = [["Variable", "Required", "Secret", "QA", "UAT", "PROD"], ["DOMAIN", "Y", "", "", site, ""]]
    wb = a_book(tmp_path, {
        "Check": [("Open", "open the form", {"Page": "chrome", "Value": "{DOMAIN}/form.html"}),
                  ("Set", "type traveller 1", {**at(FIELD), "Value": "{TRAVELLER_1}"}),
                  ("Output", "shows the first", {**at(FIELD), "Output_Property": "value", "Expected_Value": "{LASTNAME#first}", "Exact_Match": "Y"}),
                  ("Set", "type traveller 2", {**at(FIELD), "Value": "{LASTNAME#2}"}),
                  ("Output", "shows the last", {**at(FIELD), "Output_Property": "value", "Expected_Value": "{LASTNAME#last}", "Exact_Match": "Y"}),
                  ("Output", "a copy nobody made", {**at(FIELD), "Output_Property": "value", "Expected_Value": "{LASTNAME#5}", "Exact_Match": "Y"})],
        "Make": [("SET_VARIABLE", "traveller 1", {"Output_Value": "TRAVELLER_1", "Value": "{LASTNAME#1}"}),
                 ("SET_VARIABLE", "traveller 2", {"Output_Value": "TRAVELLER_2", "Value": "{LASTNAME#2}"})],
    }, environments=envs)
    cfg = make_cfg(**{"timeouts.element_s": 3, "timeouts.optional_s": 1.0})
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = await execute(RunOptions(workbook=wb, tests=["Check", "Make"], seed=1, environment="UAT"), cfg, bus)
    by_id = {t.id: t for t in result.tests}
    s = {x.name: x for x in by_id["Check"].steps}
    made = {e["name"]: e["value"] for e in events if e["type"] == "variable_set" and e["cell"] == "unique copy"}
    assert set(made) == {"LASTNAME#1", "LASTNAME#2"} and all(re.fullmatch(r"qalast[a-z]{8}", v) for v in made.values())
    assert s["shows the first"].status == "PASSED" and s["shows the first"].actual == made["LASTNAME#1"]
    assert s["type traveller 2"].value == made["LASTNAME#2"] and not any("made" in n for n in s["type traveller 2"].notes)
    assert s["shows the last"].status == "PASSED" and s["shows the last"].actual == made["LASTNAME#2"]
    assert s["a copy nobody made"].status == "FAILED" and "LASTNAME #5 was never created in this run" in s["a copy nobody made"].error
    started = [e["test"] for e in events if e["type"] == "test_started"]
    assert started.index("Make") < started.index("Check")


# -- the Workbook Builder's side: the settings, the numbers a workbook uses, rename, problems ---------------------------------------------------
def test_make_unique_is_a_setting_of_the_variable_and_the_model_lists_the_copy_numbers_the_workbook_uses(tmp_path):
    from regrunner.workbook.builder import BuildDocument, BuildError
    path = book(tmp_path / "b.xlsx", {
        "Buy": [("Set", "traveller 1", {**at(FIELD), "Value": "{LASTNAME#1}"}), ("Set", "traveller 4", {**at(FIELD), "Value": "{LASTNAME#4}"}),
                ("Output", "the last one", {**at(FIELD), "Expected_Value": "{LASTNAME#last}"}),
                ("Output", "traveller 3", {**at(FIELD), "Expected_Value": "{LASTNAME#3}"})]},
        params={"Buy": [{"LASTNAME": "qalast"}]})
    doc = BuildDocument(path)
    kinds = lambda: {(p["kind"], p["row"]) for p in doc.model()["problems"] if p["kind"] in ("not_unique_variable", "copy_never_made")}
    assert kinds() == {("not_unique_variable", 2), ("not_unique_variable", 3), ("not_unique_variable", 4), ("not_unique_variable", 5)}
    doc.apply([{"op": "set_variable", "token": "LASTNAME", "unique": True, "uniqueFormat": "letters", "uniqueLength": 6}])
    v = next(v for v in doc.model()["variables"] if v["key"] == "LASTNAME")
    assert v["unique"] == {"base": "", "format": "letters", "length": 6}
    assert v["copies"] == [1, 3, 4] and v["copiesMade"] == [1, 4]                         # gaps stay gaps; #3 is only checked
    assert {u.get("copy") for u in v["usedBy"]} == {"1", "4", "last", "3"}
    assert kinds() == {("copy_never_made", 5)}                                            # a check of #3, which nothing types
    with pytest.raises(BuildError, match="letters, mixed"):
        doc.apply([{"op": "set_variable", "token": "LASTNAME", "uniqueFormat": "emoji"}])
    doc.apply([{"op": "set_variable", "token": "LASTNAME", "unique": False}])
    assert next(v for v in doc.model()["variables"] if v["key"] == "LASTNAME")["unique"] is None


def test_a_rename_carries_the_copy_numbers_along(tmp_path):
    from regrunner.workbook.builder import BuildDocument
    path = book(tmp_path / "b.xlsx", {"Buy": [("Set", "t2", {**at(FIELD), "Value": "{LASTNAME#2}"}),
                                              ("Output", "last", {**at(FIELD), "Expected_Value": "Name: {lastname#last}"})]},
                sheets={"_rr_variables": VARIABLES})
    doc = BuildDocument(path)
    doc.apply([{"op": "rename_variable", "from": "LASTNAME", "to": "SURNAME"}])
    steps = next(t for t in doc.model()["tests"] if t["id"] == "Buy")["steps"]
    assert [s["value"] for s in steps][0] == "{SURNAME#2}" and steps[1]["expected"] == "Name: {SURNAME#last}"
    assert next(v for v in doc.model()["variables"] if v["key"] == "SURNAME")["unique"]["base"] == "qalast"


def test_a_check_card_offers_first_last_and_each_number_but_pins_a_lone_copy_and_says_so():
    from regrunner.build.recorder import unique_read_choices
    several = {"token": "LASTNAME", "label": "Last name", "copies": [1, 2, 4], "copiesMade": [1, 2]}
    assert [c["token"] for c in unique_read_choices(several)] == ["LASTNAME#first", "LASTNAME#last", "LASTNAME#1", "LASTNAME#2", "LASTNAME#4"]
    assert unique_read_choices(several)[-1]["warn"] == "No step types {LASTNAME#4}: this check fails."
    (lone,) = unique_read_choices({"token": "LASTNAME", "label": "Last name", "copies": [3], "copiesMade": [3]})
    assert lone["token"] == "LASTNAME#3" and lone["warn"] == "Only one Last name exists, so this uses #3. If more get added later, it stays on #3."
    (none,) = unique_read_choices({"token": "LASTNAME", "label": "Last name", "copies": [], "copiesMade": []})
    assert none["token"] == "LASTNAME#1" and "No step makes a Last name yet" in none["warn"]
