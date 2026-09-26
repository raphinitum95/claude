"""A second, shared copy of a finished run: ``report.html`` and ``summary.txt`` in ``<publish.dir>/<run id>/``.

The run itself always stays in ``runs/`` (that is what the UI reads).  The shared copy is best effort and bounded: a
share that is offline or hanging can delay the end of a run by ``publish.timeout_s`` at most and never fails it.  A run
that could not be copied is remembered in its ``run.json`` (``publish_error``) and copied after a later run, or by
``regrunner publish <run>``.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .runmeta import read_meta, update_meta

PROBE_TIMEOUT_S = 5
CATCH_UP_MAX = 5                                  # earlier runs retried after a success, newest first
NOT_SHARED = {"CANCELLED"}                        # a run somebody stopped is not a result to hand the team (``regrunner publish`` still can)


class ShareTimeout(Exception):
    pass


def describe(err: BaseException) -> str:
    return str(err) or type(err).__name__


# -- bounded I/O: a dead network share can block a file call for minutes, and a thread stuck in one cannot be cancelled ---------
# Daemon threads, on purpose: the default executor's threads are joined when the interpreter exits, which would hang the run.
def call_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    box: dict[str, Any] = {}
    done = threading.Event()

    def work() -> None:
        try:
            box["value"] = fn()
        except BaseException as err:              # handed to the caller
            box["error"] = err
        finally:
            done.set()

    threading.Thread(target=work, daemon=True, name="regrunner-share").start()
    if not done.wait(timeout):
        raise ShareTimeout(f"no answer within {timeout:g}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


async def call_with_timeout_async(fn: Callable[[], Any], timeout: float) -> Any:
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def settle(value: Any, error: BaseException | None) -> None:
        if not future.done():                     # not if wait_for already gave up on it
            future.set_exception(error) if error else future.set_result(value)

    def work() -> None:
        try:
            value, error = fn(), None
        except BaseException as err:
            value, error = None, err
        try:
            loop.call_soon_threadsafe(settle, value, error)
        except RuntimeError:                      # the loop is already closed
            pass

    threading.Thread(target=work, daemon=True, name="regrunner-share").start()
    try:
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        raise ShareTimeout(f"no answer within {timeout:g}s") from None


def _write_probe(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    mark = root / f".regrunner-write-test-{os.getpid()}"
    mark.write_text("ok", encoding="utf-8")
    mark.unlink()


async def probe(root: Path, timeout: float = PROBE_TIMEOUT_S) -> str:
    """"" when files can be written to ``root``; otherwise why not."""
    try:
        await call_with_timeout_async(lambda: _write_probe(root), timeout)
    except Exception as err:
        return describe(err)
    return ""


async def publish_status(cfg: Config) -> dict[str, Any] | None:
    """For the Preflight card / ``doctor``: ``None`` when no shared folder is configured."""
    if not cfg.publish.dir:
        return None
    root = cfg.path(cfg.publish.dir)
    problem = await probe(root)
    detail = (f"Finished runs are copied to {root} (report and summary)." if not problem
              else f"{root} cannot be written to right now: {problem}. Runs still work; they are copied once it is reachable again.")
    return {"id": "publish", "status": "warn" if problem else "ok", "label": "Shared folder", "detail": detail,
            "dir": str(root), "action": ""}


# -- the copy itself ------------------------------------------------------------------------------------------------------------
def _clock(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return iso or ""


def _took(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else (f"{minutes}m {secs:02d}s" if minutes else f"{secs}s")


def _clip(text: str, n: int = 300) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _browser_line(data: dict[str, Any]) -> str:
    from . import browsers
    b = browsers.identity_of(data)
    if b.get("id") in ("none", "unknown"):
        return "not recorded" if b.get("id") == "unknown" else str(b.get("text"))
    mode = "headless" if b.get("headless", True) else "headed"
    extra = "" if b.get("recorded", True) else "; version not recorded"
    extra += "; not Safari itself: Playwright's WebKit, the engine Safari uses" if b.get("approximate") else ""
    return f"{b.get('text', '')} ({mode}{extra})"


def summary_text(data: dict[str, Any]) -> str:
    """The pass/fail summary a person reads without opening the report."""
    s = data.get("summary", {})
    tests = data.get("tests", [])
    bad = s.get("failed", 0) + s.get("errored", 0)
    lines = [f"QA regression run {data.get('run_id', '')}",
             f"Result:       {data.get('status', '')}  ({s.get('passed', 0)} of {s.get('tests', len(tests))} tests passed"
             + (f", {bad} did not" if bad else "") + ")",
             f"Environment:  {data.get('environment', '')}",
             f"Browser:      {_browser_line(data)}",
             f"Started:      {_clock(data.get('started_at', ''))}  (took {_took(data.get('duration_s', 0))}, {data.get('workers', 1)} at a time)",
             f"Workbook:     {Path(str(data.get('workbook', ''))).name}",
             f"Steps:        {s.get('steps', 0)} run, {s.get('steps_failed', 0)} failed",
             f"To review:    {s.get('review_items', 0)} console / network items (informational, never a failure)", ""]
    idw = max([len(str(t.get("id", ""))) for t in tests] + [4])
    for t in tests:
        steps = f"{len(t.get('steps', []))}/{t.get('total_steps', 0)} steps"
        lines.append(f"{t.get('status', ''):<10}{str(t.get('id', '')):<{idw + 2}}{steps:<15}{_took(t.get('duration_s', 0)):<9}{t.get('title', '')}")
        if t.get("status") == "PASSED":
            continue
        if t.get("error"):
            lines.append(f"          {_clip(t['error'])}")
        failed = [st for st in t.get("steps", []) if st.get("status") == "FAILED"]
        for st in failed[:3]:
            lines.append(f"          step {st.get('seq')} (row {st.get('row')}) {st.get('name') or st.get('action', '')}: {_clip(st.get('error'))}")
        if len(failed) > 3:
            lines.append(f"          ... and {len(failed) - 3} more failed step(s)")
    from .reporting.results import variables_of
    values = [(t.get("id", ""), v) for t in tests for v in variables_of(t)]
    if values:                                                   # what the tests produced (a quote number, a policy number...)
        lines += ["", "Values set by the tests:"]
        for test_id, v in values:
            by = "entered by hand" if v.get("by_hand") else f"step {v.get('seq')} row {v.get('row')} {v.get('step') or ''}".strip()
            lines.append(f"  {test_id}: {v.get('name')} = {_clip(v.get('stored', v.get('value', '')), 200)}   ({by})")
    if data.get("warnings"):
        lines += ["", "Notes:"] + [f"  - {_clip(w, 400)}" for w in data["warnings"]]
    lines += ["", "Open report.html in this folder for the step-by-step evidence."]
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def publish_run(run_dir: Path, root: Path, screenshots: str = "failures") -> Path:
    """Blocking.  ``root/<run id>/report.html`` + ``summary.txt``, built from the run's ``results.json``."""
    from .reporting.html_report import render_html
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    dest = root / run_dir.name
    dest.mkdir(parents=True, exist_ok=True)
    _write(dest / "report.html", render_html(data, run_dir, screenshots))
    _write(dest / "summary.txt", summary_text(data))          # last: once it exists the copy is complete
    return dest


def _pending(runs_root: Path, skip: str) -> list[Path]:
    """Earlier runs that could not be copied when they finished, newest first."""
    out = []
    for d in sorted(runs_root.iterdir(), reverse=True):
        meta = read_meta(d) if d.is_dir() and d.name != skip else None
        if meta and meta.get("publish_error") and (d / "results.json").is_file():
            out.append(d)
    return out[:CATCH_UP_MAX]


def _copy_all(run_dir: Path, root: Path, screenshots: str) -> dict[str, Any]:
    dest = publish_run(run_dir, root, screenshots)            # an error here = the share is down: nothing else is tried
    caught_up = []
    for older in _pending(run_dir.parent, skip=run_dir.name):
        try:
            caught_up.append((older, publish_run(older, root, screenshots)))
        except Exception:
            continue
    return {"dest": dest, "caught_up": caught_up}


def _recorded(dest: Path) -> dict[str, Any]:
    return {"to": str(dest), "at": datetime.now().isoformat(timespec="seconds")}


async def publish_finished_run(cfg: Config, run_dir: Path, status: str, note: Callable[..., None], force: bool = False) -> None:
    """The end-of-run step: copy, then say so in the run's log.  Never raises."""
    if not cfg.publish.dir or (status in NOT_SHARED and not force):
        return
    root = cfg.path(cfg.publish.dir)
    try:
        out = await call_with_timeout_async(lambda: _copy_all(run_dir, root, cfg.publish.screenshots), cfg.publish.timeout_s)
    except Exception as err:
        problem = describe(err)
        try:
            update_meta(run_dir, publish_error=problem)
        except OSError:
            pass
        note(f"Could not copy this run to the shared folder {root}: {problem}. Nothing is lost: it is in {run_dir}. It is copied "
             f"automatically after the next run, or now with:  python -m regrunner publish {run_dir.name}", "warning")
        return
    update_meta(run_dir, published=_recorded(out["dest"]), publish_error=None)
    note(f"Copied the report and summary to {out['dest']}", "info")
    for older, dest in out["caught_up"]:
        update_meta(older, published=_recorded(dest), publish_error=None)
    if out["caught_up"]:
        note(f"Also copied {len(out['caught_up'])} earlier run(s) that could not be copied when they finished", "info")
