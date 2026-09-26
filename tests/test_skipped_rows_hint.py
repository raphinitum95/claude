"""A step someone forgot to switch on (empty blnExecute) is silent: nothing failed, it just never ran.  When a step nearby fails, say so."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from regrunner.engine.test_runner import TestRunner
from tests.workbook_factory import build_workbook

pytestmark = pytest.mark.browser


def extra(sheet, rows):
    sheet.add("get_google_token", "Get Okta PW", gate="", Value="JBSWY3DPEHPK3PXP")        # empty blnExecute: never runs
    sheet.add("Set", "Google PW", gate="", FindBy="xpath", FindBy_Value="//input[@name='answer']", Index=0, Value="=S1")
    sheet.add("Click", "Click Verify", gate="", FindBy="xpath", FindBy_Value="//input[@value='Verify']", Index=0)
    sheet.add("Wait", "Wait", Value=1)
    sheet.add("Click", "Click Australia", FindBy="xpath", FindBy_Value="//a[contains(.,'Australia')]", Index=0)     # not on the page: fails
    sheet.add("Click", "Off on purpose", gate="N", FindBy="xpath", FindBy_Value="//nothing", Index=0)


def test_the_hint_lists_the_rows_above_a_failed_step_that_did_not_run_and_says_what_to_do():
    off = {8: ("get_google_token", "Get Okta PW"), 9: ("Set", "Google PW"), 10: ("Click", "Click Verify"), 40: ("Click", "far away")}
    hint = TestRunner._skipped_hint(off, 14)
    assert hint.startswith("Not run, just above this step: rows 8-10 - Get Okta PW (get_google_token); Google PW (Set); Click Verify (Click)")
    assert "blnExecute (column A) is empty" in hint and "put Y" in hint
    assert TestRunner._skipped_hint(off, 30) == "" and TestRunner._skipped_hint({}, 14) == ""              # nothing nearby: no hint
    assert TestRunner._skipped_hint({12: ("Click", "x")}, 14).startswith("Not run, just above this step: row 12 - x (Click)")
    assert "rows 3, 9" in TestRunner._skipped_hint({3: ("A", "a"), 9: ("B", "b")}, 12)


def test_a_failed_step_carries_the_hint_and_an_off_row_marked_n_does_not(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Flow"], base_url=site, extra_steps=extra)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("timeouts: {element_s: 2, optional_s: 1}\ncaptcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    subprocess.run([sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain", "--seed", "1"],
                   cwd=tmp_path, capture_output=True, text=True, timeout=180)
    (run_dir,) = list((tmp_path / "runs").iterdir())
    steps = json.loads((run_dir / "results.json").read_text())["tests"][0]["steps"]
    (bad,) = [s for s in steps if s["name"] == "Click Australia"]
    assert bad["status"] == "FAILED" and "Object was not found" in bad["error"]
    assert "Not run, just above this step: rows " in bad["error"] and "Get Okta PW (get_google_token)" in bad["error"] and "Google PW (Set)" in bad["error"]
    assert "Off on purpose" not in bad["error"]                                               # an N is a decision, only an empty cell is reported
    assert not [s for s in steps if s["name"] in ("Get Okta PW", "Google PW", "Click Verify")]  # and they really did not run
    plain = [s for s in steps if s["status"] == "FAILED" and s["name"] != "Click Australia"]
    assert all("Not run" not in s["error"] for s in plain)
