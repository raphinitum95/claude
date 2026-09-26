"""``regrunner lint``: find workbook steps that will not behave the way the author probably assumes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .engine.actions import LEGACY_EXISTENCE_ALIASES, REGISTRY, UNSUPPORTED
from .engine.test_runner import UNSUPPORTED_PAGES
from .selectors.spec import FINDBY_ALIASES
from .workbook.model import BLANK_OK_METHODS, RESULT_COLUMNS, Workbook, is_blank
from .workbook.sheet import ErrorText

_FINDBY_ALL = {alias for aliases in FINDBY_ALIASES.values() for alias in aliases}


@dataclass
class Finding:
    severity: str          # error | warning | info
    test: str
    row: int | None
    message: str

    def __str__(self) -> str:
        where = f"{self.test}" + (f" row {self.row}" if self.row else "")
        return f"{self.severity.upper():7} {where}: {self.message}"


def lint_api(workbook: Workbook, case, seen_io: set[int]) -> list[Finding]:
    """An API data row: is the request buildable, and does the InputOutput sheet say what the author probably thinks it says?"""
    from .workbook.api import CHECK_KINDS, METHODS
    findings: list[Finding] = []
    runtime = workbook.runtime(case)
    add = lambda sev, msg, row=case.param_row: findings.append(Finding(sev, case.id, row, msg))
    request = runtime.request()
    for column in ("WEBSERVICE_URL", "WEBSERVICE_METHOD"):
        if problem := runtime.error_in(column):
            add("error", f"{problem}: regrunner cannot calculate that Excel formula")
    if not request.url and not runtime.error_in("WEBSERVICE_URL"):
        add("error", f"no URL: {request.url_problem}" if request.url_problem else "WEBSERVICE_URL is empty")
    elif request.url and not request.url.lower().startswith(("http://", "https://")):
        add("error", f"WEBSERVICE_URL {request.url!r} is not an http(s) address")
    if request.method not in METHODS:
        add("error", f"WEBSERVICE_METHOD {request.method!r} is not one of {', '.join(METHODS)}")
    if not request.json_format:
        add("warning", "JSON_FORMAT is not Y: regrunner's API tests send and read JSON only (XML / SOAP sheets are not supported)")
    for header, column in runtime.io.add_header.items():
        if column.upper() not in runtime.values:
            add("warning", f"addHeader {header}: the row has no column {column!r}, so the header is not sent")
        elif problem := runtime.error_in(column):
            add("error", f"addHeader {header}: {problem}")
    for path in runtime.io.output_json:
        if path.startswith("$") or "*" in path or ".." in path:
            add("warning", f"output_json {path!r} is a JSONPath expression; only dotted paths (a.b.[0].c) are supported")
    for kind in CHECK_KINDS:
        for expected in runtime.io.checks[kind]:
            if expected.upper() not in runtime.values:
                add("info", f"{kind} {expected}: the sheet has no such column, so this check is not made (as in the legacy runner)")
    if request.method in ("POST", "PUT", "PATCH") and not request.template_file:
        add("info", "no XML_REQUESTFILE: the request is sent without a body")
    if id(workbook) not in seen_io:                                    # the InputOutput sheet is shared by every API test: say it once
        seen_io.add(id(workbook))
        for row, why in runtime.io.ignored_rows:
            findings.append(Finding("warning", "InputOutput", row, why))
    return findings


def lint(workbook: Workbook) -> list[Finding]:
    findings: list[Finding] = [Finding("warning", "workbook", None, w) for w in workbook.warnings]
    seen_io: set[int] = set()
    for case in workbook.discover():
        if case.kind == "api":
            findings.extend(lint_api(workbook, case, seen_io))
            continue
        if not case.is_ui:
            continue
        runtime = workbook.runtime(case)
        uncompared = 0
        setters: set[str] = set()                                # parameters an earlier step of this test fills in
        for row in range(2, runtime.total_rows + 1):
            step = runtime.prepare_row(row)
            if step is None:
                continue
            method = step.method
            here = lambda sev, msg: findings.append(Finding(sev, case.id, row, f'"{step.name}": {msg}'))
            for _, token in ([] if method in BLANK_OK_METHODS else step.blank_params):
                if token.upper() not in setters:
                    sets = [w for w in runtime.writers.get(token.upper(), []) if w != case.sheet]
                    here("warning", f"parameter {token} is empty ({runtime.param_cell(token)}) and no earlier step of this test sets it"
                                    f"{f' ({chr(32).join(sets)} does, when it runs first)' if sets else ''}: the step fails, or from the web UI / a terminal "
                                    "asks for the value")
            if step.raw_output_name and step.raw_output_name.upper().strip() in runtime.params:
                setters.add(step.raw_output_name.upper().strip())
            for column, cell in step.values.items():
                if isinstance(cell, ErrorText) and cell.code == "#NAME?" and column not in RESULT_COLUMNS:
                    here("error", f"the {column.replace('_', ' ').title()} cell evaluates to #NAME? ({cell.detail or 'unknown name'}): "
                                  "regrunner cannot calculate that Excel formula")
            if step.page in UNSUPPORTED_PAGES:
                here("error", f"Page type {step.page} is not supported (web UI steps only)")
            elif method in UNSUPPORTED:
                here("error", f"action {method} is not supported by regrunner")
            elif method in LEGACY_EXISTENCE_ALIASES:
                here("warning", f"{method} was never implemented by the legacy runner; it only checks that the "
                                "element exists and does NOT verify the value")
            elif method not in REGISTRY and method not in ("BREAK", "STOP"):
                here("warning", f"unknown action {method!r}; it will only check that the element exists")
            if method in ("ASK_USER", "PROMPT", "ASK"):
                here("info", "asks a person while the run is going (on the run screen in the web UI, or at the terminal); it fails after "
                             "Timeout seconds (default 300) if nobody answers, and cannot run from a script")
                if step.output_property not in ("", "SECRET", "PASSWORD", "TEXT"):
                    here("warning", f"Output_Property {step.output_property!r} means nothing for ASK_USER (leave it empty, or SECRET to hide what is typed)")
            if step.findby and step.findby not in _FINDBY_ALL:
                here("error", f"unknown FindBy {step.findby!r}")
            if method in REGISTRY and REGISTRY[method].element and not step.findby_value and not step.locator_column:
                here("error", "element action without FindBy_Value or Locator")
            if method == "OUTPUT" and step.output_property == "INNERTEXT" and "option" in step.findby_value.lower():
                here("warning", "reads the innerText of an <option>, which is the same whether or not it is selected, so it cannot show what was selected; "
                                "point it at the <select> with Output_Property = value")
            if method == "OUTPUT" and not is_blank(step.expected) and not step.exact_match and not step.contains:
                uncompared += 1
            if method != "OUTPUT" and step.exact_match and not is_blank(step.expected):
                here("warning", "Exact_Match is set on a non-Output step; the expected value is compared with an empty result")
            runtime.record(step, "PASSED", "", "")
        if uncompared:
            findings.append(Finding("info", case.id, None,
                                    f"{uncompared} Output step(s) have an Expected_Value but neither Exact_Match nor "
                                    "Contains, so nothing is asserted (the value is only captured)"))
    return findings


def summarize(findings: Iterable[Finding]) -> dict[str, int]:
    out = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        out[f.severity] += 1
    return out
