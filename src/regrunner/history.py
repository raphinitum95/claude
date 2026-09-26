"""One record across every run, built from the run folders themselves (``runs/<id>/``): nothing extra to copy from the work computer.

What it answers:

* per run, test and step: how long it took and where the time went (``measure.timing``), what it ended as and *what kind* of failure it was
  (the site said no / an element was missing / the machine could not run it / the WAF / a captcha), what the computer was going through at
  that moment (``resources.jsonl``), how many workers, which browser, which computer;
* **what changed** between two runs of the same workbook: the runner's version (a hash of its source files), the browser's version, the
  settings that affect speed, the computer, and the **site version** (a fingerprint of the site's own code files a test loaded: a new one
  means the site deployed new code);
* **compare**: "step X of test Y is 3 x slower since <that change>", "these steps started failing after <that change>";
* which third-party hosts the pages loaded, over all runs (the input for a tracker block list).

Exported as CSV for Excel.  It never records what a step typed or read (values, expected / actual text, error messages): only times,
statuses, kinds and versions - history files may be shared.  Runs from before these measurements existed still count (their missing
numbers are blank).
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .engine.resources import read_resources, summarize

PARTS = ("site", "wait", "runner", "computer", "other")

# Settings that change how fast a run goes (not what it checks): a change to one of them is a "what changed" marker.
SPEED_SETTINGS = ("runner.workers", "runner.max_workers", "runner.stagger_s", "runner.min_page_load_gap_s", "runner.low_priority",
                  "runner.headless", "browser.args", "browser.name", "timeouts", "waits", "patience", "screenshots", "failure_capture.enabled",
                  "failure_capture.full_page_screenshot", "failure_capture.dom_snapshot", "output.match_timeout_s", "output.stable_ms")


@dataclass
class Run:
    run_id: str
    dir: Path
    data: dict[str, Any]
    meta: dict[str, Any]
    samples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def workbook(self) -> str:
        return Path(str(self.data.get("workbook") or self.meta.get("workbook") or "")).name

    @property
    def started(self) -> str:
        return str(self.data.get("started_at") or self.meta.get("started_at") or "")

    @property
    def machine(self) -> dict[str, Any]:
        return self.data.get("machine") or {}

    @property
    def runner_version(self) -> str:
        return str(self.machine.get("runner_version") or "")

    @property
    def browser_version(self) -> str:
        b = self.data.get("browser") or self.meta.get("browser") or {}
        return " ".join(x for x in (str(b.get("id") or b.get("name") or ""), str(b.get("version") or "")) if x)

    @property
    def site_version(self) -> str:
        """The fingerprint most of the run's tests saw ("" when none recorded one)."""
        seen = Counter((t.get("site_version") or {}).get("fingerprint") for t in self.data.get("tests", []))
        seen.pop(None, None)
        return seen.most_common(1)[0][0] if seen else ""

    @property
    def machine_label(self) -> str:
        m = self.machine
        if not m:
            return ""
        return f"{m.get('os', '')} {m.get('cpus', '?')} cores {round((m.get('ram_mb') or 0) / 1024)} GB"

    def speed_settings(self) -> dict[str, Any]:
        config = self.data.get("config") or {}
        out: dict[str, Any] = {}
        for dotted in SPEED_SETTINGS:
            section, _, key = dotted.partition(".")
            value = config.get(section)
            if key:
                value = value.get(key) if isinstance(value, dict) else None
            if value is not None:
                out[dotted] = value
        out["workers_used"] = self.data.get("workers")
        return out


def _parse_time(text: str) -> float | None:
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return None


def load_runs(runs_dir: Path, workbook: str | None = None) -> list[Run]:
    """Every run folder under ``runs_dir`` that has a ``results.json``, oldest first."""
    runs: list[Run] = []
    if not runs_dir.is_dir():
        return runs
    for results in runs_dir.glob("*/results.json"):
        try:
            data = json.loads(results.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            meta = json.loads((results.parent / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        run = Run(run_id=str(data.get("run_id") or results.parent.name), dir=results.parent, data=data, meta=meta)
        if workbook and workbook.lower() not in run.workbook.lower():
            continue
        run.samples = read_resources(results.parent / "resources.jsonl")
        runs.append(run)
    runs.sort(key=lambda r: (_parse_time(r.started) or 0.0, r.run_id))
    return runs


# -- kinds of failure -------------------------------------------------------------------------------------------------
_MISSING = re.compile(r"not found|did not appear|could not find|no element|timeout|timed out|not visible|not attached|is not enabled|detached", re.I)


def step_error_kind(step: dict[str, Any]) -> str:
    """What kind of failure a step was: site_said_no (the page showed something else) | element_missing | infra (the machine) | waf |
    captcha | other; "" for a step that passed."""
    status = str(step.get("status") or "")
    if status == "PASSED":
        return ""
    error = str(step.get("error") or "")
    if status == "NOT_RUN" or error.startswith("Not run:"):
        return "infra"
    if "Blocked by the site" in error:
        return "waf"
    if "captcha" in error.lower():
        return "captcha"
    if error.startswith("Comparison Failed"):
        return "site_said_no"
    if _MISSING.search(error) or _MISSING.search(str(step.get("detail") or "")):
        return "element_missing"
    return "other"


def test_error_kind(test: dict[str, Any]) -> str:
    status = str(test.get("status") or "")
    if status == "PASSED":
        return ""
    if status == "NOT_RUN" or test.get("infra"):
        return "infra"
    if test.get("blocked"):
        return "waf"
    if test.get("captcha"):
        return "captcha"
    if status in ("CANCELLED", "INTERRUPTED", "QUEUED"):
        return status.lower()
    failed = next((s for s in test.get("steps", []) if s.get("status") not in ("PASSED", None)), None)
    return step_error_kind(failed) if failed else "other"


# -- rows (CSV) -----------------------------------------------------------------------------------------------------
def _sample_at(run: Run, when: float | None) -> dict[str, Any]:
    """The resource sample in force at ``when`` (the last one taken before it)."""
    if when is None or not run.samples:
        return {}
    best = None
    for sample in run.samples:
        t = sample.get("t")
        if isinstance(t, (int, float)) and t <= when:
            best = sample
        elif isinstance(t, (int, float)) and t > when:
            break
    return best or {}


RESOURCE_COLUMNS = ("mem_free_mb", "swap_used_mb", "browsers_mb", "cpu_pct", "loop_lag_ms", "tests_running")


def run_rows(runs: list[Run]) -> list[dict[str, Any]]:
    rows = []
    for run in runs:
        summary = run.data.get("summary") or {}
        timing = run.data.get("timing") or {}
        peaks = run.data.get("resources") or summarize(run.samples)
        rows.append({"run_id": run.run_id, "started_at": run.started, "workbook": run.workbook, "environment": run.data.get("environment", ""),
                     "status": run.data.get("status", ""), "duration_s": run.data.get("duration_s"), "workers": run.data.get("workers"),
                     "tests": summary.get("tests"), "passed": summary.get("passed"), "failed": summary.get("failed"),
                     "errored": summary.get("errored"), "not_run": summary.get("not_run"),
                     **{f"{p}_s": timing.get(f"{p}_s") for p in PARTS}, "queue_s": timing.get("queue_s"),
                     "min_mem_free_mb": peaks.get("min_mem_free_mb"), "max_swap_used_mb": peaks.get("max_swap_used_mb"),
                     "max_browsers_mb": peaks.get("max_browsers_mb"), "max_loop_lag_ms": peaks.get("max_loop_lag_ms"),
                     "browser": run.browser_version, "runner_version": run.runner_version, "site_version": run.site_version,
                     "machine": run.machine_label, "ram_mb": run.machine.get("ram_mb"), "cpus": run.machine.get("cpus")})
    return rows


def test_rows(runs: list[Run]) -> list[dict[str, Any]]:
    rows = []
    for run in runs:
        for test in run.data.get("tests", []):
            timing = test.get("timing") or {}
            sample = _sample_at(run, _parse_time(str(test.get("ended_at") or "")))
            rows.append({"run_id": run.run_id, "started_at": test.get("started_at", ""), "workbook": run.workbook, "test": test.get("id", ""),
                         "status": test.get("status", ""), "error_kind": test_error_kind(test), "attempt": test.get("attempt", 1),
                         "earlier_attempts": len(test.get("attempts") or []), "duration_s": test.get("duration_s"),
                         **{f"{p}_s": timing.get(f"{p}_s") for p in PARTS}, "queue_s": timing.get("queue_s"),
                         "steps": len(test.get("steps", [])), "failed_steps": test.get("failed"),
                         "third_party_hosts": len(test.get("third_party") or []),
                         "site_version": (test.get("site_version") or {}).get("fingerprint", ""),
                         **{f"at_end_{k}": sample.get(k) for k in RESOURCE_COLUMNS}, "workers": run.data.get("workers"),
                         "browser": run.browser_version, "runner_version": run.runner_version, "machine": run.machine_label})
    return rows


def step_rows(runs: list[Run]) -> list[dict[str, Any]]:
    rows = []
    for run in runs:
        for test in run.data.get("tests", []):
            for step in test.get("steps", []):
                timing = step.get("timing") or {}
                sample = _sample_at(run, _parse_time(str(step.get("ended_at") or "")))
                rows.append({"run_id": run.run_id, "workbook": run.workbook, "test": test.get("id", ""), "attempt": test.get("attempt", 1),
                             "seq": step.get("seq"), "row": step.get("row"), "step": step.get("name", ""), "action": step.get("action", ""),
                             "status": step.get("status", ""), "error_kind": step_error_kind(step), "ended_at": step.get("ended_at", ""),
                             "duration_ms": step.get("duration_ms"), **{f"{p}_ms": timing.get(f"{p}_ms") for p in PARTS},
                             **{k: sample.get(k) for k in RESOURCE_COLUMNS}, "workers": run.data.get("workers"),
                             "browser": run.browser_version, "runner_version": run.runner_version, "site_version": run.site_version})
    return rows


def export_csv(runs: list[Run], out_dir: Path) -> list[Path]:
    """``runs.csv``, ``tests.csv``, ``steps.csv`` (UTF-8 with a BOM so Excel reads accents; one row per run / test / step)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, rows in (("runs.csv", run_rows(runs)), ("tests.csv", test_rows(runs)), ("steps.csv", step_rows(runs))):
        path = out_dir / name
        columns = list(rows[0]) if rows else ["run_id"]
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written


# -- what changed ---------------------------------------------------------------------------------------------------
@dataclass
class Marker:
    workbook: str
    run_id: str                 # the first run with the new value
    started_at: str
    kind: str                   # runner | browser | site | settings | machine
    before: str
    after: str

    def describe(self) -> str:
        what = {"runner": "runner version", "browser": "browser", "site": "site version (its code files)", "settings": "speed settings",
                "machine": "computer"}[self.kind]
        return f"{what} changed in run {self.run_id} ({self.started_at[:16].replace('T', ' ')}): {self.before or '?'} -> {self.after or '?'}"


def markers(runs: list[Run]) -> list[Marker]:
    """Every change between two consecutive runs of the same workbook (a value that was not recorded is not a change)."""
    found: list[Marker] = []
    by_book: dict[str, list[Run]] = {}
    for run in runs:
        by_book.setdefault(run.workbook, []).append(run)
    for book, series in by_book.items():
        last: dict[str, Any] = {}
        for run in series:
            now = {"runner": run.runner_version, "browser": run.browser_version, "site": run.site_version, "machine": run.machine_label,
                   "settings": run.speed_settings()}
            for kind, value in now.items():
                if not value:
                    continue
                before = last.get(kind)
                if before is not None and before != value:
                    if kind == "settings":
                        keys = sorted(k for k in set(before) | set(value) if before.get(k) != value.get(k))
                        b = ", ".join(f"{k}={json.dumps(before.get(k))}" for k in keys)
                        a = ", ".join(f"{k}={json.dumps(value.get(k))}" for k in keys)
                        found.append(Marker(book, run.run_id, run.started, kind, b, a))
                    else:
                        found.append(Marker(book, run.run_id, run.started, kind, str(before), str(value)))
                last[kind] = value
    return found


# -- compare ----------------------------------------------------------------------------------------------------------
def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def compare(runs: list[Run], *, at: str | None = None, factor: float = 2.0, min_s: float = 1.0) -> list[str]:
    """Per workbook: the runs before a change against the runs since it (the latest "what changed" marker, or the run ``at``).  Lists the
    steps that got ``factor`` times slower (and at least ``min_s`` slower), with the part of the time that grew, and the steps that passed
    in every run before and fail in every run since."""
    lines: list[str] = []
    all_markers = markers(runs)
    by_book: dict[str, list[Run]] = {}
    for run in runs:
        by_book.setdefault(run.workbook, []).append(run)
    for book, series in by_book.items():
        ids = [r.run_id for r in series]
        if at:
            if at not in ids:
                continue
            split, why = ids.index(at), f"run {at}"
        else:
            own = [m for m in all_markers if m.workbook == book]
            if not own:
                if len(series) >= 2:
                    split, why = len(series) - 1, f"the latest run {ids[-1]} (nothing changed between runs)"
                else:
                    continue
            else:
                marker = own[-1]
                split = ids.index(marker.run_id)
                changed = [m for m in own if m.run_id == marker.run_id]
                why = "; ".join(m.describe() for m in changed)
        before, since = series[:split], series[split:]
        if not before or not since:
            continue
        head = f"{book}: {len(before)} run(s) before vs {len(since)} since {why}"
        found: list[str] = []

        def steps_of(group: list[Run]) -> dict[tuple, list[dict[str, Any]]]:
            out: dict[tuple, list[dict[str, Any]]] = {}
            for run in group:
                for test in run.data.get("tests", []):
                    for step in test.get("steps", []):
                        out.setdefault((test.get("id"), step.get("row"), step.get("name") or step.get("action")), []).append(step)
            return out
        old, new = steps_of(before), steps_of(since)
        for key in [k for k in new if k in old]:
            test, row, name = key
            was = _median([float(s.get("duration_ms") or 0) / 1000 for s in old[key] if s.get("status") == "PASSED"])
            now = _median([float(s.get("duration_ms") or 0) / 1000 for s in new[key] if s.get("status") == "PASSED"])
            if was > 0 and now >= was * factor and now - was >= min_s:
                grew = {p: _median([float((s.get("timing") or {}).get(f"{p}_ms") or 0) / 1000 for s in new[key]])
                        - _median([float((s.get("timing") or {}).get(f"{p}_ms") or 0) / 1000 for s in old[key]]) for p in PARTS}
                part, extra = max(grew.items(), key=lambda kv: kv[1])
                mostly = f"; mostly {PART_LABELS[part]} (+{extra:.1f} s)" if extra > 0.2 else ""
                found.append(f"  {test} step \"{name}\" (row {row}): {now / was:.1f} x slower ({was:.1f} s -> {now:.1f} s){mostly}")
            if all(s.get("status") == "PASSED" for s in old[key]) and all(s.get("status") not in ("PASSED", "NOT_RUN") for s in new[key]):
                kinds = Counter(step_error_kind(s) for s in new[key]).most_common(1)[0][0]
                found.append(f"  {test} step \"{name}\" (row {row}): passed in every run before, fails in every run since ({kinds})")
        lines.append(head + (":" if found else ": no step got slower or started failing."))
        lines.extend(found)
    return lines


PART_LABELS = {"site": "the site", "wait": "deliberate waits", "runner": "the runner's own work", "computer": "a busy computer",
               "other": "browser / actions"}


def third_party_hosts(runs: list[Run]) -> list[dict[str, Any]]:
    """Every third-party host the pages loaded, over all runs: requests, bytes, how many tests and runs loaded it (most requested first)."""
    hosts: dict[str, dict[str, Any]] = {}
    for run in runs:
        for test in run.data.get("tests", []):
            for entry in test.get("third_party") or []:
                host = str(entry.get("host") or "")
                if not host:
                    continue
                h = hosts.setdefault(host, {"host": host, "requests": 0, "bytes": 0, "tests": 0, "runs": set()})
                h["requests"] += int(entry.get("requests") or 0)
                h["bytes"] += int(entry.get("bytes") or 0)
                h["tests"] += 1
                h["runs"].add(run.run_id)
    out = [{**h, "runs": len(h["runs"])} for h in hosts.values()]
    return sorted(out, key=lambda h: (-h["requests"], h["host"]))
