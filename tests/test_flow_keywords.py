"""The flow keywords on the mock site (CONTRACT.md 1.3): SET_VARIABLE, IF / ELSE / END_IF, ITERATION_START / END, CALL_TEST, JSON_READ, plus
``{DOMAIN}`` from the environment table, ``{SECRET:NAME}`` from secrets.env (masked everywhere) and a run that refuses to start when a required
environment variable is empty."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from regrunner.engine.runner import EnvironmentMissing, RunOptions, execute
from regrunner.events import EventBus
from regrunner.reporting.from_events import results_from_events
from tests.flow_books import at, book
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser

FIELD = "//input[@name='display_tripCost']"


def envs(site: str) -> list[list]:
    return [["Variable", "Required", "Secret", "QA", "UAT", "PROD"], ["DOMAIN", "Y", "", "", site, ""]]


async def run(make_cfg, wb: Path, tests: list[str]):
    cfg = make_cfg(**{"timeouts.element_s": 3, "timeouts.optional_s": 1.0})
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = await execute(RunOptions(workbook=wb, tests=tests, seed=1), cfg, bus)
    return result, events, cfg.path(cfg.runs_dir) / result.run_id


def steps(test) -> dict:
    return {s.name: s for s in test.steps}


async def test_a_variable_one_test_saves_is_typed_by_another_that_waits_for_it_even_when_listed_first(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {
        "Reader": [("Open", "open the form", {"Page": "chrome", "Value": "{DOMAIN}/form.html"}),
                   ("Set", "type the order", {**at(FIELD), "Value": "order {ORDER_ID}"}),
                   ("Output", "the field holds it", {**at(FIELD), "Output_Property": "value", "Expected_Value": "order {ORDER_ID}", "Exact_Match": "Y"})],
        "Writer": [("SET_VARIABLE", "save the order", {"Output_Value": "ORDER_ID", "Value": "O-1234"})],
    }, environments=envs(site))
    result, events, _ = await run(make_cfg, wb, ["Reader", "Writer"])
    by_id = {t.id: t for t in result.tests}
    assert by_id["Reader"].status == "PASSED" and by_id["Writer"].status == "PASSED"
    assert steps(by_id["Reader"])["the field holds it"].actual == "order O-1234"
    started = [e["test"] for e in events if e["type"] == "test_started"]
    assert started.index("Writer") < started.index("Reader")                      # the reader waited for the test that provides ORDER_ID
    (saved,) = [e for e in events if e["type"] == "variable_set"]
    assert saved["name"] == "ORDER_ID" and saved["value"] == "O-1234" and saved["cell"] == "run variable" and saved["by_hand"] is False
    assert by_id["Writer"].variables[0]["name"] == "ORDER_ID"


async def test_if_runs_only_the_side_whose_condition_holds_and_reports_the_other_side_as_skipped(make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [
        ("SET_VARIABLE", "plan", {"Output_Value": "PLAN", "Value": "Max"}),
        ("IF", "is it max", {"Value": "{PLAN} = max"}),
        ("SET_VARIABLE", "chose max", {"Output_Value": "CHOICE", "Value": "max side"}),
        ("ELSE", "", {}),
        ("SET_VARIABLE", "chose other", {"Output_Value": "CHOICE", "Value": "other side"}),
        ("END_IF", "", {}),
        ("IF", "has a promo", {"Value": "{PROMO} is filled"}),
        ("SET_VARIABLE", "promo", {"Output_Value": "USED_PROMO", "Value": "{PROMO}"}),
        ("END_IF", "", {}),
        ("SET_VARIABLE", "after", {"Output_Value": "DONE", "Value": "{CHOICE}"}),
    ]})
    result, events, run_dir = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert test.status == "PASSED", test.error
    assert [s.name for s in test.steps] == ["plan", "is it max", "chose max", "has a promo", "after"]
    assert steps(test)["after"].actual == "max side" and steps(test)["is it max"].actual == "true" and steps(test)["has a promo"].actual == "false"
    assert [(e["condition"], e["result"]) for e in events if e["type"] == "branch_taken"] == [("{PLAN} = max", True), ("{PROMO} is filled", False)]
    skipped = [e for e in events if e["type"] == "step_skipped"]
    assert [e["name"] for e in skipped] == ["chose other", "promo"] and test.skipped == 2
    assert "false" in skipped[1]["reason"]
    assert [s.name for s in results_from_events(run_dir).tests[0].steps] == [s.name for s in test.steps]


async def test_an_if_that_cannot_be_decided_fails_and_runs_neither_side(make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [
        ("IF", "compare two unknowns", {"Value": "{NOBODY} = {ALSO_NOBODY}", "Ignore_not_existing_object": "Y"}),
        ("SET_VARIABLE", "yes side", {"Output_Value": "SIDE", "Value": "yes"}),
        ("ELSE", "", {}),
        ("SET_VARIABLE", "no side", {"Output_Value": "SIDE", "Value": "no"}),
        ("END_IF", "", {}),
        ("SET_VARIABLE", "after", {"Output_Value": "DONE", "Value": "y"}),
    ]})
    result, events, _ = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert [s.name for s in test.steps] == ["compare two unknowns", "after"]
    assert test.steps[0].status == "FAILED" and "ALSO_NOBODY has no value" in test.steps[0].error
    assert [e["name"] for e in events if e["type"] == "step_skipped"] == ["yes side", "no side"]


async def test_a_loop_repeats_its_steps_once_per_enabled_data_row_reading_that_row(make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [
        ("SET_VARIABLE", "start empty", {"Output_Value": "ALL"}),
        ("ITERATION_START", "each traveller", {"Value": "Travellers"}),
        ("SET_VARIABLE", "add the name", {"Output_Value": "ALL", "Value": "{ALL}{NAME};"}),
        ("ITERATION_END", "", {}),
        ("SET_VARIABLE", "all names", {"Output_Value": "RESULT", "Value": "{ALL}"}),
    ]}, sheets={"Travellers": [["blnExecute", "Name"], ["Y", "Ann"], ["N", "Not me"], ["Y", "Bob"]]})
    result, events, _ = await run(make_cfg, wb, ["T"])
    (test,) = result.tests
    assert test.status == "PASSED", test.error
    assert [s.name for s in test.steps] == ["start empty", "each traveller", "add the name", "add the name", "all names"]
    assert [s.seq for s in test.steps] == [1, 2, 3, 4, 5] and test.total_steps == 5
    assert steps(test)["all names"].actual == "Ann;Bob;"
    assert [(e["iteration"], e["of"], e["sheet"]) for e in events if e["type"] == "iteration_started"] == [(1, 2, "Travellers"), (2, 2, "Travellers")]


async def test_call_test_runs_the_other_test_in_its_own_browser_then_carries_on_with_what_it_saved(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {
        "Caller": [("Open", "open the form", {"Page": "chrome", "Value": "{DOMAIN}/form.html"}),
                   ("CALL_TEST", "log in first", {"Value": "Login"}),
                   ("GET_CURRENT_URL", "still on my page", {"Expected_Value": "form.html", "Contains": "Y"}),
                   ("SET_VARIABLE", "use the token", {"Output_Value": "SEEN", "Value": "{TOKEN}"})],
        "Login": [("Open", "open another page", {"Page": "chrome", "Value": "{DOMAIN}/second.html"}),
                  ("SET_VARIABLE", "save the token", {"Output_Value": "TOKEN", "Value": "tok-1"})],
    }, enabled=["Caller"], environments=envs(site))
    result, events, _ = await run(make_cfg, wb, ["Caller"])
    (test,) = result.tests
    assert test.status == "PASSED", test.error
    assert steps(test)["use the token"].actual == "tok-1" and steps(test)["still on my page"].status == "PASSED"
    assert sorted(s.seq for s in test.steps) == [1, 2, 3, 4, 5, 6]
    assert {s.name: s.seq for s in test.steps}["save the token"] == 4 and "in Login (CALL_TEST)" in steps(test)["save the token"].notes
    assert [e["test"] for e in events if e["type"] == "test_started"] == ["Caller"]      # one test on the run screen
    started = next(e for e in events if e["type"] == "call_started")
    finished = next(e for e in events if e["type"] == "call_finished")
    assert started["called"] == "Login" and started["step"] == 2 and finished["status"] == "PASSED"


async def test_a_called_test_that_fails_fails_the_call_test_step(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {
        "Caller": [("CALL_TEST", "run the broken one", {"Value": "Broken", "Ignore_not_existing_object": "Y"}),
                   ("CALL_TEST", "a test that does not exist", {"Value": "Nope"})],
        "Broken": [("Open", "open", {"Page": "chrome", "Value": "{DOMAIN}/form.html"}),
                   ("Exist", "a missing element", at("//div[@id='not-there']"))],
    }, enabled=["Caller"], environments=envs(site))
    result, events, _ = await run(make_cfg, wb, ["Caller"])
    (test,) = result.tests
    assert test.status == "FAILED"
    call = steps(test)["run the broken one"]
    assert call.status == "FAILED" and "Broken ended FAILED" in call.error                 # Ignore_not_existing_object does not hide a failed call
    assert "no test 'Nope'" in steps(test)["a test that does not exist"].error
    assert next(e for e in events if e["type"] == "call_finished")["status"] == "FAILED"


async def test_json_read_reads_a_path_out_of_a_saved_response_and_checks_it(make_cfg, tmp_path):
    response = json.dumps({"policy": {"number": "P-7"}, "items": [{"id": 3}, {"id": 4}]})
    wb = book(tmp_path / "a.xlsx", {"T": [
        ("SET_VARIABLE", "the response", {"Output_Value": "RESPONSE", "Value": response}),
        ("JSON_READ", "policy number", {"Value": "{RESPONSE}", "FindBy_Value": "policy.number", "Output_Value": "POLICY",
                                        "Expected_Value": "P-7", "Exact_Match": "Y"}),
        ("JSON_READ", "second item", {"Value": "{RESPONSE}", "FindBy_Value": "items[1].id", "Expected_Value": "4", "Exact_Match": "Y"}),
        ("JSON_READ", "a path that is not there", {"Value": "{RESPONSE}", "FindBy_Value": "policy.status"}),
        ("SET_VARIABLE", "use it", {"Output_Value": "SEEN", "Value": "{POLICY}"}),
    ]})
    result, _, _ = await run(make_cfg, wb, ["T"])
    s = steps(result.tests[0])
    assert s["policy number"].status == "PASSED" and s["second item"].status == "PASSED" and s["second item"].actual == "4"
    assert s["a path that is not there"].status == "FAILED" and "policy.status" in s["a path that is not there"].error
    assert s["use it"].actual == "P-7"


async def test_a_secret_is_typed_into_the_page_but_never_appears_in_the_run_folder(site, make_cfg, tmp_path, monkeypatch):
    secret = "Hunter2-very-secret"
    monkeypatch.setenv("RR_SECRET_UAT_PASSWORD", secret)
    wb = book(tmp_path / "a.xlsx", {"T": [
        ("Open", "open the form", {"Page": "chrome", "Value": "{DOMAIN}/form.html"}),
        ("Set", "type the password", {**at(FIELD), "Value": "{SECRET:PASSWORD}"}),
        ("Output", "the field holds it", {**at(FIELD), "Output_Property": "value", "Expected_Value": "{SECRET:PASSWORD}", "Exact_Match": "Y",
                                          "Output_Value": "{COPY}"}),
        ("Output", "a wrong check shows no value", {**at(FIELD), "Output_Property": "value", "Expected_Value": "nope", "Exact_Match": "Y"}),
    ]}, environments=envs(site))
    result, events, run_dir = await run(make_cfg, wb, ["T"])
    s = steps(result.tests[0])
    assert s["type the password"].status == "PASSED" and s["the field holds it"].status == "PASSED"
    assert s["type the password"].value == "••••••" and s["the field holds it"].expected == "••••••"
    assert s["a wrong check shows no value"].status == "FAILED" and secret not in s["a wrong check shows no value"].actual
    assert secret not in json.dumps(events, ensure_ascii=False)
    for path in run_dir.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".html", ".txt", ".log"):
            assert secret not in path.read_text(encoding="utf-8", errors="ignore"), path


async def test_a_name_nobody_has_a_value_for_fails_the_step_and_nothing_is_typed(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [
        ("Open", "open the form", {"Page": "chrome", "Value": "{DOMAIN}/form.html"}),
        ("Set", "type an unknown", {**at(FIELD), "Value": "{NOBODY}", "Ignore_not_existing_object": "Y"}),
        ("Output", "the field is empty", {**at(FIELD), "Output_Property": "value"}),
    ]}, environments=envs(site))
    result, _, _ = await run(make_cfg, wb, ["T"])
    s = steps(result.tests[0])
    assert s["type an unknown"].status == "FAILED" and "variable NOBODY has no value" in s["type an unknown"].error
    assert s["the field is empty"].actual == ""


async def test_a_run_whose_environment_lacks_a_required_variable_refuses_to_start(site, make_cfg, tmp_path):
    wb = book(tmp_path / "a.xlsx", {"T": [("Open", "open", {"Page": "chrome", "Value": "{DOMAIN}/form.html"})]},
              environment="QA", environments=envs(site))
    cfg = make_cfg()
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    with pytest.raises(EnvironmentMissing) as err:
        await execute(RunOptions(workbook=wb, tests=["T"], seed=1), cfg, bus)
    assert "DOMAIN" in str(err.value) and "QA" in str(err.value)
    assert [(e["type"], e["environment"], e["variables"]) for e in events] == [("env_missing", "QA", ["DOMAIN"])]
    assert not cfg.path(cfg.runs_dir).exists() or not any(cfg.path(cfg.runs_dir).iterdir())


def test_the_web_server_refuses_a_run_whose_environment_lacks_a_required_variable(web, site):
    book(web.root / "workbooks" / "envs.xlsx", {"T": [("Open", "open", {"Page": "chrome", "Value": "{DOMAIN}/form.html"})]},
         environments=envs(site))
    with web.client() as c:
        before = c.get("/api/runs").json()
        refused = c.post("/api/runs", json={"workbook": "envs.xlsx", "all": True, "env": "QA"})
        assert refused.status_code == 422 and refused.json()["kind"] == "env_missing" and "DOMAIN" in refused.json()["error"]
        assert c.get("/api/runs").json() == before
