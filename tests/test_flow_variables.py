"""The variable side of the flow keywords, without a browser: ``{NAME}`` lookup, secrets, the environment table, IF conditions, how IF / loops
match up, what a test plans, and how Needs / Provides order the tests of a run (CONTRACT.md 1.2-1.4)."""
from __future__ import annotations

import pytest

from regrunner.engine.order import Flow, plan_order
from regrunner.preflight import environment_problem
from regrunner.workbook.model import Workbook
from regrunner.workbook.variables import VariablePool, evaluate_condition, flow_map, parse_condition, secret_value
from tests.flow_books import book

ENVS = [["Variable", "Required", "Secret", "QA", "UAT", "PROD"],
        ["DOMAIN", "Y", "", "https://qa.example", "https://uat.example", ""],
        ["API_KEY", "Y", "Y", "{SECRET:API_KEY}", "{SECRET:API_KEY}", "{SECRET:API_KEY}"],
        ["PLAN", "", "", "Basic", "", ""]]


def runtime_of(wb_path, test: str, pool: VariablePool | None = None, environment: str | None = None):
    wb = Workbook(wb_path, environment=environment)
    case = next(c for c in wb.discover() if c.id == test)
    return wb, wb.runtime(case, pool=pool)


def test_a_secret_is_looked_up_for_the_environment_first_then_for_every_environment_then_as_a_workbook_variable():
    env = {"RR_SECRET_UAT_PW": "uat-pw", "RR_SECRET_PW": "any-pw", "RR_VAR_PW": "var-pw", "RR_VAR_ONLY": "old-style"}
    assert secret_value("pw", "UAT", env) == "uat-pw"
    assert secret_value("PW", "QA", env) == "any-pw"
    assert secret_value("ONLY", "QA", env) == "old-style"
    assert secret_value("NOPE", "QA", env) is None


def test_inline_names_come_from_the_params_row_then_the_run_pool_then_the_environment_table(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("Wait", "use them", {"Value": "{FIRST} {SHARED} {DOMAIN} {PLAN}"})]},
                params={"T": [{"FIRST": "Ann", "PLAN": ""}]}, environment="QA", environments=ENVS)
    pool = VariablePool()
    pool.set("shared", "from-another-test")
    pool.set("FIRST", "loses to the Params row")
    _, rt = runtime_of(path, "T", pool)
    step = rt.prepare_row(2)
    assert step.text("VALUE") == "Ann from-another-test https://qa.example Basic"
    assert step.missing_vars == [] and step.blank_params == []


def test_a_name_nobody_gives_a_value_is_missing_and_stays_as_written(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("Set", "type it", {"Value": "hello {NOBODY}", "FindBy": "id", "FindBy_Value": "x"})]})
    _, rt = runtime_of(path, "T")
    step = rt.prepare_row(2)
    assert step.missing_vars == ["NOBODY"] and step.text("VALUE") == "hello {NOBODY}"


def test_an_empty_params_column_with_no_other_value_is_a_blank_parameter_a_person_can_be_asked_for(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("Wait", "use it", {"Value": "{CODE}"})]}, params={"T": [{"CODE": None}]})
    _, rt = runtime_of(path, "T")
    step = rt.prepare_row(2)
    assert step.blank_params == [("VALUE", "CODE")] and step.missing_vars == []


def test_sendkeys_key_names_stay_keys_and_template_placeholders_are_reported(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("SendKeys", "keys", {"Value": "{TAB}{ENTER}", "FindBy": "id", "FindBy_Value": "x"}),
                                            ("Set", "unmapped", {"Value": "{?FIRST_NAME}", "FindBy": "id", "FindBy_Value": "x"})]})
    _, rt = runtime_of(path, "T")
    keys, unmapped = rt.prepare_row(2), rt.prepare_row(3)
    assert keys.text("VALUE") == "{TAB}{ENTER}" and keys.missing_vars == []
    assert unmapped.unmapped == ["FIRST_NAME"]


def test_a_secret_put_into_a_cell_marks_the_column_secret_and_joins_the_values_to_mask(tmp_path, monkeypatch):
    monkeypatch.setenv("RR_SECRET_UAT_PASSWORD", "hunter2-uat")
    path = book(tmp_path / "a.xlsx", {"T": [("Set", "password", {"Value": "{SECRET:PASSWORD}", "FindBy": "id", "FindBy_Value": "pw"}),
                                            ("Wait", "api key via the environment", {"Value": "{API_KEY}"})]},
                environments=ENVS)
    monkeypatch.setenv("RR_SECRET_API_KEY", "key-12345")
    _, rt = runtime_of(path, "T")
    pw, key = rt.prepare_row(2), rt.prepare_row(3)
    assert pw.text("VALUE") == "hunter2-uat" and "VALUE" in pw.secret_columns
    assert key.text("VALUE") == "key-12345" and "VALUE" in key.secret_columns
    assert {"hunter2-uat", "key-12345"} <= rt.secret_values


def test_a_required_environment_variable_that_is_empty_refuses_the_run_and_names_it_without_values(tmp_path, monkeypatch):
    monkeypatch.delenv("RR_SECRET_API_KEY", raising=False)
    monkeypatch.delenv("RR_VAR_API_KEY", raising=False)
    path = book(tmp_path / "a.xlsx", {"T": [("Wait", "w", {"Value": "1"})]}, environments=ENVS)
    wb = Workbook(path)
    message, missing = environment_problem(wb, "PROD")
    assert missing == ["DOMAIN", "API_KEY"] and "PROD" in message and "DOMAIN" in message
    assert environment_problem(wb, "UAT")[1] == ["API_KEY"]                          # a secret that is not in secrets.env counts as empty
    monkeypatch.setenv("RR_SECRET_API_KEY", "k-1")
    assert environment_problem(wb, "UAT") == ("", [])
    assert "k-1" not in environment_problem(wb, "PROD")[0]


def test_a_workbook_without_an_environment_table_never_refuses_a_run(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("Wait", "w", {"Value": "1"})]})
    assert environment_problem(Workbook(path), "PROD") == ("", [])


@pytest.mark.parametrize("text, values, expected", [
    ("{A} is filled", {"A": "x"}, True),
    ("{A} is filled", {"A": "  "}, False),
    ("{A} is empty", {}, True),
    ("{A} = max", {"A": "Max"}, True),
    ("{A} != Max", {"A": "Max"}, False),
    ("{A} contains ASIC", {"A": "Basic plan"}, True),
    ("{A} > 3", {"A": "10"}, True),
    ("{A} <= 3", {"A": "3"}, True),
    ("{A} = {B}", {"A": "same", "B": "SAME"}, True),
])
def test_an_if_condition_compares_variables_as_text_ignoring_case_and_numbers_as_numbers(text, values, expected):
    assert evaluate_condition(parse_condition(text), lambda n: values.get(n.upper())) is expected


def test_an_if_that_cannot_compare_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        evaluate_condition(parse_condition("{A} > 3"), lambda n: "lots")
    with pytest.raises(ValueError):
        evaluate_condition(parse_condition("{A} = {B}"), lambda n: "x" if n == "A" else None)
    with pytest.raises(ValueError):
        parse_condition("A is filled")


def test_if_else_and_loops_are_matched_up_and_a_missing_end_is_reported():
    fm = flow_map({2: "IF", 4: "ELSE", 6: "END_IF", 7: "ITERATION_START", 8: "IF", 9: "END_IF", 10: "ITERATION_END"})
    assert fm.else_of == {2: 4} and fm.end_of == {2: 6, 4: 6, 8: 9, 7: 10} and fm.start_of == {10: 7} and not fm.errors
    assert flow_map({2: "IF", 3: "ITERATION_END"}).errors
    assert "no END_IF" in flow_map({2: "IF"}).errors[0]


def test_a_test_whose_if_has_no_end_if_cannot_run_and_says_why(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("IF", "if", {"Value": "{A} is filled"}), ("Wait", "w", {"Value": "1"})]})
    _, rt = runtime_of(path, "T")
    assert "no END_IF" in rt.blocked_reason and rt.plan() == []


def test_a_plan_repeats_a_loops_steps_per_data_row_and_leaves_out_else_and_end_rows(tmp_path):
    rows = [("ITERATION_START", "each traveller", {"Value": "Travellers"}),
            ("Wait", "use the row", {"Value": "{NAME}"}),
            ("ITERATION_END", "", {}),
            ("IF", "has a promo", {"Value": "{PROMO} is filled"}),
            ("Wait", "promo", {"Value": "1"}),
            ("ELSE", "", {}),
            ("Wait", "no promo", {"Value": "1"}),
            ("END_IF", "", {})]
    path = book(tmp_path / "a.xlsx", {"T": rows},
                sheets={"Travellers": [["blnExecute", "Name"], ["Y", "Ann"], ["N", "Skipped"], ["Y", "Bob"]]})
    _, rt = runtime_of(path, "T")
    assert [(r, m) for r, _, m in rt.plan()] == [(2, "ITERATION_START"), (3, "WAIT"), (3, "WAIT"), (5, "IF"), (6, "WAIT"), (8, "WAIT")]
    assert rt.pool_reads == {"PROMO"}                                         # NAME comes from the loop's data sheet, PROMO from another test


def test_output_value_names_a_variable_when_it_is_braced_a_params_column_or_the_step_is_there_to_save(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("Output", "braced", {"Output_Value": "{ORDER}"}),
                                            ("Output", "params column", {"Output_Value": "DT_OUT"}),
                                            ("SET_VARIABLE", "set", {"Output_Value": "PLAN", "Value": "Max"}),
                                            ("Wait", "a literal to compare with", {"Output_Value": "PASSED"})]},
                params={"T": [{"DT_OUT": None}]})
    _, rt = runtime_of(path, "T")
    assert [rt.prepare_row(r).output_name for r in (2, 3, 4, 5)] == ["ORDER", "DT_OUT", "PLAN", ""]


def test_set_variable_replaces_the_value_and_lands_in_the_pool_and_the_params_cell(tmp_path):
    path = book(tmp_path / "a.xlsx", {"T": [("SET_VARIABLE", "set", {"Output_Value": "DT_OUT", "Value": "one"}),
                                            ("SET_VARIABLE", "again", {"Output_Value": "{DT_OUT}", "Value": "two"}),
                                            ("SET_VARIABLE", "pool only", {"Output_Value": "ORDER_ID", "Value": "O-1"})]},
                params={"T": [{"DT_OUT": None}]})
    pool = VariablePool()
    _, rt = runtime_of(path, "T", pool)
    for row, value in ((2, "one"), (3, "two"), (4, "O-1")):
        sets = rt.record(rt.prepare_row(row), "PASSED", "", value)
    assert rt.params["DT_OUT"] == "two" and pool.get("DT_OUT") == "two"             # replaced, not "one;two"
    assert sets == [{"name": "ORDER_ID", "value": "O-1", "stored": "O-1", "cell": "run variable"}] and pool.get("order_id") == "O-1"


def flow(id_: str, index: int, needs=(), provides=(), calls=()) -> Flow:
    return Flow(id=id_, index=index, sheet=id_, needs=set(needs), provides=set(provides), calls=list(calls))


def test_a_test_that_needs_a_variable_waits_for_the_test_that_provides_it_even_when_listed_first():
    flows = [flow("View", 0, needs={"ORDER_ID"}), flow("Buy", 1, provides={"ORDER_ID"}), flow("Other", 2)]
    order = plan_order(flows, ["View", "Buy", "Other"])
    assert order.deps["View"] == ["Buy"] and order.deps["Buy"] == [] and order.data["View"] == {"ORDER_ID": ["Buy"]}
    assert any(n["kind"] == "waits" and "{ORDER_ID}" in n["message"] for n in order.notes)


def test_an_earlier_provider_is_preferred_and_what_a_called_test_saves_counts_for_its_caller():
    flows = [flow("Login", 0, provides={"TOKEN"}), flow("Setup", 1, calls=["Login"]), flow("Use", 2, needs={"TOKEN"}), flow("Late", 3, provides={"TOKEN"})]
    order = plan_order(flows, ["Setup", "Use", "Late"])
    assert order.deps["Use"] == ["Setup"]


def test_a_needed_variable_nothing_in_the_run_provides_is_said_before_the_run():
    flows = [flow("View", 0, needs={"ORDER_ID"}), flow("Buy", 1, provides={"ORDER_ID"})]
    order = plan_order(flows, ["View"])
    (note,) = [n for n in order.notes if n["kind"] == "missing"]
    assert note["available"] == ["Buy"] and order.deps["View"] == []


def test_needs_and_provides_come_from_the_dry_run_of_each_test(tmp_path):
    path = book(tmp_path / "a.xlsx", {
        "View": [("Wait", "use it", {"Value": "{ORDER_ID}"})],
        "Buy": [("SET_VARIABLE", "save it", {"Output_Value": "ORDER_ID", "Value": "O-9"})],
    })
    wb = Workbook(path)
    flows = []
    for i, case in enumerate(wb.discover()):
        rt = wb.runtime(case)
        rt.plan()
        flows.append(Flow.of(case, i, rt))
    assert flows[0].needs == {"ORDER_ID"} and flows[1].provides == {"ORDER_ID"}
    assert plan_order(flows, ["View", "Buy"]).deps["View"] == ["Buy"]
