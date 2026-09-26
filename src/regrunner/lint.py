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


# ---------------------------------------------------------------------------------------------
# Problems engine for the Workbook Builder (Q31): runs live on the builder's model (workbook/builder.py), never blocks saving
# ---------------------------------------------------------------------------------------------
def builder_problems(model: dict) -> list[dict]:
    """Problems of a builder model (CONTRACT.md 2.7).  Works on the JSON only, so it is fast enough to run after every edit and needs
    no formula evaluation: a Params cell holding a formula counts as filled."""
    from .workbook.builder import ELEMENT_METHODS, KNOWN_METHODS, SIDE_EFFECT_WORDS, UNMAPPED_RE, parse_condition

    out: list[dict] = []
    seen: set[str] = set()

    def add(severity: str, kind: str, message: str, test: str = "", step: dict | None = None, variable: str = "") -> None:
        row = step["row"] if step else None
        pid = f"{kind}:{test}:{row or ''}:{variable}"
        if pid in seen:
            return
        seen.add(pid)
        out.append({"id": pid, "severity": severity, "kind": kind, "message": message, "test": test, "row": row,
                    "n": step["n"] if step else None, "variable": variable})

    env = model.get("environment", "")
    envs = model.get("environments") or {"names": [], "production": [], "rows": [], "source": "none"}
    production = {n.upper() for n in envs.get("production", [])}
    on_prod = env in production
    env_rows = {r["variable"].upper(): r for r in envs.get("rows", [])}
    variables = {v["key"]: v for v in model.get("variables", [])}
    tests = {t["id"].upper(): t for t in model.get("tests", [])}
    fingerprints = {f["name"].upper() for f in model.get("fingerprints", [])}
    env_name_by_upper = {n.upper(): n for n in envs.get("names", [])}

    # -- environment table (Q43/44): required values, per environment ---------------------------------------------
    if envs.get("source") == "rr":
        for r in envs.get("rows", []):
            if not r.get("required"):
                continue
            for name in envs.get("names", []):
                if not str(r["values"].get(name, "")).strip():
                    chosen = name.upper() == env
                    add("error" if chosen else "warning", "missing_environment_value",
                        f"{r['variable']} has no value for {name}: a run in {name} refuses to start until it has one"
                        + (" (this is the environment the workbook is set to)" if chosen else ""), variable=r["variable"].upper())

    for t in model.get("tests", []):
        tid = t["id"]
        needs = t.get("_needs", {})
        stack: list[tuple[str, dict]] = []
        for s in t.get("steps", []):
            m = s["method"]
            if s["enabled"] is False and not s["condition"]:
                continue                                           # switched off (a flag that is N in this data row may be Y in another)
            # unset variables (Q21)
            for u in s["uses"]:
                k = u["token"]
                need = needs.get(k)
                if need is None or need["row"] != s["row"]:
                    continue
                v = variables.get(k, {})
                providers = [p for p in v.get("providedBy", []) if p.upper() != tid.upper()]
                enabled = [p for p in providers if tests.get(p.upper(), {}).get("enabled")]
                label = v.get("label") or k
                where = f" (empty in data row{'s' if len(need['rows']) > 1 else ''} {', '.join(map(str, need['rows']))})" if need["rows"] else ""
                if enabled:
                    continue                                       # another test provides it: the run orders them (Q21)
                if providers:
                    add("warning", "unset_variable", f"{label} ({k}) is only set by {', '.join(providers)}, which is switched off{where}",
                        tid, s, k)
                elif k in env_rows:
                    pass
                elif need.get("maybe"):
                    add("warning", "unset_variable", f"{label} ({k}) is used here but nothing sets it{where}; a formula in blnExecute "
                                                     "decides whether this step runs, so it may be fine", tid, s, k)
                else:
                    add("error", "unset_variable", f"{label} ({k}) is used here but nothing sets it{where}", tid, s, k)
            # environment variables used inline with no value in the chosen environment
            for u in s["uses"]:
                r = env_rows.get(u["token"])
                if r is None or u["form"] not in ("inline",) or not env or env not in env_name_by_upper:
                    continue
                if not str(r["values"].get(env_name_by_upper[env], "")).strip():
                    add("error", "missing_environment_value", f"{r['variable']} has no value for {env_name_by_upper[env]}", tid, s, r["variable"].upper())
            # unmapped template placeholders (P11 leaves {?NAME})
            for text in (s["value"], s["expected"], s["locator"]["value"], s["page"], s["output"]):
                for name in UNMAPPED_RE.findall(text or ""):
                    add("error", "unmapped_template_variable", f"template variable {name} was never mapped to a variable of this workbook",
                        tid, s, name.upper())
            # checks without an expected value
            if not str(s["expected"]).strip() and (
                    (m in ("OUTPUT", "CHECK_VALUE") and s["match"]) or m in ("CHECK_REGEX", "CHECK_COMPARE", "CHECK_COUNT", "CHECK_SELECTED",
                                                                             "CHECK_DATE_FORMAT")
                    or (m == "WAIT_UNTIL" and s["outputProperty"].upper() == "TEXT")):
                add("warning", "missing_expected", "this check has no expected value, so it compares with an empty text", tid, s)
            # side effects (Q13)
            if s["sideEffects"] and on_prod:
                add("warning", "side_effect_on_prod", f"has side effects: blocked when running in {env}", tid, s)
            elif not s["sideEffects"] and s["kind"] in ("act", "input") and SIDE_EFFECT_WORDS.search(f"{s['name']} {s['target']} {s['autoName']}"):
                add("info", "side_effect_suggested", "looks like it has real consequences (purchase / pay / submit): flag it as a side-effect step?",
                    tid, s)
            # last run (Q32/33): a passive badge
            last = s.get("lastResult") or {}
            if last.get("locatorMiss"):
                add("warning", "last_run_locator_miss", f"the element was not found on the last run ({last.get('runId', '')})", tid, s)
            # structure
            if m and m not in KNOWN_METHODS:
                add("warning", "unknown_method", f"unknown action {m!r}: the runner only checks that the element exists", tid, s)
            if m in ELEMENT_METHODS and not s["locator"]["value"] and not s["locator"]["name"]:
                add("error", "missing_locator", "acts on an element but has no locator", tid, s)
            if m == "CALL_TEST" and s["call"].split("#")[0].upper() not in tests:
                add("error", "unknown_test", f"calls {s['call'] or '(nothing)'}, which is not a test of this workbook", tid, s)
            if m == "CALL_TEST" and s["call"].split("#")[0].upper() == tid.upper():
                add("error", "unknown_test", "a test cannot call itself", tid, s)
            if m == "ASSERT_PAGE" and s["value"].upper() not in fingerprints:
                add("error", "unknown_fingerprint", f"no page fingerprint called {s['value'] or '(empty)'}: define it in the page fingerprints", tid, s)
            if m == "IF":
                try:
                    parse_condition(s["value"])
                except ValueError as err:
                    add("error", "bad_condition", str(err), tid, s)
            # IF / loop balance
            if m == "IF" or m == "ITERATION_START":
                stack.append((m, s))
            elif m in ("ELSE", "END_IF"):
                if not stack or stack[-1][0] != "IF":
                    add("error", "unbalanced_flow", f"{m} without a matching IF", tid, s)
                elif m == "END_IF":
                    stack.pop()
            elif m == "ITERATION_END":
                if not stack or stack[-1][0] != "ITERATION_START":
                    add("error", "unbalanced_flow", "ITERATION_END without a matching ITERATION_START", tid, s)
                else:
                    stack.pop()
        for m, s in stack:
            add("error", "unbalanced_flow", f"{m} is never closed ({'END_IF' if m == 'IF' else 'ITERATION_END'} missing)", tid, s)
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda p: (order[p["severity"]], p["test"], p["row"] or 0))
    return out
