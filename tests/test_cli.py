from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from regrunner.cli import main
from tests.workbook_factory import build_workbook

REAL = Path(__file__).resolve().parents[1] / "workbooks" / "UAT_AEM_Travelex Regression_v9.1.xlsx"
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not REAL.exists(), reason="real workbook not present")
def test_list_plan_lint_and_selector_audit_on_the_real_workbook(capsys):
    assert main(["list", str(REAL)]) == 0
    out = capsys.readouterr().out
    assert "CW" in out and "Travel Protection Plan" in out
    assert main(["plan", str(REAL), "CW"]) == 0
    assert "151 step(s) would run." in capsys.readouterr().out
    assert main(["lint", str(REAL), "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "0 error(s), 9 warning(s)" in out
    assert 'Travelkore row 70: "Verify AOAD Amount is the same as previously selected": reads the innerText of an <option>' in out     # the flawed check the lint now finds
    assert main(["selectors", "audit", str(REAL), "--top", "3"]) == 0
    assert "provably equivalent generic (CSS) locator" in capsys.readouterr().out


@pytest.mark.browser
def test_run_command_prints_progress_lines_writes_evidence_and_sets_the_exit_code(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=site)
    (tmp_path / "config.yaml").write_text(
        "timeouts: {element_s: 6, optional_s: 1.5}\noutput: {match_timeout_s: 3}\n"
        "captcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(tmp_path / "config.yaml"), "run", str(wb),
                           "--plain", "--seed", "1"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Login flow: step 15/48 passed (31%) | overall 31%" in proc.stdout        # the format asked for
    assert "PASSED: 1/1 tests passed" in proc.stdout
    (run_dir,) = list((tmp_path / "runs").iterdir())
    assert (run_dir / "results.json").is_file() and (run_dir / "events.jsonl").is_file() and (run_dir / "workbook.xlsx").is_file()
    (net,) = list((run_dir / "tests").glob("*/network.jsonl"))                     # the site's own calls, for explaining "why did the page do that"
    calls = [__import__("json").loads(line) for line in net.read_text().splitlines()]
    assert any(c["url"].startswith("/api/whoami") and c["status"] == 200 and c["method"] == "GET" for c in calls)


@pytest.mark.browser
def test_exit_codes_for_failure_and_bad_selection(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["A"], base_url=site, expect_bypass="WRONG")           # cookie check will fail
    cfg = tmp_path / "config.yaml"
    cfg.write_text("timeouts: {element_s: 4, optional_s: 1}\noutput: {match_timeout_s: 1}\ncaptcha_bypass: {values: {UAT: X}}\nreports: {html: false}\n")
    base = [sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain"]
    failed = subprocess.run(base, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert failed.returncode == 1 and "FAILED" in failed.stdout and "Failed steps:" in failed.stdout
    bad = subprocess.run([*base, "--tests", "Nope"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2 and "Unknown test(s): nope" in bad.stderr


def test_boolean_options_can_be_turned_on_and_off_from_the_command_line():
    from regrunner.cli import build_parser
    parse = lambda *a: build_parser().parse_args(["run", "wb.xlsx", *a])
    unset = parse()
    assert unset.pdf is None and unset.harvest is None and unset.nice is None          # None = "use config.yaml"
    assert parse("--pdf", "--harvest", "--nice").pdf is True
    off = parse("--no-pdf", "--no-harvest", "--no-nice")
    assert off.pdf is False and off.harvest is False and off.nice is False
    assert parse("--no-report", "--headed", "--allow-prod").no_report is True


def test_serve_reports_a_busy_port_instead_of_crashing(capsys):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        assert main(["serve", "--port", str(taken.getsockname()[1])]) == 0
    assert "already listening" in capsys.readouterr().out


def test_the_app_window_is_the_installed_edge_or_chrome_in_app_mode_and_outlives_the_launcher(monkeypatch, tmp_path):
    from regrunner import browsers, cli
    edge = tmp_path / "msedge"
    monkeypatch.setattr(browsers, "installed_executable", lambda browser: edge if browser.id == "msedge" else None)
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: launched.append((cmd, kw)))
    assert cli.open_in_app_window("http://127.0.0.1:8765") is True
    (cmd, kw), = launched
    assert cmd == [str(edge), "--app=http://127.0.0.1:8765"]
    assert kw.get("start_new_session") or kw.get("creationflags")


def test_with_no_edge_or_chrome_the_app_window_falls_back_to_the_default_browser(monkeypatch):
    import webbrowser

    from regrunner import browsers, cli
    monkeypatch.setattr(browsers, "installed_executable", lambda browser: None)
    assert cli.open_in_app_window("http://127.0.0.1:1") is False
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert main(["serve", "--port", str(port), "--app"]) == 0
    assert opened == [f"http://127.0.0.1:{port}"]
