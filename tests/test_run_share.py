"""Sharing a run: the whole folder as one zip, taking such a zip in from another computer (a stranger's file: nothing in it is trusted), keeping imported
runs out of this computer's own history, and reading what a test recorded of its session."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from regrunner import history
from tests.test_web_batches import fake_run
from tests.web_fixtures import web  # noqa: F401  (fixture)


def make_run(web, run_id: str, *, status="FAILED", workbook="mock.xlsx", extra: dict[str, str] | None = None) -> Path:
    fake_run(web, run_id, workbook=workbook, status=status, started_at="2026-05-01T10:00:00", batch_id="theirs", batch_label="Their batch")
    folder = web.run_dir(run_id)
    files = {
        "results.json": json.dumps({"run_id": run_id, "workbook": str(web.root / "workbooks" / workbook), "environment": "UAT", "status": status, "duration_s": 3.0,
                                    "tests": [{"id": "DTC_UAT", "sheet": "DTC_UAT", "status": status, "duration_s": 3.0, "total_steps": 2, "failed": 1,
                                               "steps": [{"seq": 1, "row": 3, "name": "Open", "action": "OPEN", "status": "PASSED", "notes": []},
                                                         {"seq": 2, "row": 4, "name": "Submit", "action": "CLICK", "status": "FAILED", "notes": ["Warning: x"]}]}]}),
        "events.jsonl": '{"type": "run_started"}\n', "report.html": "<html><script>1</script></html>", "runner.log": "log\n", "summary.txt": "s",
        "tests/DTC_UAT/screenshots/0001_r3_Open.jpg": "jpg", "tests/DTC_UAT/network.jsonl": json.dumps({"step": 2, "method": "POST", "url": "/bin/q", "status": 200,
                                                                                                         "request_body": "{}", "response_body": "{\"message\": \"system error\"}"}) + "\n",
        "tests/DTC_UAT/console.jsonl": json.dumps({"step": 1, "level": "pageerror", "text": "boom", "stack": "at x"}) + "\n",
        "tests/DTC_UAT/state.jsonl": json.dumps({"step": 1, "row": 3, "name": "Open", "url": "u", "full": True, "fields": {"dob2": {"label": "DOB", "value": ""}}}) + "\n",
        "tests/DTC_UAT/trace.zip": "TRACE", "cancel/DTC_UAT": "x", **(extra or {}),
    }
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return folder


def names_in(content: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(content)).namelist()


def zip_of(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, text in entries.items():
            z.writestr(name, text)
    return buffer.getvalue()


def post_zip(c, content: bytes, name="run.zip"):
    return c.post("/api/runs/import", files={"file": (name, content, "application/zip")})


def test_the_download_holds_the_whole_run_but_not_its_control_files_or_the_trace(web):
    make_run(web, "sh-1")
    with web.client() as c:
        res = c.get("/api/runs/sh-1/download.zip")
    assert res.status_code == 200 and res.headers["content-disposition"].endswith('sh-1.zip"')
    names = names_in(res.content)
    assert "sh-1/run.json" in names and "sh-1/results.json" in names and "sh-1/report.html" in names and "sh-1/share.json" in names
    assert "sh-1/tests/DTC_UAT/screenshots/0001_r3_Open.jpg" in names and "sh-1/tests/DTC_UAT/state.jsonl" in names
    assert not any("cancel" in n or "trace" in n for n in names)                       # a trace holds what was typed: only when asked for
    with web.client() as c:
        assert "sh-1/tests/DTC_UAT/trace.zip" in names_in(c.get("/api/runs/sh-1/download.zip?trace=1").content)


def test_downloading_a_run_that_does_not_exist_is_a_plain_404(web):
    with web.client() as c:
        assert c.get("/api/runs/nope-1/download.zip").status_code == 404


def test_a_run_goes_out_as_a_zip_and_comes_back_in_as_an_imported_run(web):
    make_run(web, "sh-2")
    with web.client() as c:
        download = c.get("/api/runs/sh-2/download.zip").content
        imported = post_zip(c, download)
        assert imported.status_code == 200, imported.text
        info = imported.json()
        assert info["run_id"] == "sh-2-imported" and info["original_run_id"] == "sh-2" and info["renamed"] and info["tests"] == 1      # (the original is still here)
        meta = json.loads((web.run_dir("sh-2-imported") / "run.json").read_text(encoding="utf-8"))
        assert meta["imported"] and meta["imported_from"] == "sh-2" and "batch_id" not in meta and meta["imported_batch"]["batch_id"] == "theirs"
        assert json.loads((web.run_dir("sh-2-imported") / "results.json").read_text(encoding="utf-8"))["run_id"] == "sh-2-imported"
        assert (web.run_dir("sh-2-imported") / "tests" / "DTC_UAT" / "screenshots" / "0001_r3_Open.jpg").is_file()
        listed = {r["run_id"]: r for r in c.get("/api/runs").json()}
        assert listed["sh-2-imported"]["imported"] is True and not listed["sh-2-imported"].get("batch_id")
        assert c.get("/api/runs/sh-2-imported").json()["results"]["tests"][0]["id"] == "DTC_UAT"
        assert not list((web.root / "runs").glob(".import-*"))                                                                       # nothing half-unpacked is left


def test_the_same_run_imported_with_its_own_name_when_it_is_free(web):
    make_run(web, "sh-3")
    with web.client() as c:
        download = c.get("/api/runs/sh-3/download.zip").content
        c.delete("/api/runs/sh-3")
        info = post_zip(c, download).json()
    assert info["run_id"] == "sh-3" and not info["renamed"]


def test_the_smaller_logs_zip_can_be_imported_too(web):
    make_run(web, "sh-4")
    with web.client() as c:
        logs = c.get("/api/runs/sh-4/logs.zip").content
        c.delete("/api/runs/sh-4")
        info = post_zip(c, logs, "sh-4-logs.zip").json()
    assert info["run_id"] == "sh-4" and info["tests"] == 1 and not info["has_screenshots"]


def test_zips_that_are_not_a_run_or_not_safe_are_refused_and_leave_nothing_behind(web):
    before = sorted(p.name for p in (web.root / "runs").iterdir())
    cases = {
        "not a zip": (b"hello", "x.zip", 400, "not a zip"),
        "wrong extension": (zip_of({"run.json": "{}"}), "x.txt", 400, "Choose the .zip"),
        "no run.json": (zip_of({"a.txt": "x"}), "x.zip", 400, "no run.json"),
        "no results": (zip_of({"r/run.json": "{}"}), "x.zip", 400, "nothing to look at"),
        "climbs out": (zip_of({"r/run.json": "{}", "r/results.json": "{}", "r/../../evil.txt": "x"}), "x.zip", 400, "unsafe"),
        "absolute path": (zip_of({"run.json": "{}", "results.json": "{}", "/etc/evil": "x"}), "x.zip", 400, "unsafe"),
        "drive letter": (zip_of({"run.json": "{}", "results.json": "{}", "C:/evil": "x"}), "x.zip", 400, "unsafe"),
        "two runs": (zip_of({"a/run.json": "{}", "a/results.json": "{}", "b/run.json": "{}", "b/results.json": "{}"}), "x.zip", 400, "several runs"),
        "bad run.json": (zip_of({"run.json": "{not json", "results.json": "{}"}), "x.zip", 400, "cannot be read"),
    }
    with web.client() as c:
        for label, (content, name, status, why) in cases.items():
            res = post_zip(c, content, name)
            assert res.status_code == status and why in res.json()["error"], (label, res.text)
    assert sorted(p.name for p in (web.root / "runs").iterdir()) == before
    assert not (web.root.parent / "evil.txt").exists() and not Path("/etc/evil").exists()


def test_a_run_brought_in_from_elsewhere_never_counts_in_this_computers_history_or_page_sandbox(web):
    make_run(web, "sh-5", workbook="mock.xlsx")
    with web.client() as c:
        info = post_zip(c, c.get("/api/runs/sh-5/download.zip").content).json()
        imported = info["run_id"]
        assert imported != "sh-5"
        ids = {r.run_id for r in history.load_runs(web.root / "runs", "mock.xlsx")}
        assert "sh-5" in ids and imported not in ids
        page = c.get(f"/runs/{imported}/files/report.html")
        assert page.headers["content-security-policy"] == "sandbox allow-scripts"                                                      # its scripts cannot call this interface
        assert "content-security-policy" not in c.get("/runs/sh-5/files/report.html").headers


def test_a_tests_session_comes_grouped_by_step(web):
    make_run(web, "sh-6")
    with web.client() as c:
        res = c.get("/api/results/runs/sh-6/tests/DTC_UAT/session")
        assert res.status_code == 200
        data = res.json()
        assert data["has"] == {"console": True, "network": True, "state": True, "bodies": True}
        assert data["steps"]["1"]["console"][0]["level"] == "pageerror" and data["steps"]["2"]["calls"][0]["response_body"].startswith("{")
        assert data["state"][0]["fields"]["dob2"]["label"] == "DOB" and data["traces"] == ["tests/DTC_UAT/trace.zip"]
        assert c.get("/api/results/runs/sh-6/tests/NOPE/session").status_code == 404
