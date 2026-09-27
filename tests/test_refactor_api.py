"""Duplicate/find-replace/merge routes (web/refactor_api.py), in-process (no browser)."""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from regrunner.config import load_config
from regrunner.web.app import create_app
from tests.workbook_factory import build_workbook

HEADERS = {"X-Requested-With": "regrunner"}


@pytest.fixture
def api(tmp_path):
    (tmp_path / "workbooks").mkdir()
    rows = build_workbook(tmp_path / "workbooks" / "mock.xlsx", flows=["FlowA"])
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({"runner": {"workers": 1}}))
    app = create_app(load_config(cfg_file, base_dir=tmp_path), str(cfg_file))
    client = TestClient(app, base_url="http://127.0.0.1", headers=HEADERS)
    client.rows = rows["FlowA"]
    return client


def test_find_preview_then_apply_writes_the_hits(api):
    preview = api.post("/api/build/workbooks/mock.xlsx/find", json={"pairs": [{"find": "Singapore", "replace": "Tokyo"}]})
    hits = preview.json()["hits"]
    assert hits and all(h["after"] == "Tokyo" for h in hits)

    r = api.post("/api/build/workbooks/mock.xlsx/find/apply", json={"hits": hits, "version": 1})
    assert r.status_code == 200
    assert r.json()["model"]["status"]["modified"] is True

    empty = api.post("/api/build/workbooks/mock.xlsx/find/apply", json={"hits": [], "version": 2})
    assert empty.status_code == 400 and empty.json()["kind"] == "empty"


def test_duplicate_candidates_lists_domain_and_name_rows(api):
    api.post("/api/build/workbooks/mock.xlsx/edit", json={"version": 1, "ops": [
        {"op": "set_environments", "names": ["UAT", "PROD"], "production": ["PROD"],
         "rows": [{"variable": "DOMAIN", "required": True, "values": {"UAT": "uat.example.test", "PROD": "www.example.com"}}]}]})
    r = api.get("/api/build/workbooks/mock.xlsx/duplicate-candidates", params={"newName": "Copy of mock"})
    rows = r.json()["rows"]
    assert any(row["kind"] == "domain" for row in rows)
    assert any(row["kind"] == "name" for row in rows)


def test_merge_pulls_a_picked_row_back_from_disk(api, tmp_path):
    path = tmp_path / "workbooks" / "mock.xlsx"
    model = api.get("/api/build/workbooks/mock.xlsx").json()
    row = api.rows["dep"]
    api.post("/api/build/workbooks/mock.xlsx/edit", json={"version": model["version"],
                                                          "ops": [{"op": "update_step", "test": "FlowA", "row": row, "set": {"value": "mine"}}]})
    # someone else edits the real file directly, behind the draft's back
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb["FlowA"]
    ws.cell(row, 13, "theirs")                                       # Value column
    wb.save(path)

    r = api.post("/api/build/workbooks/mock.xlsx/merge", json={"picks": {f"FlowA:{row}": "theirs"}})
    assert r.status_code == 200
    step = next(s for s in r.json()["model"]["tests"][0]["steps"] if s["row"] == row)
    assert step["value"] == "theirs"

    none_picked = api.post("/api/build/workbooks/mock.xlsx/merge", json={"picks": {}})
    assert none_picked.status_code == 400 and none_picked.json()["kind"] == "empty"
