"""Things that work on the interpreter this suite runs on but break on Python 3.9 (the copy that ships with macOS)."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.workbook_factory import build_workbook

SRC = Path(__file__).resolve().parents[1] / "src" / "regrunner"
PRIMITIVES = {"Event", "Lock", "Queue", "Semaphore", "Condition"}
CONSTRUCTED_INSIDE_A_COROUTINE = {("engine/throttle.py", "__init__"), ("engine/schedule.py", "__init__"),           # Throttle / Schedule / Pool / Engine are only built inside execute_many()
                                  ("engine/pool.py", "__init__"), ("engine/runner.py", "__init__")}


def test_asyncio_primitives_are_created_inside_coroutines():
    """On Python 3.9 an asyncio.Event/Lock/Queue is bound to the loop that is current when it is *created*.  One made before
    asyncio.run() starts its own loop fails as soon as a second task waits on it ('attached to a different loop'), which is what
    made every run with two or more workers crash on 3.9 while working on 3.12."""
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in PRIMITIVES
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "asyncio"):
                continue
            fn = node
            while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = parents[fn]
            rel = path.relative_to(SRC).as_posix()
            if isinstance(fn, ast.AsyncFunctionDef) or (isinstance(fn, ast.FunctionDef) and (rel, fn.name) in CONSTRUCTED_INSIDE_A_COROUTINE):
                continue
            offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"asyncio primitives created outside a coroutine: {offenders}"


def test_two_workers_run_two_tests_at_once(site, tmp_path):
    """The command that crashed on Python 3.9: two tests, two workers (the second worker waits out the stagger)."""
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["A", "B"], base_url=site, enabled=["A", "B"])
    cfg = tmp_path / "config.yaml"
    cfg.write_text("runner: {workers: 2, stagger_s: 1}\ntimeouts: {element_s: 6, optional_s: 1.5}\noutput: {match_timeout_s: 3}\n"
                   "captcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain", "--workers", "2"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert "RuntimeError" not in proc.stderr and "Traceback" not in proc.stderr, proc.stderr[-1500:]
    assert "2 test(s), 2 worker(s)" in proc.stdout
