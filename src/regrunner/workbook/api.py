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
* the Workbook Builder adds a whole-response check: ``compare_response`` expected column -> ``RESPONSE_OUT`` (the entire body against the
  expected column's text, ``workbook/api_compare.py``) and ``ignore_in_response`` expected column -> ``timestamp; $.meta.id`` (the fields it
  leaves out).  Both are functions the legacy runner did not know, so it skipped them.

Nothing here touches the network; ``engine/api_runner.py`` sends the request.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .api_compare import ignore_list
from .sheet import BookState, ErrorText, cell_text
from .variables import COPY_RE

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
CHECK_KINDS = ("compare", "compare_ignore_case", "contains", "contains_ignore_case", "greater_than", "less_than", "between", "matches",
               "compare_response")
# (the last five are written by the Workbook Builder - P10, and compare_response for the whole response: only the new runner reads them; the
# legacy runner skipped unknown functions)
RESPONSE_CHECK = "compare_response"     # expected column -> RESPONSE_OUT: the whole response body against the expected column's text
RESPONSE_ACTUAL = "RESPONSE_OUT"        # the actual column a whole-response check names (a label: the body is never written into a cell)
_FUNCTIONS = {"addheader": "add_header", "add_header": "add_header", "update_json": "update_json", "output_json": "output_json",
              "compare": "compare", "compare_ignore_case": "compare_ignore_case", "contains": "contains",
              "contains_ignore_case": "contains_ignore_case", "disablecheckpoint": "disable", "disable_checkpoint": "disable",
              "replace": "replace", "output": "output", "greater_than": "greater_than", "less_than": "less_than", "between": "between",
              "matches": "matches", "compare_response": "compare_response", "ignore_in_response": "ignore_in_response"}


def is_api_sheet(headers) -> bool:
    """Is a sheet with these (UPPER) headers an API sheet?  The legacy web-service runner required ``ENVIRONMENT_PARAMETER`` (the URL comes from the
    ``Environments`` sheet); ``WEBSERVICE_URL`` is the newer way to give the URL in the row itself.  Either one, next to ``blnExecute``, makes it one."""
    return "BLNEXECUTE" in headers and ("WEBSERVICE_URL" in headers or "ENVIRONMENT_PARAMETER" in headers)


@dataclass
class Checkpoint:
    kind: str                     # one of CHECK_KINDS
    expected_column: str
    actual_column: str
    ignore: list[str] = field(default_factory=list)       # compare_response: the fields left out (``ignore_in_response``)

    @property
    def name(self) -> str:
        return self.actual_column

    @property
    def step_name(self) -> str:
        """The step's name in the report: ``Check Premium_OUT``, or ``Check the whole response``."""
        return "Check the whole response" if self.kind == RESPONSE_CHECK else f"Check {self.actual_column}"


@dataclass
class InputOutput:
    add_header: dict[str, str] = field(default_factory=dict)          # header name -> column
    update_json: dict[str, str] = field(default_factory=dict)         # JSON path -> column
    output_json: dict[str, str] = field(default_factory=dict)         # JSON path -> column
    replace: dict[str, str] = field(default_factory=dict)             # text in the request template -> column holding what goes there
    output: dict[str, str] = field(default_factory=dict)              # element path (a/b[2]/c) in the response -> column
    checks: dict[str, dict[str, str]] = field(default_factory=lambda: {k: {} for k in CHECK_KINDS})   # kind -> {expected column: actual column}
    disabled: dict[str, str] = field(default_factory=dict)            # test name -> "col;col"
    ignore_in_response: dict[str, str] = field(default_factory=dict)  # a compare_response's expected column (UPPER) -> "field; $.path; /x/@y"
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
        elif kind == "ignore_in_response":
            io.ignore_in_response[param.upper()] = value
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
def _number(text: str) -> float | None:
    try:
        return float(re.sub(r"[^\d.\-]", "", text.replace(",", "")) or "x")
    except ValueError:
        return None


def check(kind: str, expected: Any, actual: str) -> bool:
    """The legacy verdict: text equality after trimming (numbers compare to four decimals), or containment; ``_ignore_case`` upper-cases both.
    The builder's kinds: ``greater_than`` / ``less_than`` (numbers, "$1,234.50" reads as 1234.5), ``between`` (expected ``low;high`` or ``low and
    high``, both ends included) and ``matches`` (a regular expression found in the actual text)."""
    exp_text = cell_text(expected).strip()
    act_text = (actual or "").strip()
    if kind in ("greater_than", "less_than", "between"):
        value = _number(act_text)
        ends = [_number(p) for p in re.split(r"\s*(?:;|\band\b)\s*", exp_text, flags=re.I) if p.strip()]
        if value is None or not ends or None in ends:
            return False
        if kind == "between":
            return len(ends) == 2 and min(ends) <= value <= max(ends)
        return value > ends[0] if kind == "greater_than" else value < ends[0]
    if kind == "matches":
        try:
            return re.search(exp_text, act_text) is not None
        except re.error:
            return False
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
    """One data row of an API sheet, evaluated the way the UI rows are (formulas, tokens); results are written back into the sheet state.

    ``{NAME}`` / ``{SECRET:NAME}`` in the URL, header values, the ``REQUEST_BODY`` cell and response paths (written by the Workbook Builder) are
    filled from the row's own columns, then the run's shared variables (``pool``), then the environment table (``env_table``, ``_rr_environments``);
    a secret put in is kept in ``secret_values`` so every file and report masks it.  Legacy rows have no braces, so nothing changes for them."""

    def __init__(self, book: BookState, case, globals_: dict[str, Any], secrets: Mapping[str, str], *, pool=None, env_table=None, unique=None):
        self.book, self.case, self.globals, self.secrets = book, case, globals_, secrets
        self.pool, self.env_table = pool, env_table
        self.unique = unique or {}                                   # unique variables: an API request reads their copies ({NAME#2}), never makes one
        self.secret_values: set[str] = pool.secret_values if pool is not None else set()   # (the pool's own set: masked in every test of the run)
        self.sheet = book.sheet(case.sheet)
        self.row = case.param_row
        self.columns = self.sheet.data.headers
        self.values: dict[str, Any] = {name: self.sheet.read(self.row, col) for name, col in self.columns.items()}
        self.io = read_input_output(book)
        self.outputs: dict[str, str] = {}
        self.response_text = ""                                      # the body of the response (read_response): what compare_response reads
        self.response_data: Any = None
        self.response_is_json = False
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
                headers[header] = self.fill(text).text
                secret_headers.add(header)                              # values are masked in every file and report
        json_format = cell_text(self.values.get("JSON_FORMAT")).strip().upper() in ("Y", "YES", "TRUE", "1")
        url, soap_action, content_type, url_problem = self.endpoint()
        if url and "{" in url:
            filled = self.fill(url, quote=True)
            url = filled.text
            if filled.missing and not url_problem:
                url_problem = "nothing gives a value for " + ", ".join("{%s}" % m for m in filled.missing) + " in the URL"
                url = ""
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

    # -- {NAME} ---------------------------------------------------------------------------------------------------------------------------
    def value_of(self, name: str) -> str | None:
        """``{NAME}``: a non-empty column of this row, else the run's shared variables, else the environment table (``None`` = nothing gives one)."""
        from .variables import SECRET_RE, secret_value
        key = name.upper().strip()
        if key in self.values and cell_text(self.values[key]).strip():
            return cell_text(self.values[key])
        pooled = self.pool.get(key) if self.pool is not None else None
        if pooled is not None:
            return pooled
        env = self.env_table.value(key, self.environment) if self.env_table is not None else None
        if env is None:
            return None

        def put(m) -> str:
            value = secret_value(m.group(1), self.environment)
            if value is None:
                return m.group(0)
            self.secret_values.add(value)
            return value
        return SECRET_RE.sub(put, env)

    def copy_of(self, name: str, which: str) -> tuple[str | None, str]:
        """``{NAME#2}`` / ``{NAME#last}``: a copy a UI test of the run made (an API request only reads them)."""
        key = name.upper().strip()
        if key not in self.unique:
            return None, f"{key} is not a unique variable"
        value = self.pool.copy(key, which) if self.pool is not None else None
        return (value, "") if value is not None else (None, f"{key} #{which.lower()} was never created in this run")

    def fill(self, text: str, *, escape=None, quote: bool = False):
        """``text`` with ``{NAME}`` / ``{SECRET:NAME}`` filled in (``variables.Substituted``: ``missing`` names stay as written).  ``escape``: how
        a value is written into a body (JSON string / XML text); ``quote``: URL-encode the values (a path or query part)."""
        from urllib.parse import quote as url_quote
        from .variables import secret_value, substitute

        def secret(name: str) -> str | None:
            return secret_value(name, self.environment)

        out = substitute(text or "", lambda n: (self.value_of(n), False), secret, copies=self.copy_of)
        out.missing.extend(m.group(1) + "#" + m.group(2).lower() for m in COPY_RE.finditer(text or "") if self.copy_of(m.group(1), m.group(2))[0] is None)
        self.secret_values.update(v for v in out.secrets if v)
        if (escape or quote) and out.used + out.secrets:
            # (filled again, value by value, so only the values are escaped - never the text around them)
            def one(value: str) -> str:
                value = escape(value) if escape else value
                return url_quote(value, safe="/:?&=@+,;%~") if quote else value
            fresh = substitute(text or "", lambda n: ((lambda v: None if v is None else one(v))(self.value_of(n)), False),
                               lambda n: (lambda v: None if v is None else one(v))(secret(n)),
                               copies=lambda n, w: (lambda v: (None if v[0] is None else one(v[0]), v[1]))(self.copy_of(n, w)))
            out.text = fresh.text
        return out

    def names_used(self) -> set[str]:
        """Every ``{NAME}`` in the URL, header columns, body and response paths of this row (UPPER; secrets not included)."""
        from .variables import INLINE_RE
        texts = [self.text("WEBSERVICE_URL"), self.text("REQUEST_BODY"), *self.io.output_json.keys(), *self.io.output.keys()]
        texts += [self.text(c) for c in self.io.add_header.values()]
        return {m.upper() for t in texts for m in INLINE_RE.findall(t or "")}

    def copies_used(self) -> set[str]:
        """Every unique copy (``{NAME#2}``, ``{NAME#last}``) the URL, headers, body and response paths read, as Needs: LASTNAME#2 / LASTNAME#*."""
        texts = [self.text("WEBSERVICE_URL"), self.text("REQUEST_BODY"), *self.io.output_json.keys(), *self.io.output.keys()]
        texts += [self.text(c) for c in self.io.add_header.values()]
        return {f"{n.upper()}#{w}" if w.isdigit() else f"{n.upper()}#*" for t in texts for n, w in COPY_RE.findall(t or "")}

    def pool_reads(self) -> set[str]:
        """``{NAME}``s only the run's shared variables can give (not a column of the row, not the environment table): the test Needs them."""
        out = set(self.copies_used())
        for name in self.names_used():
            if name in self.values and cell_text(self.values[name]).strip():
                continue
            if self.env_table is not None and self.env_table.value(name, self.environment) is not None:
                continue
            out.add(name)
        return out

    def pool_sets(self) -> set[str]:
        """The names a response puts into the run's shared variables (Provides): ``output_json`` / ``Output`` columns this sheet has."""
        return {c.upper() for c in [*self.io.output_json.values(), *self.io.output.values()] if c.upper() in self.columns}

    def request_body(self, json_format: bool) -> tuple[str | None, list[str]]:
        """``(body, names nothing gives a value for)``: the body typed in the ``REQUEST_BODY`` cell (the Workbook Builder's form), filled in;
        ``None`` when the row has none (a template file, or no body).  A value is escaped for the body's format, so a quote in it cannot break
        the JSON / XML."""
        text = self.text("REQUEST_BODY") if "REQUEST_BODY" in self.columns else ""
        if not text:
            return None, []
        from xml.sax.saxutils import escape as xml_escape
        esc = (lambda v: json.dumps(v)[1:-1]) if json_format else xml_escape
        filled = self.fill(text, escape=esc)
        return filled.text, filled.missing

    def mask(self, text: str) -> str:
        """``text`` with every secret value put into this row's request replaced by dots."""
        for value in sorted(self.secret_values, key=len, reverse=True):
            if value and len(value) >= 3:
                text = text.replace(value, "\u2022" * 6)
        return text

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

    def formula_reads(self) -> list[dict[str, Any]]:
        """Every cell of *another sheet* that a formula anywhere in this row names, not only the request's inputs: an expected value such as
        ``PolicyStatus_EXP = =AgentPortal_Params!X3`` is what a website test of the run captured, so the API test has to wait for that test as
        surely as for its policy number.  Same shape as ``cell_reads`` (``blank`` is always False: nothing is asked for a checked value, the
        run only waits for whoever sets it)."""
        from openpyxl.utils import get_column_letter
        data = self.sheet.data
        out: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        for header, col in self.columns.items():
            cell = data.cells.get((self.row, col))
            if cell is None or not cell.formula:
                continue
            for key in referenced_cells(cell.formula, self.book):
                if key in seen or key[0].upper() == str(self.case.sheet).upper():
                    continue
                seen.add(key)
                other = self.book.data.sheet(key[0])
                name = other.header_names.get(key[2]) if other is not None else None
                out.append({"column": header, "param": name or header, "key": key, "blank": False, "own": False, "in_url": False,
                            "source": f"{key[0]}!{get_column_letter(key[2])}{key[1]}" + (f" ({name})" if name else "")})
        return out

    # -- what gets checked -----------------------------------------------------------------------------------------------------------
    def checkpoints(self) -> list[Checkpoint]:
        skip = skipped_columns(self.io, self.values, self.global_text("TC_Name_Column", "TC_Name"))
        out = []
        for kind in CHECK_KINDS:
            for expected, actual in self.io.checks[kind].items():
                if expected.upper() not in self.values or actual.upper() in skip:
                    continue                                            # no expected value column in this sheet, or switched off for this test
                ignore = ignore_list(self.io.ignore_in_response.get(expected.upper(), "")) if kind == RESPONSE_CHECK else []
                out.append(Checkpoint(kind, expected, actual, ignore))
        return out

    def expected_value(self, point: Checkpoint) -> Any:
        """The expected cell of a check, ``{NAME}``s filled in (the builder writes ``{PLAN}``).  A whole expected response is filled with each
        value escaped for the response's format, so a quote in a value cannot break the expected JSON / XML."""
        raw = self.values.get(point.expected_column.upper())
        if not (isinstance(raw, str) and "{" in raw):
            return raw
        if point.kind != RESPONSE_CHECK:
            return self.fill(raw).text
        from xml.sax.saxutils import escape as xml_escape
        return self.fill(raw, escape=(lambda v: json.dumps(v)[1:-1]) if self.response_is_json else xml_escape).text

    def verdict(self, point: Checkpoint) -> tuple[bool, str, str, list[str]]:
        """``(passed, expected, actual, notes)`` of one check, the way a run reports it and Send now shows it (secrets masked).  A whole-response
        check compares the body ``record_response`` kept and lists its differences in the notes (the first ``MAX_DIFFERENCES``)."""
        expected_raw = self.expected_value(point)
        if point.kind == RESPONSE_CHECK:
            from .api_compare import compare_response
            result = compare_response(cell_text(expected_raw), self.response_text, ignore=point.ignore, actual_data=self.response_data,
                                      actual_is_json=self.response_is_json)
            ignoring = f" (ignoring {'; '.join(point.ignore)})" if point.ignore else ""
            expected = f"the whole response in {point.expected_column}{ignoring}"
            if result.problem:
                return False, expected, "", [self.mask(result.problem)]
            if result.same:
                return True, expected, "the same" + (f" ({result.ignored} ignored)" if result.ignored else ""), []
            actual = f"{result.count} difference{'s' if result.count != 1 else ''}: {result.differences[0]}"
            notes = [self.mask(d) for d in result.differences]
            if result.count > len(result.differences):
                notes.append(f"... and {result.count - len(result.differences)} more")
            return False, expected, self.mask(actual[:300]), notes
        actual = self.actual(point.actual_column)
        return check(point.kind, expected_raw, actual), self.mask(cell_text(expected_raw)), actual, []

    def plan(self) -> list[tuple[int, str, str]]:
        """Dry run: the request, then each check (used for progress totals and the previews)."""
        req = self.request()
        steps = [(self.row, f"{req.method} {req.url}".strip(), req.method)]
        steps += [(self.row, c.step_name, c.kind.upper()) for c in self.checkpoints()]
        return steps

    def record_output(self, column: str, value: str) -> None:
        """A value taken from the response: kept, and written into the row when the sheet has that column (so formulas can read it)."""
        self.outputs[column.upper()] = value
        col = self.columns.get(column.upper())
        if col:
            self.sheet.set(self.row, col, value)
            self.written[(self.case.sheet, self.row, col)] = value
            if self.pool is not None and column.upper() in self.pool_sets():
                self.pool.set(column.upper(), value, self.case.id)          # {COLUMN} in any later test of the run
        self.values[column.upper()] = value

    def record_response(self, text: str, data: Any, is_json: bool) -> None:
        """Keep the whole response for a ``compare_response`` check.  Never written into a cell: a body can be far longer than Excel's 32,767
        characters, and the evidence folder already holds it (``response.json`` / ``.xml``)."""
        self.response_text, self.response_data, self.response_is_json = text or "", data, bool(is_json)

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
