"""Variables the new flow keywords share (CONTRACT.md 1.2-1.4): the run-wide pool, the environment table, secrets, ``{TOKEN}`` text and IF.

* **Pool** (Q21): one per run.  Every value a step saves under a name (``Output_Value`` = ``NAME`` or ``{NAME}``, ``SET_VARIABLE``) lands in it,
  whichever test saved it, so a later test reads it with ``{NAME}``.  Tests that need a name wait for the tests that provide it (``engine/order.py``).
* **Environment table** (``_rr_environments``, Q43/Q44): per environment values such as ``DOMAIN``.  A *required* variable that is empty for the
  chosen environment stops the run before it starts (``missing_required``), in the runner and in the web server.
* **Secrets** (Q42): ``{SECRET:NAME}`` is replaced by the value from ``secrets.env`` (``RR_SECRET_<ENV>_<NAME>``, ``RR_SECRET_<NAME>``, then
  ``RR_VAR_<NAME>``) at the moment the step runs.  The value never goes back into the workbook, and every place a step's values are shown
  masks it (``engine/test_runner.py``).
* ``{TOKEN}`` inside text is looked up in: the loop row (inside ``ITERATION_START``), the test's Params row, the pool, the environment table.
  A name nobody has a value for fails the step with "variable X has no value": its name is never typed into the page.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .sheet import SheetData, WorkbookData, cell_text

INLINE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")                # same as builder.INLINE_RE (the builder imports the engine, not the other way)
SECRET_RE = re.compile(r"\{SECRET:([A-Za-z_][A-Za-z0-9_]*)\}", re.I)
UNMAPPED_RE = re.compile(r"\{\?([A-Za-z_][A-Za-z0-9_]*)\}")
TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

INLINE_COLUMNS = ("VALUE", "FINDBY_VALUE", "EXPECTED_VALUE", "LOCATOR", "PAGE", "BACKUP_LOCATORS")
RR_VARIABLES = "_rr_variables"
RR_ENVIRONMENTS = "_rr_environments"
PRODUCTION_ROW = "#PRODUCTION"
ALWAYS_REQUIRED = {"DOMAIN"}
SAVE_METHODS = {"SET_VARIABLE", "JSON_READ", "ASK_USER", "PROMPT", "ASK", "ALERT_TEXT_OUT", "GET_CURRENT_URL"}   # a bare name in Output_Value is a variable

IF_METHODS = ("IF", "ELSE", "END_IF")
LOOP_METHODS = ("ITERATION_START", "ITERATION_END")
MARKERS = {"ELSE", "END_IF", "ITERATION_END"}                          # structure only: never a step of their own


# -- secrets ---------------------------------------------------------------------------------------------------------------------------------------
def secret_value(name: str, environment: str = "", environ: Mapping[str, str] | None = None) -> str | None:
    """The value of ``{SECRET:NAME}`` for ``environment``: ``RR_SECRET_<ENV>_<NAME>``, else ``RR_SECRET_<NAME>``, else ``RR_VAR_<NAME>``."""
    env = os.environ if environ is None else environ
    key, where = name.upper().strip(), environment.upper().strip()
    for candidate in ([f"RR_SECRET_{where}_{key}"] if where else []) + [f"RR_SECRET_{key}", f"RR_VAR_{key}"]:
        value = env.get(candidate)
        if value:
            return value
    return None


# -- the run's pool --------------------------------------------------------------------------------------------------------------------------------
class VariablePool:
    """Values the tests of one run saved, by UPPER name (last write wins), plus every secret value any of them used (masked everywhere)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_by: dict[str, str] = {}                # NAME -> test that set it last
        self.secret_values: set[str] = set()

    def get(self, name: str) -> str | None:
        return self.values.get(name.upper().strip())

    def set(self, name: str, value: Any, test: str = "") -> None:
        key = name.upper().strip()
        self.values[key] = cell_text(value)
        self.set_by[key] = test

    def __contains__(self, name: str) -> bool:
        return name.upper().strip() in self.values


# -- the environment table --------------------------------------------------------------------------------------------------------------------------
@dataclass
class EnvRow:
    variable: str
    required: bool
    secret: bool
    values: dict[str, str] = field(default_factory=dict)          # UPPER environment -> cell text


@dataclass
class EnvironmentTable:
    source: str = "none"                                           # rr | legacy | none
    names: list[str] = field(default_factory=list)                 # environments as written
    production: list[str] = field(default_factory=list)
    rows: list[EnvRow] = field(default_factory=list)

    def has(self, environment: str) -> bool:
        return environment.upper().strip() in {n.upper() for n in self.names}

    def value(self, variable: str, environment: str) -> str | None:
        key = variable.upper().strip()
        for row in self.rows:
            if row.variable.upper() == key:
                text = row.values.get(environment.upper().strip(), "")
                return text if text != "" else None
        return None

    def missing_required(self, environment: str, environ: Mapping[str, str] | None = None) -> list[str]:
        """Required variables with no value for ``environment`` (a ``{SECRET:X}`` cell whose secret is not set counts as empty)."""
        if self.source != "rr":
            return []
        missing = []
        for row in self.rows:
            if not (row.required or row.variable.upper() in ALWAYS_REQUIRED):
                continue
            text = row.values.get(environment.upper().strip(), "").strip()
            unresolved = [n for n in SECRET_RE.findall(text) if secret_value(n, environment, environ) is None]
            if not text or unresolved:
                missing.append(row.variable)
        return missing

    def is_production(self, environment: str) -> bool:
        return environment.upper().strip() in {n.upper() for n in self.production}


def _text(sheet: SheetData, row: int, col: int | None) -> str:
    if not col:
        return ""
    cell = sheet.cells.get((row, col))
    if cell is None:
        return ""
    return (cell.formula or cell_text(cell.value)).strip()


def _true(text: str) -> bool:
    return text.upper().strip() in ("1", "Y", "YES", "TRUE")


def read_environment_table(data: WorkbookData) -> EnvironmentTable:
    """``_rr_environments`` (``Variable | Required | Secret | <env>...``); without it the legacy ``Environments`` sheet (no required rows)."""
    sheet = data.sheet(RR_ENVIRONMENTS)
    if sheet is not None and "VARIABLE" in sheet.headers:
        fixed = {"VARIABLE", "REQUIRED", "SECRET"}
        envs = [(col, name) for col, name in sorted(sheet.header_names.items()) if name.upper() not in fixed]
        table = EnvironmentTable(source="rr", names=[n for _, n in envs])
        marked = False
        for r in range(2, sheet.max_row + 1):
            var = _text(sheet, r, sheet.headers["VARIABLE"])
            if not var:
                continue
            if var.upper() == PRODUCTION_ROW:
                marked = True
                table.production = [n for c, n in envs if _true(_text(sheet, r, c))]
                continue
            table.rows.append(EnvRow(var, _true(_text(sheet, r, sheet.headers.get("REQUIRED"))), _true(_text(sheet, r, sheet.headers.get("SECRET"))),
                                     {n.upper(): _text(sheet, r, c) for c, n in envs}))
        if not marked:
            table.production = [n for n in table.names if n.upper() in ("PROD", "PRODUCTION")]
        return table
    legacy = data.sheet("Environments")
    if legacy is not None and {"ENVIRONMENT", "PARAMETER", "VALUE"} <= set(legacy.headers):
        table = EnvironmentTable(source="legacy")
        by: dict[str, EnvRow] = {}
        for r in range(2, legacy.max_row + 1):
            env, param = _text(legacy, r, legacy.headers["ENVIRONMENT"]), _text(legacy, r, legacy.headers["PARAMETER"])
            if not env or not param:
                continue
            if env not in table.names:
                table.names.append(env)
            cell = legacy.cells.get((r, legacy.headers["VALUE"]))
            value = "" if cell is None or cell.formula else cell_text(cell.value).strip()
            by.setdefault(param.upper(), EnvRow(param, False, False)).values[env.upper()] = value
        table.rows = list(by.values())
        table.production = [n for n in table.names if n.upper() in ("PROD", "PRODUCTION")]
        return table
    return EnvironmentTable()


def declared_variables(data: WorkbookData) -> dict[str, dict[str, bool]]:
    """``_rr_variables``: UPPER token -> {secret, env}."""
    sheet = data.sheet(RR_VARIABLES)
    out: dict[str, dict[str, bool]] = {}
    if sheet is None or "TOKEN" not in sheet.headers:
        return out
    for r in range(2, sheet.max_row + 1):
        token = _text(sheet, r, sheet.headers["TOKEN"])
        if token:
            out[token.upper()] = {"secret": _true(_text(sheet, r, sheet.headers.get("SECRET"))),
                                  "env": _true(_text(sheet, r, sheet.headers.get("ENVSPECIFIC")))}
    return out


def env_missing_message(environment: str, missing: list[str]) -> str:
    names = ", ".join(missing)
    return (f"The run cannot start: {'this variable has' if len(missing) == 1 else 'these variables have'} no value for the environment "
            f"{environment or '(none chosen)'}: {names}. Fill {'it' if len(missing) == 1 else 'them'} in the workbook's environment table "
            "(Build tab, Environments; a secret goes in secrets.env), or pick another environment.")


# -- {TOKEN} text --------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Substituted:
    text: str
    missing: list[str] = field(default_factory=list)              # names nobody had a value for (the step fails)
    blank_params: list[str] = field(default_factory=list)         # names that are a Params column of the test, empty (a person may be asked)
    secrets: list[str] = field(default_factory=list)              # secret *values* put into the text (masked wherever the step is shown)
    unmapped: list[str] = field(default_factory=list)             # {?NAME}: a template placeholder nobody mapped
    used: list[str] = field(default_factory=list)                 # every {NAME} that was replaced


Lookup = Callable[[str], "tuple[str | None, bool]"]              # NAME -> (value or None, is it a Params column of the test)


def substitute(text: str, lookup: Lookup, secret: Callable[[str], "str | None"], *, keep: set[str] | None = None,
               soft: set[str] | None = None) -> Substituted:
    """Replace ``{SECRET:NAME}`` and ``{NAME}`` in ``text``.  ``keep``: names that stay as written (``{TAB}`` in a SendKeys value).  ``soft``: names
    that stay as written when nothing gives them a value, instead of failing the step (key names in older sheets' other steps)."""
    out = Substituted(text)
    out.unmapped = UNMAPPED_RE.findall(text)

    def put_secret(m: re.Match) -> str:
        value = secret(m.group(1))
        if value is None:
            out.missing.append(f"SECRET:{m.group(1).upper()}")
            return m.group(0)
        out.secrets.append(value)
        return value

    def put(m: re.Match) -> str:
        name = m.group(1)
        if keep and name.upper() in keep:
            return m.group(0)
        value, is_param = lookup(name)
        if value is None and soft and name.upper() in soft and not is_param:
            return m.group(0)
        if value is None:
            (out.blank_params if is_param else out.missing).append(name)
            return m.group(0)
        out.used.append(name.upper())
        return value

    text = SECRET_RE.sub(put_secret, text)
    out.text = INLINE_RE.sub(put, text)
    return out


# -- IF --------------------------------------------------------------------------------------------------------------------------------------------
_COND_RE = re.compile(r"^\s*(\{[A-Za-z_][A-Za-z0-9_]*\})\s*(?:(is\s+filled|is\s+empty)|(!=|>=|<=|=|>|<|contains)\s*(.*?))\s*$", re.I)


@dataclass
class Condition:
    left: str
    op: str             # filled | empty | = | != | contains | > | >= | < | <=
    right: str = ""


def parse_condition(text: str) -> Condition:
    """The IF grammar of CONTRACT.md 1.3.  Prefers ``builder.parse_condition`` (the one the UI and lint use) so both always agree."""
    try:
        from .builder import parse_condition as shared
    except Exception:                                              # (the builder is optional for the engine)
        shared = None
    if shared is not None:
        c = shared(text)
        return Condition(c.left, c.op, c.right)
    m = _COND_RE.match(str(text or ""))
    if not m:
        raise ValueError(f"not a condition: {text!r} (write e.g. {{PROMO_CODE}} is filled, or {{PLAN}} = Max)")
    left = m.group(1)[1:-1]
    if m.group(2):
        return Condition(left, "filled" if "filled" in m.group(2).lower() else "empty")
    return Condition(left, m.group(3).lower(), m.group(4).strip())


def _number(text: str) -> float:
    return float(text.replace(",", "").strip())


def evaluate_condition(cond: Condition, value_of: Callable[[str], "str | None"]) -> bool:
    """True / False, on variables only.  ``value_of(NAME)`` gives the variable's value (``None``: it has none).  Raises ``ValueError`` when a
    comparison cannot be made (a name with no value on either side of ``=``, a number that is not one)."""
    left = value_of(cond.left)
    if cond.op == "filled":
        return left is not None and left.strip() != ""
    if cond.op == "empty":
        return left is None or left.strip() == ""
    right = cond.right
    m = INLINE_RE.fullmatch(right)
    if m:
        right = value_of(m.group(1))
        if right is None:
            raise ValueError(f"variable {m.group(1)} has no value")
    left_text = "" if left is None else left
    if cond.op in (">", ">=", "<", "<="):
        try:
            a, b = _number(left_text), _number(right)
        except ValueError:
            raise ValueError(f"{cond.op} compares numbers: {cond.left} is {'empty' if not left_text.strip() else 'not a number'}") from None
        return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[cond.op]
    a, b = left_text.strip().lower(), right.strip().lower()
    if cond.op == "=":
        return a == b
    if cond.op == "!=":
        return a != b
    return b in a                                                  # contains


# -- structure of IF / loops -----------------------------------------------------------------------------------------------------------------------
@dataclass
class FlowMap:
    """Where each IF / ELSE / loop of a sheet ends (by row).  Built from the Method column as written, whatever blnExecute says."""
    else_of: dict[int, int] = field(default_factory=dict)          # IF row -> its ELSE row
    end_of: dict[int, int] = field(default_factory=dict)           # IF / ELSE / ITERATION_START row -> its END_IF / ITERATION_END row
    start_of: dict[int, int] = field(default_factory=dict)         # ITERATION_END row -> its ITERATION_START row
    errors: list[str] = field(default_factory=list)


def flow_map(methods: Mapping[int, str]) -> FlowMap:
    """``methods``: row -> Method (UPPER).  Unbalanced structure is reported in ``errors`` (the test cannot run)."""
    fm = FlowMap()
    stack: list[tuple[str, int]] = []
    for row in sorted(methods):
        method = methods[row]
        if method in ("IF", "ITERATION_START"):
            stack.append((method, row))
        elif method == "ELSE":
            if not stack or stack[-1][0] != "IF":
                fm.errors.append(f"ELSE at row {row} has no IF above it")
                continue
            if stack[-1][1] in fm.else_of:
                fm.errors.append(f"IF at row {stack[-1][1]} has two ELSE rows ({fm.else_of[stack[-1][1]]} and {row})")
                continue
            fm.else_of[stack[-1][1]] = row
        elif method == "END_IF":
            if not stack or stack[-1][0] != "IF":
                fm.errors.append(f"END_IF at row {row} has no IF above it")
                continue
            _, start = stack.pop()
            fm.end_of[start] = row
            if start in fm.else_of:
                fm.end_of[fm.else_of[start]] = row
        elif method == "ITERATION_END":
            if not stack or stack[-1][0] != "ITERATION_START":
                fm.errors.append(f"ITERATION_END at row {row} has no ITERATION_START above it")
                continue
            _, start = stack.pop()
            fm.end_of[start] = row
            fm.start_of[row] = start
    for method, row in stack:
        fm.errors.append(f"{method} at row {row} has no {'END_IF' if method == 'IF' else 'ITERATION_END'}")
    return fm
