"""Console listener: another subscriber to the same event stream the web UI reads.

* Plain mode (pipes, CI, ``--plain``): one line per step - ``Login flow: step 15/30 passed (50%)``
* Rich mode (interactive terminal): live per-test progress bars plus a global bar.
"""
from __future__ import annotations

import sys
import time
from typing import Any, TextIO

from ..events import Event


def _browser_text(e) -> str:
    """The browser every test of the run uses, e.g. Google Chrome 141.0.7390.55, headless."""
    b = e.get("browser") or {}
    if not b:
        return "unknown"
    return b.get("text", "unknown") if b.get("id") == "none" else f'{b.get("text", "unknown")}, {"headless" if b.get("headless", True) else "headed"}'


class ConsoleState:
    """Aggregates events into what a console needs to show."""

    def __init__(self):
        self.tests: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.done = self.total = 0
        self.failures: list[str] = []
        self.review = 0
        self.workers = 1
        self.environment = ""

    def apply(self, e: Event) -> None:
        kind = e["type"]
        if kind == "run_started":
            self.workers, self.environment = e.get("workers", 1), e.get("environment", "")
            for t in e.get("tests", []):
                self.order.append(t["id"])
                self.tests[t["id"]] = {"title": t["title"], "done": 0, "total": t.get("total_steps", 0),
                                       "status": "queued", "failed": 0, "step": ""}
        elif kind == "test_started":
            t = self.tests.setdefault(e["test"], {"title": e.get("title", e["test"]), "done": 0, "total": 0,
                                                  "status": "", "failed": 0, "step": ""})
            t.update(status="running", total=e.get("total_steps", t["total"]))
        elif kind in ("step_passed", "step_failed"):
            t = self.tests[e["test"]]
            t["done"] += 1
            t["total"] = max(t["total"], t["done"])
            t["step"] = e.get("name") or e.get("action", "")
            if kind == "step_failed":
                t["failed"] += 1
                self.failures.append(f'{t["title"]}: step {e["step"]} "{e.get("name", "")}" - {e.get("error", "")}')
        elif kind == "test_finished":
            t = self.tests[e["test"]]
            t["status"] = e["status"].lower()
            t["done"] = t["total"] = max(t["done"], t["total"])
        elif kind in ("console_error", "network_error", "review_item"):
            self.review += 1
        if kind in ("run_started", "test_started", "step_passed", "step_failed", "test_finished"):
            # Own totals (not the derived run_progress event, which is queued one event behind).
            self.done = sum(t["done"] for t in self.tests.values())
            self.total = sum(t["total"] for t in self.tests.values())

    @property
    def percent(self) -> float:
        return round(100 * self.done / self.total, 1) if self.total else 0.0


def pct(done: int, total: int) -> int:
    return int(100 * done / total) if total else 0


class PlainConsole:
    def __init__(self, stream: TextIO | None = None, prefix: str = ""):
        self.out = stream or sys.stdout
        self.state = ConsoleState()
        self.prefix = prefix                                  # several runs in one terminal: every line says which workbook it is about

    def _p(self, text: str = "") -> None:
        print(f"{self.prefix}{text}" if text and self.prefix else text, file=self.out, flush=True)

    def __call__(self, e: Event) -> None:
        self.state.apply(e)
        kind, s = e["type"], self.state
        if kind == "run_started":
            self._p(f'Run {e["run_id"]}: {len(e["tests"])} test(s), {e["workers"]} worker(s), environment {e["environment"]}, browser {_browser_text(e)}')
            for w in e.get("warnings", []):
                self._p(f"  ! {w}")
        elif kind in ("step_passed", "step_failed"):
            t = s.tests[e["test"]]
            verb = "passed" if kind == "step_passed" else "FAILED"
            extra = f' - {e.get("error", "")}' if kind == "step_failed" else ""
            self._p(f'{t["title"]}: step {t["done"]}/{t["total"]} {verb} ({pct(t["done"], t["total"])}%) '
                    f'| overall {pct(s.done, s.total)}%{extra}')
        elif kind == "test_finished":
            t = s.tests[e["test"]]
            self._p(f'{t["title"]}: {e["status"]} - {e["passed"]} passed, {e["failed"]} failed in {e["duration_s"]}s'
                    + (f' ({e["error"]})' if e.get("error") else ""))
        elif kind == "log":
            self._p(f'[{e["level"]}] {e["message"]}')
        elif kind == "worker_waiting":
            self._p(f'[waiting] {e.get("test", "")} (worker {e.get("worker", "?")}): {e.get("message", "")}')

    def finish(self, result, run_dir) -> None:
        summary_lines(result, run_dir, self._p)


def summary_lines(result, run_dir, emit) -> None:
    s = result.summary
    emit("")
    emit(f'{result.status}: {s["passed"]}/{s["tests"]} tests passed, {s["steps_failed"]} failed step(s), '
         f'{s["steps"]} steps in {result.duration_s}s')
    if s.get("not_run"):
        emit(f'  {s["not_run"]} test(s) NOT RUN: the browser crashed / ran out of memory / disconnected on every attempt. Neither passed nor failed.')
    for t in result.tests:
        emit(f'  {t.status:9} {t.title:24} {t.passed} passed / {t.failed} failed / {len(t.review)} to review  ({t.duration_s}s)')
    failures = [(t, st) for t in result.tests for st in t.steps if st.status == "FAILED"]
    if failures:
        emit("")
        emit("Failed steps:")
        for t, st in failures[:40]:
            emit(f'  {t.title} #{st.seq} (row {st.row}) "{st.name}": {st.error}'
                 + (f' | expected {st.expected!r} actual {st.actual!r}' if st.comparison else ""))
    review = [(t, i) for t in result.tests for i in t.review]
    if review:
        emit("")
        emit(f"Things to review ({len(review)}; informational - does not affect results):")
        for t, i in review[:40]:
            what = i.get("message") or i.get("url") or ""
            emit(f'  {t.title} step {i.get("step")}: [{i.get("kind") or i.get("category")}'
                 f'{" " + str(i["status"]) if i.get("status") else ""}] {str(what)[:150]}'
                 + (f' x{i["count"]}' if i.get("count", 1) > 1 else ""))
        if len(review) > 40:
            emit(f"  ... {len(review) - 40} more in the report")
    emit("")
    for label, rel in result.artifacts.items():
        emit(f"  {label}: {run_dir / rel}")


class RichConsole:
    def __init__(self):
        from rich.console import Console
        from rich.live import Live
        self.console = Console()
        self.state = ConsoleState()
        self.live = Live(console=self.console, refresh_per_second=6, transient=False)
        self._last = 0.0
        self._started = False
        self._header = ""

    def _render(self):
        from rich.console import Group
        from rich.progress_bar import ProgressBar
        from rich.table import Table
        from rich.text import Text
        s = self.state
        table = Table(box=None, pad_edge=False, expand=True)
        table.add_column("Test", no_wrap=True)
        table.add_column("Progress", ratio=1)
        table.add_column("Step", justify="right", no_wrap=True)
        table.add_column("%", justify="right", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        colors = {"passed": "green", "failed": "red", "running": "cyan", "queued": "grey50", "error": "red",
                  "cancelled": "yellow", "not_run": "yellow"}
        for tid in s.order:
            t = s.tests[tid]
            color = "red" if t["failed"] else colors.get(t["status"], "white")
            table.add_row(t["title"], ProgressBar(total=max(t["total"], 1), completed=t["done"], width=None,
                                                  complete_style=color, finished_style=color),
                          f'{t["done"]}/{t["total"]}', f'{pct(t["done"], t["total"])}%',
                          Text(t["status"] + (f' ({t["failed"]} failed)' if t["failed"] else ""), style=color))
        overall = Group(
            Text(f'Overall {pct(s.done, s.total)}%  ({s.done}/{s.total} steps)  ·  {s.review} item(s) to review  ·  '
                 f'{s.workers} worker(s)', style="bold"),
            ProgressBar(total=max(s.total, 1), completed=s.done, width=None))
        recent = Text("\n".join(s.failures[-3:]), style="red") if s.failures else Text("")
        return Group(Text(self._header, style="dim"), table, overall, recent)

    def __call__(self, e: Event) -> None:
        self.state.apply(e)
        if e["type"] == "run_started":
            self._header = f'Run {e["run_id"]} · {e["environment"]} · {_browser_text(e)}'
            for w in e.get("warnings", []):
                self.console.print(f"[yellow]! {w}[/yellow]")
            self.live.start()
            self._started = True
        if e["type"] == "log":
            self.console.print(f'[dim][{e["level"]}] {e["message"]}[/dim]')
        if e["type"] == "worker_waiting":
            from rich.markup import escape
            self.console.print(f'[yellow]waiting · {escape(str(e.get("test", "")))} (worker {e.get("worker", "?")}): {escape(str(e.get("message", "")))}[/yellow]')
        now = time.monotonic()
        if self._started and (now - self._last > 0.1 or e["type"] in ("test_finished", "run_finished")):
            self.live.update(self._render())
            self._last = now

    def finish(self, result, run_dir) -> None:
        if self._started:
            self.live.update(self._render())
            self.live.stop()
        summary_lines(result, run_dir, lambda text="": self.console.print(text, highlight=False, markup=False))


def make_console(plain: bool = False, prefix: str = ""):
    return PlainConsole(prefix=prefix) if plain or prefix or not sys.stdout.isatty() else RichConsole()
