"""Read-only questions about a workbook: what tests does it hold, what would run, what looks risky.

Everything here works on the parsed workbook only - no browser is started and no site is contacted - so
it is safe to call from the CLI or the web UI at any time.
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .lint import lint, summarize
from .selectors.migrate import collect
from .selectors.resolve import SelectorMap, build_chain
from .workbook.model import TestCase, Workbook
from .workbook.sheet import cell_text


def test_tags(case: TestCase, cfg: Config) -> list[str]:
    """Tags from the workbook's DataSheets column plus the groups defined in config.yaml."""
    tags = list(case.tags)
    for tag, ids in cfg.tags.items():
        if (case.id in ids or case.sheet in ids) and tag not in tags:
            tags.append(tag)
    return tags


def list_tests(workbook: Workbook, cfg: Config, flows: list | None = None) -> list[dict[str, Any]]:
    """The test table: UI keyword sheets and API data rows, with a dry-run step count for each.  ``flows``: when a list is given, it is filled with
    what each test does with parameters (engine/order.py), from the very same dry run - the run order needs no second pass over the workbook."""
    from .engine.order import Flow
    tests = []
    for index, case in enumerate(workbook.discover()):
        if not case.runnable:
            continue
        runtime = workbook.runtime(case)
        planned = runtime.plan()
        if flows is not None:
            flows.append(Flow.of(case, index, runtime))
        tests.append({
            "id": case.id, "kind": case.kind, "sheet": case.sheet, "title": case.title, "scenario": case.scenario,
            "description": case.description, "enabled": case.enabled, "runnable": case.param_enabled,
            "iteration": case.iteration, "iterations": case.iterations, "tags": test_tags(case, cfg),
            "steps": len(planned), "asks": sum(method in ("ASK_USER", "PROMPT", "ASK") for _, _, method in planned),
            "needs": getattr(runtime, "needs", []),          # empty parameters the test uses that nothing in it sets: [{param, cell, rows, steps, set_by}]
        })
    return tests


def summary_and_flows(workbook: Workbook, cfg: Config) -> tuple[dict[str, Any], list]:
    """``workbook_summary`` plus the flows of every test (for the run order), from one pass over the workbook."""
    flows: list = []
    return workbook_summary(workbook, cfg, flows), flows


def workbook_summary(workbook: Workbook, cfg: Config, flows: list | None = None) -> dict[str, Any]:
    tests = list_tests(workbook, cfg, flows)
    settings = workbook.global_settings()
    return {"tests": tests, "warnings": list(workbook.warnings), "environment": str(settings.get("Environment", "")).upper(),
            "sheets": len(tests), "flagged": sum(t["enabled"] for t in tests)}


def plan_steps(workbook: Workbook, cfg: Config, test: str, *, limit: int = 5000) -> dict[str, Any]:
    """Dry run of one test: every step that would execute, after token substitution and gating."""
    wanted = test.lower()
    cases = [c for c in workbook.discover() if c.runnable and wanted in (c.id.lower(), c.sheet.lower())]
    if not cases:
        raise KeyError(test)
    case = cases[0]
    if case.kind == "api":
        planned = workbook.runtime(case).plan()
        return {"test": case.id, "count": len(planned), "truncated": False,
                "steps": [{"n": n, "row": row, "action": method, "name": name, "target": "", "value": ""}
                          for n, (row, name, method) in enumerate(planned[:limit], start=1)]}
    smap = SelectorMap.load(cfg.path(cfg.selectors.map))
    runtime = workbook.runtime(case)
    steps: list[dict[str, Any]] = []
    total = 0
    for row in range(2, runtime.total_rows + 1):
        step = runtime.prepare_row(row)
        if step is None:
            continue
        total += 1
        if total <= limit:
            chain = build_chain(step.findby, step.findby_value, step.locator_column, smap,
                                legacy_fallback=cfg.selectors.legacy_fallback)
            value = "••••••" if "VALUE" in step.secret_columns else step.text("VALUE")
            steps.append({"n": total, "row": row, "action": step.method, "name": step.name,
                          "target": chain[0].describe() if chain else "", "value": value[:80]})
        runtime.record(step, "PASSED", "", "")
    return {"test": case.id, "count": total, "steps": steps, "truncated": total > limit}


def lint_report(workbook: Workbook) -> dict[str, Any]:
    order = {"error": 0, "warning": 1, "info": 2}
    findings = lint(workbook)
    ordered = sorted(findings, key=lambda f: (order[f.severity], f.test, f.row or 0))
    return {"counts": summarize(findings),
            "findings": [{"severity": f.severity, "test": f.test, "row": f.row, "message": f.message} for f in ordered]}


def audit_report(workbook: Workbook, cfg: Config, *, top: int = 25) -> dict[str, Any]:
    """How resilient the workbook's locators are, and how much of it ``selectors.yaml`` already covers."""
    uses = collect(workbook)
    smap = SelectorMap.load(cfg.path(cfg.selectors.map))
    total = sum(u.uses for u in uses)
    covered = sum(u.uses for u in uses if u.key in smap.entries)
    convertible = sum(u.uses for u in uses if u.css)
    labels = {lab: sum(u.uses for u in uses if u.label == lab) for lab in ("strong", "ok", "weak")}
    weakest = [{"score": u.score, "uses": u.uses, "value": u.value, "reasons": u.reasons, "css": u.css,
                "skipped": u.skipped_reason, "mapped": u.key in smap.entries, "tests": sorted(u.tests)}
               for u in sorted((u for u in uses if u.label != "strong"), key=lambda u: (u.score, -u.uses))[:top]]
    pct = lambda n: round(100 * n / total) if total else 0
    return {"distinct": len(uses), "uses": total, "map_entries": len(smap), "covered_uses": covered,
            "covered_pct": pct(covered), "convertible_uses": convertible, "convertible_pct": pct(convertible),
            "labels": labels, "weakest": weakest}


def start_url(workbook: Workbook) -> str:
    """The first URL any test opens - a sensible default for the one-time SSO sign-in."""
    from .engine.actions import parse_open_value
    for case in workbook.discover():
        if not case.is_ui:
            continue
        runtime = workbook.runtime(case)
        for row in range(2, runtime.total_rows + 1):
            step = runtime.prepare_row(row)
            if step is None:
                continue
            if step.method == "OPEN":
                url = parse_open_value(cell_text(step.value)).get("URL", "").strip()
                if url.lower().startswith(("http://", "https://")):
                    return url
            runtime.record(step, "PASSED", "", "")
    return ""
