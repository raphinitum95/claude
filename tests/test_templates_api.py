"""``/api/build/templates*`` (web/templates_api.py): the shared template library, in-process (no browser)."""
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


def test_library_starts_empty_then_save_list_and_map(api):
    assert api.get("/api/build/templates").json() == {"templates": []}
    r = api.post("/api/build/templates", json={"workbook": "mock.xlsx", "test": "FlowA", "fromRow": api.rows["open"],
                                                "toRow": api.rows["open"], "name": "Open browser", "description": "just Open"})
    assert r.status_code == 201 and r.json() == {"name": "Open browser", "count": 1}

    listed = api.get("/api/build/templates").json()["templates"]
    assert len(listed) == 1 and listed[0]["name"] == "Open browser" and listed[0]["description"] == "just Open"

    mapping = api.get("/api/build/templates/Open browser/mapping", params={"workbook": "mock.xlsx"}).json()
    assert mapping["template"]["count"] == 1
    assert isinstance(mapping["mapping"], list)


def test_saving_a_duplicate_name_is_refused_and_unknown_template_404s(api):
    body = {"workbook": "mock.xlsx", "test": "FlowA", "fromRow": api.rows["open"], "toRow": api.rows["open"], "name": "Dup"}
    assert api.post("/api/build/templates", json=body).status_code == 201
    dup = api.post("/api/build/templates", json=body)
    assert dup.status_code == 409 and dup.json()["kind"] == "exists"
    assert api.get("/api/build/templates/nope/mapping", params={"workbook": "mock.xlsx"}).status_code == 404


def test_insert_template_maps_variables_and_writes_new_steps(api):
    api.post("/api/build/templates", json={"workbook": "mock.xlsx", "test": "FlowA", "fromRow": api.rows["dep"],
                                           "toRow": api.rows["dep"], "name": "Departure"})
    model = api.get("/api/build/workbooks/mock.xlsx").json()
    before = len(next(t for t in model["tests"] if t["id"] == "FlowA")["steps"])
    r = api.post("/api/build/workbooks/mock.xlsx/templates/insert",
                json={"template": "Departure", "test": "FlowA", "after": api.rows["dep"], "mapping": {"DEPDATE": "DEPDATE"},
                     "version": model["version"]})
    assert r.status_code == 200
    t = next(x for x in r.json()["model"]["tests"] if x["id"] == "FlowA")
    assert len(t["steps"]) == before + 1
