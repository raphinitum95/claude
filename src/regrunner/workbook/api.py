"""API (web service) tests: a data row of an API sheet plus the workbook's ``InputOutput`` sheet.

The same workbook format the legacy web-service runner used, JSON over HTTP:

* one **data row** (``blnExecute`` = Y) is one test.  The sheet has ``ENVIRONMENT_PARAMETER`` (the URL is that row of the ``Environments`` sheet for
  the run's environment) and / or ``WEBSERVICE_URL`` (the URL in the row itself, wins), ``WEBSERVICE_METHOD`` / ``JSON_FORMAT`` and the ``DT_*`` values;
* ``InputOutput`` (function | parameter | value) says what to do with it:
  ``addHeader`` header name -> column holding its value, ``update_json`` JSON path -> column and ``Replace`` text in the request template -> column
  (the request body), ``output_json`` JSON path and ``Output`` element path (``a/b[2]/c``) in the response -> column, ``compare`` /
  ``compare_ignore_case`` / ``contains`` / ``contains_ignore_case`` expected column -> actual column, ``DisableCheckpoint`` test name -> the actual
  columns not to check.  A row with no function name is ignored (the legacy runner did), and so is anything else (``compareX`` is how authors
  switch a check off).

Nothing here touches the network; ``engine/api_runner.py`` sends the request.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .sheet import BookState, ErrorText, cell_text

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
CHECK_KINDS = ("compare", "compare_ignore_case", "contains", "contains_ignore_case")
_FUNCTIONS = {"addheader": "add_header", "add_header": "add_header", "update_json": "update_json", "output_json": "output_json",
              "compare": "compare", "compare_ignore_case": "compare_ignore_case", "contains": "contains",
              "contains_ignore_case": "contains_ignore_case", "disablecheckpoint": "disable", "disable_checkpoint": "disable",
              "replace": "replace", "output": "output"}


def is_api_sheet(headers) -> bool:
    """Is a sheet with these (UPPER) headers an API sheet?  The legacy web-service runner required ``ENVIRONMENT_PARAMETER`` (the URL comes from the
    ``Environments`` sheet); ``WEBSERVICE_URL`` is the newer way to give the URL in the row itself.  Either one, next to ``blnExecute``, makes it one."""
    return "BLNEXECUTE" in headers and ("WEBSERVICE_URL" in headers or "ENVIRONMENT_PARAMETER" in headers)


@dataclass
class Checkpoint:
    kind: str                     # one of CHECK_KINDS
    expected_column: str
    actual_column: str

    @property
    def name(self) -> str:
        return self.actual_column


@dataclass
class InputOutput:
    add_header: dict[str, str] = field(default_factory=dict)          # header name -> column
    update_json: dict[str, str] = field(default_factory=dict)         # JSON path -> column
    output_json: dict[str, str] = field(default_factory=dict)         # JSON path -> column
    replace: dict[str, str] = field(default_factory=dict)             # text in the request template -> column holding what goes there
    output: dict[str, str] = field(default_factory=dict)              # element path (a/b[2]/c) in the response -> column
    checks: dict[str, dict[str, str]] = field(default_factory=lambda: {k: {} for k in CHECK_KINDS})   # kind -> {expected column: actual column}
    disabled: dict[str, str] = field(default_factory=dict)            # test name -> "col;col"
    ignored_rows: list[tuple[int, str]] = field(default_factory=list)  # (row, why) for rows the legacy runner skipped


def read_input_output(book: BookState) -> InputOutput:
    io = InputOutput()
    if not book.has_sheet("InputOutput"):
        return io
    sheet = book.sheet("InputOutput")
    for row in range(2, sheet.data.max_row + 1):
        function, param, value = (cell_text(sheet.read(row, c)).strip() for c in (1, 2, 3))
        if not function:
            if value:                                                 # (a heading such as PURCHASE REQUEST has no value: nothing to warn about)
                io.ignored_rows.append((row, f"no function name (parameter {param!r}); the legacy runner skipped it"))
            continue
        if not param:
            continue                                                  # a section heading such as INPUT_Contract
        kind = _FUNCTIONS.get(function.lower())
        if kind is None:
            continue
        if kind in CHECK_KINDS:
            io.checks[kind][param] = value
        elif kind == "disable":
            io.disabled[param] = value
        else:
            getattr(io, kind)[param] = value
    return io


def skipped_columns(io: InputOutput, values: Mapping[str, Any], test_name_column: str) -> set[str]:
    """Actual columns whose checks are disabled for this row (``DisableCheckpoint``: the row's test name -> ``col;col``)."""
    name = cell_text(values.get(test_name_column.upper())).strip().upper() if test_name_column else ""
    out: set[str] = set()
    for test, columns in io.disabled.items():
        if name and test.strip().upper() == name:
            out.update(c.strip().upper() for c in columns.split(";") if c.strip())
    return out


# -- JSON paths ------------------------------------------------------------------------------------------------------------------
_INDEX = re.compile(r"^\[(\d+)\]$")


def _tokens(path: str) -> list[str | int]:
    out: list[str | int] = []
    for part in re.split(r"[./]", path.strip()):
        if part == "":
            continue
        m = _INDEX.match(part)
        out.append(int(m.group(1)) if m else part)
    return out


def json_get(data: Any, path: str) -> Any:
    """The value at ``a.b.[0].c`` (``/`` works as the separator too); ``None`` when any step is missing."""
    node = data
    for token in _tokens(path):
        if isinstance(token, int):
            if not isinstance(node, list) or token >= len(node):
                return None
            node = node[token]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return None
    return node


_MISSING = object()


def json_find(data: Any, path: str) -> Any:
    """Like ``json_get`` but tells a missing step (``_MISSING``) from a JSON ``null`` (``None``)."""
    node = data
    for token in _tokens(path):
        if isinstance(token, int):
            if not isinstance(node, list) or token >= len(node):
                return _MISSING
            node = node[token]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return _MISSING
    return node


def output_json_text(data: Any, path: str) -> str:
    """What the legacy runner stored for an ``output_json`` path (``get_json_value`` + ``output_json_data``): the value as text - and the text
    ``None`` (Python's ``str(None)``) for a JSON ``null`` and for a dotted / slashed path that does not resolve (``travelers.[0].customElements.[2].value``
    when the list is shorter): sheets rely on it (``MedScen01_EXP = None`` for a policy without medical conditions).  A plain key that is absent
    stores nothing, and neither does an empty string."""
    value = json_find(data, path)
    if value is _MISSING:
        return "None" if ("." in path or "/" in path) else ""
    if value is None:
        return "None"
    return output_text(value)


def json_set(data: Any, path: str, value: Any) -> bool:
    """Set the value at ``path`` (an existing node keeps its JSON type: number stays a number).  False when the path does not exist."""
    tokens = _tokens(path)
    if not tokens:
        return False
    node = data
    for token in tokens[:-1]:
        if isinstance(token, int):
            if not isinstance(node, list) or token >= len(node):
                return False
            node = node[token]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return False
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(node, list) or last >= len(node):
            return False
        node[last] = _like(node[last], value)
    elif isinstance(node, dict):
        node[last] = _like(node.get(last), value)
    else:
        return False
    return True


def _like(existing: Any, value: Any) -> Any:
    text = cell_text(value)
    if isinstance(existing, bool):
        return text.strip().lower() in ("true", "y", "yes", "1")
    if isinstance(existing, int):
        try:
            return int(float(text))
        except ValueError:
            return text
    if isinstance(existing, float):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def output_text(value: Any) -> str:
    """How a JSON value lands in a cell (Python ``str()``, like the legacy runner; a ``null`` cell value is empty - ``output_json_text`` gives ``None`` for an output path)."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# -- comparing -----------------------------------------------------------------------------------------------------------------------
def check(kind: str, expected: Any, actual: str) -> bool:
    """The legacy verdict: text equality after trimming (numbers compare to four decimals), or containment; ``_ignore_case`` upper-cases both."""
    exp_text = cell_text(expected).strip()
    act_text = (actual or "").strip()
    if kind.startswith("compare") and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        exp_text = "{:20.4f}".format(float(expected))
        try:
            act_text = "{:20.4f}".format(float(act_text))
        except ValueError:
            pass
    if kind.endswith("ignore_case"):
        exp_text, act_text = exp_text.upper(), act_text.upper()
    return exp_text == act_text if kind.startswith("compare") else exp_text in act_text


# a cell of the same row named in a formula (Q3), not one of another sheet (Global!$E$1) or a range end ($E$1:$G$4)
_LOCAL_REF = re.compile(r"(?<![A-Za-z0-9_!:$'\"])\$?([A-Z]{1,3})\$?(\d+)\b(?!\s*[:(])")
_SHEET_REF = re.compile(r"(?<![A-Za-z0-9_])'?([A-Za-z0-9_ ]+?)'?!\$?([A-Z]{1,3})\$?(\d+)\b(?!\s*:)")       # Params_1!T2 (not the start of a range: Global!$E$1:$G$4)
_CELL_REF = re.compile(r"^=\s*'?([^'!]+)'?!\$?([A-Z]{1,3})\$?(\d+)\s*$")


def referenced_cells(formula: str, book: BookState) -> list[tuple[str, int, int]]:
    """The cells of other sheets a formula names, ``(sheet, row, column)``: ``=PurchaseUS!FB3`` -> ``[("PurchaseUS", 3, 158)]``."""
    from openpyxl.utils import column_index_from_string
    out: list[tuple[str, int, int]] = []
    for name, letter, row in _SHEET_REF.findall(formula or ""):
        data = book.data.sheet(name)
        if data is not None:
            cell = (data.name, int(row), column_index_from_string(letter))
            if cell not in out:
                out.append(cell)
    return out


# -- the runtime of one API row ------------------------------------------------------------------------------------------------------
@dataclass
class ApiRequest:
    method: str
    url: str
    headers: dict[str, str]
    secret_headers: set[str]
    json_format: bool
    template_location: str
    template_file: str
    url_problem: str = ""                   # why there is no URL (the Environments sheet has no such parameter for this environment)


class ApiRuntime:
    """One data row of an API sheet, evaluated the way the UI rows are (formulas, tokens); results are written back into the sheet state."""

    def __init__(self, book: BookState, case, globals_: dict[str, Any], secrets: Mapping[str, str]):
        self.book, self.case, self.globals, self.secrets = book, case, globals_, secrets
        self.sheet = book.sheet(case.sheet)
        self.row = case.param_row
        self.columns = self.sheet.data.headers
        self.values: dict[str, Any] = {name: self.sheet.read(self.row, col) for name, col in self.columns.items()}
        self.io = read_input_output(book)
        self.outputs: dict[str, str] = {}
        self.written: dict[tuple[str, int, int], str] = {}          # cells of the row the response filled in: handed to the tests that read them
        self.blocked_reason = ""

    # -- global helpers (same as TestRuntime) ---------------------------------------------------------------------------------
    def global_text(self, name: str, default: str = "") -> str:
        for key, value in self.globals.items():
            if key.upper() == name.upper():
                return cell_text(value)
        return default

    @property
    def environment(self) -> str:
        return self.global_text("Environment", "").strip().upper()

    def text(self, column: str) -> str:
        return cell_text(self.values.get(column.upper())).strip()

    def error_in(self, column: str) -> str:
        """Why a column is unusable (an Excel error such as an unsupported function), else ""."""
        value = self.values.get(column.upper())
        if isinstance(value, ErrorText):
            return f"the {column} cell evaluates to {value.code}" + (f" ({value.detail})" if value.detail else "")
        return ""

    # -- the request -----------------------------------------------------------------------------------------------------------------
    def request(self) -> ApiRequest:
        headers: dict[str, str] = {}
        secret_headers: set[str] = set()
        for header, column in self.io.add_header.items():
            key = column.upper()
            override = self.secrets.get(key, "")                       # RR_VAR_<COLUMN> in secrets.env wins over the workbook cell
            raw = override or self.values.get(key)
            text = cell_text(raw).strip()
            if "[BLANK]" in text.upper():
                headers.pop(header, None)
            elif text.lower() == "none":
                headers[header] = ""
            elif key in self.values or override:
                headers[header] = text
                secret_headers.add(header)                              # values are masked in every file and report
        json_format = cell_text(self.values.get("JSON_FORMAT")).strip().upper() in ("Y", "YES", "TRUE", "1")
        url, soap_action, content_type, url_problem = self.endpoint()
        if json_format:
            headers.setdefault("Content-Type", "application/json")
        elif content_type:
            headers.setdefault("Content-Type", content_type)
        if soap_action:
            headers.setdefault("SOAPAction", soap_action)
        location = self.text("XML_LOCATION") or self.text("TEMPLATES_PATH")
        template_file = self.text("XML_REQUESTFILE") or self.text("REQUESTFILE") or self.text("TEMPLATE_FILE")
        return ApiRequest(method=(self.text("WEBSERVICE_METHOD") or "POST").upper(), url=url, headers=headers,
                          secret_headers=secret_headers, json_format=json_format, template_location=location,
                          template_file=template_file, url_problem=url_problem)

    def environment_table(self) -> dict[str, str]:
        """The ``Environments`` sheet for the run's environment: ``{Parameter: Value}`` (Environment | Parameter | Value; the legacy ``getParamDict``)."""
        table: dict[str, str] = {}
        if not self.book.has_sheet("Environments"):
            return table
        sheet = self.book.sheet("Environments")
        wanted = self.environment
        for row in range(2, sheet.data.max_row + 1):
            if cell_text(sheet.read(row, 1)).strip().upper() == wanted:
                key = cell_text(sheet.read(row, 2)).strip()
                if key:
                    table[key] = cell_text(sheet.read(row, 3)).strip()
        return table

    def endpoint(self) -> tuple[str, str, str, str]:
        """``(url, SOAPAction, content type, why there is no url)``.  The URL is the ``WEBSERVICE_URL`` cell when it has one, else the
        ``Environments`` row named by ``ENVIRONMENT_PARAMETER`` (the legacy ``setHeaderAndURL``: the first parameter that contains that name);
        ``<prefix>_SoapAction`` and ``<prefix>_ContentHeader`` of the same prefix (the part before the first ``_``) come with it."""
        own = self.text("WEBSERVICE_URL")
        parameter = self.text("ENVIRONMENT_PARAMETER")
        if not parameter:
            return own, "", "", ""
        table = self.environment_table()
        url = soap = content = ""
        found = False
        prefix = parameter.split("_")[0]
        for key, value in table.items():
            if parameter.upper() in key.upper():
                url, found = value, True
                break
        for key, value in table.items():
            if key.upper() == f"{prefix}_SOAPACTION".upper():
                soap = value
            elif key.upper() == f"{prefix}_CONTENTHEADER".upper():
                content = value
        if own:
            return own, soap, content, ""
        if not found:
            what = f"the Environments sheet has no {parameter!r} for environment {self.environment or '(none set in Global)'}"
            return "", soap, content, what
        return url, soap, content, ""

    def lower_tags(self) -> bool:
        """The legacy runner parsed a response as HTML when Global ``isHTMLParsing`` (or ``isHTMLParsing_Response``) is Y: element names come out lower case."""
        return any(cell_text(v).strip().upper() in ("Y", "YES", "TRUE", "1") for k, v in self.globals.items()
                   if k.strip().upper() in ("ISHTMLPARSING", "ISHTMLPARSING_RESPONSE"))

    def strip_response(self) -> bool:
        return cell_text(self.values.get("STRIP_RESPONSE")).strip().upper() in ("Y", "YES", "TRUE", "1")

    def body_updates(self) -> list[tuple[str, Any]]:
        """``update_json``: (JSON path, value from the row's column) for every column that exists."""
        return [(path, self.values.get(column.upper())) for path, column in self.io.update_json.items() if column.upper() in self.values]

    def request_inputs(self) -> list[dict[str, Any]]:
        """The cells the request is built from, with where each gets its value: ``[{column, param, source, key, blank, own, in_url}]``.  ``key`` is the cell
        ``(sheet, row, column)``; ``own`` says it lives in this API sheet (a constant typed there), else it is a cell of another sheet - a value some
        other test of the run produces (``=AgentPortal_Params!R3``).  Read from the URL formula, the ``addHeader`` columns and the ``update_json`` columns."""
        from openpyxl.utils import column_index_from_string
        data = self.sheet.data
        found: dict[tuple, dict[str, Any]] = {}

        def add(column: str, source: str, key: tuple, blank: bool, own: bool, in_url: bool, param: str = "") -> None:
            item = found.setdefault(key, {"column": column, "source": source, "key": key, "blank": blank, "own": own, "in_url": False,
                                          "param": param or column})
            item["in_url"] = item["in_url"] or in_url

        def from_column(col: int, in_url: bool) -> None:
            """A column of this row: a plain value, or a direct reference to a cell of another sheet (=AgentPortal_Params!R3)."""
            header = data.header_names.get(col)
            if not header:
                return
            blank = not cell_text(self.values.get(header.upper())).strip()
            cell = data.cells.get((self.row, col))
            ref = _CELL_REF.match(cell.formula) if cell is not None and cell.formula else None
            if ref and self.book.has_sheet(ref.group(1)):
                other = self.book.sheet(ref.group(1)).data
                col2, row2 = column_index_from_string(ref.group(2)), int(ref.group(3))
                name = other.header_names.get(col2)
                add(header, f"{other.name}!{ref.group(2)}{row2}" + (f" ({name})" if name else ""), (other.name, row2, col2), blank, False, in_url, name or "")
            else:
                add(header, header, (self.case.sheet, self.row, col), blank, True, in_url)

        url_col = self.columns.get("WEBSERVICE_URL")
        raw = data.cells.get((self.row, url_col)) if url_col else None
        if raw is not None and raw.formula:
            for name, letter, row in _SHEET_REF.findall(raw.formula):                # =...&Params_1!T2: a cell of another sheet, right in the URL
                if self.book.has_sheet(name):
                    other, col2, row2 = self.book.sheet(name), column_index_from_string(letter), int(row)
                    header = other.data.header_names.get(col2)
                    add(header or f"{letter}{row2}", f"{other.data.name}!{letter}{row2}" + (f" ({header})" if header else ""), (other.data.name, row2, col2),
                        not cell_text(other.read(row2, col2)).strip(), False, True, header or "")
            for letter, row in _LOCAL_REF.findall(raw.formula):                      # ...&Q3: a cell of this row
                if int(row) == self.row:
                    from_column(column_index_from_string(letter), True)
        for column in [*self.io.add_header.values(), *self.io.update_json.values(), *self.io.replace.values()]:
            col = self.columns.get(column.upper())
            if col:
                from_column(col, False)
        return list(found.values())

    def empty_inputs(self) -> list[dict[str, Any]]:
        """The inputs the request URL is built from that are empty (a policy number nobody has produced)."""
        return [i for i in self.request_inputs() if i["blank"] and i["in_url"]]

    def output_cells(self) -> set[tuple[str, int, int]]:
        """The cells of this row the response can fill in (``Output`` / ``output_json`` columns the sheet has): what other sheets may read."""
        return {(self.case.sheet, self.row, self.columns[c.upper()]) for c in [*self.io.output.values(), *self.io.output_json.values()]
                if c.upper() in self.columns}

    def cell_reads(self) -> list[dict[str, Any]]:
        """The cells of *other sheets* the request reads: what other tests of the run have to produce first."""
        return [i for i in self.request_inputs() if not i["own"]]

    # -- what gets checked -----------------------------------------------------------------------------------------------------------
    def checkpoints(self) -> list[Checkpoint]:
        skip = skipped_columns(self.io, self.values, self.global_text("TC_Name_Column", "TC_Name"))
        out = []
        for kind in CHECK_KINDS:
            for expected, actual in self.io.checks[kind].items():
                if expected.upper() not in self.values or actual.upper() in skip:
                    continue                                            # no expected value column in this sheet, or switched off for this test
                out.append(Checkpoint(kind, expected, actual))
        return out

    def plan(self) -> list[tuple[int, str, str]]:
        """Dry run: the request, then each check (used for progress totals and the previews)."""
        req = self.request()
        steps = [(self.row, f"{req.method} {req.url}".strip(), req.method)]
        steps += [(self.row, f"Check {c.actual_column}", c.kind.upper()) for c in self.checkpoints()]
        return steps

    def record_output(self, column: str, value: str) -> None:
        """A value taken from the response: kept, and written into the row when the sheet has that column (so formulas can read it)."""
        self.outputs[column.upper()] = value
        col = self.columns.get(column.upper())
        if col:
            self.sheet.set(self.row, col, value)
            self.written[(self.case.sheet, self.row, col)] = value
        self.values[column.upper()] = value

    def actual(self, column: str) -> str:
        return cell_text(self.values.get(column.upper())).strip() if column.upper() in self.outputs else ""


# -- request templates (JSON bodies for POST tests) --------------------------------------------------------------------------------------
def template_candidates(location: str, filename: str, fallback_dirs: list[str], workbook_dir: Path) -> list[Path]:
    """Where a request template may be, in order: the workbook's own location (an ``L:\\`` path on the QA machines), then the folders
    named in ``api.templates_dir`` / ``RR_API_TEMPLATES_DIR`` (secrets.env), then beside the workbook (``templates/`` and its own folder)."""
    tried: list[Path] = []

    def add(path: Path) -> None:
        if path not in tried:
            tried.append(path)

    location = location.strip()
    if location and filename:
        add(Path(location) / filename)
        if os.sep == "/" and "\\" in location:
            add(Path(location.replace("\\", "/")) / filename)
    last_folder = re.split(r"[\\/]+", location.rstrip("\\/"))[-1] if location else ""
    for base in fallback_dirs:
        if not base.strip():
            continue
        root = Path(base.strip()).expanduser()
        add(root / filename)
        if last_folder:
            add(root / last_folder / filename)
    add(workbook_dir / "templates" / filename)
    add(workbook_dir / filename)
    return tried
