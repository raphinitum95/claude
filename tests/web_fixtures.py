"""A live web UI + backend on a scratch project whose workbooks only ever point at the local mock site."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml

from regrunner.config import load_config
from regrunner.web.app import create_app
from tests.workbook_factory import build_workbook

HEADERS = {"X-Requested-With": "regrunner"}


@dataclass
class Web:
    base: str
    root: Path
    cfg_file: Path
    site: str

    def client(self, **kw) -> httpx.Client:
        return httpx.Client(base_url=self.base, headers=HEADERS, timeout=60, **kw)

    def aclient(self, **kw) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, headers=HEADERS, timeout=60, **kw)

    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def wait_finished(self, run_id: str, timeout: float = 150) -> dict:
        deadline = time.time() + timeout
        with self.client() as c:
            while time.time() < deadline:
                detail = c.get(f"/api/runs/{run_id}").json()
                if detail["meta"]["status"] != "RUNNING":
                    return detail
                time.sleep(0.5)
        raise TimeoutError(f"run {run_id} did not finish in {timeout}s")


def failing_step(sheet, rows):
    """An Output step that cannot match, so a flow ends FAILED with an expected/actual pair to show."""
    sheet.add("Output", "Plan total", FindBy="xpath", FindBy_Value="//span[contains(@class,'totalBaseRate')]", Index=0,
              Output_Property="innertext", Expected_Value="$1.00", Exact_Match="Y")


@pytest.fixture(scope="module")
def web(site, tmp_path_factory):
    root = tmp_path_factory.mktemp("web")
    (root / "workbooks").mkdir()
    build_workbook(root / "workbooks" / "mock.xlsx", flows=["FlowA", "FlowB"], base_url=site, enabled=["FlowA", "FlowB"])
    build_workbook(root / "workbooks" / "bad.xlsx", flows=["FlowX", "FlowY"], base_url=site, enabled=["FlowX", "FlowY"],
                   extra_steps=failing_step)
    cfg_file = root / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "runner": {"workers": 2, "low_priority": True},
        "timeouts": {"element_s": 6, "optional_s": 1.5, "optional_repeat_s": 0.3},
        "output": {"match_timeout_s": 3, "stable_ms": 300}, "waits": {"quiet_ms": 400},
        "screenshots": {"quality": 40},
        "captcha_bypass": {"values": {"UAT": "TEST-UAT-TOKEN", "QA": "${RECAPTCHA_BYPASS_TOKEN_QA}"}},
        "auth": {"headless": True},                      # the sign-in window is visible for people, headless for tests
        "captcha": {"headless": True},                   # ...and so is the window a captcha is solved in
        "tags": {"smoke": ["FlowA"]},
    }))
    cfg = load_config(cfg_file, base_dir=root)
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, str(cfg_file)), host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield Web(f"http://127.0.0.1:{port}", root, cfg_file, site)
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def bad_run(web):
    """One finished run of the failing workbook, used by the API and UI tests that need real evidence."""
    with web.client() as c:
        res = c.post("/api/runs", json={"workbook": "bad.xlsx", "tests": ["FlowX", "FlowY"], "harvest": True})
        assert res.status_code == 200, res.text
        run_id = res.json()["run_id"]
    web.wait_finished(run_id)
    return run_id
