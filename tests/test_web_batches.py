"""Batches (dev/plan/CONTRACT.md; engineering doc section 5): a UI label over runs that stay individual - their own id,
folder, results.json and report.  ``web/run_batch.py`` only groups run.json entries that share a ``batch_id``."""
from __future__ import annotations

import json

import pytest

from regrunner.runmeta import update_meta
from tests.web_fixtures import bad_run, web  # noqa: F401  (fixtures)

BOTH = {"workbooks": [{"workbook": "mock.xlsx", "tests": ["FlowA"]}, {"workbook": "bad.xlsx", "tests": ["FlowX"]}]}


def fake_run(web, run_id, *, workbook, status="PASSED", tests=1, started_at="2026-01-01T00:00:00", batch_id=None, batch_label=None):
    """A finished run's run.json, without actually running anything: what ``/api/batches`` reads is just this file."""
    fields = {"run_id": run_id, "workbook": str(web.root / "workbooks" / workbook), "environment": "UAT",
              "started_at": started_at, "ended_at": started_at, "status": status, "tests": tests,
              "test_ids": [f"T{i}" for i in range(tests)]}
    if batch_id:
        fields["batch_id"] = batch_id
    if batch_label:
        fields["batch_label"] = batch_label
    update_meta(web.run_dir(run_id), **fields)
    return run_id


def test_batches_group_and_summarize_the_runs_that_share_a_batch_id(web):
    fake_run(web, "b1-mock", workbook="mock.xlsx", status="PASSED", tests=3, started_at="2026-01-01T00:00:00", batch_id="b1", batch_label="Nightly")
    fake_run(web, "b1-bad", workbook="bad.xlsx", status="FAILED", tests=2, started_at="2026-01-01T00:00:05", batch_id="b1")
    fake_run(web, "solo", workbook="mock.xlsx", status="PASSED", tests=1, started_at="2026-01-01T00:00:10")     # no batch_id: not a batch
    with web.client() as c:
        batches = {b["id"]: b for b in c.get("/api/batches").json()}
        assert "b1" in batches and "solo" not in [rid for b in batches.values() for rid in b["run_ids"]]
        b1 = batches["b1"]
        assert b1["label"] == "Nightly" and b1["run_ids"] == ["b1-mock", "b1-bad"] and set(b1["workbooks"]) == {"mock.xlsx", "bad.xlsx"}
        assert b1["active"] is False and b1["tests"] == 5 and b1["passed"] == 1 and b1["failed"] == 1 and b1["finished"] == 2 and b1["total"] == 2
        assert b1["percent"] == 100 and b1["started_at"] == "2026-01-01T00:00:00" and b1["environment"] == "UAT"

        detail = c.get("/api/batches/b1").json()
        assert detail["id"] == "b1" and [r["run_id"] for r in detail["runs"]] == ["b1-mock", "b1-bad"]
        assert detail["runs"][0]["batch_label"] == "Nightly"

        missing = c.get("/api/batches/no-such-batch")
        assert missing.status_code == 404 and missing.json()["kind"] == "not_found"


def test_a_batch_label_defaults_to_the_batch_id_when_nobody_named_it(web):
    fake_run(web, "b2-mock", workbook="mock.xlsx", status="PASSED", tests=1, started_at="2026-01-02T00:00:00", batch_id="b2")
    fake_run(web, "b2-bad", workbook="bad.xlsx", status="PASSED", tests=1, started_at="2026-01-02T00:00:01", batch_id="b2")
    with web.client() as c:
        b2 = c.get("/api/batches/b2").json()
    assert b2["label"] == "Batch b2"


def test_last_durations_reads_only_the_most_recent_finished_run_of_each_named_workbook(web):
    older = web.run_dir("dur-old")
    update_meta(older, run_id="dur-old", workbook=str(web.root / "workbooks" / "mock.xlsx"), status="PASSED", started_at="2026-01-01T00:00:00")
    (older / "results.json").write_text(json.dumps({"tests": [{"id": "FlowA", "duration_s": 10.0}]}))
    newer = web.run_dir("dur-new")
    update_meta(newer, run_id="dur-new", workbook=str(web.root / "workbooks" / "mock.xlsx"), status="PASSED", started_at="2026-01-01T01:00:00")
    (newer / "results.json").write_text(json.dumps({"tests": [{"id": "FlowA", "duration_s": 20.0}, {"id": "FlowB", "duration_s": 5.0}]}))
    going = web.run_dir("dur-running")
    update_meta(going, run_id="dur-running", workbook=str(web.root / "workbooks" / "mock.xlsx"), status="RUNNING", started_at="2026-01-01T02:00:00")

    with web.client() as c:
        got = c.post("/api/batches/last-durations", json={"workbooks": ["mock.xlsx", "unknown.xlsx"]}).json()
    assert got == {"mock.xlsx": {"FlowA": 20.0, "FlowB": 5.0}}                     # the newer run's numbers, not the older one's; nothing for a workbook never run
    with web.client() as c:
        assert c.post("/api/batches/last-durations", json={"workbooks": []}).json() == {}


@pytest.mark.browser
def test_launching_two_workbooks_together_gets_one_batch_id_that_a_later_run_can_join(web):
    with web.client() as c:
        started = c.post("/api/runs", json={**BOTH, "workers": 2})
        assert started.status_code == 200, started.text
        body = started.json()
        batch_id = body["batch_id"]
        assert batch_id
        first, second = body["run_ids"]
        for rid in (first, second):
            assert c.get(f"/api/runs/{rid}").json()["meta"]["batch_id"] == batch_id
        listed = {b["id"]: b for b in c.get("/api/batches").json()}
        assert batch_id in listed and set(listed[batch_id]["run_ids"]) == {first, second}
        web.wait_finished(first, 240)
        web.wait_finished(second, 240)

        joined = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowB"], "batch_id": batch_id})     # "Add tests to this batch"
        assert joined.status_code == 200, joined.text
        third = joined.json()["run_id"]
        assert joined.json()["batch_id"] == batch_id
        assert c.get(f"/api/runs/{third}").json()["meta"]["batch_id"] == batch_id
        detail = c.get(f"/api/batches/{batch_id}").json()
        assert set(detail["run_ids"]) == {first, second, third}

        solo = c.post("/api/runs", json={"workbook": "bad.xlsx", "tests": ["FlowY"]})                              # a plain solo run: no batch at all
        assert solo.status_code == 200, solo.text
        assert solo.json().get("batch_id") is None
        assert "batch_id" not in c.get(f"/api/runs/{solo.json()['run_id']}").json()["meta"]

        web.wait_finished(third, 240)
        web.wait_finished(solo.json()["run_id"], 240)


# ---- deleting runs and batches ------------------------------------------------------------------------------------------------------
def test_deleting_one_run_of_a_batch_leaves_the_batch_with_one_run_fewer_and_keeps_the_folder_in_the_trash(web):
    fake_run(web, "d1-mock", workbook="mock.xlsx", started_at="2026-02-01T00:00:00", batch_id="d1")
    fake_run(web, "d1-bad", workbook="bad.xlsx", status="FAILED", started_at="2026-02-01T00:00:01", batch_id="d1")
    (web.run_dir("d1-bad") / "results.json").write_text("{}")
    with web.client() as c:
        gone = c.delete("/api/runs/d1-bad")
        assert gone.status_code == 200, gone.text
        assert gone.json()["deleted"] == ["d1-bad"]
        assert c.get("/api/runs/d1-bad").status_code == 404
        batch = c.get("/api/batches/d1").json()
        assert batch["run_ids"] == ["d1-mock"] and batch["total"] == 1 and batch["failed"] == 0
        assert "d1-bad" not in [r["run_id"] for r in c.get("/api/runs").json()]
    trashed = list((web.root / "runs" / ".trash").glob("*-d1-bad"))
    assert len(trashed) == 1 and (trashed[0] / "results.json").is_file()


def test_deleting_the_last_run_of_a_batch_makes_the_batch_disappear(web):
    fake_run(web, "d2-only", workbook="mock.xlsx", started_at="2026-02-02T00:00:00", batch_id="d2")
    with web.client() as c:
        assert c.delete("/api/runs/d2-only").status_code == 200
        assert "d2" not in [b["id"] for b in c.get("/api/batches").json()]
        assert c.get("/api/batches/d2").status_code == 404


def test_deleting_a_batch_removes_every_run_in_it_and_no_other_run(web):
    fake_run(web, "d3-a", workbook="mock.xlsx", started_at="2026-02-03T00:00:00", batch_id="d3")
    fake_run(web, "d3-b", workbook="bad.xlsx", started_at="2026-02-03T00:00:01", batch_id="d3")
    fake_run(web, "d3-other", workbook="mock.xlsx", started_at="2026-02-03T00:00:02", batch_id="d3-elsewhere")
    fake_run(web, "d3-solo", workbook="mock.xlsx", started_at="2026-02-03T00:00:03")
    with web.client() as c:
        gone = c.delete("/api/batches/d3")
        assert gone.status_code == 200, gone.text
        assert sorted(gone.json()["deleted"]) == ["d3-a", "d3-b"]
        assert c.get("/api/batches/d3").status_code == 404
        left = {r["run_id"] for r in c.get("/api/runs").json()}
        assert {"d3-other", "d3-solo"} <= left and not ({"d3-a", "d3-b"} & left)
        assert c.get("/api/batches/d3-elsewhere").status_code == 200
        assert c.delete("/api/batches/d3").status_code == 404                       # already gone


def test_a_running_run_cannot_be_deleted_and_a_batch_with_one_running_run_moves_nothing(web):
    fake_run(web, "d4-done", workbook="mock.xlsx", started_at="2026-02-04T00:00:00", batch_id="d4")
    fake_run(web, "d4-live", workbook="bad.xlsx", status="RUNNING", started_at="2026-02-04T00:00:01", batch_id="d4")
    (web.run_dir("d4-live") / "events.jsonl").write_text("")                        # fresh events + RUNNING = the UI counts it as going
    with web.client() as c:
        one = c.delete("/api/runs/d4-live")
        assert one.status_code == 409 and one.json()["kind"] == "busy"
        many = c.delete("/api/batches/d4")
        assert many.status_code == 409 and many.json()["kind"] == "busy"
        assert c.get("/api/runs/d4-done").status_code == 200                        # the finished one was not touched either


def test_only_real_runs_can_be_deleted_never_the_trash_or_the_build_folders(web):
    fake_run(web, "d5-a", workbook="mock.xlsx", started_at="2026-02-05T00:00:00")
    with web.client() as c:
        assert c.delete("/api/runs/d5-a").status_code == 200                        # makes runs/.trash
        (web.root / "runs" / ".build").mkdir(exist_ok=True)
        for odd in (".trash", ".build", "no-such-run"):
            assert c.delete(f"/api/runs/{odd}").status_code == 404, odd
    assert (web.root / "runs" / ".trash").is_dir() and (web.root / "runs" / ".build").is_dir()


def test_deleting_the_same_run_id_twice_in_one_second_keeps_both_copies(web):
    with web.client() as c:
        for _ in range(2):
            fake_run(web, "d6-again", workbook="mock.xlsx", started_at="2026-02-06T00:00:00")
            assert c.delete("/api/runs/d6-again").status_code == 200
    assert len(list((web.root / "runs" / ".trash").glob("*-d6-again*"))) == 2
