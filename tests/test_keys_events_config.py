from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from regrunner.config import Config, expand_env, load_config, load_env_file, workbook_secrets
from regrunner.engine.keys import parse_sendkeys
from regrunner.engine.session import cookie_domains
from regrunner.events import EventBus, JsonlListener, ProgressTracker, read_events


# ---- SendKeys parser ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("source,expected", [
    ("{TAB}", ["Tab"]), ("ab", ["a", "b"]), ("{DOWN 3}", ["ArrowDown"] * 3), ("^-", ["Control+-"]),
    ("^{+}", ["Control++"]), ("+(ab)", ["Shift+a", "Shift+b"]), ("%{F4}", ["Alt+F4"]), ("a~b", ["a", "Enter", "b"]),
    ("{{}x{}}", ["{", "x", "}"]), ("", []),
])
def test_sendkeys_parser(source, expected):
    assert [op.combo for op in parse_sendkeys(source)] == expected


def test_browser_zoom_shortcuts_are_recognised():
    assert all(op.is_browser_zoom for op in parse_sendkeys("^-^-^{+}"))
    assert not any(op.is_browser_zoom for op in parse_sendkeys("{TAB}12"))


# ---- events -------------------------------------------------------------------------------------------------
def test_bus_preserves_order_when_listeners_emit():
    bus = EventBus("r1")
    seen: list[str] = []
    bus.subscribe(lambda e: bus.emit("derived", of=e["type"]) if e["type"] == "a" else None)
    bus.subscribe(lambda e: seen.append(e["type"]))
    bus.emit("a")
    bus.emit("b")
    assert seen == ["a", "derived", "b"]                       # never interleaved, derived event queued behind its cause


def test_bad_listener_never_breaks_the_run():
    bus = EventBus()
    got: list[dict] = []
    bus.subscribe(lambda e: 1 / 0)
    bus.subscribe(got.append)
    bus.emit("x")
    assert got[0]["type"] == "x" and any(e["type"] == "log" and e["level"] == "error" for e in got)


def test_progress_tracker_percentages():
    bus = EventBus()
    out: list[dict] = []
    bus.subscribe(out.append)
    ProgressTracker(bus)
    bus.emit("run_started", tests=[{"id": "A", "title": "A", "total_steps": 2}, {"id": "B", "title": "B", "total_steps": 2}])
    bus.emit("test_started", test="A", total_steps=2)
    bus.emit("step_passed", test="A", step=1, total_steps=2)
    last = [e for e in out if e["type"] == "run_progress"][-1]
    assert last["percent"] == 25.0 and last["tests"]["A"]["percent"] == 50.0 and last["tests"]["B"]["percent"] == 0.0
    bus.emit("step_passed", test="A", step=2, total_steps=2)
    bus.emit("test_finished", test="A", status="PASSED")
    last = [e for e in out if e["type"] == "run_progress"][-1]
    assert last["percent"] == 50.0 and last["tests"]["A"]["status"] == "passed"


def test_progress_never_exceeds_100_when_more_steps_run_than_planned():
    bus = EventBus()
    out: list[dict] = []
    bus.subscribe(out.append)
    ProgressTracker(bus)
    bus.emit("run_started", tests=[{"id": "A", "title": "A", "total_steps": 1}])
    for i in range(3):
        bus.emit("step_passed", test="A", step=i + 1)
    assert [e for e in out if e["type"] == "run_progress"][-1]["percent"] <= 100.0


def test_jsonl_tailing_ignores_partial_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = JsonlListener(path)
    writer({"type": "a"})
    with path.open("a") as fh:
        fh.write('{"type": "b"')                              # writer mid-line
    events, offset = read_events(path, 0)
    assert [e["type"] for e in events] == ["a"]
    with path.open("a") as fh:
        fh.write("}\n")
    events, offset = read_events(path, offset)
    assert [e["type"] for e in events] == ["b"]


# ---- config -------------------------------------------------------------------------------------------------
def test_env_expansion_and_defaults(monkeypatch):
    monkeypatch.setenv("FOO_TOKEN", "abc")
    assert expand_env({"a": "${FOO_TOKEN}", "b": ["${MISSING_X:-fallback}", "${MISSING_Y}"]}) == {"a": "abc", "b": ["fallback", ""]}


def test_secrets_env_does_not_override_real_environment(tmp_path, monkeypatch):
    (tmp_path / "secrets.env").write_text("# c\nRR_TEST_A=from-file\nRR_TEST_B='quoted'\n")
    monkeypatch.setenv("RR_TEST_A", "from-env")
    monkeypatch.delenv("RR_TEST_B", raising=False)
    load_env_file(tmp_path / "secrets.env")
    assert os.environ["RR_TEST_A"] == "from-env" and os.environ["RR_TEST_B"] == "quoted"
    monkeypatch.delenv("RR_TEST_B")


def test_config_rejects_unknown_keys_and_masks_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAPTCHA_BYPASS_TOKEN_UAT", "s3cret")
    (tmp_path / "config.yaml").write_text("captcha_bypass:\n  values:\n    UAT: ${RECAPTCHA_BYPASS_TOKEN_UAT}\n    QA: ${NOT_SET_ANYWHERE}\n")
    cfg = load_config(base_dir=tmp_path)
    assert cfg.bypass_token("uat") == "s3cret" and cfg.bypass_token("QA") == ""
    public = json.dumps(cfg.public())
    assert "s3cret" not in public and '"UAT": "set"' in public and '"QA": "missing"' in public
    (tmp_path / "config.yaml").write_text("runner:\n  wrokers: 3\n")
    with pytest.raises(ValueError, match="wrokers"):
        load_config(base_dir=tmp_path)


def test_worker_count_is_capped():
    cfg = Config()
    cfg.runner.workers, cfg.runner.max_workers = 50, 8
    assert cfg.effective_workers == 8
    cfg.runner.workers = 0
    assert cfg.effective_workers == 1


def test_workbook_secret_tokens_come_from_rr_var_env(monkeypatch):
    monkeypatch.setenv("RR_VAR_DT_ZScalerUser", "me@x")
    assert workbook_secrets()["DT_ZSCALERUSER"] == "me@x"


@pytest.mark.parametrize("url,domains", [
    ("https://owneradvantage.uat.insurancebytravelex.com/", [".insurancebytravelex.com"]),
    ("https://cw.uat.travelexinsurance.net/x", [".travelexinsurance.net"]),
    ("https://shop.example.co.uk/", [".example.co.uk"]),
    ("http://127.0.0.1:8000/", ["127.0.0.1"]),
    ("http://localhost:3000", ["localhost"]),
])
def test_cookie_domains(url, domains):
    assert cookie_domains(url) == domains
    assert cookie_domains(url, [".extra.net"])[-1] == ".extra.net"


# ---- the "must not touch the user's keyboard/mouse" guarantee -------------------------------------------
def test_no_os_level_input_anywhere_in_the_package():
    forbidden = re.compile(r"\b(pyautogui|pynput|win32api|win32com|win32gui|WScript|SendInput|keybd_event|mouse_event|"
                           r"pywinauto|xdotool|osascript|import keyboard|from keyboard|comtypes)\b")
    root = Path(__file__).resolve().parents[1] / "src" / "regrunner"
    offenders = []
    for path in root.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if forbidden.search(code) and '"""' not in code:
                offenders.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
    assert not offenders, offenders
