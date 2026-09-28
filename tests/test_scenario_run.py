"""Concurrency scenarios on the mock site: two agents edit one policy at the same time (sync points, an order marker), a lane that fails or
waits too long never hangs the others, and two lanes signing in with one authenticator key get different code windows."""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from regrunner import totp
from regrunner.engine.runner import RunOptions, execute
from regrunner.events import EventBus
from regrunner.workbook.scenarios import HEADERS
from tests.flow_books import at, book
from tests.site import server as mock_server

pytestmark = pytest.mark.browser

SCENARIO = "Two agents edit one policy"


@pytest.fixture(autouse=True)
def fresh_policy():
    mock_server.SHARED_POLICY.update(version=1, log=[])
    yield
    mock_server.SHARED_POLICY.update(version=1, log=[])


def scenario_table(*rows) -> list[list]:
    """``_rr_scenarios`` with the scenario row, lanes A (data row 2) and B (row 3), and ``rows``."""
    blank = [None] * (len(HEADERS) - 2)
    lane = lambda key, row, label: [SCENARIO, "lane", label, key, "Edit", row, *[None] * 6]
    return [list(HEADERS), [SCENARIO, "scenario", *blank[:-3], rows[0] if rows and isinstance(rows[0], int) else None, "Y", "two users"],
            lane("A", 2, "Ana"), lane("B", 3, "Ben"), *[r for r in rows if isinstance(r, list)]]


def sync(name: str, lane: str, block: str) -> list:
    return [SCENARIO, "sync", name, lane, None, None, block, None, None, None, None, None]


def order(name: str, first: str, first_block: str, then: str, then_block: str) -> list:
    return [SCENARIO, "order", name, first, None, None, first_block, then, then_block, None, None, None]


EDIT = [
    ("Open", "Open the policy", {"Value": "DT_URL", "BLOCK": "Open policy"}),
    ("Click", "Click the heading", {**at("DT_LANDMARK"), "Timeout": 1, "BLOCK": "Open policy"}),
    ("Wait", "Take a moment", {"Value": "DT_PAUSE", "BLOCK": "Open policy"}),
    ("Output", "Version 1 is open", {**at("//span[@id='version']"), "Output_Property": "innertext", "Expected_Value": "1", "Exact_Match": "Y",
                                     "BLOCK": "Open policy"}),
    ("Set", "Type the address", {**at("//input[@id='address']"), "Value": "DT_ADDRESS", "BLOCK": "Edit"}),
    ("Click", "Save changes", {**at("//button[@id='save']"), "BLOCK": "Save"}),
    ("Output", "What the site said", {**at("//p[@id='msg']"), "Output_Property": "innertext", "Expected_Value": "DT_EXPECT", "Exact_Match": "Y",
                                      "BLOCK": "Check"}),
]


def agents(site, *, ben_expects: str = "Changed by another user", ana_landmark: str = "//h1", ben_pause: int = 0) -> list[dict]:
    row = lambda who, address, expect, landmark, pause: {"DT_URL": f"{site}scenario_policy.html?agent={who}", "DT_ADDRESS": address,
                                                         "DT_EXPECT": expect, "DT_LANDMARK": landmark, "DT_PAUSE": pause}
    return [row("Ana", "1 Main St", "Saved", ana_landmark, 0), row("Ben", "2 High St", ben_expects, "//h1", ben_pause)]


async def run(wb, cfg, tests=(SCENARIO,), workers=1):
    events: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = await asyncio.wait_for(execute(RunOptions(workbook=wb, seed=1, tests=list(tests), workers=workers), cfg, bus), 180)
    return result, events


def failures(result) -> list:
    return [(t.id, t.error, [(s.name, s.error, s.actual) for s in t.steps if s.status != "PASSED"]) for t in result.tests]


async def test_two_agents_open_together_and_the_second_save_sees_the_first(site, make_cfg, tmp_path):
    wb = book(tmp_path / "wb.xlsx", {"Edit": EDIT}, params={"Edit": agents(site)},
              sheets={"_rr_scenarios": scenario_table(sync("Sync 1", "A", "Open policy"), sync("Sync 1", "B", "Open policy"),
                                                      order("A saves first", "A", "Save", "B", "Save"))})
    result, events = await run(wb, make_cfg(**{"runner.stagger_s": 0}))
    assert {t.id: t.status for t in result.tests} == {f"{SCENARIO} · A": "PASSED", f"{SCENARIO} · B": "PASSED"}, failures(result)
    log = mock_server.SHARED_POLICY["log"]
    assert sorted(log[:2]) == [("open", "Ana"), ("open", "Ben")]                 # both opened version 1 before anyone saved (the sync)
    assert log[2:] == [("saved", "Ana"), ("refused", "Ben")]                      # Ana saved first (the order marker), Ben was told
    starts = [e for e in events if e["type"] == "test_started"]
    assert {e["worker"] for e in starts} == {1} and len(starts) == 2               # one worker ran both lanes, at the same time
    a, b = result.tests
    assert a.lane == {"scenario": SCENARIO, "key": "A", "label": "Ana", "test": "Edit#1", "sheet": "Edit", "data_row": 2}
    assert [s["state"] for s in a.syncs if s["item"] == "Sync 1"][-1] == "released"
    assert [s["state"] for s in b.syncs if s["item"] == "A saves first"][-1] == "released"
    assert any(s["state"] == "done" for s in a.syncs if s["item"] == "A saves first")
    started = next(e for e in events if e["type"] == "run_started")
    assert started["scenarios"][0]["syncs"] == [{"name": "Sync 1", "lanes": ["A", "B"]}]
    assert {t["id"]: t.get("lane", {}).get("key") for t in started["tests"]} == {f"{SCENARIO} · A": "A", f"{SCENARIO} · B": "B"}
    saved = json.loads((result_dir(make_cfg, result) / "results.json").read_text())
    assert [t["lane"]["key"] for t in saved["tests"]] == ["A", "B"] and all(t["syncs"] for t in saved["tests"])


def result_dir(make_cfg, result):
    return make_cfg().path("runs") / result.run_id


async def test_a_lane_that_fails_before_the_sync_releases_the_others(site, make_cfg, tmp_path):
    wb = book(tmp_path / "wb.xlsx", {"Edit": EDIT}, params={"Edit": agents(site, ben_expects="Saved", ana_landmark="//h2[@id='nope']")},
              sheets={"_rr_scenarios": scenario_table(sync("Sync 1", "A", "Open policy"), sync("Sync 1", "B", "Open policy"),
                                                      order("A saves first", "A", "Save", "B", "Save"))})
    result, events = await run(wb, make_cfg(**{"runner.stagger_s": 0, "runner.stop_after_failed_steps": 1}))
    status = {t.id: t.status for t in result.tests}
    assert status == {f"{SCENARIO} · A": "FAILED", f"{SCENARIO} · B": "PASSED"}, failures(result)
    b = result.tests[1]
    released = [s for s in b.syncs if s["state"] == "released"]
    assert {s["item"] for s in released} == {"Sync 1", "A saves first"}
    assert all("A" in s["message"] and "ended" in s["message"] for s in released)          # it says why it did not wait
    assert mock_server.SHARED_POLICY["log"][-1] == ("saved", "Ben")
    ended = [e for e in events if e["type"] == "scenario_sync" and e["lane"] == "A" and e["state"] == "ended"]
    assert {e["sync"] for e in ended} == {"Sync 1", "A saves first"}


async def test_a_lane_that_waits_too_long_gives_up_and_the_other_carries_on(site, make_cfg, tmp_path):
    wb = book(tmp_path / "wb.xlsx", {"Edit": EDIT}, params={"Edit": agents(site, ben_expects="Saved", ben_pause=12)},
              sheets={"_rr_scenarios": scenario_table(5, sync("Sync 1", "A", "Open policy"), sync("Sync 1", "B", "Open policy"))})
    result, events = await run(wb, make_cfg(**{"runner.stagger_s": 0, "waits.mode": "legacy"}))
    a, b = result.tests
    assert (a.status, b.status) == ("ERROR", "PASSED"), failures(result)
    assert "gave up at Sync 1" in a.error and "Timeout" in a.error
    assert [s["state"] for s in a.syncs] == ["arrived", "timeout"]
    assert a.skipped and not any(s.name == "Save changes" for s in a.steps)               # the rest of lane A was not run
    waits = [e for e in events if e["type"] == "worker_waiting" and e["code"] == "scenario_sync"]
    assert waits and waits[0]["test"] == f"{SCENARIO} · A"                                 # the run screen showed it waiting on purpose


SECRET = base64.b32encode(b"one-account-two-lanes").decode().rstrip("=")


async def test_two_lanes_with_one_authenticator_key_get_different_code_windows(site, make_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(totp, "STEP_S", 10)                                  # 10 s code windows: the same rules, a shorter test
    mock_server.OKTA.update(secret=SECRET, used=set(), seen=[])
    try:
        rows = [("Open", "Open", {"Value": "DT_URL", "BLOCK": "Open"}),
                ("GET_GOOGLE_TOKEN", "Get Okta code", {"Value": "DT_Key", "BLOCK": "Sign in"})]
        code_row = 3
        rows += [("Set", "Enter code", {**at("//input[@id='code']"), "Value": f"=S{code_row}", "BLOCK": "Sign in"}),
                 ("Click", "Verify", {**at("//button[@id='verify']"), "BLOCK": "Sign in"}),
                 ("Output", "Signed in", {**at("//p[@id='msg']"), "Output_Property": "innertext", "Expected_Value": "Welcome", "Exact_Match": "Y",
                                          "BLOCK": "Sign in"})]
        lanes = [["Sign in twice", "lane", "Ana", "A", "Login", 2, *[None] * 6], ["Sign in twice", "lane", "Ana again", "B", "Login", 3, *[None] * 6]]
        syncs = [["Sign in twice", "sync", "Together", k, None, None, "Open", None, None, None, None, None] for k in "AB"]
        wb = book(tmp_path / "wb.xlsx", {"Login": rows}, params={"Login": [{"DT_URL": site + "okta.html", "DT_Key": SECRET}] * 2},
                  sheets={"_rr_scenarios": [list(HEADERS), *lanes, *syncs]})
        result, events = await run(wb, make_cfg(**{"runner.stagger_s": 0, "runner.min_page_load_gap_s": 0}), tests=["Sign in twice"])
        assert [t.status for t in result.tests] == ["PASSED", "PASSED"], failures(result)
        assert len(mock_server.OKTA["used"]) == 2                                          # two different codes, each accepted the first time
        assert any(e["type"] == "worker_waiting" and e["code"] == "login_code" for e in events)
        assert any(e["type"] == "log" and "same one-time-code key" in e["message"] for e in events)
        assert SECRET not in json.dumps(events)
    finally:
        mock_server.OKTA.update(secret="", used=set(), seen=[])
