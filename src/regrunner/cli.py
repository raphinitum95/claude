"""Command line: ``regrunner <command>`` (also ``python -m regrunner``)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import signal
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, browsers
from .config import Config, load_config, workbook_secrets
from .engine.runner import RunOptions, SelectionError, execute_many, new_run_id
from .events import EventBus
from .priority import lower_priority

HARD_STOP_S = 8            # after SIGTERM / a second Ctrl+C the runner gets this long to wind down, then exits


def _csv(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _workbook_path(cfg: Config, name: str) -> Path:
    p = Path(name)
    if p.is_file():
        return p
    candidate = cfg.path(cfg.workbooks_dir) / name
    if candidate.is_file():
        return candidate
    raise SystemExit(f"Workbook not found: {name}")


class TerminalAsker:
    """Answers the run's questions (ASK_USER) at the terminal: one prompt at a time, the answer handed over through the run's answers folder."""

    def __init__(self, cfg: Config):
        import queue
        import threading
        self.cfg = cfg
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self.books: dict[str, str] = {}                       # run id -> workbook name (only said when several runs share this terminal)
        threading.Thread(target=self._loop, daemon=True, name="regrunner-ask").start()

    def _who(self, event) -> str:
        book = self.books.get(event.get("run_id", ""), "") if len(self.books) > 1 else ""
        return f"{book} · {event['test']}" if book else event["test"]

    def __call__(self, event) -> None:                       # an EventBus listener
        if event["type"] == "run_started":
            self.books[event["run_id"]] = Path(str(event.get("workbook", ""))).name
        if event["type"] == "user_input_needed" and event.get("mode") == "terminal":
            if event.get("kind") == "captcha":                # nothing to type: the test carries on by itself once the captcha is solved
                print(f"\n[{self._who(event)}] {event['question']}  ({int(event.get('timeout_s', 0))} s)", flush=True)
                return
            self.queue.put({**event, "who": self._who(event)})

    def _loop(self) -> None:
        import getpass
        from .engine.ask import write_answer
        while True:
            e = self.queue.get()
            run_dir = self.cfg.path(self.cfg.runs_dir) / e["run_id"]
            prompt = f"\n[{e.get('who') or e['test']}] {e['question']}  ({int(e.get('timeout_s', 0))} s to answer)\n> "
            try:
                answer = getpass.getpass(prompt) if e.get("secret") and sys.stdin.isatty() else input(prompt)
            except (EOFError, KeyboardInterrupt):
                continue                                      # nobody there: the question times out
            write_answer(run_dir, e["ask"], answer)


# -------------------------------------------------------------------------------------------------
def _run_options(args, cfg: Config, nice: bool, ask: str) -> RunOptions:
    options = RunOptions(
        workbook=_workbook_path(cfg, args.workbook), tests=_csv(args.tests), tags=_csv(args.tag),
        environment=args.env, workers=args.workers, headless=False if args.headed else None, browser=args.browser, seed=args.seed,
        screenshots=args.screenshots, run_id=args.run_id, report=not args.no_report,
        pdf=args.pdf, harvest=args.harvest, retries=args.retries, allow_prod=args.allow_prod,
        chains=[] if args.no_chains else ([[x.strip() for x in c.split(",") if x.strip()] for c in args.chain] if args.chain else None),
        extra={"nice": nice, "ask": ask})
    if args.all:
        from .workbook.model import Workbook
        wb = Workbook(options.workbook)
        options.tests = [c.id for c in wb.discover() if c.runnable]
    return options


def cmd_run(args, cfg: Config) -> int:
    """Run one workbook, or several at once on one set of workers (``regrunner run A.xlsx --tests X B.xlsx --all``: see ``split_workbooks``)."""
    from .reporting.console import make_console
    every = [args, *getattr(args, "also", [])]
    if args.workers:
        cfg.runner.workers = args.workers
    nice = cfg.runner.low_priority if args.nice is None else args.nice
    note = lower_priority() if nice else "not lowered"
    ask = args.ask or ("terminal" if sys.stdin.isatty() else "off")    # who answers ASK_USER steps: a terminal run answers at the terminal
    optionses = [_run_options(a, cfg, nice, ask) for a in every]
    several = len(optionses) > 1
    buses, consoles = [], []
    asker = TerminalAsker(cfg) if ask == "terminal" else None
    for a, options in zip(every, optionses):
        bus = EventBus()
        console = make_console(plain=a.plain or ask == "terminal",     # live progress bars and a prompt would fight over the screen
                               prefix=f"[{Path(str(options.workbook)).name}] " if several else "")
        bus.subscribe(console)
        if asker is not None:
            bus.subscribe(asker)
        buses.append(bus)
        consoles.append(console)

    async def main():
        loop = asyncio.get_running_loop()
        cancel = asyncio.Event()             # created inside the running loop: on Python 3.9 an Event is bound to the loop it is
                                             # created in, and one made before asyncio.run() breaks the moment a second worker waits on it

        def hard_stop() -> None:
            from .engine.diagnostics import dump_tasks
            dump_tasks("hard stop: the run did not stop in time")
            sys.stderr.flush()
            os._exit(130)                                     # results.json already holds every finished test

        def on_signal(sig: signal.Signals) -> None:
            # First Ctrl+C: finish the current step and stop.  Ctrl+C again, or SIGTERM (what the UI sends when a
            # cancel is taking too long): stop for real - a stuck browser must never be able to keep the run alive.
            if sig == signal.SIGTERM or cancel.is_set():
                print("\nStopping now...", file=sys.stderr, flush=True)
                cancel.set()
                loop.call_later(HARD_STOP_S, hard_stop)
            else:
                cancel.set()
                print("\nStopping after the current step... (Ctrl+C again to stop now)", file=sys.stderr, flush=True)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, on_signal, sig)
            except NotImplementedError:                       # Windows
                pass
        return await execute_many(optionses, cfg, buses, cancel, inbox_dir=Path(args.inbox) if args.inbox else None)

    try:
        results = asyncio.run(main())
    except SelectionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    for console, result in zip(consoles, results):
        console.finish(result, cfg.path(cfg.runs_dir) / result.run_id)
    statuses = {r.status for r in results}
    return 0 if statuses == {"PASSED"} else (130 if "CANCELLED" in statuses else 1)


def cmd_list(args, cfg: Config) -> int:
    from .workbook.model import Workbook
    wb = Workbook(_workbook_path(cfg, args.workbook), environment=args.env)
    rows = []
    for case in wb.discover():
        steps = len(wb.runtime(case).plan()) if case.runnable else 0
        rows.append({"id": case.id, "sheet": case.sheet, "enabled": case.enabled, "is_ui": case.is_ui, "kind": case.kind,
                     "steps": steps, "scenario": case.scenario, "description": case.description, "tags": case.tags})
    if args.json:
        print(json.dumps({"tests": rows, "warnings": wb.warnings}, indent=2))
        return 0
    print(f"{'TEST':16}{'RUN?':6}{'STEPS':>6}  {'SCENARIO':12}{'TAGS':14}DESCRIPTION")
    for r in rows:
        print(f"{r['id']:16}{'Y' if r['enabled'] else 'N':6}{r['steps']:>6}  {r['scenario']:12}{','.join(r['tags']):14}{r['description']}")
    for w in wb.warnings:
        print(f"warning: {w}")
    return 0


def cmd_plan(args, cfg: Config) -> int:
    """Dry run: show exactly which steps would execute (after token substitution and gating)."""
    from .selectors.resolve import SelectorMap, build_chain
    from .workbook.model import Workbook
    wb = Workbook(_workbook_path(cfg, args.workbook), environment=args.env, seed=args.seed)
    smap = SelectorMap.load(cfg.path(cfg.selectors.map))
    cases = [c for c in wb.discover() if c.runnable and (c.id.lower() == args.test.lower() or c.sheet.lower() == args.test.lower())]
    if not cases:
        raise SystemExit(f"Unknown test {args.test!r}")
    rt = wb.runtime(cases[0])
    if cases[0].kind == "api":                                      # the request, then every check the InputOutput sheet asks for
        for n, (row, name, method) in enumerate(rt.plan(), start=1):
            print(f"{n:4} row {row:4} {method:18} {name[:100]}")
        print(f"\n{len(rt.plan())} step(s) would run (an API test: no browser).")
        return 0
    n = 0
    for row in range(2, rt.total_rows + 1):
        step = rt.prepare_row(row)
        if step is None:
            continue
        n += 1
        chain = build_chain(step.findby, step.findby_value, step.locator_column, smap, legacy_fallback=True)
        target = chain[0].describe() if chain else ""
        print(f"{n:4} row {row:4} {step.method:18} {step.name[:34]:34} {target[:70]:70} {step.text('VALUE')[:30]}")
        rt.record(step, "PASSED", "", "")
    print(f"\n{n} step(s) would run.")
    return 0


def cmd_lint(args, cfg: Config) -> int:
    from .lint import lint, summarize
    from .workbook.model import Workbook
    findings = lint(Workbook(_workbook_path(cfg, args.workbook), environment=args.env))
    order = {"error": 0, "warning": 1, "info": 2}
    for f in sorted(findings, key=lambda f: (order[f.severity], f.test, f.row or 0)):
        if args.quiet and f.severity == "info":
            continue
        print(f)
    counts = summarize(findings)
    print(f"\n{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} note(s)")
    return 1 if counts["error"] else 0


def cmd_selectors(args, cfg: Config) -> int:
    from .selectors.harvest import apply_suggestions
    from .selectors.migrate import collect, merge_into_map
    from .selectors.resolve import SelectorMap
    smap = SelectorMap.load(cfg.path(cfg.selectors.map))
    if args.action == "apply":
        run_dir = cfg.path(cfg.runs_dir) / args.target
        added = apply_suggestions(run_dir / "selector_suggestions.json", smap, min_score=args.min_score)
        print(f"Merged {added} harvested locator(s) into {smap.save(cfg.path(cfg.selectors.map))}")
        return 0
    from .workbook.model import Workbook
    wb = Workbook(_workbook_path(cfg, args.target), environment=args.env, seed=1)
    uses = collect(wb, _csv(args.tests))
    total = sum(u.uses for u in uses)
    convertible = sum(u.uses for u in uses if u.css)
    labels = {lab: sum(u.uses for u in uses if u.label == lab) for lab in ("strong", "ok", "weak")}
    print(f"{len(uses)} distinct locators used {total} times: strong {labels['strong']}, ok {labels['ok']}, weak {labels['weak']}")
    print(f"{convertible} of {total} uses ({100 * convertible // max(total, 1)}%) have a provably equivalent generic (CSS) locator\n")
    print("Weakest locators (most used first) - candidates to replace with an id/name/data attribute:")
    for u in sorted([u for u in uses if u.label != "strong"], key=lambda u: (u.score, -u.uses))[:args.top]:
        print(f"  score {u.score:3} {u.uses:4}x  {u.value[:90]}\n            {'; '.join(u.reasons)}"
              + (f"\n            -> {u.css}" if u.css else ""))
    if args.action == "migrate":
        added = merge_into_map(uses, smap, include_positional=args.include_positional)
        path = smap.save(cfg.path(cfg.selectors.map))
        print(f"\nWrote {added} new generic locator(s) to {path} ({len(smap)} total). The workbook was not modified;"
              " legacy XPaths remain as fallbacks.")
    return 0


def cmd_auth(args, cfg: Config) -> int:
    """One-time interactive sign-in (Zscaler/Okta SSO); the session is reused by every headless test."""
    from .signin import SignInError, SignInSession

    async def login():
        session = SignInSession(cfg)
        await session.open(args.url)
        print("A browser window opened. Complete the sign-in yourself (SSO / MFA), then come back here and press Enter.")
        await asyncio.to_thread(input)
        target = await session.save()
        print(f"Saved session to {target} (keep it private; delete it to sign out).")
    try:
        asyncio.run(login())
    except SignInError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


def cmd_report(args, cfg: Config) -> int:
    from .reporting.html_report import build_report
    run_dir = Path(args.run) if Path(args.run).is_dir() else cfg.path(cfg.runs_dir) / args.run
    artifacts = asyncio.run(build_report(run_dir, pdf=args.pdf))
    for label, rel in artifacts.items():
        print(f"{label}: {run_dir / rel}")
    return 0


def cmd_publish(args, cfg: Config) -> int:
    """Copy a finished run's report and summary to the shared folder (again): the share was offline, or the run was cancelled."""
    from .publish import call_with_timeout, describe, publish_run
    from .runmeta import update_meta
    run_dir = Path(args.run) if Path(args.run).is_dir() else cfg.path(cfg.runs_dir) / args.run
    target = args.to or cfg.publish.dir
    if not target:
        print("error: no shared folder. Set publish.dir in config.yaml, or pass --to <folder>.", file=sys.stderr)
        return 2
    if not (run_dir / "results.json").is_file():
        print(f"error: {run_dir} has no results.json (is that a run folder?)", file=sys.stderr)
        return 2
    try:
        dest = call_with_timeout(lambda: publish_run(run_dir, cfg.path(target), args.screenshots or cfg.publish.screenshots),
                                 cfg.publish.timeout_s)
    except Exception as err:
        print(f"error: could not copy to {cfg.path(target)}: {describe(err)}", file=sys.stderr)
        return 1
    update_meta(run_dir, published={"to": str(dest), "at": datetime.now().isoformat(timespec="seconds")}, publish_error=None)
    print(f"Copied the report and summary to {dest}")
    return 0


def open_in_app_window(url: str) -> bool:
    """Open ``url`` in a window of its own: Edge or Chrome in "app" mode (no tabs, no address bar, its own taskbar icon), so the UI
    looks like a program and not one more tab. Uses the browser that is already installed (nothing is downloaded or installed).
    False when neither is there or it would not start; the caller then falls back to the default browser."""
    import subprocess
    order = ("msedge", "chrome") if browsers.platform_key() == "win32" else ("chrome", "msedge")
    for name in order:
        exe = browsers.installed_executable(browsers.resolve(name))
        if not exe:
            continue
        detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
                  else {"start_new_session": True})           # closing the launcher window must not close the UI window with it
        try:
            subprocess.Popen([str(exe), f"--app={url}"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **detach)
            return True
        except OSError:
            continue
    return False


def cmd_serve(args, cfg: Config) -> int:
    import socket
    import threading
    import webbrowser

    import uvicorn

    from .web.app import create_app
    url = f"http://{args.host}:{args.port}"

    def show_ui() -> None:
        if not (args.app and open_in_app_window(url)):
            webbrowser.open(url)

    with socket.socket() as probe:
        if probe.connect_ex((args.host, args.port)) == 0:
            print(f"Something is already listening on {url} - most likely regrunner is already running.")
            if args.open or args.app:
                show_ui()
            return 0
    print(f"regrunner UI on {url}  (Ctrl+C to stop)")
    if args.open or args.app:
        threading.Timer(1.2, show_ui).start()
    config_path = args.config or (str(cfg.base_dir / "config.yaml") if (cfg.base_dir / "config.yaml").is_file() else None)
    uvicorn.run(create_app(cfg, config_path), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_history(args, cfg: Config) -> int:
    """Every run in runs/ as one record: what changed between runs, which steps got slower or started failing since, CSV for Excel."""
    from .history import compare, export_csv, load_runs, markers, third_party_hosts
    runs_dir = Path(args.runs) if args.runs else cfg.path(cfg.runs_dir)
    runs = load_runs(runs_dir, args.workbook)
    if not runs:
        print(f"No finished runs in {runs_dir}" + (f" for a workbook named like {args.workbook!r}" if args.workbook else ""))
        return 1
    books = sorted({r.workbook for r in runs})
    print(f"{len(runs)} run(s) of {len(books)} workbook(s) in {runs_dir}, {runs[0].started[:10]} to {runs[-1].started[:10]}")
    if args.csv:
        for path in export_csv(runs, Path(args.csv)):
            print(f"written: {path}")
    if args.hosts:
        hosts = third_party_hosts(runs)
        print("\nThird-party hosts the pages loaded (candidates for the tracker block list; never block sign-in, payment, captcha or the consent manager):")
        for h in hosts or []:
            print(f"  {h['host']:<45} {h['requests']:>7} requests  {h['bytes'] / 1048576:>8.1f} MB  in {h['tests']} test(s) of {h['runs']} run(s)")
        if not hosts:
            print("  none recorded (runs from before measure.third_party, or pages that load nothing from elsewhere)")
    changes = markers(runs)
    print("\nWhat changed between runs:" if changes else "\nNothing recorded changed between runs (runner, browser, site version, speed settings, computer).")
    for m in changes:
        print(f"  {m.workbook}: {m.describe()}")
    print()
    for line in compare(runs, at=args.at, factor=args.factor, min_s=args.min_s) or ["Too few runs to compare."]:
        print(line)
    return 0


def cmd_doctor(args, cfg: Config) -> int:
    from .preflight import run_preflight
    report = asyncio.run(run_preflight(cfg, deep=True))
    marks = {"ok": "ok", "warn": "--", "err": "!!"}
    for check in report["checks"]:
        print(f"[{marks[check['status']]}] {check['label']}: {check['detail']}")
    return 1 if report["counts"]["err"] else 0


# -------------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="regrunner", description="Keyword-driven Playwright regression runner")
    p.add_argument("--version", action="version", version=f"regrunner {__version__}")
    p.add_argument("--config", help="path to config.yaml (default: ./config.yaml)")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run tests from one or more workbooks (several at once share the workers: WORKBOOK [its options] WORKBOOK [its options] ...)")
    r.add_argument("workbook")
    r.add_argument("--tests", help="comma-separated test ids/sheet names (overrides the workbook's Y/N flags)")
    r.add_argument("--all", action="store_true", help="run every UI test in the workbook")
    r.add_argument("--tag", help="comma-separated tags (DataSheets 'Tags' column or config.yaml tags:)")
    r.add_argument("--env", help="QA | UAT | PROD (overrides Global!Environment)")
    r.add_argument("--workers", type=int, help="concurrent tests (default from config, max 8)")
    r.add_argument("--browser", choices=browsers.choices(), help="chrome | msedge (Edge) | safari (Playwright's WebKit, the engine Safari uses) | chromium "
                                                                   "(the download); default: browser.name in config.yaml, else chromium")
    r.add_argument("--headed", action="store_true", help="show the browsers (debugging; not for daily use)")
    r.add_argument("--screenshots", choices=["every_step", "on_failure", "off"])
    r.add_argument("--seed", type=int, help="seed for RANDBETWEEN so generated data is reproducible")
    r.add_argument("--retries", type=int, help="re-run a failed test up to N times")
    r.add_argument("--chain", action="append", metavar="A,B,C",
                   help="run these tests one after another, in this order (repeat for more chains); replaces the chains saved for the workbook")
    r.add_argument("--no-chains", action="store_true", help="ignore the chains saved for the workbook / in config.yaml")
    r.add_argument("--pdf", action=argparse.BooleanOptionalAction, default=None, help="also export the report as PDF")
    r.add_argument("--no-report", action="store_true", help="skip the HTML report (results.json only)")
    r.add_argument("--harvest", action=argparse.BooleanOptionalAction, default=None,
                   help="record stable locators from the live DOM")
    r.add_argument("--allow-prod", action="store_true", help="permit PROD runs (real transactions!)")
    r.add_argument("--plain", action="store_true", help="plain text output instead of the live display")
    r.add_argument("--nice", action=argparse.BooleanOptionalAction, default=None,
                   help="lower (or with --no-nice, keep normal) process priority; default from config.yaml")
    r.add_argument("--run-id", help=argparse.SUPPRESS)
    r.add_argument("--inbox", help=argparse.SUPPRESS)              # the web UI: a folder further runs can be dropped into while this one is going
    r.add_argument("--ask", choices=["off", "terminal", "ui"], help="who answers ASK_USER steps (default: this terminal when there is one, else nobody; the web UI passes ui)")
    r.set_defaults(fn=cmd_run)
    p.run_parser = r

    l = sub.add_parser("list", help="list the tests in a workbook")
    l.add_argument("workbook")
    l.add_argument("--env")
    l.add_argument("--json", action="store_true")
    l.set_defaults(fn=cmd_list)

    pl = sub.add_parser("plan", help="show the resolved steps of one test without opening a browser")
    pl.add_argument("workbook")
    pl.add_argument("test")
    pl.add_argument("--env")
    pl.add_argument("--seed", type=int)
    pl.set_defaults(fn=cmd_plan)

    li = sub.add_parser("lint", help="find steps that will not behave as the author probably expects")
    li.add_argument("workbook")
    li.add_argument("--env")
    li.add_argument("--quiet", action="store_true", help="hide informational notes")
    li.set_defaults(fn=cmd_lint)

    s = sub.add_parser("selectors", help="audit / migrate / apply generic locators")
    s.add_argument("action", choices=["audit", "migrate", "apply"])
    s.add_argument("target", help="workbook (audit/migrate) or run id (apply)")
    s.add_argument("--env")
    s.add_argument("--tests")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--min-score", type=int, default=85)
    s.add_argument("--include-positional", action="store_true",
                   help="migrate: also convert (//x)[n] XPaths (equivalent, but just as layout-dependent)")
    s.set_defaults(fn=cmd_selectors)

    a = sub.add_parser("auth", help="one-time interactive SSO sign-in reused by headless runs")
    a.add_argument("action", choices=["login"])
    a.add_argument("--url", required=True)
    a.set_defaults(fn=cmd_auth)

    rp = sub.add_parser("report", help="(re)build the HTML/PDF report for a finished run")
    rp.add_argument("run")
    rp.add_argument("--pdf", action="store_true")
    rp.set_defaults(fn=cmd_report)

    pb = sub.add_parser("publish", help="copy a finished run's report + pass/fail summary to the shared folder (publish.dir)")
    pb.add_argument("run", help="run id (or path to a run folder)")
    pb.add_argument("--to", help="shared folder to use instead of publish.dir")
    pb.add_argument("--screenshots", choices=["failures", "all", "none"], help="screenshots embedded in the shared report (default: publish.screenshots)")
    pb.set_defaults(fn=cmd_publish)

    sv = sub.add_parser("serve", help="start the local web UI")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--open", action="store_true", help="open the UI in your default browser")
    sv.add_argument("--app", action="store_true",
                    help="open the UI in a window of its own (Edge or Chrome app mode); the default browser if neither is installed")
    sv.set_defaults(fn=cmd_serve)

    d = sub.add_parser("doctor", help="check the installation and configuration")
    d.set_defaults(fn=cmd_doctor)

    h = sub.add_parser("history", help="all runs in runs/: what changed between them, what got slower or started failing since, CSV export")
    h.add_argument("--workbook", help="only runs of workbooks whose file name contains this")
    h.add_argument("--csv", metavar="FOLDER", help="write runs.csv, tests.csv and steps.csv (for Excel) into FOLDER")
    h.add_argument("--at", metavar="RUN_ID", help="compare the runs before this one with it and the runs after (default: the latest change)")
    h.add_argument("--factor", type=float, default=2.0, help="a step counts as slower from this many times its earlier time (default 2)")
    h.add_argument("--min-s", dest="min_s", type=float, default=1.0, help="...and at least this many seconds slower (default 1)")
    h.add_argument("--hosts", action="store_true", help="also list the third-party hosts the pages loaded (for a tracker block list)")
    h.add_argument("--runs", metavar="FOLDER", help="the runs folder (default: runs_dir of config.yaml)")
    h.set_defaults(fn=cmd_history)
    return p


# What belongs to one workbook when several are run together; everything else (environment, workers, browser, screenshots...) is shared by all of them.
PER_WORKBOOK = ("--tests", "--tag", "--all", "--chain", "--no-chains", "--run-id")


def split_workbooks(parser: argparse.ArgumentParser, argv: list[str]) -> list[list[str]] | None:
    """``run A.xlsx --tests X B.xlsx --all --workers 4``: one argument list per workbook, or ``None`` when the command names a single workbook.

    A workbook's own options (``PER_WORKBOOK``) go with the workbook they follow (before the first workbook they go with the first);
    every other option is shared and given to each of them.  So ``regrunner run wb.xlsx --all`` is exactly what it always was."""
    run = getattr(parser, "run_parser", None)
    i = 0
    while i < len(argv) and argv[i].startswith("-"):                     # options before the sub-command: --config X
        i += 2 if argv[i] in ("--config",) else 1
    if run is None or i >= len(argv) or argv[i] != "run":
        return None
    prefix, rest = argv[:i], argv[i + 1:]
    known = run._option_string_actions

    def option(token: str):
        name = token.partition("=")[0]
        if name in known:
            return name, known[name]
        matches = [o for o in known if o.startswith(name) and name.startswith("--")]          # argparse accepts an unambiguous abbreviation
        return (matches[0], known[matches[0]]) if len(matches) == 1 else (name, None)

    books: list[dict] = []
    shared: list[str] = []
    early: list[str] = []
    j = 0
    while j < len(rest):
        token = rest[j]
        if token.startswith("-") and len(token) > 1:
            name, action = option(token)
            tokens = [token]
            if action is not None and action.nargs != 0 and "=" not in token and j + 1 < len(rest):
                j += 1
                tokens.append(rest[j])                                    # its value
            mine = name in PER_WORKBOOK
            (books[-1]["own"] if books else early).extend(tokens) if mine else shared.extend(tokens)
        else:
            books.append({"workbook": token, "own": []})
        j += 1
    if len(books) < 2:
        return None
    books[0]["own"][:0] = early
    return [[*prefix, "run", b["workbook"], *b["own"], *shared] for b in books]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    groups = split_workbooks(parser, argv)
    if groups:
        every = [parser.parse_args(g) for g in groups]
        args = every[0]
        args.also = every[1:]
    else:
        args = parser.parse_args(argv)
    cfg = load_config(args.config)
    return args.fn(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
