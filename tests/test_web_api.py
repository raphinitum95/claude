"""The web backend: guards, command building, uploads, workbook insight, run lifecycle and recovery."""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from regrunner.web.app import StartRun, cli_flags, command_tokens, quote_arg
from regrunner.config import Config
from tests.web_fixtures import HEADERS, bad_run, web  # noqa: F401  (fixtures)


def zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------
def test_config_and_preflight_report_state_without_leaking_secrets(web):
    with web.client() as c:
        cfg = c.get("/api/config")
        pre = c.get("/api/preflight")
    data = cfg.json()
    assert data["workers"] == 2 and data["tags"] == {"smoke": ["FlowA"]} and data["cookie_name"] == "recaptchaBypassToken"
    assert data["tokens"]["UAT"] is True and data["tokens"]["PROD"] is False
    assert data["max_workers"] == 8 and data["nice"] is True and data["pdf"] is False and data["harvest"] is False
    checks = {x["id"]: x for x in pre.json()["checks"]}
    assert checks["browser"]["status"] == "ok" and checks["sso"]["status"] == "warn" and checks["sso"]["action"] == "sign_in"
    assert checks["token_UAT"]["status"] == "ok" and checks["folder_runs"]["status"] == "ok"
    assert "TEST-UAT-TOKEN" not in cfg.text + pre.text                         # only set/missing ever leaves the server


def test_secrets_env_edits_apply_without_restarting_the_server(web, monkeypatch):
    monkeypatch.delenv("RECAPTCHA_BYPASS_TOKEN_QA", raising=False)
    secrets = web.root / "secrets.env"
    with web.client() as c:
        assert c.get("/api/config").json()["tokens"]["QA"] is False
        secrets.write_text("RECAPTCHA_BYPASS_TOKEN_QA=qa-secret\n")
        assert c.get("/api/config").json()["tokens"]["QA"] is True
        secrets.write_text("# removed\n")
        assert c.get("/api/config").json()["tokens"]["QA"] is False
    secrets.unlink()


def test_state_changing_requests_must_come_from_the_page(web):
    body = {"workbook": "mock.xlsx", "all": True}
    with httpx.Client(base_url=web.base) as bare:                              # what another website could send
        assert bare.get("/api/config").status_code == 200                      # reads are fine
        assert bare.post("/api/runs/command", json=body).status_code == 403
        assert bare.post("/api/runs/command", json=body, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
        assert bare.post("/api/runs/command", json=body, headers={**HEADERS, "Origin": web.base}).status_code == 200
        # DNS-rebinding: a hostile name pointing at 127.0.0.1 is refused outright
        assert bare.get("/api/config", headers={"Host": "attacker.example:8765"}).status_code == 403


@pytest.mark.parametrize("request_body, expected", [
    ({"all": True}, "regrunner run mock.xlsx --all"),
    ({"tests": ["FlowA", "FlowB"]}, "regrunner run mock.xlsx --tests FlowA,FlowB"),
    ({"tests": ["FlowA"], "env": "qa", "workers": 3, "screenshots": "on_failure", "retries": 2, "seed": 7, "pdf": True,
      "harvest": True, "headed": True, "nice": False, "no_report": True},
     "regrunner run mock.xlsx --tests FlowA --env QA --workers 3 --screenshots on_failure --retries 2 --seed 7 --pdf "
     "--harvest --headed --no-nice --no-report"),
    ({"all": True, "workers": 2, "screenshots": "every_step", "retries": 0, "pdf": False, "harvest": False, "nice": True},
     "regrunner run mock.xlsx --all"),                                         # values equal to config.yaml add no flags
    ({"all": True, "env": "PROD", "allow_prod": True}, "regrunner run mock.xlsx --all --env PROD --allow-prod"),
    ({"all": True, "env": "UAT", "allow_prod": True}, "regrunner run mock.xlsx --all --env UAT"),
])
def test_command_preview_lists_only_what_differs_from_config(web, request_body, expected):
    with web.client() as c:
        res = c.post("/api/runs/command", json={"workbook": "mock.xlsx", **request_body})
    assert res.status_code == 200 and res.json()["text"] == expected
    kinds = {t["k"] for t in res.json()["tokens"]}
    assert kinds <= {"cmd", "arg", "flag", "value"}


def test_workbook_names_with_spaces_and_quotes_are_quoted_for_a_terminal():
    assert quote_arg("plain.xlsx") == "plain.xlsx"
    assert quote_arg("UAT Regression v9.1.xlsx") == '"UAT Regression v9.1.xlsx"'
    assert quote_arg('odd "name".xlsx') == '"odd \\"name\\".xlsx"'
    cfg = Config()
    flags = cli_flags(StartRun(workbook="x", tests=["A"], workers=cfg.effective_workers), cfg, "UAT")
    assert [t["t"] for t in command_tokens("My Book.xlsx", flags)] == ["regrunner", "run", '"My Book.xlsx"', "--tests", "A"]


def test_upload_is_validated_by_type_content_and_size_and_names_are_sanitised(web, monkeypatch):
    good = (web.root / "workbooks" / "mock.xlsx").read_bytes()
    with web.client() as c:
        wrong_type = c.post("/api/workbooks", files={"file": ("evil.exe", b"MZ")})
        assert wrong_type.status_code == 400 and wrong_type.json()["kind"] == "type"
        not_zip = c.post("/api/workbooks", files={"file": ("fake.xlsx", b"not a zip")})
        assert not_zip.status_code == 400 and not_zip.json()["kind"] == "content"
        other_zip = c.post("/api/workbooks", files={"file": ("doc.xlsx", zip_bytes({"hello.txt": "hi"}))})
        assert other_zip.status_code == 400 and other_zip.json()["kind"] == "content"    # a zip, but not a workbook
        sneaky = c.post("/api/workbooks", files={"file": ("../../escape.xlsx", good)})
        assert sneaky.status_code == 200 and sneaky.json()["name"] == "escape.xlsx"
        assert (web.root / "workbooks" / "escape.xlsx").is_file() and not (web.root.parent / "escape.xlsx").exists()
        monkeypatch.setattr("regrunner.web.app.MAX_UPLOAD_MB", 0.01)             # ~10 KB ceiling
        too_big = c.post("/api/workbooks", files={"file": ("big.xlsx", good)})
        assert too_big.status_code == 413 and too_big.json()["kind"] == "size"
        monkeypatch.undo()
        assert {w["name"] for w in c.get("/api/workbooks").json()} >= {"mock.xlsx", "bad.xlsx", "escape.xlsx"}
    (web.root / "workbooks" / "escape.xlsx").unlink()


def test_workbook_insight_endpoints(web):
    with web.client() as c:
        info = c.get("/api/workbooks/mock.xlsx/tests").json()
        assert [t["id"] for t in info["tests"]] == ["FlowA", "FlowB"] and all(t["steps"] > 40 for t in info["tests"])
        assert info["sheets"] == 2 and info["flagged"] == 2 and info["environment"] == "UAT" and info["name"] == "mock.xlsx"
        assert {t["id"]: t["tags"] for t in info["tests"]} == {"FlowA": ["smoke"], "FlowB": ["full"]}
        assert all("captcha" not in json.dumps(t).lower() for t in info["tests"])          # the cookie is always sent

        lint = c.post("/api/workbooks/mock.xlsx/lint", json={}).json()
        assert lint["counts"]["warning"] >= 1 and any("never implemented" in f["message"] for f in lint["findings"])

        plan = c.post("/api/workbooks/mock.xlsx/plan", json={"test": "FlowA"}).json()
        assert plan["count"] > 40 and plan["steps"][0]["n"] == 1 and {"row", "action", "name", "target", "value"} <= plan["steps"][0].keys()
        assert c.post("/api/workbooks/mock.xlsx/plan", json={"test": "Nope"}).status_code == 404
        assert c.post("/api/workbooks/mock.xlsx/plan", json={}).status_code == 400

        audit = c.post("/api/workbooks/mock.xlsx/audit", json={}).json()
        assert audit["uses"] > 0 and audit["map_entries"] == 0 and audit["covered_pct"] == 0 and audit["weakest"]

        assert c.get("/api/workbooks/mock.xlsx/start-url").json()["url"] == web.site
        assert c.get("/api/workbooks/missing.xlsx/tests").status_code == 404


def test_an_unreadable_workbook_is_reported_with_details(web):
    junk = zip_bytes({"xl/workbook.xml": "<not really a workbook>"})
    with web.client() as c:
        assert c.post("/api/workbooks", files={"file": ("junk.xlsx", junk)}).status_code == 200
        res = c.get("/api/workbooks/junk.xlsx/tests")
    assert res.status_code == 422 and res.json()["kind"] == "unreadable"
    assert res.json()["error"].startswith("Could not read workbook") and res.json()["details"]
    (web.root / "workbooks" / "junk.xlsx").unlink()


def test_runs_are_refused_before_anything_starts_when_the_request_is_unsafe_or_wrong(web):
    with web.client() as c:
        before = c.get("/api/runs").json()
        unconfirmed = c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "env": "PROD"})
        assert unconfirmed.status_code == 400 and unconfirmed.json()["kind"] == "prod_confirm"
        flag_only = c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "env": "PROD", "allow_prod": True})
        assert flag_only.status_code == 400 and flag_only.json()["kind"] == "prod_confirm"
        wrong_word = c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "env": "PROD", "allow_prod": True, "confirm_prod": "prod"})
        assert wrong_word.status_code == 400
        bad = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["Nope"]})
        assert bad.status_code == 422 and bad.json()["kind"] == "selection" and "Available: FlowA, FlowB" in bad.json()["error"]
        assert c.post("/api/runs", json={"workbook": "missing.xlsx", "all": True}).status_code == 404
        assert c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "workers": 0}).status_code == 422
        assert c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "screenshots": "sometimes"}).status_code == 422
        assert c.post("/api/runs", json={"workbook": "mock.xlsx", "all": True, "env": "UAT; rm -rf /"}).status_code == 422
        assert c.get("/api/runs").json() == before                                  # nothing was started or created


# ---------------------------------------------------------------------------------------------------
@pytest.mark.browser
def test_options_reach_the_run_and_the_run_records_how_it_was_started(web, bad_run):
    with web.client() as c:
        detail = c.get(f"/api/runs/{bad_run}").json()
        meta, results = detail["meta"], detail["results"]
        events = c.get(f"/api/runs/{bad_run}/events").json()["events"]
    assert meta["status"] == "FAILED" and meta["test_ids"] == ["FlowX", "FlowY"] and meta["tests"] == 2
    assert meta["command"] == "regrunner run bad.xlsx --tests FlowX,FlowY --harvest"
    assert meta["params"]["harvest"] is True and meta["params"]["workers"] == 2 and meta["params"]["screenshots"] == "every_step"
    assert detail["files"]["suggestions"] is True and detail["files"]["report_html"] and detail["files"]["screenshots"] > 50
    start = next(e for e in events if e["type"] == "run_started")
    assert start["params"] == meta["params"] and [t["id"] for t in start["tests"]] == ["FlowX", "FlowY"]
    assert results["summary"]["tests"] == 2 and results["summary"]["steps_failed"] == 2

    # the extra fields the UI draws from
    boxes = [e["box"] for e in events if e["type"] == "screenshot_saved" and e.get("box")]
    assert boxes and all(0 <= b["x"] <= 100 and 0 <= b["y"] <= 100 and b["w"] > 0 and b["h"] > 0 for b in boxes)
    step_events = [e for e in events if e["type"] in ("step_passed", "step_failed") and e.get("locator")]
    assert {e["locator_origin"] for e in step_events} == {"legacy"} and any("fallback" in e for e in step_events)
    for finished in (e for e in events if e["type"] == "test_finished"):
        expected = [i["count"] for t in results["tests"] if t["id"] == finished["test"] for i in t["review"]]
        assert finished["review_counts"] == expected
    failed_step = next(s for t in results["tests"] for s in t["steps"] if s["status"] == "FAILED")
    assert failed_step["comparison"] == "exact" and failed_step["expected"] == "$1.00"
    assert failed_step["locator"] == "" and failed_step["locator_origin"] == ""          # element absent at that point: nothing matched


@pytest.mark.browser
def test_cancel_and_a_workbook_cannot_be_run_twice_at_once(web):
    with web.client() as c:
        first = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowA"]})
        assert first.status_code == 200
        run_id = first.json()["run_id"]
        second = c.post("/api/runs", json={"workbook": "mock.xlsx", "tests": ["FlowB"]})
        assert second.status_code == 409 and second.json()["kind"] == "busy" and second.json()["run_id"] == run_id
        assert "mock.xlsx is already being run" in second.json()["error"]
        listed = next(r for r in c.get("/api/runs").json() if r["run_id"] == run_id)
        assert listed["active"] is True and listed["test_ids"] == ["FlowA"]
        time.sleep(2)
        assert c.post(f"/api/runs/{run_id}/cancel").json() == {"ok": True}
        detail = web.wait_finished(run_id)
        assert detail["meta"]["status"] == "CANCELLED" and detail["meta"]["cancel_grace_s"] == 45 and detail["meta"]["cancel_requested_at"]
        events = c.get(f"/api/runs/{run_id}/events").json()["events"]
        assert events[-1]["type"] == "run_finished" and events[-1]["status"] == "CANCELLED"
        assert c.post("/api/runs/nope-123/cancel").status_code == 404


@pytest.mark.browser
def test_sign_in_flow_saves_a_private_session_and_refuses_bad_addresses(web):
    with web.client() as c:
        assert c.post("/api/auth/save").status_code == 409                          # nothing open yet
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "", "example.com"):
            assert c.post("/api/auth/login", json={"url": bad}).status_code == 400
        assert c.get("/api/auth").json()["present"] is False
        opened = c.post("/api/auth/login", json={"url": web.site})
        assert opened.status_code == 200 and opened.json()["window_open"] is True
        assert c.get("/api/auth").json()["window_open"] is True
        saved = c.post("/api/auth/save")
        assert saved.status_code == 200 and saved.json()["saved"] is True
        state = web.root / ".auth" / "state.json"
        assert state.is_file() and json.loads(state.read_text())["cookies"] is not None
        if sys.platform != "win32":
            assert stat.S_IMODE(state.stat().st_mode) == 0o600
        pre = c.get("/api/preflight").json()
        assert pre["sso"]["present"] is True and {x["id"]: x for x in pre["checks"]}["sso"]["status"] == "ok"
        assert c.post("/api/auth/login", json={"url": web.site}).status_code == 200
        assert c.post("/api/auth/cancel").json() == {"window_open": False}
        assert c.get("/api/auth").json()["window_open"] is False
    state.unlink()


# ---------------------------------------------------------------------------------------------------
def make_interrupted_copy(web, source_id: str, name: str) -> str:
    """A run that died mid-flight: the event log stops after the first finished test and nothing else was written."""
    src, dst = web.run_dir(source_id), web.run_dir(name)
    shutil.copytree(src, dst)
    lines = (src / "events.jsonl").read_text().splitlines()
    cut = next(i for i, line in enumerate(lines) if '"test_finished"' in line)
    (dst / "events.jsonl").write_text("\n".join(lines[: cut + 1]) + "\n")
    for gone in ("results.json", "report.html", "selector_suggestions.json"):
        (dst / gone).unlink(missing_ok=True)
    meta = json.loads((dst / "run.json").read_text())
    for key in ("ended_at", "summary", "artifacts", "duration_s"):
        meta.pop(key, None)
    meta.update(run_id=name, status="RUNNING")
    (dst / "run.json").write_text(json.dumps(meta))
    old = time.time() - 600
    os.utime(dst / "events.jsonl", (old, old))
    return name


@pytest.mark.browser
def test_an_interrupted_run_is_detected_and_its_report_can_be_rebuilt_from_events(web, bad_run):
    run_id = make_interrupted_copy(web, bad_run, "20260101-000000-UAT")
    with web.client() as c:
        listed = next(r for r in c.get("/api/runs").json() if r["run_id"] == run_id)
        assert listed["status"] == "INTERRUPTED" and listed["active"] is False
        assert c.get(f"/api/runs/{run_id}").json()["results"] is None
        built = c.post(f"/api/runs/{run_id}/report", json={"from_events": True})
        assert built.status_code == 200 and built.json()["artifacts"]["report_html"] == "report.html"
        results = c.get(f"/api/runs/{run_id}").json()["results"]
        assert results["partial"] is True and results["status"] == "INTERRUPTED"
        by = {t["id"]: t for t in results["tests"]}
        assert sorted(t["status"] for t in by.values()) == ["FAILED", "INTERRUPTED"]
        finished = next(t for t in by.values() if t["status"] == "FAILED")
        assert any(step["status"] == "FAILED" for step in finished["steps"])
        report = c.get(f"/runs/{run_id}/files/report.html").text
        assert "rebuilt from the event log" in report and "INTERRUPTED" in report
        assert c.post(f"/api/runs/{bad_run}/report", json={}).status_code == 200      # a normal rebuild still works
        assert c.post("/api/runs/20260101-999999-UAT/report", json={}).status_code == 404


def test_harvested_locators_can_be_reviewed_and_merged_selectively(web):
    run_id = "20260101-000001-UAT"
    run_dir = web.run_dir(run_id)
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "status": "PASSED", "started_at": "2026-01-01T00:00:01"}))
    (run_dir / "selector_suggestions.json").write_text(json.dumps({"suggestions": {
        "xpath=//input[3]": {"use": ['css=input[name="a"]'], "index": 0, "score": 90, "kind": "name", "legacy_score": 30, "uses": 4, "example_step": "Age"},
        "xpath=//button[9]": {"use": ["css=#go"], "index": 0, "score": 92, "kind": "id", "legacy_score": 20, "uses": 2, "example_step": "Go"}},
        "skipped": {"xpath=//div[2]": "no unique, clearly more stable locator for at least one use"}}))
    with web.client() as c:
        shown = c.get(f"/api/runs/{run_id}/selectors").json()
        assert shown["available"] and [s["key"] for s in shown["suggestions"]] == ["xpath=//button[9]", "xpath=//input[3]"]
        assert shown["skipped"][0]["reason"].startswith("no unique") and shown["already"] == 0
        applied = c.post(f"/api/runs/{run_id}/selectors/apply", json={"keys": ["xpath=//input[3]"]}).json()
        assert applied["added"] == 1 and applied["total"] == 1
        again = c.get(f"/api/runs/{run_id}/selectors").json()
        assert [s["key"] for s in again["suggestions"]] == ["xpath=//button[9]"] and again["already"] == 1
        assert c.post(f"/api/runs/{run_id}/selectors/apply", json={}).json()["added"] == 1
    assert "css=input[name=\"a\"]" in (web.root / "selectors.yaml").read_text()
    with web.client() as c:
        assert c.get("/api/runs/20260101-000002-UAT/selectors").json()["available"] is False


def test_show_folder_opens_only_the_runs_own_folders(web, monkeypatch, bad_run):
    opened: list[list[str]] = []
    monkeypatch.setattr("regrunner.web.app.subprocess.Popen", lambda args, **kw: opened.append(args))
    with web.client() as c:
        assert c.post(f"/api/runs/{bad_run}/reveal", json={"folder": "tests"}).status_code == 200
        assert c.post(f"/api/runs/{bad_run}/reveal", json={"folder": "../.."}).status_code == 200
        assert c.post("/api/runs/nope/reveal").status_code == 404
    assert opened[0][-1] == str(web.run_dir(bad_run) / "tests") and opened[1][-1] == str(web.run_dir(bad_run))


def test_run_files_cannot_escape_their_folder_and_logs_are_bounded(web, bad_run):
    with web.client() as c:
        assert c.get(f"/runs/{bad_run}/files/../../config.yaml").status_code in (400, 404)
        assert c.get(f"/runs/{bad_run}/files/%2e%2e/%2e%2e/config.yaml").status_code in (400, 404)
        assert c.get(f"/runs/{bad_run}/files/results.json?download=1").headers["content-disposition"].startswith("attachment")
        assert c.get("/runs/bad id/files/x").status_code in (400, 404)
        assert isinstance(c.get(f"/api/runs/{bad_run}/log?tail=5").json()["lines"], list)
        assert len(c.get(f"/api/runs/{bad_run}/log?tail=5").json()["lines"]) <= 5
        assert c.get("/api/runs/does-not-exist").status_code == 404


def test_the_page_carries_a_strict_content_security_policy(web):
    with web.client() as c:
        res = c.get("/")
        csp = res.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "default-src 'self'" in csp
        assert res.headers["x-frame-options"] == "DENY" and "unsafe-inline" not in csp.split("style-src")[0]     # no inline script
        assert c.get("/static/js/main.js").status_code == 200 and c.get("/static/app.css").status_code == 200
