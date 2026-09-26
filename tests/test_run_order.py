"""Tests that depend on each other: a test that reads a parameter another test of the run sets waits for it (data), chains fix an order by hand, and
streams with nothing in common still run side by side."""
from __future__ import annotations

import asyncio
from pathlib import Path

import openpyxl
import pytest

from regrunner.config import Config
from regrunner.engine.order import analyse, chains_file, clean_chains, load_chains, plan_order, save_chains
from regrunner.engine.runner import RunOptions, execute
from regrunner.engine.schedule import Schedule
from regrunner.events import EventBus
from regrunner.workbook import Workbook
from tests.workbook_factory import Sheet


def build(path: Path, site: str, *, buy_fails_in_row: int | None = None) -> Path:
    """Sheets, in DataSheets order: Buy (sets DT_Policy_Out = its DT_Tag), Cancel and View (both type DT_Policy_Out into the code field and capture the
    echo).  Two parameter rows, so two streams: Buy#1 / Cancel#1 / View#1 with tag A, Buy#2 / Cancel#2 / View#2 with tag B."""
    wb = openpyxl.Workbook()
    ds = wb.active
    ds.title = "DataSheets"
    ds.append(["SheetsToExecute", "blnExecute", "ParameterSheet", "Comments"])
    for name in ("Buy", "Cancel", "View"):
        ds.append([name, "Y", "Params_1", name])
    g = wb.create_sheet("Global")
    g.append(["Parameter", "Value"])
    g.append(["Environment", "UAT"])
    ps = wb.create_sheet("Params_1")
    ps.append(["blnExecute", "DT_URL", "DT_Tag", "DT_Policy_Out"])
    for tag in ("A", "B"):
        ps.append(["Y", f"{site}ask.html", tag, None])
    buy = Sheet(wb.create_sheet("Buy"), "Y")
    buy.add("Open", "Open", Page="chrome", Value="DT_URL")
    buy.add("Set", "Type the tag", FindBy="xpath", FindBy_Value="//input[@id='code']", Index=0, Value="DT_Tag")
    buy.add("Output", "Get Policy Number", FindBy="xpath",
            FindBy_Value="//span[@id='echo']" if buy_fails_in_row is None else "//span[@id='does-not-exist']", Index=0,
            Output_Property="innertext", Output_Value="DT_Policy_Out")
    for name in ("Cancel", "View"):
        sheet = Sheet(wb.create_sheet(name), "Y")
        sheet.add("Open", "Open", Page="chrome", Value="DT_URL")
        sheet.add("Set", "Enter Policy Number", FindBy="xpath", FindBy_Value="//input[@id='code']", Index=0, Value="DT_Policy_Out")
        sheet.add("Output", "What the field holds", FindBy="xpath", FindBy_Value="//span[@id='echo']", Index=0, Output_Property="innertext")
    wb.save(path)
    return path


def build_with_api(path: Path, site: str, **kw) -> Path:
    """The same workbook plus an API sheet ``Policy`` (two rows): its URL is the base URL from the Global table + policyNumber_IN, and policyNumber_IN is
    ``=Params_1!D2`` / ``=Params_1!D3`` - the DT_Policy_Out cell of each stream, which Buy fills in (the real PolicySearch does the same with =AgentPortal_Params!R3)."""
    build(path, site, **kw)
    wb = openpyxl.load_workbook(path)
    wb["DataSheets"].append(["Policy", "Y", None, "Policy API"])
    g = wb["Global"]
    for r, values in enumerate([("Env", "URL", "API"), ("QA", "http://qa.invalid/", "http://qa.invalid/api/"), ("UAT", site, site + "policy/v4/")], start=1):
        for c, value in enumerate(values, start=5):
            g.cell(r, c, value)
    io = wb.create_sheet("InputOutput")
    for row in [("Function", "Parameter", "Value"), ("addHeader", "Authorization", "DT_bearerToken"), ("addHeader", "apiKey", "DT_apiKey"),
                ("OUTPUT_Contract", None, None), ("output_json", "transactionStatus", "transactionStatus_OUT"),
                ("COMPARE_Contract", None, None), ("compare", "transactionStatus_EXP", "transactionStatus_OUT")]:
        io.append(list(row))
    ws = wb.create_sheet("Policy")
    ws.append(["blnExecute", "TCID", "TC_Name", "WEBSERVICE_URL", "JSON_FORMAT", "WEBSERVICE_METHOD", "DT_apiKey", "DT_bearerToken", "policyNumber_IN",
               "transactionStatus_EXP", "transactionStatus_OUT"])
    for n, row in enumerate((2, 3), start=1):
        ws.append(["Y", f"00{n}", f"Policy {n}", f"=VLOOKUP(Global!$B$2,Global!$E$1:$G$3,3,FALSE)&I{n + 1}", "Y", "GET", "KEY-123", "Bearer TOKEN-abc",
                   f"=Params_1!D{row}", "Success", None])
    wb.save(path)
    return path


def flows_of(path: Path):
    return analyse(Workbook(path, seed=1))


ALL = ["Buy#1", "Buy#2", "Cancel#1", "Cancel#2", "View#1", "View#2"]


# -- who waits for whom -------------------------------------------------------------------------------------------------------------------------------
def test_a_test_waits_for_the_test_that_sets_what_it_reads_in_its_own_parameter_row(site, tmp_path):
    order = plan_order(flows_of(build(tmp_path / "a.xlsx", site)), ALL)
    assert order.deps["Buy#1"] == [] and order.deps["Buy#2"] == []
    assert order.deps["Cancel#1"] == ["Buy#1"] and order.deps["View#1"] == ["Buy#1"]          # never Buy#2: that one fills row 3, not row 2
    assert order.deps["Cancel#2"] == ["Buy#2"] and order.deps["View#2"] == ["Buy#2"]
    assert order.data["View#1"] == {"DT_POLICY_OUT": ["Buy#1"]}
    assert [s["tests"] for s in order.streams] == [["Buy#1", "Cancel#1", "View#1"], ["Buy#2", "Cancel#2", "View#2"]]       # two streams, side by side
    assert order.streams[0]["levels"] == {"Buy#1": 0, "Cancel#1": 1, "View#1": 1} and order.streams[0]["params"] == ["DT_Policy_Out"]
    said = {(n["kind"], n["test"]) for n in order.notes}
    assert ("waits", "View#1") in said and ("parallel", "Cancel#1") in said                    # Cancel and View would run together: say so


def test_a_chain_fixes_the_order_data_cannot(site, tmp_path):
    chains = [["Buy#1", "View#1", "Cancel#1"], ["Buy#2", "View#2", "Cancel#2"]]
    order = plan_order(flows_of(build(tmp_path / "a.xlsx", site)), ALL, chains)
    assert set(order.deps["Cancel#1"]) == {"View#1", "Buy#1"} and order.deps["View#1"] == ["Buy#1"]
    assert [s["tests"] for s in order.streams] == [["Buy#1", "View#1", "Cancel#1"], ["Buy#2", "View#2", "Cancel#2"]]
    assert order.streams[0]["levels"] == {"Buy#1": 0, "View#1": 1, "Cancel#1": 2}
    assert not [n for n in order.notes if n["kind"] == "parallel"] and order.chains == chains


def test_a_test_whose_producer_is_not_in_the_run_says_what_could_set_it(site, tmp_path):
    order = plan_order(flows_of(build(tmp_path / "a.xlsx", site)), ["View#1", "Cancel#2"])
    assert order.deps == {"Cancel#2": [], "View#1": []}
    notes = {n["test"]: n for n in order.notes if n["kind"] == "missing"}
    assert notes["View#1"]["available"] == ["Buy#1"] and "add it to the run, or you will be asked" in notes["View#1"]["message"]
    assert notes["Cancel#2"]["available"] == ["Buy#2"]


def test_a_chain_that_contradicts_the_data_does_not_make_a_cycle(site, tmp_path):
    order = plan_order(flows_of(build(tmp_path / "a.xlsx", site)), ALL, [["View#1", "Buy#1"]])       # View before Buy, but View reads what Buy sets
    assert order.deps["Buy#1"] == ["View#1"] and "Buy#1" not in order.deps["View#1"]                  # the person's order wins
    assert [n["kind"] for n in order.notes if n["kind"] == "conflict"] == ["conflict"]


def test_chains_ignore_members_that_are_not_in_the_run_and_unknown_names_are_reported(site, tmp_path):
    order = plan_order(flows_of(build(tmp_path / "a.xlsx", site)), ["Buy#1", "View#1"], [["Buy#1", "Cancel#1", "View#1", "Nope#9"]])
    assert order.chains == [["Buy#1", "View#1"]]
    assert [n["test"] for n in order.notes if n["kind"] == "chain_unknown"] == ["Nope#9"]


def test_chains_are_remembered_beside_the_workbook_and_cleaned(tmp_path):
    wb = tmp_path / "workbooks" / "x.xlsx"
    wb.parent.mkdir()
    save_chains(wb, [["A", "B", "B", "C"], ["only-one"], "junk", ["D", "E"]])
    assert chains_file(wb) == wb.parent / ".chains" / "x.xlsx.json"
    assert load_chains(Config(), wb) == ([["A", "B", "C"], ["D", "E"]], "saved")
    cfg = Config()
    cfg.chains = {"*": [["P", "Q"]], "x.xlsx": [["R", "S"]]}
    save_chains(wb, [])                                                                            # forgetting them falls back to config.yaml
    assert load_chains(cfg, wb) == ([["R", "S"]], "config") and load_chains(Config(), wb) == ([], "none")
    assert clean_chains(None) == []


# -- the scheduler ------------------------------------------------------------------------------------------------------------------------------
class Case:
    def __init__(self, id):
        self.id = id


async def test_the_scheduler_holds_a_test_back_until_what_it_waits_for_has_finished():
    a, b, c = Case("a"), Case("b"), Case("c")
    schedule = Schedule([b, a, c], {"b": ["a"], "a": [], "c": []})                                   # b is first in priority but waits for a
    cancel = asyncio.Event()
    first = await schedule.take(cancel)
    second = await schedule.take(cancel)
    assert [first.id, second.id] == ["a", "c"]                                                       # b is skipped over while a is unfinished
    waiter = asyncio.create_task(schedule.take(cancel))
    await asyncio.sleep(0.3)
    assert not waiter.done()                                                                         # nothing ready: a worker waits
    await schedule.finished("a")
    assert (await asyncio.wait_for(waiter, 2)).id == "b"
    assert await schedule.take(cancel) is None                                                       # nothing left


async def test_a_waiting_worker_lets_a_cancel_through():
    schedule = Schedule([Case("b"), Case("a")], {"b": ["a"], "a": ["b"]})                            # (a cycle: the guard runs the first one)
    cancel = asyncio.Event()
    assert (await schedule.take(cancel)).id == "b"                                                   # nothing is running, so it does not hang
    waiter = asyncio.create_task(schedule.take(cancel))
    await asyncio.sleep(0.2)
    cancel.set()
    assert await asyncio.wait_for(waiter, 2) is None


# -- a real run --------------------------------------------------------------------------------------------------------------------------------------
async def run(make_cfg, wb: Path, tests: list[str], chains=None, workers: int = 3):
    cfg = make_cfg(**{"runner.workers": workers, "runner.stagger_s": 0, "runner.min_page_load_gap_s": 0})
    bus = EventBus()
    events: list[dict] = []
    bus.subscribe(events.append)
    result = await execute(RunOptions(workbook=wb, tests=tests, seed=1, chains=chains, extra={"ask": "off"}), cfg, bus)
    return {t.id: t for t in result.tests}, events


def at(events, kind: str, test: str) -> int:
    return next(i for i, e in enumerate(events) if e["type"] == kind and e.get("test") == test)


@pytest.mark.browser
async def test_tests_start_after_the_test_that_sets_their_parameter_and_use_its_value(site, make_cfg, tmp_path):
    tests, events = await run(make_cfg, build(tmp_path / "a.xlsx", site), ALL)
    assert {t.status for t in tests.values()} == {"PASSED"}, {k: v.error for k, v in tests.items() if v.status != "PASSED"}
    for n in ("1", "2"):
        assert at(events, "test_finished", f"Buy#{n}") < at(events, "test_started", f"View#{n}")     # the value exists before it is needed
        assert at(events, "test_finished", f"Buy#{n}") < at(events, "test_started", f"Cancel#{n}")
    typed = lambda t: next(s.actual for s in tests[t].steps if s.name == "What the field holds")
    assert (typed("View#1"), typed("View#2"), typed("Cancel#1"), typed("Cancel#2")) == ("A", "B", "A", "B")       # each stream used its own row's value
    # the streams run side by side: Buy#2 is under way before Buy#1 is done
    assert at(events, "test_started", "Buy#2") < at(events, "test_finished", "Buy#1")
    started = next(e for e in events if e["type"] == "run_started")
    assert {t["id"]: t["waits_for"] for t in started["tests"]}["View#1"] == ["Buy#1"]                    # the run screen can say what waits


@pytest.mark.browser
async def test_a_chain_puts_one_consumer_before_the_other(site, make_cfg, tmp_path):
    chains = [["Buy#1", "View#1", "Cancel#1"]]
    tests, events = await run(make_cfg, build(tmp_path / "a.xlsx", site), ["Buy#1", "Cancel#1", "View#1"], chains)
    assert {t.status for t in tests.values()} == {"PASSED"}
    assert at(events, "test_finished", "View#1") < at(events, "test_started", "Cancel#1")               # without the chain they would have run together


@pytest.mark.browser
async def test_a_test_whose_producer_did_not_set_the_value_is_not_run_and_says_why(site, make_cfg, tmp_path):
    tests, events = await run(make_cfg, build(tmp_path / "a.xlsx", site, buy_fails_in_row=1), ["Buy#1", "View#1", "Cancel#1"])
    assert tests["Buy#1"].status == "FAILED"
    for name in ("View#1", "Cancel#1"):
        t = tests[name]
        assert t.status == "ERROR" and t.steps == [] and t.skipped == t.total_steps > 0
        assert "Not run: " + name + " needs DT_Policy_Out" in t.error and "Buy#1 ended FAILED" in t.error and "Nothing was typed in its place" in t.error
    finished = [e for e in events if e["type"] == "test_finished" and e["test"] == "View#1"]
    assert finished and finished[0]["status"] == "ERROR"                                                # the run screen shows it as a finished test


@pytest.mark.browser
async def test_without_the_producer_in_the_run_the_test_runs_at_once_and_asks_for_the_value(site, make_cfg, tmp_path):
    tests, events = await run(make_cfg, build(tmp_path / "a.xlsx", site), ["View#1"])                  # nobody to ask in this run: the step fails, the test does not wait
    step = next(s for s in tests["View#1"].steps if s.name == "Enter Policy Number")
    assert step.status == "FAILED" and "Parameter DT_Policy_Out is empty" in step.error


# -- API tests are part of the order ---------------------------------------------------------------------------------------------------------------
ALL_API = ALL + ["Policy#1", "Policy#2"]


def test_an_api_test_that_reads_a_cell_another_test_sets_is_in_the_stream_and_waits_for_it(site, tmp_path):
    """The question: PolicySearch reads the policy number Purchase produces, so why was it not part of the run order?"""
    order = plan_order(flows_of(build_with_api(tmp_path / "a.xlsx", site)), ALL_API)
    assert order.data["Policy#1"] == {"DT_POLICY_OUT": ["Buy#1"]} and order.data["Policy#2"] == {"DT_POLICY_OUT": ["Buy#2"]}       # each stream's own cell
    assert "Buy#1" in order.deps["Policy#1"] and "Buy#2" not in order.deps["Policy#1"] or set(order.deps["Policy#1"]) >= {"Buy#1"}
    stream = order.streams[0]
    assert stream["tests"][0] == "Buy#1" and stream["tests"][-1] == "Policy#1" and "Policy#2" not in stream["tests"]              # in its stream, after the others
    assert order.streams[1]["tests"][-1] == "Policy#2"
    assert order.after_ui == ["Policy#1", "Policy#2"] and any(n["kind"] == "after_ui" for n in order.notes)                         # the default is said, not silent
    assert set(order.deps["Policy#1"]) == {"Buy#1", "Buy#2", "Cancel#1", "Cancel#2", "View#1", "View#2"}                          # unchanged: after every UI test


def test_an_api_test_can_be_chained_and_then_only_waits_where_the_chain_and_the_data_say(site, tmp_path):
    """Before: Purchase#1 -> PolicySearch#1 -> Cancellation#1 made PolicySearch wait for Cancellation (all UI tests) while Cancellation waited for it: a deadlock."""
    order = plan_order(flows_of(build_with_api(tmp_path / "a.xlsx", site)), ALL_API, [["Buy#1", "Policy#1", "Cancel#1"]])
    assert order.deps["Policy#1"] == ["Buy#1"] and set(order.deps["Cancel#1"]) == {"Policy#1", "Buy#1"}
    assert order.after_ui == ["Policy#2"]                                                                                          # only the unchained one keeps the default
    assert [n["kind"] for n in order.notes if n["kind"] == "conflict"] == []


def test_an_api_test_whose_cell_nothing_sets_says_which_cell_and_who_could_set_it(site, tmp_path):
    order = plan_order(flows_of(build_with_api(tmp_path / "a.xlsx", site)), ["Policy#1"])
    (note,) = [n for n in order.notes if n["kind"] == "missing"]
    assert note["test"] == "Policy#1" and note["available"] == ["Buy#1"] and "Params_1!D2" in note["message"] and "add it to the run" in note["message"]


@pytest.mark.browser
async def test_an_api_test_runs_after_the_test_that_sets_its_cell_and_sends_that_value(site, make_cfg, tmp_path):
    tests, events = await run(make_cfg, build_with_api(tmp_path / "a.xlsx", site), ["Buy#1", "Buy#2", "Policy#1", "Policy#2"])
    assert tests["Buy#1"].status == tests["Buy#2"].status == "PASSED"
    for n in ("1", "2"):
        assert at(events, "test_finished", f"Buy#{n}") < at(events, "test_started", f"Policy#{n}")
    assert tests["Policy#1"].steps[0].name.endswith("/policy/v4/A") and tests["Policy#2"].steps[0].name.endswith("/policy/v4/B")     # each got its own stream's value


@pytest.mark.browser
async def test_a_chain_with_an_api_test_in_the_middle_runs_in_that_order_without_stalling(site, make_cfg, tmp_path):
    chains = [["Buy#1", "Policy#1", "Cancel#1"]]
    tests, events = await asyncio.wait_for(run(make_cfg, build_with_api(tmp_path / "a.xlsx", site), ["Buy#1", "Policy#1", "Cancel#1"], chains), 90)
    assert at(events, "test_finished", "Buy#1") < at(events, "test_started", "Policy#1") < at(events, "test_finished", "Policy#1") < at(events, "test_started", "Cancel#1")
    assert tests["Cancel#1"].status == "PASSED"


@pytest.mark.browser
async def test_an_api_test_whose_producer_did_not_set_the_value_is_not_run(site, make_cfg, tmp_path):
    tests, _ = await run(make_cfg, build_with_api(tmp_path / "a.xlsx", site, buy_fails_in_row=1), ["Buy#1", "Policy#1"])
    assert tests["Buy#1"].status == "FAILED"
    t = tests["Policy#1"]
    assert t.status == "ERROR" and t.steps == [] and "Not run: Policy#1 needs DT_Policy_Out" in t.error and "Buy#1 ended FAILED" in t.error
