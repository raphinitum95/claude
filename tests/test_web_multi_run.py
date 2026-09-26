"""The web backend with several workbooks: one run each on shared workers, and a new run joining workers that are going."""
from __future__ import annotations

import json
import time

import pytest

from tests.web_fixtures import HEADERS, web  # noqa: F401  (fixtures)

BOTH = {"workbooks": [{"workbook": "mock.xlsx", "tests": ["FlowA"]}, {"workbook": "bad.xlsx", "tests": ["FlowX"]}]}


def test_the_command_for_several_workbooks_gives_each_its_own_tests_and_chains_and_shares_the_rest(web):
    with web.client() as c:
        text = c.post("/api/runs/command", json={**BOTH, "env": "qa", "workers": 3}).json()["text"]
        assert text == "regrunner run mock.xlsx --tests FlowA bad.xlsx --tests FlowX --env QA --workers 3"
        both_all = c.post("/api/runs/command", json={"workbooks": [{"workbook": "mock.xlsx", "all": True, "chains": [["FlowA", "FlowB"]]},
                                                                  {"workbook": "bad.xlsx", "all": True, "chains": []}]}).json()["text"]
        assert both_all == "regrunner run mock.xlsx --all --chain FlowA,FlowB bad.xlsx --all --no-chains"
        one = c.post("/api/runs/command", json={"workbooks": [{"workbook": "mock.xlsx", "tests": ["FlowA"]}], "workers": 3}).json()["text"]
        assert one == c.post("/api/runs/command", json={"workbook": "mock.xlsx", "tests": ["FlowA"], "workers": 3}).json()["text"]     # one is one, however it is asked


def test_a_request_names_the_workbooks_one_way_and_each_only_once(web):
    with web.client() as c:
        assert c.post("/api/runs", json={"tests": ["FlowA"]}).status_code == 422                                                     # no workbook at all
        assert c.post("/api/runs", json={"workbook": "mock.xlsx", **BOTH}).status_code == 422                                        # both ways
        twice = c.post("/api/runs", json={"workbooks": [{"workbook": "mock.xlsx", "all": True}, {"workbook": "MOCK.xlsx", "tests": ["FlowB"]}]})
        assert twice.status_code == 422 and "only be in a run once" in json.dumps(twice.json())
        assert c.post("/api/runs", json={"workbooks": []}).status_code == 422
        missing = c.post("/api/runs", json={"workbooks": [{"workbook": "mock.xlsx", "all": True}, {"workbook": "nope.xlsx", "all": True}]})
        assert missing.status_code == 404
        bad_pick = c.post("/api/runs", json={"workbooks": [{"workbook": "mock.xlsx", "tests": ["FlowA"]}, {"workbook": "bad.xlsx", "tests": ["Nope"]}]})
        assert bad_pick.status_code == 422 and bad_pick.json()["kind"] == "selection" and bad_pick.json()["error"].startswith("bad.xlsx: ")     # says whose it was
        prod = c.post("/api/runs", json={**BOTH, "env": "PROD"})
        assert prod.status_code == 400 and prod.json()["kind"] == "prod_confirm" and "mock.xlsx, bad.xlsx would run against PROD" in prod.json()["error"]
        assert not [r for r in c.get("/api/runs").json() if r["active"]]                                                            # nothing was started by any of it


def finish_all(web, run_ids, timeout=240):
    return {rid: web.wait_finished(rid, timeout) for rid in run_ids}


@pytest.mark.browser
def test_several_workbooks_start_together_as_runs_of_their_own_on_one_set_of_workers(web):
    with web.client() as c:
        started = c.post("/api/runs", json={**BOTH, "workers": 2})
        assert started.status_code == 200, started.text
        body = started.json()
        first, second = body["run_ids"]
        assert body["run_id"] == first and body["joined"] is False and [r["workbook"] for r in body["runs"]] == ["mock.xlsx", "bad.xlsx"]
        assert body["command"] == "regrunner run mock.xlsx --tests FlowA bad.xlsx --tests FlowX"
        listed = {r["run_id"]: r for r in c.get("/api/runs").json()}
        assert listed[first]["active"] and listed[second]["active"] and listed[first]["workbook"].endswith("mock.xlsx") and listed[second]["workbook"].endswith("bad.xlsx")
        assert listed[first]["command"] == "regrunner run mock.xlsx --tests FlowA --workers 2" or listed[first]["command"].startswith("regrunner run mock.xlsx --tests FlowA")
        assert listed[first]["pool"]["joinable"] is True and listed[first]["pool"]["runs"] == [first, second]
        done = finish_all(web, [first, second])
        assert done[first]["meta"]["status"] == "PASSED" and done[second]["meta"]["status"] == "FAILED"                              # each run has its own verdict
        assert [t["id"] for t in done[first]["results"]["tests"]] == ["FlowA"] and [t["id"] for t in done[second]["results"]["tests"]] == ["FlowX"]
        assert done[first]["meta"]["shares"][0]["run_id"] == second and done[second]["meta"]["shares"][0]["run_id"] == first
        assert done[first]["files"]["report_html"] and done[second]["files"]["report_html"]
        assert (web.run_dir(first) / "runner.log").is_file() and "shares one process with" in (web.run_dir(second) / "runner.log").read_text()
        events = c.get(f"/api/runs/{second}/events").json()["events"]
        assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished" and events[-1]["status"] == "FAILED"


@pytest.mark.browser
def test_a_new_run_joins_the_workers_that_are_going_and_the_same_workbook_cannot_run_twice(web):
    with web.client() as c:
        first = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"], "workers": 2})
        assert first.status_code == 200, first.text
        run_a = first.json()["run_id"]
        again = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowB"]})
        assert again.status_code == 409 and again.json()["kind"] == "busy" and again.json()["run_id"] == run_a
        assert "mock.xlsx is already being run" in again.json()["error"]

        joined = c.post("/api/runs", json={"workbook": "bad.xlsx", "tests": ["FlowX", "FlowY"]})
        assert joined.status_code == 200, joined.text
        assert joined.json()["joined"] is True
        run_b = joined.json()["run_id"]
        assert run_b != run_a
        assert next(r for r in c.get("/api/runs").json() if r["run_id"] == run_b)["active"]
        other_browser = c.post("/api/runs", json={"workbook": "escape-hatch.xlsx", "all": True})                                       # (a missing workbook is still a 404 first)
        assert other_browser.status_code == 404
        done = finish_all(web, [run_a, run_b])
        assert done[run_a]["meta"]["status"] == "PASSED" and done[run_b]["meta"]["status"] == "FAILED"
        assert {t["id"] for t in done[run_b]["results"]["tests"]} == {"FlowX", "FlowY"}
        events_a = c.get(f"/api/runs/{run_a}/events").json()["events"]
        assert any(e["type"] == "pool_changed" and e["shares"][0]["run_id"] == run_b for e in events_a)                                # the run that was going was told
        assert done[run_b]["meta"]["params"]["workers"] >= 2                                                                            # the workers grew to what was asked for
        assert "shares one process with" in (web.run_dir(run_b) / "runner.log").read_text()
        # the process is over now: a new run starts a process of its own
        time.sleep(1)
        alone = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowB"]})
        assert alone.status_code == 200 and alone.json()["joined"] is False
        web.wait_finished(alone.json()["run_id"], 200)


@pytest.mark.browser
def test_a_run_that_wants_another_browser_or_window_mode_cannot_share_the_workers_that_are_going(web):
    with web.client() as c:
        first = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"], "browser": "chromium"})
        assert first.status_code == 200, first.text
        run_a = first.json()["run_id"]
        edge = c.post("/api/runs", json={"workbook": "bad.xlsx", "tests": ["FlowX"], "browser": "msedge"})
        assert edge.status_code == 409 and edge.json()["kind"] == "busy" and "share one set of workers" in edge.json()["error"] and edge.json()["run_id"] == run_a
        headed = c.post("/api/runs", json={"workbook": "bad.xlsx", "tests": ["FlowX"], "browser": "chromium", "headed": True})
        assert headed.status_code == 409 and "windows shown" not in headed.json()["error"] and "headless" in headed.json()["error"]
        assert len([r for r in c.get("/api/runs").json() if r["active"]]) == 1                                                        # the refused ones left nothing behind
        web.wait_finished(run_a, 200)


@pytest.mark.browser
def test_cancelling_one_of_two_runs_on_shared_workers_stops_that_run_only(web):
    with web.client() as c:
        started = c.post("/api/runs", json={**BOTH})
        assert started.status_code == 200, started.text
        keep, stop = started.json()["run_ids"]
        time.sleep(3)
        assert c.post(f"/api/runs/{stop}/cancel").json() == {"ok": True}
        done = web.wait_finished(stop, 200)
        assert done["meta"]["status"] == "CANCELLED" and done["meta"]["cancel_requested_at"]
        events = c.get(f"/api/runs/{stop}/events").json()["events"]
        assert events[-1]["type"] == "run_finished" and events[-1]["status"] == "CANCELLED"
        other = web.wait_finished(keep, 200)
        assert other["meta"]["status"] == "PASSED"                                                                                    # the other run did not notice
