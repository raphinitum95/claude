"""Workbook -> tests, and the row-by-row *resolution* loop.

This module is a faithful re-implementation of the legacy runner's data handling
(``GUI_Test_Main.run`` + ``GUI_Functions.replacetemplatevalues`` / ``writeresults``), minus Excel:

* Each ``DataSheets`` row is a test; each enabled row of its parameter sheet is one iteration.
* Rows are processed in order.  For every row, any cell (except the result columns) whose text
  equals a parameter-sheet header is replaced by that parameter's value *in the sheet state*, so
  later formulas that reference the cell see the substituted value.
* ``blnExecute`` may be ``Y``/``N``, a literal, a formula, or a parameter *flag column name*.
* After a step runs, ``Status``/``Error_Check``/``Output_Value`` are written back to the sheet
  (so formulas such as ``=S49`` or ``=IF($D$13="PASSED",...)`` work) and, when the result cell
  names a parameter column, into the parameter row (append semantics, like the legacy runner).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .api import is_api_sheet
from .sheet import BookState, ErrorText, SheetState, WorkbookData, cell_text

UI_COLUMNS = ("METHOD", "PAGE", "FINDBY", "FINDBY_VALUE")
RESULT_COLUMNS = ("STATUS", "ERROR_CHECK", "OUTPUT_VALUE", "START_TIME", "END_TIME", "DURATION")
BLANK_OK_METHODS = {"GET_GOOGLE_TOKEN", "ASK_USER", "PROMPT", "ASK"}     # steps that deal with an empty Value themselves (they ask a person for the code / the answer)
DATA_COLUMNS = ("VALUE", "FINDBY_VALUE", "EXPECTED_VALUE")       # where a row's data comes from: a parameter named here that is empty is a problem
_TRUE = {"1", "Y", "YES", "TRUE"}


def is_true(value: Any) -> bool:
    return cell_text(value).upper().strip() in _TRUE


def is_blank(value: Any) -> bool:
    return value is None or cell_text(value).upper().strip() in ("", "NONE")


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(cell_text(value)))
    except (TypeError, ValueError):
        return default


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "test"


@dataclass
class TestCase:
    """One runnable unit: an action sheet paired with one enabled parameter row."""

    id: str
    sheet: str
    param_sheet: str | None
    param_row: int
    title: str
    description: str = ""
    scenario: str = ""
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    is_ui: bool = True
    kind: str = "ui"                 # ui | api  (an API test is one data row of a WEBSERVICE_URL sheet: see workbook/api.py)
    iteration: int = 1
    iterations: int = 1
    param_enabled: bool = True       # False: the parameter sheet has no row with blnExecute=Y

    __test__ = False  # not a pytest class

    @property
    def slug(self) -> str:
        return slug(self.id)

    @property
    def runnable(self) -> bool:
        """Something regrunner can execute: a UI keyword sheet row set, or an API data row."""
        return self.is_ui or self.kind == "api"


@dataclass
class PreparedStep:
    """A fully resolved row, ready to execute."""

    row: int
    values: dict[str, Any]                       # UPPER column -> value after substitution/formulas
    raw_output_name: str = ""                    # the Output_Value cell *as authored* (a variable name)
    secret_columns: set[str] = field(default_factory=set)
    blank_params: list[tuple[str, str]] = field(default_factory=list)   # (column, parameter as authored) whose Params cell is empty: the token stays in the cell
    param_reads: list[tuple[str, str]] = field(default_factory=list)    # (column, parameter as authored) for every parameter the row's data comes from

    def text(self, column: str) -> str:
        return cell_text(self.values.get(column))

    @property
    def method(self) -> str:
        return self.text("METHOD").upper().strip()

    @property
    def name(self) -> str:
        return self.text("STEP_NAME").strip()

    @property
    def page(self) -> str:
        return self.text("PAGE").upper().strip()

    @property
    def findby(self) -> str:
        return self.text("FINDBY").upper().strip()

    @property
    def findby_value(self) -> str:
        return self.text("FINDBY_VALUE")

    @property
    def index(self) -> int:
        return to_int(self.values.get("INDEX"))

    @property
    def value(self) -> Any:
        return self.values.get("VALUE")

    @property
    def output_property(self) -> str:
        return self.text("OUTPUT_PROPERTY").upper().strip()

    @property
    def ignore_missing(self) -> bool:
        return is_true(self.values.get("IGNORE_NOT_EXISTING_OBJECT"))

    @property
    def timeout(self) -> int | None:
        raw = self.values.get("TIMEOUT")
        return None if is_blank(raw) else max(to_int(raw, 0), 0) or None

    @property
    def expected(self) -> Any:
        return self.values.get("EXPECTED_VALUE")

    @property
    def exact_match(self) -> bool:
        return is_true(self.values.get("EXACT_MATCH"))

    @property
    def contains(self) -> bool:
        return is_true(self.values.get("CONTAINS"))

    @property
    def locator_column(self) -> str:
        """Optional generic-selector column (``Locator``); empty when the sheet has none."""
        return self.text("LOCATOR").strip()

    @property
    def test_case(self) -> str:
        return self.text("TEST_CASE")


# ---------------------------------------------------------------------------------------------
class Workbook:
    """A loaded workbook plus run-level settings; creates one ``TestRuntime`` per test."""

    def __init__(self, path: str | Path, *, environment: str | None = None, headless: bool = True,
                 seed: int | None = None, now: datetime | None = None,
                 secrets: Mapping[str, str] | None = None):
        self.path = Path(path)
        self.data = WorkbookData.load(self.path)
        self.environment = environment
        self.headless = headless
        self.seed = seed
        self.now = now
        self.secrets = {str(k).upper(): str(v) for k, v in (secrets or {}).items() if v not in (None, "")}
        self.warnings: list[str] = []
        self._discovered: list[TestCase] = []           # what discover() found last (param_writers reads it)

    # -- discovery ---------------------------------------------------------------------------
    def global_settings(self) -> dict[str, Any]:
        """The evaluated ``Global`` sheet with run overrides applied."""
        book = BookState(self.data, now=self.now, seed=self.seed)
        return self._build_global(book)

    def _build_global(self, book: BookState) -> dict[str, Any]:
        if not book.has_sheet("Global"):
            return {}
        sheet = book.sheet("Global")
        overrides = {"ENVIRONMENT": self.environment, "HEADLESSMODE": "Y" if self.headless else "N"}
        for row in range(2, sheet.data.max_row + 1):
            key = cell_text(sheet.get(row, 1)).strip().upper()
            if key in overrides and overrides[key] is not None:
                sheet.set(row, 2, overrides[key])
        sheet.freeze()
        settings: dict[str, Any] = {}
        for row in range(2, sheet.data.max_row + 1):
            name = cell_text(sheet.get(row, 1)).strip()
            if name:
                settings[name] = sheet.read(row, 2)
        return settings

    def discover(self) -> list[TestCase]:
        self.warnings = []                                  # rebuilt on every call: asking twice must not say everything twice
        if "EXPORT SUMMARY" in self.data.sheets:
            self.warnings.append('This workbook was exported from Apple Numbers (it has an "Export Summary" sheet). Numbers replaces formulas with the values they had on the day '
                                 'of the export: dates such as TODAY()+1 stay frozen in the past and calculated cells stop calculating. Edit the .xlsx in Excel (or LibreOffice) '
                                 'instead, or restore the copy from before it was saved in Numbers.')
        ds = self.data.sheet("DataSheets")
        if ds is None:
            raise ValueError("Workbook has no 'DataSheets' sheet listing the tests to run.")
        headers = ds.headers
        col_sheet = headers.get("SHEETSTOEXECUTE", 1)
        col_flag = headers.get("BLNEXECUTE", 2)
        col_param = headers.get("PARAMETERSHEET")
        col_comment = headers.get("COMMENTS")
        col_tags = headers.get("TAGS")
        cases: list[TestCase] = []
        for row in range(2, ds.max_row + 1):
            sheet_name = _raw(ds, row, col_sheet)
            if not sheet_name:
                continue
            action = self.data.sheet(sheet_name)
            if action is None:
                self.warnings.append(f"DataSheets row {row}: sheet {sheet_name!r} does not exist")
                continue
            is_ui = all(c in action.headers for c in UI_COLUMNS)
            param_name = _raw(ds, row, col_param) if col_param else ""
            comment = _raw(ds, row, col_comment) if col_comment else ""
            tags = [t.strip() for t in re.split(r"[;,]", _raw(ds, row, col_tags))] if col_tags else []
            if not is_ui and is_api_sheet(action.headers):
                cases.extend(self._api_cases(sheet_name, comment, tags, is_true(_raw(ds, row, col_flag))))
                continue
            if not is_ui:
                self.warnings.append(f"Sheet {sheet_name!r} is not a UI keyword sheet; skipped")
            enabled = is_true(_raw(ds, row, col_flag))
            iterations = self._enabled_param_rows(param_name)
            no_enabled_row = bool(param_name) and not iterations
            if no_enabled_row:
                self.warnings.append(f"Parameter sheet {param_name!r} has no row with blnExecute=Y; "
                                     f"test {sheet_name!r} cannot run")
            for n, prow in enumerate(iterations or [2], start=1):
                scenario = self._scenario_label(param_name, prow)
                tid = sheet_name if len(iterations) <= 1 else f"{sheet_name}#{n}"
                title = sheet_name if not scenario or len(iterations) <= 1 else f"{sheet_name} · {scenario}"
                cases.append(TestCase(
                    id=tid, sheet=sheet_name, param_sheet=param_name or None, param_row=prow,
                    title=title, description=comment, scenario=scenario, tags=[t for t in tags if t],
                    enabled=enabled and not no_enabled_row, is_ui=is_ui, iteration=n,
                    iterations=max(len(iterations), 1), param_enabled=not no_enabled_row))
        self._discovered = cases
        return cases

    def _api_cases(self, sheet_name: str, comment: str, tags: list[str], enabled: bool) -> list[TestCase]:
        """One test per data row of an API sheet whose ``blnExecute`` is Y."""
        state = BookState(self.data, now=self.now, seed=self.seed).sheet(sheet_name)
        bln = state.data.headers["BLNEXECUTE"]
        rows = [r for r in range(2, state.data.max_row + 1) if is_true(state.read(r, bln))]
        if not rows:
            self.warnings.append(f"API sheet {sheet_name!r} has no row with blnExecute=Y; nothing to run")
        out = []
        for n, r in enumerate(rows, start=1):
            scenario = ""
            for header in ("TC_NAME", "TESTCONDITION"):
                col = state.data.headers.get(header)
                if col and (text := cell_text(state.read(r, col)).strip()):
                    scenario = text
                    break
            out.append(TestCase(id=sheet_name if len(rows) == 1 else f"{sheet_name}#{n}", sheet=sheet_name, param_sheet=None, param_row=r,
                                title=sheet_name if not scenario or len(rows) == 1 else f"{sheet_name} · {scenario}", description=comment,
                                scenario=scenario, tags=[t for t in tags if t], enabled=enabled, is_ui=False, kind="api",
                                iteration=n, iterations=len(rows)))
        return out

    def _enabled_param_rows(self, param_name: str) -> list[int]:
        if not param_name:
            return []
        params = self.data.sheet(param_name)
        if params is None:
            self.warnings.append(f"Parameter sheet {param_name!r} does not exist")
            return []
        col = params.headers.get("BLNEXECUTE")
        if col is None:
            return []
        book = BookState(self.data, now=self.now, seed=self.seed)
        state = book.sheet(param_name)
        return [r for r in range(2, params.max_row + 1) if is_true(state.read(r, col))]

    def _scenario_label(self, param_name: str, row: int) -> str:
        if not param_name:
            return ""
        params = self.data.sheet(param_name)
        if params is None:
            return ""
        for header in ("NOTES", "SCENARIO"):
            col = params.headers.get(header)
            if col:
                value = params.cells.get((row, col))
                if value is not None and value.formula is None and value.value:
                    return str(value.value)
        return ""

    # -- runtime -----------------------------------------------------------------------------
    def api_runtime(self, case: TestCase, shared: dict | None = None, *, seed: int | None = None):
        """Runtime of an API row.  ``shared``: cells the UI tests of this run wrote into their parameter sheets, ``{(sheet, row, col): value}``,
        so that ``=AgentStandAlone_Params!E2`` in an API row sees the policy number the UI test produced."""
        from .api import ApiRuntime
        book = BookState(self.data, now=self.now, seed=self.seed if seed is None else seed)
        globals_ = self._build_global(book)
        for (sheet, row, col), value in (shared or {}).items():
            if book.has_sheet(sheet):
                book.sheet(sheet).set(row, col, value)
        return ApiRuntime(book, case, globals_, self.secrets)

    def runtime(self, case: TestCase, *, seed: int | None = None, shared: dict | None = None) -> "TestRuntime":
        """``shared``: parameter cells other tests of the run wrote (or a person supplied), ``{(sheet, row, col): value}``; this test sees them."""
        if case.kind == "api":
            return self.api_runtime(case, shared, seed=seed)               # type: ignore[return-value]
        book = BookState(self.data, now=self.now, seed=self.seed if seed is None else seed)
        globals_ = self._build_global(book)
        params_state = None
        if case.param_sheet:
            params_state = book.sheet(case.param_sheet)
            for (sheet, row, col), value in (shared or {}).items():
                if sheet == case.param_sheet and row == case.param_row:
                    params_state.set(row, col, value)
            for (sheet, row, col), value in (shared or {}).items():      # a Params cell may be =PurchaseUS!FB3: the cell an API test filled in
                other = self.data.sheet(sheet)
                if other is not None and sheet != case.param_sheet and is_api_sheet(other.headers) and book.has_sheet(sheet):
                    book.sheet(sheet).set(row, col, value)
            params_state.freeze()            # one consistent value per volatile formula for this test
        return TestRuntime(book, case, globals_, params_state, self.secrets, writers=self.param_writers())

    def param_writers(self) -> dict[str, list[str]]:
        """Which sheets have a step that writes a parameter (its Output_Value cell holds the parameter's name): ``{PARAMETER: [sheet, ...]}``.
        Read from the tests found by ``discover()``; empty before that."""
        writers: dict[str, list[str]] = {}
        seen: set[tuple[str, str]] = set()
        for case in self._discovered:
            if not case.is_ui or not case.param_sheet or (case.sheet, case.param_sheet) in seen:
                continue
            seen.add((case.sheet, case.param_sheet))
            params, sheet = self.data.sheet(case.param_sheet), self.data.sheet(case.sheet)
            col = sheet.headers.get("OUTPUT_VALUE") if sheet is not None else None
            if params is None or not col:
                continue
            for row in range(2, sheet.max_row + 1):
                name = _raw(sheet, row, col).upper()
                if name in params.headers and case.sheet not in writers.setdefault(name, []):
                    writers[name].append(case.sheet)
        return writers


def _raw(sheet, row: int, col: int | None) -> str:
    if not col:
        return ""
    cell = sheet.cells.get((row, col))
    if cell is None:
        return ""
    return cell_text(cell.value).strip() if cell.formula is None else ""


class TestRuntime:
    """Per-test row processor. Not shared between tests."""

    __test__ = False  # not a pytest class

    def __init__(self, book: BookState, case: TestCase, globals_: dict[str, Any],
                 params: SheetState | None, secrets: Mapping[str, str], writers: Mapping[str, list[str]] | None = None):
        self.book = book
        self.writers = writers or {}                             # PARAMETER -> sheets that fill it in (for the message about an empty one)
        self.needs: list[dict[str, Any]] = []                    # filled by plan(): parameters this test uses that are empty and nothing in it sets
        self.reads: dict[str, dict[str, Any]] = {}               # filled by plan(): PARAMETER -> {param, rows, blank} for every parameter it uses that no earlier step of it sets
        self.sets: set[str] = set()                              # filled by plan(): parameters its steps set (Output_Value names them)
        self.case = case
        self.globals = globals_
        self.sheet: SheetState = book.sheet(case.sheet)
        self.params_sheet = params
        self.secrets = secrets
        self.columns = self.sheet.data.headers                   # UPPER -> col
        self.column_names = sorted(self.columns.items(), key=lambda kv: kv[1])
        self.params: dict[str, Any] = {}
        if params is not None:
            for header, col in params.data.headers.items():
                self.params[header] = params.read(case.param_row, col)
        self.total_rows = self.sheet.data.max_row
        self.written: dict[tuple[str, int, int], Any] = {}         # parameter cells this test wrote: handed to the API tests of the run
        self.secret_values: set[str] = set()                       # answers a person typed in as secrets: masked wherever a later step shows them
        self.blocked_reason = "" if case.param_enabled else (
            f"Parameter sheet {case.param_sheet!r} has no row with blnExecute=Y")

    # -- global helpers -----------------------------------------------------------------------
    def global_flag(self, name: str, default: bool = False) -> bool:
        for key, value in self.globals.items():
            if key.upper() == name.upper():
                return is_true(value)
        return default

    def global_text(self, name: str, default: str = "") -> str:
        for key, value in self.globals.items():
            if key.upper() == name.upper():
                return cell_text(value)
        return default

    @property
    def environment(self) -> str:
        return self.global_text("Environment", "").strip().upper()

    # -- row processing -------------------------------------------------------------------------
    def prepare_row(self, row: int) -> PreparedStep | None:
        """Substitute tokens for ``row`` and return it if it should execute, else ``None``."""
        blanks, reads = self._replace_template_values(row)
        # STEP_NUMBER is `=COUNTA($B$1:B<n>)` (== row-1). Evaluating it is quadratic and it never
        # influences behaviour, so it is synthesised instead.
        values = {name: (row - 1 if name == "STEP_NUMBER" else self.sheet.read(row, col))
                  for name, col in self.columns.items()}
        if not is_true(values.get("BLNEXECUTE")):
            return None
        raw_output = self._authored_text(row, "OUTPUT_VALUE")
        prepared = PreparedStep(row=row, values=values, raw_output_name=raw_output, blank_params=blanks, param_reads=reads)
        self._assign_secrets(prepared)
        if not prepared.method:
            return None
        return prepared

    def _authored_text(self, row: int, column: str) -> str:
        col = self.columns.get(column)
        return cell_text(self.sheet.read(row, col)).strip() if col else ""

    def _replace_template_values(self, row: int) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Replace each parameter named in the row by its value.  Returns ``(blanks, reads)``: the (column, parameter) pairs whose parameter is empty
        (the legacy runner left the token in the cell then and typed its name into the page; regrunner reports it instead, see ``TestRunner``), and
        every parameter the row's data comes from."""
        blanks: list[tuple[str, str]] = []
        reads: list[tuple[str, str]] = []
        params = self.params
        if not params:
            return blanks, reads
        for name, col in self.column_names:
            if name in RESULT_COLUMNS or name == "STEP_NUMBER":
                continue
            authored = cell_text(self.sheet.read(row, col)).strip()
            cell_upper = authored.upper() or "NONE"
            if cell_upper not in params:
                if name == "BLNEXECUTE" and not is_true(cell_upper):
                    return blanks, reads
                continue
            if name == "BLNEXECUTE" and not is_true(params[cell_upper]):
                return blanks, reads
            if name in DATA_COLUMNS:
                reads.append((name, authored))
            replacement = params[cell_upper]
            if replacement is None:
                if name in DATA_COLUMNS:
                    blanks.append((name, authored))
                continue          # keep the token: blank parameters do not overwrite the sheet
            self.sheet.set(row, col, cell_text(replacement))
        return blanks, reads

    def _assign_secrets(self, step: PreparedStep) -> None:
        if not self.secrets:
            return
        for name, value in list(step.values.items()):
            if name in RESULT_COLUMNS or value in (None, ""):
                continue
            key = cell_text(value).upper().strip()
            if key in self.secrets:
                step.values[name] = self.secrets[key]
                step.secret_columns.add(name)

    def record(self, step: PreparedStep, status: str, error: str, output: Any) -> list[dict[str, str]]:
        """Write the step result back into the sheet and (when named) into the parameter row.  Returns the parameters this step set:
        ``[{name, value, stored, cell}]`` (``value`` what the step wrote, ``stored`` what the cell holds now: writes to one parameter add up)."""
        out_text = "" if output is None else cell_text(output)
        for column, value in (("STATUS", status), ("ERROR_CHECK", error), ("OUTPUT_VALUE", out_text)):
            col = self.columns.get(column)
            if col:
                self.sheet.set(step.row, col, value)
        sets: list[dict[str, str] | None] = []
        if self.params_sheet is None:
            return []
        for column, cell in step.values.items():
            if is_blank(cell):
                continue
            token = cell_text(cell).upper().strip()
            if token not in self.params or column in step.secret_columns:
                continue
            authored = cell_text(cell).strip()
            if column == "ERROR_CHECK":
                if not is_blank(error):
                    sets.append(self._write_param(token, error, authored))
            elif column == "STATUS":
                sets.append(self._write_param(token, status, authored))
            elif column == "OUTPUT_VALUE":
                if not is_blank(out_text) and out_text.upper() != token:
                    sets.append(self._write_param(token, out_text, authored))
        return [x for x in sets if x]

    def param_cell(self, token: str) -> str:
        """Where a parameter lives, for a message: ``AgentPortal_Params!R3``."""
        col = self.params_sheet.data.headers.get(token.upper().strip()) if self.params_sheet is not None else None
        if not col:
            return token
        from openpyxl.utils import get_column_letter
        return f"{self.params_sheet.name}!{get_column_letter(col)}{self.case.param_row}"

    def provide(self, token: str, value: str) -> None:
        """A value a person supplied for an empty parameter: this test uses it from now on, and it is handed on like any value a step wrote."""
        key = token.upper().strip()
        col = self.params_sheet.data.headers.get(key) if self.params_sheet is not None else None
        if col is None:
            return
        self.params[key] = value
        self.params_sheet.set(self.case.param_row, col, value)
        self.written[(self.params_sheet.name, self.case.param_row, col)] = value

    def _write_param(self, token: str, value: str, authored: str = "") -> dict[str, str] | None:
        col = self.params_sheet.data.headers.get(token)
        if col is None:
            return None
        current = self.params.get(token)
        new = str(value) if is_blank(current) else f"{cell_text(current)};{value}"
        self.params[token] = new
        self.params_sheet.set(self.case.param_row, col, new)
        self.written[(self.params_sheet.name, self.case.param_row, col)] = new
        return {"name": authored or token, "value": str(value), "stored": new, "cell": self.param_cell(token)}

    def empty_flag_step(self, row: int) -> tuple[str, str] | None:
        """(method, step name) when ``row`` holds a step but its ``blnExecute`` cell is *empty*: an ``N`` is a decision, an empty cell is easily
        an oversight, and either way the row does not run.  A flag that is a formula is not reported (it may legitimately give "")."""
        bln, method = self.columns.get("BLNEXECUTE"), self.columns.get("METHOD")
        if not bln or not method or self.sheet.is_formula(row, bln):
            return None
        if cell_text(self.sheet.read(row, bln)).strip():
            return None
        what = cell_text(self.sheet.read(row, method)).replace("\xa0", " ").strip()
        if not what:
            return None
        name = self.columns.get("STEP_NAME")
        return what, cell_text(self.sheet.read(row, name)).strip() if name else ""

    # -- planning ------------------------------------------------------------------------------
    def plan(self) -> list[tuple[int, str, str]]:
        """Dry-run the row loop (no browser) and return ``(row, step name, method)`` for each step.

        Statuses are assumed PASSED so status-gated rows are planned; used for progress totals.
        """
        planned = []
        if self.blocked_reason:
            return planned
        setters: set[str] = set()                                # parameters an earlier step of this test fills in
        needs: dict[str, dict[str, Any]] = {}
        reads: dict[str, dict[str, Any]] = {}
        for row in range(2, self.total_rows + 1):
            step = self.prepare_row(row)
            if step is None:
                continue
            planned.append((row, step.name, step.method))
            for _, token in step.param_reads:
                if token.upper() not in setters:
                    col = self.params_sheet.data.headers.get(token.upper()) if self.params_sheet is not None else None
                    read = reads.setdefault(token.upper(), {"param": token, "rows": [], "blank": False, "source": self.param_cell(token),
                                                            "key": (self.params_sheet.name, self.case.param_row, col) if col else None})
                    read["rows"].append(row)
            for _, token in ([] if step.method in BLANK_OK_METHODS else step.blank_params):
                if token.upper() not in setters:
                    need = needs.setdefault(token.upper(), {"param": token, "cell": self.param_cell(token), "rows": [], "steps": [],
                                                            "set_by": [w for w in self.writers.get(token.upper(), []) if w != self.case.sheet]})
                    need["rows"].append(row)
                    need["steps"].append(step.name)
                    if token.upper() in reads:
                        reads[token.upper()]["blank"] = True
            if step.raw_output_name and step.raw_output_name.upper().strip() in self.params:
                setters.add(step.raw_output_name.upper().strip())
            self.record(step, "PASSED", "", "")
        self.needs = list(needs.values())
        self.reads, self.sets = reads, setters
        return planned
