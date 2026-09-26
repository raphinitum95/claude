"""``/api/build/*`` (web/build_api.py): the Workbook Builder's routes, in-process (no browser, no server thread)."""
from __future__ import annotations


import pytest
import yaml
from fastapi.testclient import TestClient

from regrunner.config import load_config
from regrunner.web.app import create_app
from regrunner.workbook.writer import draft_path
from tests.workbook_factory import build_workbook

HEADERS = {"X-Requested-With": "regrunner"}


@pytest.fixture
def api(tmp_path):
    (tmp_path / "workbooks").mkdir()
    rows = build_workbook(tmp_path / "workbooks" / "mock.xlsx", flows=["FlowA", "FlowB"])
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({"runner": {"workers": 1}}))
    app = create_app(load_config(cfg_file, base_dir=tmp_path), str(cfg_file))
    client = TestClient(app, base_url="http://127.0.0.1", headers=HEADERS)     # no lifespan: nothing starts a browser
    client.rows = rows["FlowA"]
    client.root = tmp_path
    return client


def test_the_model_route_returns_tests_blocks_steps_variables_and_status(api):
    model = api.get("/api/build/workbooks/mock.xlsx").json()
    assert model["name"] == "mock.xlsx" and model["environment"] == "UAT"
    assert [t["id"] for t in model["tests"]] == ["FlowA", "FlowB"]
    assert model["tests"][0]["blocks"][0]["title"] == "Open" and model["tests"][0]["steps"][0]["n"] == 1
    assert model["status"] == {"version": 1, "modified": False, "hasDraft": False, "draftSaved": None, "externalChange": False,
                               "locked": False, "canUndo": False, "canRedo": False, "file": "mock.xlsx"}
    assert api.get("/api/build/workbooks/nope.xlsx").status_code == 404


def test_edits_need_the_page_header_and_the_current_version(api):
    body = {"version": 1, "ops": [{"op": "update_step", "test": "FlowA", "row": api.rows["dep"], "set": {"timeout": 12}}]}
    bare = TestClient(api.app, base_url="http://127.0.0.1")
    assert bare.post("/api/build/workbooks/mock.xlsx/edit", json=body).status_code == 403
    stale = api.post("/api/build/workbooks/mock.xlsx/edit", json={**body, "version": 0})
    assert stale.status_code == 409 and stale.json()["kind"] == "stale" and stale.json()["version"] == 1
    ok = api.post("/api/build/workbooks/mock.xlsx/edit", json=body).json()
    assert ok["applied"] == [{"op": "update_step", "test": "FlowA", "row": api.rows["dep"]}]
    step = next(s for s in ok["model"]["tests"][0]["steps"] if s["row"] == api.rows["dep"])
    assert step["timeout"] == 12 and ok["model"]["status"]["modified"] and ok["model"]["version"] == 2
    assert draft_path(api.root / "workbooks" / "mock.xlsx").is_file()


def test_a_bad_op_is_refused_with_its_index_and_nothing_changes(api):
    r = api.post("/api/build/workbooks/mock.xlsx/edit", json={"ops": [
        {"op": "update_step", "test": "FlowA", "row": api.rows["dep"], "set": {"timeout": 3}},
        {"op": "update_step", "test": "FlowA", "row": api.rows["cost_yes"], "set": {"value": "x"}}]})
    assert r.status_code == 422 and r.json()["kind"] == "legacy" and r.json()["index"] == 1
    assert api.get("/api/build/workbooks/mock.xlsx/status").json()["modified"] is False
    assert api.post("/api/build/workbooks/mock.xlsx/edit", json={"ops": []}).status_code == 400


def test_undo_redo_save_history_diff_and_restore(api):
    row = api.rows["ret"]
    api.post("/api/build/workbooks/mock.xlsx/edit", json={"ops": [{"op": "delete_steps", "test": "FlowA", "rows": [row]}]})
    diff = api.get("/api/build/workbooks/mock.xlsx/diff").json()["changes"]
    assert [(c["kind"], c["before"]["name"]) for c in diff] == [("removed", "Return Date")]
    undone = api.post("/api/build/workbooks/mock.xlsx/undo").json()["model"]
    assert undone["status"]["canRedo"] and not undone["status"]["modified"]
    assert api.post("/api/build/workbooks/mock.xlsx/undo").status_code == 409
    api.post("/api/build/workbooks/mock.xlsx/redo")
    saved = api.post("/api/build/workbooks/mock.xlsx/save", json={}).json()
    assert saved["backup"].startswith("mock.") and saved["status"]["modified"] is False
    history = api.get("/api/build/workbooks/mock.xlsx/history").json()
    assert [h["id"] for h in history] == [saved["backup"]]
    restored = api.post("/api/build/workbooks/mock.xlsx/restore", json={"id": saved["backup"]}).json()["model"]
    assert any(s["name"] == "Return Date" for s in restored["tests"][0]["steps"]) and restored["status"]["modified"]
    assert api.post("/api/build/workbooks/mock.xlsx/restore", json={"id": "../../secrets.env"}).status_code == 404
    reloaded = api.post("/api/build/workbooks/mock.xlsx/reload").json()["model"]
    assert not any(s["name"] == "Return Date" for s in reloaded["tests"][0]["steps"]) and not reloaded["status"]["hasDraft"]


def test_a_workbook_open_in_excel_cannot_be_saved(api):
    api.post("/api/build/workbooks/mock.xlsx/edit", json={"ops": [{"op": "update_step", "test": "FlowA", "row": api.rows["dep"],
                                                                  "set": {"timeout": 4}}]})
    lock = api.root / "workbooks" / "~$mock.xlsx"
    lock.write_text("x")
    r = api.post("/api/build/workbooks/mock.xlsx/save", json={})
    assert r.status_code == 423 and r.json()["kind"] == "locked" and "Close it in Excel" in r.json()["error"]
    assert api.get("/api/build/workbooks/mock.xlsx/status").json()["locked"] is True
    lock.unlink()
    assert api.post("/api/build/workbooks/mock.xlsx/save", json={}).status_code == 200


def test_variables_problems_environments_fingerprints_and_the_grid(api):
    variables = api.get("/api/build/workbooks/mock.xlsx/variables").json()
    assert any(v["key"] == "PREMIUM_OUT" and v["setBy"] for v in variables)
    api.post("/api/build/workbooks/mock.xlsx/edit", json={"ops": [
        {"op": "set_environments", "names": ["UAT", "PROD"], "production": ["PROD"],
         "rows": [{"variable": "DOMAIN", "required": True, "values": {"UAT": "", "PROD": "https://example"}}]},
        {"op": "set_fingerprint", "name": "Payment page", "urlContains": "/payment", "landmark": "css=h1"}]})
    problems = api.get("/api/build/workbooks/mock.xlsx/problems").json()
    assert problems["environment"] == "UAT" and any(p["kind"] == "missing_environment_value" and p["severity"] == "error"
                                                    for p in problems["problems"])
    assert not any(p["kind"] == "missing_environment_value" and p["severity"] == "error"
                   for p in api.get("/api/build/workbooks/mock.xlsx/problems?env=PROD").json()["problems"])
    assert api.get("/api/build/workbooks/mock.xlsx/environments").json()["production"] == ["PROD"]
    assert api.get("/api/build/workbooks/mock.xlsx/fingerprints").json()[0]["urlContains"] == "/payment"
    grid = api.get("/api/build/workbooks/mock.xlsx/sheets/flowa").json()
    assert grid["name"] == "FlowA" and grid["headers"][0] == "blnExecute" and grid["rows"][0][0] == "Open"
    assert api.get("/api/build/workbooks/mock.xlsx/sheets/_rr_environments").json()["hidden"] is True
    assert api.get("/api/build/workbooks/mock.xlsx/sheets/Nope").status_code == 404


def test_new_workbooks_are_created_from_scratch_or_as_a_copy(api):
    r = api.post("/api/build/workbooks", json={"name": "Qantas new", "environments": [
        {"name": "UAT", "domain": "https://uat.example"}, {"name": "PROD", "domain": "https://example", "production": True}]})
    assert r.status_code == 201 and r.json()["name"] == "Qantas new.xlsx"
    assert r.json()["model"]["environments"]["rows"][0]["values"] == {"UAT": "https://uat.example", "PROD": "https://example"}
    assert (api.root / "workbooks" / "Qantas new.xlsx").is_file()
    assert api.post("/api/build/workbooks", json={"name": "Qantas new"}).status_code == 409
    copy = api.post("/api/build/workbooks", json={"name": "../copy of mock.xlsx", "from": "mock.xlsx"})
    assert copy.status_code == 201 and copy.json()["name"] == "copy of mock.xlsx"
    assert [t["id"] for t in copy.json()["model"]["tests"]] == ["FlowA", "FlowB"]
    assert any(w["name"] == "Qantas new.xlsx" for w in api.get("/api/workbooks").json())


def test_the_keyword_catalogue_groups_every_action(api):
    data = api.get("/api/build/keywords").json()
    groups = {g["group"]: [m["method"] for m in g["methods"]] for g in data["groups"]}
    assert "CLICK" in groups["Do"] and "SET" in groups["Type"] and "ASSERT_PAGE" in groups["Check"] and "WAIT_UNTIL" in groups["Wait"]
    assert "CALL_TEST" in groups["Flow"] and "GO_TO_ROW" in data["legacy"] and "IF" in data["newKeywords"]
    assert not set(data["legacy"]) & {m for ms in groups.values() for m in ms}
