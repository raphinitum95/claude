"""Concurrency scenarios without a browser: the ``_rr_scenarios`` table, the Build tab's board and its problems, the ops, which lanes a run
picks, how lanes are scheduled, and the sync points / order markers themselves (``engine/scenario.py``'s Coordinator)."""
from __future__ import annotations

import asyncio

import pytest

from regrunner.engine import scenario as E
from regrunner.engine.order import Order
from regrunner.engine.runner import RunOptions
from regrunner.engine.schedule import Schedule
from regrunner.workbook import builder as B
from regrunner.workbook import scenarios as S
from regrunner.workbook.model import Workbook
from regrunner.workbook.writer import WorkbookEditor
from tests.flow_books import at, book

SC = "Two agents"

STEPS = [("Open", "Open", {"Value": "DT_URL", "BLOCK": "Open policy"}),
         ("Click", "Edit", {**at("//a"), "BLOCK": "Edit"}),
         ("Click", "Save", {**at("//b"), "BLOCK": "Save"}),
         ("Output", "Check", {**at("//p"), "Output_Property": "innertext", "BLOCK": "Check"})]


def definition(**over) -> dict:
    d = {"name": SC, "enabled": True, "timeout": 60, "notes": "two users",
         "lanes": [{"key": "A", "test": "Edit", "dataRow": 2, "label": "Ana"}, {"key": "B", "test": "Edit", "dataRow": 3, "label": "Ben"}],
         "syncs": [{"name": "Sync 1", "timeout": None, "points": [{"lane": "A", "block": "Open policy"}, {"lane": "B", "block": "Open policy"}]}],
         "orders": [{"name": "A saves first", "timeout": None, "first": {"lane": "A", "block": "Save"}, "then": {"lane": "B", "block": "Save"}}]}
    d.update(over)
    return d


def workbook(tmp_path, definitions=None, *, keys=("K1", "K2"), extra_tests=None, login=False, name="wb.xlsx"):
    steps = list(STEPS)
    if login:
        steps.insert(1, ("GET_GOOGLE_TOKEN", "Code", {"Value": "DT_KEY", "BLOCK": "Open policy"}))
    rows = [{"DT_URL": "u1", "DT_KEY": keys[0]}, {"DT_URL": "u2", "DT_KEY": keys[1]}, {"DT_URL": "u3", "DT_KEY": "K3", "blnExecute": "N"}]
    tests = {"Edit": steps, **(extra_tests or {})}
    return book(tmp_path / name, tests, params={"Edit": rows},
                sheets={"_rr_scenarios": S.table_rows(definitions if definitions is not None else [definition()])} if definitions != [] else None)


def board_of(path) -> tuple[list[dict], dict]:
    model = B.build_model(WorkbookEditor.open(path))
    return model["scenarios"], model


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The table and the board
# ---------------------------------------------------------------------------------------------------------------------------------------------
def test_the_table_reads_back_exactly_what_was_written():
    defs = [definition(), definition(name="Other", enabled=False, timeout=None, notes="", syncs=[], orders=[])]
    assert S.read_definitions(S.table_rows(defs)) == defs


def test_the_board_shows_each_lane_with_its_blocks_and_data_row(tmp_path):
    scenarios, model = board_of(workbook(tmp_path))
    sc = scenarios[0]
    assert [l["key"] for l in sc["lanes"]] == ["A", "B"] and sc["problems"] == []
    assert [b["ref"] for b in sc["lanes"][0]["blocks"]] == ["Open policy", "Edit", "Save", "Check"]
    assert sc["lanes"][1]["usesRow"] == 3 and sc["timeoutUsed"] == 60
    assert not [p for p in model["problems"] if p.get("scenario")]


def test_a_block_title_that_repeats_is_named_with_its_number():
    blocks = [{"title": "Start", "firstRow": 2}, {"title": "Pay", "firstRow": 5}, {"title": "Start", "firstRow": 9}]
    assert S.block_refs(blocks) == ["Start", "Pay", "Start#2"]
    assert S.find_block(blocks, "start#2") == 2 and S.find_block(blocks, "Start#1") == 0
    assert S.after_block(blocks, "Pay") == 9 and S.after_block(blocks, "Start#2") == S.END and S.after_block(blocks, "") == 0
    assert S.before_block(blocks, "Pay") == 5 and S.before_block(blocks, "Nope") is None


def test_problems_name_a_missing_test_a_missing_block_and_a_one_lane_sync(tmp_path):
    d = definition(lanes=[{"key": "A", "test": "Edit", "dataRow": 2, "label": ""}, {"key": "B", "test": "Nope", "dataRow": None, "label": ""}],
                   syncs=[{"name": "Sync 1", "timeout": None, "points": [{"lane": "A", "block": "Payment"}]}], orders=[])
    scenarios, model = board_of(workbook(tmp_path, [d]))
    kinds = {p["kind"] for p in scenarios[0]["problems"]}
    assert {"scenario_unknown_test", "scenario_unknown_block", "scenario_sync_one_lane"} <= kinds
    shown = [p for p in model["problems"] if p.get("scenario") == SC]
    assert shown and all(p["message"].startswith(f'Scenario "{SC}"') and p["test"] == "" for p in shown)


def test_waits_that_could_never_all_be_met_are_a_deadlock(tmp_path):
    # B must finish Save before A even opens the policy, but B cannot get past Sync 1 (after opening) until A is there too.
    d = definition(orders=[{"name": "B first", "timeout": None, "first": {"lane": "B", "block": "Save"}, "then": {"lane": "A", "block": "Open policy"}}])
    scenarios, _ = board_of(workbook(tmp_path, [d]))
    dead = [p for p in scenarios[0]["problems"] if p["kind"] == "scenario_deadlock"]
    assert dead and "Sync 1" in dead[0]["message"] and "B first" in dead[0]["message"]


def test_a_sync_and_an_order_that_agree_are_not_a_deadlock(tmp_path):
    scenarios, _ = board_of(workbook(tmp_path))
    assert not [p for p in scenarios[0]["problems"] if p["kind"] == "scenario_deadlock"]


def test_two_lanes_with_the_same_data_row_are_flagged(tmp_path):
    d = definition(lanes=[{"key": "A", "test": "Edit", "dataRow": 2, "label": ""}, {"key": "B", "test": "Edit", "dataRow": 2, "label": ""}])
    scenarios, _ = board_of(workbook(tmp_path, [d]))
    assert any(p["kind"] == "scenario_same_data_row" for p in scenarios[0]["problems"])


def test_lanes_that_sign_in_with_the_same_key_are_said_and_the_key_never_appears(tmp_path):
    scenarios, _ = board_of(workbook(tmp_path, keys=("JBSWY3DPEHPK3PXP", "JBSWY3DPEHPK3PXP"), login=True))
    sc = scenarios[0]
    assert sc["sharedSignIn"] == [["A", "B"]]
    assert any(p["kind"] == "scenario_shared_sign_in" for p in sc["problems"])
    assert "JBSWY3DPEHPK3PXP" not in repr(sc)
    other, _ = board_of(workbook(tmp_path, keys=("JBSWY3DPEHPK3PXP", "KRSXG5CTMVRXEZLU"), login=True, name="other.xlsx"))
    assert other[0]["sharedSignIn"] == []


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------------------------------------------------------------------------
def test_set_scenario_writes_a_hidden_table_and_rename_keeps_its_place(tmp_path):
    path = workbook(tmp_path, [])
    e = WorkbookEditor.open(path)
    B.apply_ops(e, [{"op": "set_scenario", "scenario": definition()}, {"op": "set_scenario", "scenario": definition(name="Later", syncs=[], orders=[])}])
    assert e.is_hidden(S.RR_SCENARIOS)
    B.apply_ops(e, [{"op": "set_scenario", "rename": SC, "scenario": definition(name="Renamed")}])
    assert [d["name"] for d in S.read_scenarios(e)] == ["Renamed", "Later"]
    with pytest.raises(B.BuildError) as err:
        B.apply_ops(e, [{"op": "set_scenario", "rename": "Later", "scenario": definition(name="Renamed")}])
    assert err.value.status == 409
    B.apply_ops(e, [{"op": "delete_scenario", "name": "renamed"}])
    assert [d["name"] for d in S.read_scenarios(e)] == ["Later"]


@pytest.mark.parametrize("bad", [{"name": "Edit"}, {"name": "A/B"}, {"lanes": [{"key": "1"}]}, {"lanes": [{"key": "A"}, {"key": "a"}]},
                                 {"timeout": 1}])
def test_set_scenario_refuses_what_a_run_could_not_use(tmp_path, bad):
    e = WorkbookEditor.open(workbook(tmp_path, []))
    with pytest.raises(B.BuildError):
        B.apply_ops(e, [{"op": "set_scenario", "scenario": definition(**bad)}])


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Which lanes a run takes, and how they are scheduled
# ---------------------------------------------------------------------------------------------------------------------------------------------
def pick(path, **options):
    wb = Workbook(path)
    return E.pick(wb, RunOptions(workbook=path, **options), wb.discover())


def test_naming_a_scenario_runs_every_lane_and_leaves_the_other_names_alone(tmp_path):
    plans, rest = pick(workbook(tmp_path), tests=["two agents", "Edit"])
    assert rest == ["Edit"]
    assert [c.id for c in plans[0].lanes] == [f"{SC} · A", f"{SC} · B"]
    a = plans[0].lanes[0]
    assert (a.sheet, a.param_row, a.group, a.lane, a.label, a.base_id) == ("Edit", 2, SC, "A", "Ana", "Edit#1")


def test_naming_one_lane_runs_the_whole_scenario(tmp_path):
    plans, rest = pick(workbook(tmp_path), tests=[f"{SC} · B"])
    assert rest == [] and len(plans[0].lanes) == 2


def test_a_plain_run_includes_the_scenarios_marked_to_run_and_a_run_by_tag_none(tmp_path):
    path = workbook(tmp_path, [definition(), definition(name="Off", enabled=False)])
    plans, rest = pick(path)
    assert [p.name for p in plans] == [SC] and rest is None
    assert pick(path, tags=["smoke"])[0] == []


def test_a_data_row_that_is_switched_off_still_runs_in_a_scenario(tmp_path):
    d = definition(lanes=[{"key": "A", "test": "Edit", "dataRow": 2, "label": ""}, {"key": "B", "test": "Edit", "dataRow": 4, "label": ""}])
    plans, _ = pick(workbook(tmp_path, [d]), tests=[SC])
    assert plans[0].lanes[1].param_row == 4 and plans[0].lanes[1].enabled


def test_a_scenario_that_cannot_run_as_written_refuses_with_the_reason(tmp_path):
    d = definition(syncs=[{"name": "Sync 1", "timeout": None, "points": [{"lane": "A", "block": "Nowhere"}, {"lane": "B", "block": ""}]}])
    with pytest.raises(E.ScenarioError, match="no block called \"Nowhere\""):
        pick(workbook(tmp_path, [d]), tests=[SC])


def test_points_are_rows_after_and_before_blocks(tmp_path):
    plans, _ = pick(workbook(tmp_path), tests=[SC])
    points = {(p.lane, p.role, p.item): p.at for p in plans[0].resolved.points}
    # rows: 2 Open (Open policy), 3 Edit, 4 Save, 5 Check
    assert points == {("A", "sync", "Sync 1"): 3, ("B", "sync", "Sync 1"): 3, ("A", "first", "A saves first"): 5, ("B", "then", "A saves first"): 4}


def test_lanes_wait_for_what_any_of_them_waits_for_but_never_for_each_other():
    ids = [f"{SC} · A", f"{SC} · B"]
    plan = E.ScenarioPlan(SC, [E.LaneCase(id=i, sheet="Edit", param_sheet=None, param_row=2, title=i) for i in ids], S.Resolved(SC, 60, ["A", "B"]))
    order = Order(deps={ids[0]: ["Login"], ids[1]: [ids[0]], "Login": [], "After": [ids[1]]}, data={ids[1]: {"POLICY": [ids[0]]}},
                  after_ui=[ids[0]])
    E.adjust_order(order, [plan])
    assert order.deps[ids[0]] == order.deps[ids[1]] == ["Login"]
    assert ids[1] not in order.data and order.after_ui == []
    assert set(order.deps["After"]) == set(ids)


def test_starting_one_lane_starts_the_whole_group():
    class C:
        def __init__(self, i):
            self.id = i
    cases = [C("A"), C("x"), C("B")]
    sched = Schedule(cases, {}, groups={"A": ["A", "B"], "B": ["A", "B"]})
    first = sched.next_ready()
    assert first.id == "A" and [c.id for c in sched.group_of(first)] == ["A", "B"]
    sched.start(first)
    assert sched.running == 2 and [c.id for c in sched._pending] == ["x"]


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Sync points and order markers
# ---------------------------------------------------------------------------------------------------------------------------------------------
class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type_, **fields):
        self.events.append({"type": type_, **fields})


def coordinator(points, timeout=60.0):
    resolved = S.Resolved(SC, timeout, ["A", "B"], points=points)
    for p in points:
        if p.role == "sync":
            resolved.syncs.setdefault(p.item, []).append(p.lane)
    plan = E.ScenarioPlan(SC, [E.LaneCase(id=f"{SC} · {k}", sheet="Edit", param_sheet=None, param_row=2, title=k, lane=k) for k in "AB"], resolved)
    bus = Bus()
    return E.Coordinator(plan, bus, asyncio.Event()), bus


async def test_a_sync_holds_the_first_lane_until_the_other_arrives():
    c, bus = coordinator([S.Point("A", 3, "sync", "Sync 1"), S.Point("B", 3, "sync", "Sync 1")])
    a = asyncio.ensure_future(c.advance("A", 3))
    await asyncio.sleep(0.2)
    assert not a.done()                                                  # A waits at Sync 1
    assert await c.advance("B", 4) == ""                                 # B arrives (passing row 3 on the way): everyone is there
    assert await asyncio.wait_for(a, 2) == ""
    states = [(e["lane"], e["state"]) for e in bus.events]
    assert ("A", "arrived") in states and ("A", "released") in states and ("B", "released") in states


async def test_a_lane_that_ends_releases_the_others_and_says_so():
    c, bus = coordinator([S.Point("A", 3, "sync", "Sync 1"), S.Point("B", 3, "sync", "Sync 1")])
    a = asyncio.ensure_future(c.advance("A", 3))
    await asyncio.sleep(0.1)
    await c.end("B", "FAILED")
    assert await asyncio.wait_for(a, 2) == ""
    released = [e for e in bus.events if e["lane"] == "A" and e["state"] == "released"][0]
    assert released["ended"] == ["B"] and "FAILED" in released["message"]
    assert any(e["lane"] == "B" and e["state"] == "ended" for e in bus.events)


async def test_an_order_marker_holds_the_second_lane_until_the_first_has_done_its_part():
    c, bus = coordinator([S.Point("A", 5, "first", "A first"), S.Point("B", 4, "then", "A first")])
    b = asyncio.ensure_future(c.advance("B", 4))
    await asyncio.sleep(0.1)
    assert await c.advance("A", 4) == "" and not b.done()                # A is still before the end of its part
    assert await c.advance("A", 5) == ""
    assert await asyncio.wait_for(b, 2) == ""
    assert [e["state"] for e in bus.events if e["lane"] == "A"] == ["done"]
    assert [e["state"] for e in bus.events if e["lane"] == "B"] == ["waiting", "released"]


async def test_a_wait_gives_up_when_the_others_do_not_move_and_starts_counting_again_when_they_do(monkeypatch):
    c, bus = coordinator([S.Point("A", 3, "sync", "Sync 1", timeout=0.6), S.Point("B", 3, "sync", "Sync 1", timeout=0.6)])
    a = asyncio.ensure_future(c.advance("A", 3))
    for _ in range(4):                                                   # B keeps finishing steps: A keeps waiting
        await asyncio.sleep(0.3)
        c.stepped("B")
    assert not a.done()
    why = await asyncio.wait_for(a, 5)                                   # B stops moving: A gives up
    assert "gave up at Sync 1" in why and "B did not start or finish a step" in why
    assert bus.events[-1]["state"] == "timeout"


async def test_a_cancelled_run_ends_a_wait_at_once():
    c, _ = coordinator([S.Point("A", 3, "sync", "Sync 1"), S.Point("B", 3, "sync", "Sync 1")])
    a = asyncio.ensure_future(c.advance("A", 3))
    await asyncio.sleep(0.1)
    c.cancel.set()
    assert await asyncio.wait_for(a, 2) == ""



def test_the_board_s_last_runs_are_the_newest_runs_of_this_workbook_that_ran_the_scenario(tmp_path):
    import json
    from regrunner.runmeta import update_meta
    from regrunner.web.scenario_api import scenario_runs
    lane = lambda key, status: {"id": f"{SC} · {key}", "status": status, "lane": {"scenario": SC, "key": key, "label": "", "test": "Edit#1"},
                                "syncs": [{"item": "Sync 1", "state": "released"}]}
    for run_id, workbook, tests in (("20260901-000001-UAT", "wb.xlsx", [lane("A", "PASSED"), lane("B", "FAILED")]),
                                    ("20260902-000001-UAT", "wb.xlsx", [{"id": "Edit", "status": "PASSED"}]),         # a plain run: not listed
                                    ("20260903-000001-UAT", "other.xlsx", [lane("A", "PASSED")]),                    # another workbook
                                    ("20260904-000001-UAT", "wb.xlsx", [lane("A", "PASSED"), lane("B", "PASSED")])):
        d = tmp_path / run_id
        update_meta(d, run_id=run_id, workbook=str(tmp_path / workbook), status="PASSED")
        (d / "results.json").write_text(json.dumps({"status": "PASSED", "environment": "UAT", "started_at": run_id, "tests": tests}))
    runs = scenario_runs(tmp_path, "wb.xlsx", "two AGENTS")
    assert [r["runId"] for r in runs] == ["20260904-000001-UAT", "20260901-000001-UAT"]
    assert [(l["key"], l["status"]) for l in runs[1]["lanes"]] == [("A", "PASSED"), ("B", "FAILED")] and runs[1]["lanes"][0]["syncs"]
    assert len(scenario_runs(tmp_path, "wb.xlsx", SC, limit=1)) == 1
