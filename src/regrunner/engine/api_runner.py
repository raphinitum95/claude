"""Runs ONE API test: a data row of a ``WEBSERVICE_URL`` sheet (see ``workbook/api.py``).

It reports through the same events as a UI test, so the console, the web UI, the report and the shared copy need nothing new:
step 1 is the request, and every check the workbook asks for (``compare`` / ``contains`` ...) is a step of its own with the expected and the
actual value.  Only the request and the response are stored (``tests/<id>/request.txt``, ``response.json`` / ``.xml`` / ``.txt``); header values from ``addHeader``
(bearer tokens, API keys) are never written anywhere.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from urllib.parse import urlparse

from ..config import Config
from .ask import AskCancelled, AskTimeout, AskUnavailable
from .cancel import cancel_reason
from ..events import EventBus, now_iso
from ..reporting.results import StepRecord, TestResult
from ..workbook.api import METHODS, RESPONSE_CHECK, ApiRuntime, json_get, json_set, output_json_text, output_text, template_candidates
from ..workbook.api_paths import MISSING, is_extended_xpath, is_json_path, json_path_first, xpath_all
from ..workbook.api_template import apply_replacements, json_to_tree, output_values, replacement_text, xml_to_tree
from ..workbook.model import TestCase, Workbook
from .outcome import FAILED, PASSED
from .session import http_block_message

MASK = "••••••"


def tls_hint(message: str) -> str:
    low = message.lower()
    if "certificate" in low or "ssl" in low or "tls" in low:
        return (" If this network re-signs HTTPS (Zscaler), point NODE_EXTRA_CA_CERTS at the company root certificate, or set "
                "api.ignore_https_errors: true in config.yaml (for testing only).")
    return ""


def api_message(text: str) -> str:
    """What the API said about a refusal: its own ``message`` (API Gateway, most REST APIs), else the start of the body."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ("message", "Message", "error", "errorMessage", "error_description", "detail"):
            if isinstance(data.get(key), str) and data[key].strip():
                return " ".join(data[key].split())[:300]
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())[:200]


def is_an_error_page(status: int, headers: dict, text: str) -> bool:
    """A refusal from a firewall / CDN in front of the API (429, CloudFront's own error page, an HTML page) rather than the API's own JSON answer.
    Waiting and trying again can help with the first kind; it cannot fix a wrong key, so the second kind is reported at once."""
    if status == 429:
        return True
    low = {str(k).lower(): str(v).lower() for k, v in headers.items()}
    if "error from cloudfront" in low.get("x-cache", ""):
        return True
    return "json" not in low.get("content-type", "") and not text.lstrip().startswith(("{", "["))


# -- the pieces "Send now" in the Workbook Builder shares with a run (build/api_builder.py): same request, same reading of the response ----------
def prepare_body(runtime: ApiRuntime, request, cfg: Config, workbook_dir: Path) -> tuple[bytes | None, list[str], str]:
    """``(body, notes, problem)`` of a row: the body typed in ``REQUEST_BODY`` (the builder's form), else the request template (JSON: ``update_json`` +
    ``Replace``; any other text - an XML / SOAP envelope - ``Replace`` only, each value XML-escaped), else none."""
    typed, missing = runtime.request_body(request.json_format)
    if typed is not None:
        if request.method in ("GET", "HEAD"):
            return None, [f"body: not sent with {request.method} (the REQUEST_BODY cell is kept for another method)"], ""
        if missing:
            return None, [], "Nothing gives a value for " + ", ".join("{%s}" % m for m in missing) + " in the request body."
        return typed.encode("utf-8"), ["body: the REQUEST_BODY cell"], ""
    if request.method not in ("POST", "PUT", "PATCH") or not request.template_file:
        return None, [], ""
    fallback = [cfg.api.templates_dir, os.environ.get("RR_API_TEMPLATES_DIR", "")]
    tried = template_candidates(request.template_location, request.template_file, fallback, workbook_dir)
    found = next((p for p in tried if p.is_file()), None)
    if found is None:
        return None, [], (f"Request template {request.template_file!r} was not found. Looked in: " + "; ".join(str(p) for p in tried)
                          + ". On the QA machines it is on the L: drive; elsewhere put the folder in secrets.env as RR_API_TEMPLATES_DIR=<folder>.")
    try:
        raw = found.read_text(encoding="utf-8-sig")
    except OSError as err:
        return None, [], f"Request template {found} could not be read: {err}"
    notes = [f"template: {found}"]
    try:
        data = json.loads(raw)
    except ValueError as err:
        if not raw.lstrip().startswith("<"):
            return None, [], f"Request template {found} could not be read as JSON: {err}"
        return _xml_template(runtime, found, raw, notes)
    for path, value in runtime.body_updates():
        if not json_set(data, path, value):
            notes.append(f"update_json: {path} does not exist in the template (left as it is)")
    if runtime.io.replace:
        try:
            data, filled = apply_replacements(data, runtime.io.replace, runtime.values)
        except ValueError as err:
            return None, [], f"Cannot build the request from {found.name}: {err}."
        notes.append(f"Replace: {filled} placeholders filled from this row")
    return json.dumps(data, indent=4).encode("utf-8"), notes, ""


def _xml_template(runtime: ApiRuntime, found: Path, text: str, notes: list[str]) -> tuple[bytes | None, list[str], str]:
    """An XML (SOAP) request template: every ``Replace`` placeholder is swapped for its column's text, XML-escaped, in InputOutput order."""
    filled = 0
    for placeholder, column in runtime.io.replace.items():
        key = column.strip().upper()
        if not placeholder or key not in runtime.values or placeholder not in text:
            continue
        problem = runtime.error_in(column)
        if problem:
            return None, [], f"Cannot build the request from {found.name}: {problem}."
        filled += text.count(placeholder)
        text = text.replace(placeholder, xml_escape(replacement_text(runtime.values[key])))
    if runtime.io.update_json and runtime.body_updates():
        notes.append("update_json does not apply to an XML template (Replace does)")
    notes.append(f"Replace: {filled} placeholders filled from this row")
    return text.encode("utf-8"), notes, ""


@dataclass
class ApiResponse:
    status: int
    headers: dict
    text: str
    elapsed_ms: int
    data: object = None                         # the body as JSON, when it is JSON
    is_json: bool = False
    notes: list = field(default_factory=list)


async def fetch(pw, cfg: Config, method: str, url: str, headers: dict, body: bytes | None) -> ApiResponse:
    """Send one request with Playwright's request context (the same proxy and HTTPS settings as a run).  Raises when no response arrived."""
    api = cfg.api
    insecure = cfg.browser.ignore_https_errors if api.ignore_https_errors is None else api.ignore_https_errors
    context = None
    t0 = time.perf_counter()
    try:
        options = {"ignore_https_errors": bool(insecure)}
        if api.proxy:
            options["proxy"] = {"server": api.proxy}
        context = await pw.request.new_context(**options)
        response = await asyncio.wait_for(context.fetch(url, method=method, headers=headers, data=body, timeout=api.timeout_s * 1000),
                                          timeout=api.timeout_s + 5)
        status, got, text = response.status, dict(response.headers), await response.text()
    finally:
        if context is not None:
            try:
                await context.dispose()
            except Exception:
                pass
    out = ApiResponse(status, got, text, int((time.perf_counter() - t0) * 1000))
    try:
        out.data = json.loads(text) if text.strip() else None
    except ValueError:
        pass
    out.is_json = out.data is not None
    return out


def read_response(runtime: ApiRuntime, response: ApiResponse) -> list[str]:
    """Put what the ``output_json`` / ``Output`` rows ask for into the row (``runtime.record_output``), like the legacy runner, plus the paths the
    Workbook Builder writes: a JSONPath (``$.plans[?(@.code=='{PLAN}')].eligible``) and an XPath that starts at the document or ends on ``@attr``.
    Returns the notes for the report."""
    notes: list[str] = []
    runtime.record_response(response.text, response.data, response.is_json)            # (for a whole-response check)
    runtime.record_output("RES_STATUS_CD_OUT", str(response.status))
    runtime.record_output("ELAPSEDTIME_OUT", str(response.elapsed_ms))
    data = response.data if response.is_json else None
    for path, column in runtime.io.output_json.items():
        filled = runtime.fill(path)
        if filled.missing:
            notes.append(f"output_json: nothing gives a value for {', '.join('{%s}' % m for m in filled.missing)} in {path!r}")
            continue
        if is_json_path(filled.text):
            if ".." in filled.text:
                notes.append(f"output_json: {path!r} uses '..', which is not supported (write the whole path)")
                continue
            found = json_path_first(data, filled.text) if response.is_json else MISSING
            value = "None" if found is MISSING or found is None else output_text(found)
        elif "*" in path or ".." in path:
            notes.append(f"output_json: {path!r} is a JSONPath expression this runner cannot read")
            continue
        else:
            value = output_json_text(data, filled.text) if response.is_json else ""
        if value != "":
            runtime.record_output(column, value)
    if runtime.io.output:                                                 # Output: element paths (policyresponses/policydetail/policynumber)
        tree = json_to_tree(data, runtime.lower_tags()) if response.is_json else xml_to_tree(response.text)
        if tree is None:
            notes.append("Output: the response is neither JSON nor XML, so nothing was read from it")
        else:
            legacy = {p: c for p, c in runtime.io.output.items() if not ("{" in p or is_extended_xpath(p))}
            got = [(column, value) for _p, column, value in output_values(tree, legacy, strip=runtime.strip_response())]
            for path, column in runtime.io.output.items():
                if path in legacy:
                    continue
                filled = runtime.fill(path)
                try:
                    values = [] if filled.missing else xpath_all(tree, filled.text)
                except ValueError as err:
                    notes.append(f"Output: {err}")
                    continue
                values = [v.strip() if runtime.strip_response() else v for v in values if v.strip() and v.strip().upper() != "NONE"]
                if values:
                    got.append((column, ";".join(values)))
            for column, value in got:
                runtime.record_output(column, value)
            notes.append(f"Output: {len(got)} values read from the response")
    return notes


class ApiTestRunner:
    __test__ = False

    def __init__(self, *, workbook: Workbook, case: TestCase, pw, cfg: Config, bus: EventBus, run_dir: Path, cancel: asyncio.Event,
                 planned: int, shared: dict, worker: int = 0, attempt: int = 1, throttle=None, asker=None, pool=None):
        self.workbook, self.case, self.pw, self.cfg, self.bus = workbook, case, pw, cfg, bus
        self.run_dir, self.cancel, self.shared, self.worker, self.attempt, self.throttle = run_dir, cancel, shared, worker, attempt, throttle
        self.test_dir = run_dir / "tests" / case.slug
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.result = TestResult(id=case.id, title=case.title, sheet=case.sheet, scenario=case.scenario, description=case.description,
                                 total_steps=planned, attempt=attempt)
        self._asker = asker
        self._pool = pool                         # the run's shared variables ({NAME}; what a response saves goes in)
        self._runtime: ApiRuntime | None = None   # the runtime in use (replaced when a person supplies an empty input)

    def _emit(self, type_: str, **fields):
        return self.bus.emit(type_, test=self.case.id, **fields)

    # -- one step -----------------------------------------------------------------------------------------------------------------
    def _record(self, seq: int, row: int, name: str, action: str, status: str, *, error: str = "", expected: str = "", actual: str = "",
                comparison: str = "", value: str = "", notes: list[str] | None = None, sets: list[dict] | None = None,
                started_at: str, t0: float) -> StepRecord:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        record = StepRecord(seq=seq, row=row, name=name, action=action, status=status, error=error, expected=expected, actual=actual,
                            comparison=comparison, value=value[:500], notes=notes or [], started_at=started_at, ended_at=now_iso(),
                            duration_ms=duration_ms, sets=sets or [])
        self.result.variables.extend({**s, "seq": seq, "row": row, "step": name, "by_hand": False} for s in sets or [])
        self.result.steps.append(record)
        if status == PASSED:
            self.result.passed += 1
        else:
            self.result.failed += 1
        failed = status == FAILED
        self._emit("step_failed" if failed else "step_passed", step=seq, total_steps=self.result.total_steps, row=row, name=name, action=action,
                   status=status, duration_ms=duration_ms, expected=expected, actual=actual, error=error, locator="", locator_origin="",
                   fallback=False, comparison=comparison, notes=record.notes, screenshot=None, sets=record.sets)
        return record

    def _begin(self, seq: int, row: int, name: str, action: str) -> tuple[str, float]:
        self._emit("step_started", step=seq, total_steps=self.result.total_steps, row=row, name=name, action=action)
        return now_iso(), time.perf_counter()

    def _template(self, runtime: ApiRuntime, request) -> tuple[bytes | None, list[str], str]:
        """(body, notes, error) of the request (``prepare_body``)."""
        return prepare_body(runtime, request, self.cfg, self.workbook.path.parent)

    # -- the test -------------------------------------------------------------------------------------------------------------------
    async def run(self) -> TestResult:
        case, result = self.case, self.result
        started = time.perf_counter()
        result.started_at = now_iso()
        self._emit("test_started", title=case.title, total_steps=result.total_steps, worker=self.worker, attempt=self.attempt)
        try:
            if self.cancel.is_set():
                result.status, result.error = "CANCELLED", cancel_reason(self.cancel, "")
                return result
            runtime = self._runtime = self.workbook.api_runtime(case, self.shared, pool=self._pool)
            checks = runtime.checkpoints()
            result.total_steps = 1 + len(checks)
            sent = await self._request(runtime)
            runtime = self._runtime                                          # (a value a person supplied rebuilds it)
            if not sent:
                result.status = "ERROR"
                result.skipped = len(checks)
                result.error = result.error or result.steps[-1].error
                return result
            for n, point in enumerate(checks, start=2):
                if self.cancel.is_set():
                    result.status, result.error = "CANCELLED", cancel_reason(self.cancel, "")
                    break
                self._check(runtime, point, n)
            if result.status != "CANCELLED":
                result.status = "FAILED" if result.failed else "PASSED"
        except asyncio.CancelledError:
            result.status, result.error = "ERROR", result.error or "Test was cancelled (time limit or shutdown)"
            raise
        except Exception as err:                                          # a runner bug must not take the run down
            result.status, result.error = "ERROR", f"{type(err).__name__}: {err}"
        finally:
            result.ended_at = now_iso()
            result.duration_s = round(time.perf_counter() - started, 2)
            self._emit("test_finished", status=result.status, passed=result.passed, failed=result.failed, skipped=result.skipped,
                       duration_s=result.duration_s, error=result.error, review_counts=[])
        return result

    async def _request(self, runtime: ApiRuntime) -> bool:
        """Step 1.  True when a response arrived (whatever its status); False when the test cannot go on."""
        result, row = self.result, runtime.row
        request = runtime.request()
        name = runtime.mask(f"{request.method} {request.url}".strip())
        started_at, t0 = self._begin(1, row, name, request.method)
        fail = lambda message: (self._record(1, row, name, request.method, FAILED, error=message, value=runtime.mask(request.url), started_at=started_at, t0=t0), False)[1]

        problem = runtime.error_in("WEBSERVICE_URL") or runtime.error_in("WEBSERVICE_METHOD")
        if problem:
            return fail(f"Cannot build the request: {problem}. regrunner cannot calculate that Excel formula.")
        expects_a_status = any(c.actual_column.upper() == "RES_STATUS_CD_OUT" for c in runtime.checkpoints())     # a test that expects one may mean to send it empty
        empty = [] if expects_a_status else runtime.empty_inputs()
        if empty:
            runtime, problem = await self._fill_inputs(runtime, empty, request)
            if problem:
                return fail(problem)
            self._runtime = runtime
            request = runtime.request()
            name = runtime.mask(f"{request.method} {request.url}".strip())
        if not request.url:
            return fail(f"There is no URL for this row: {request.url_problem}." if request.url_problem else "WEBSERVICE_URL is empty for this row.")
        if urlparse(request.url).scheme not in ("http", "https"):
            return fail(f"WEBSERVICE_URL {request.url!r} is not an http(s) address.")
        if request.method not in METHODS:
            return fail(f"WEBSERVICE_METHOD {request.method!r} is not one of {', '.join(METHODS)}.")
        body, notes, problem = self._template(runtime, request)
        if problem:
            return fail(problem)

        (self.test_dir / "request.txt").write_text(runtime.mask(
            f"{request.method} {request.url}\n" + "".join(f"{k}: {MASK if k in request.secret_headers else v}\n" for k, v in request.headers.items())
            + ("\n" + body.decode("utf-8") if body else "")), encoding="utf-8")
        if self.throttle is not None:
            await self.throttle.before_load(self.cancel)                  # the run-wide gap and any cool-down after a block
        t0 = time.perf_counter()                                          # (the time the request took, not the time it waited for its turn)
        try:
            response = await fetch(self.pw, self.cfg, request.method, request.url, request.headers, body)
        except Exception as err:
            reason = runtime.mask((str(err).strip().splitlines() or [type(err).__name__])[0][:300])
            return fail(f"The request could not be completed: {reason}.{tls_hint(reason)}")
        status, headers, text, elapsed_ms = response.status, response.headers, response.text, response.elapsed_ms
        if response.is_json:
            (self.test_dir / "response.json").write_text(json.dumps(response.data, indent=4, ensure_ascii=False), encoding="utf-8")
        else:
            (self.test_dir / ("response.xml" if xml_to_tree(text) is not None else "response.txt")).write_text(text, encoding="utf-8")
        notes.append(f"HTTP {status} in {elapsed_ms} ms; response saved in tests/{self.case.slug}/")
        if status in self.cfg.runner.block_statuses and is_an_error_page(status, headers, text):
            message = runtime.mask(http_block_message(request.url, status, headers))
            result.blocked = message                                          # the runner pauses and tries again (or stops, see throttle.retry_budget)
            result.error = f"The site did not answer. {message}"
            self._record(1, row, name, request.method, FAILED, error=message, value=runtime.mask(request.url), notes=notes, started_at=started_at, t0=t0)
            return False
        if status in (401, 403) and not expects_a_status:                     # the API itself said no, and nothing in the workbook expected that
            message = runtime.mask(self._refusal(runtime, request, status, text))
            result.error = message
            self._record(1, row, name, request.method, FAILED, error=message, value=runtime.mask(request.url), notes=notes, started_at=started_at, t0=t0)
            return False
        if self.throttle is not None and status < 400:
            self.throttle.loaded_ok = True
        notes += read_response(runtime, response)
        if status >= 400:
            notes.append("the response is an error; checks below read from it")
        self._record(1, row, name, request.method, PASSED, value=runtime.mask(request.url), notes=notes, sets=self._sets(runtime), started_at=started_at, t0=t0)
        return True

    @property
    def written(self) -> dict:
        """The cells of the API sheet the response filled in (a policy number ...): the tests that read them (=PurchaseUS!FB3) come after this one."""
        return dict(self._runtime.written) if self._runtime is not None else {}

    def _sets(self, runtime: ApiRuntime) -> list[dict]:
        """What the response put into the row, for the report: only columns the sheet has, and never the status / timing bookkeeping."""
        from openpyxl.utils import get_column_letter
        skip = {"RES_STATUS_CD_OUT", "ELAPSEDTIME_OUT", "REQUESTTIME_OUT", "RESPONSETIME_OUT"}
        out = []
        for (sheet, r, col), value in runtime.written.items():
            header = runtime.sheet.data.header_names.get(col, "")
            if header.upper() in skip:
                continue
            out.append({"name": header, "value": value, "stored": value, "cell": f"{sheet}!{get_column_letter(col)}{r}"})
        return out

    def _refusal(self, runtime: ApiRuntime, request, status: int, text: str) -> str:
        """The API answered 401 / 403: what it said, which credentials were sent and where they come from, and the usual causes."""
        said = api_message(text)
        sent = ", ".join(f"{h} (column {c})" for h, c in runtime.io.add_header.items() if h in request.headers) or "no credential headers"
        parts = [f"{urlparse(request.url).netloc} refused the request: HTTP {status}" + (f' - "{said}"' if said else "") + ".",
                 f"Headers sent: {sent}. Their values come from those columns of the sheet; RR_VAR_<COLUMN> in secrets.env (RR_VAR_DT_APIKEY, "
                 "RR_VAR_DT_BEARERTOKEN) wins over the cell.",
                 "Check that the key and the bearer token are for this environment and that the token has not expired."]
        if request.url.rstrip("?").endswith("/"):
            parts.append(f"The URL ends in '/' ({request.url}): something that belongs after it - usually the policy number - is probably empty, "
                         "and the gateway then answers as if the route did not exist.")
        elif "key=value pair" in said or "Missing Authentication Token" in said:
            parts.append("AWS API Gateway says this when the Authorization header is not what the route expects, or when the URL is not one of its routes.")
        return " ".join(parts)

    async def _fill_inputs(self, runtime: ApiRuntime, empty: list[dict], request) -> tuple[ApiRuntime, str]:
        """The URL is built from an empty cell (a policy number nobody has produced): ask a person for it (used for this run only), else say so
        instead of sending a request that cannot work."""
        asker = self._asker
        for need in empty:
            why = (f"Not sent: {need['column']} is empty ({need['source']}) and the request URL is built from it, so it would go to {request.url}. "
                   "A UI test of the sheet that sets it (Purchase) has to run first in the same run, or the cell needs a value.")
            if asker is None or not asker.available:
                return runtime, f"{why} Start the run from the web UI or a terminal to be asked for it."
            question = f"{need['column']} is empty for {self.case.id} ({need['source']}). Type the value to use in this run; the workbook is not changed."
            try:
                answer = (await asker.ask(self.case.id, 1, question, timeout_s=self.cfg.ask.timeout_s)).strip()
            except AskUnavailable as err:
                return runtime, f"{why} {err}"
            except AskTimeout as err:
                return runtime, f"{why} Nobody answered: {err}"
            except AskCancelled:
                return runtime, "The run was cancelled while waiting for a value."
            if not answer:
                return runtime, f"{why} No value was given."
            self.shared[need["key"]] = answer
            self.result.variables.append({"name": need["column"], "value": answer, "stored": answer, "cell": need["source"], "seq": 1,
                                          "row": runtime.row, "step": "", "by_hand": True})
            self._emit("variable_set", step=1, name=need["column"], value=answer, cell=need["source"], by_hand=True)
        return self.workbook.api_runtime(self.case, self.shared, pool=self._pool), ""

    def _check(self, runtime: ApiRuntime, point, seq: int) -> None:
        started_at, t0 = self._begin(seq, runtime.row, point.step_name, point.kind.upper())
        ok, expected, actual, differences = runtime.verdict(point)     # (an expected value may be {PLAN}: the builder writes it)
        whole = point.kind == RESPONSE_CHECK
        comparison = "" if whole else "contains" if point.kind.startswith("contains") else "exact" if point.kind.startswith("compare") else ""
        how = "" if comparison or whole else f" ({point.kind.replace('_', ' ')})"   # greater than / between / matches: said in the notes
        notes = differences if whole else [] if ok else [f"{point.expected_column} vs {point.actual_column}{how}"]
        if not ok and actual == "" and not whole:
            notes.append("nothing was found in the response for that column (path missing or empty)")
        self._record(seq, runtime.row, point.step_name, point.kind.upper(), PASSED if ok else FAILED,
                     error="" if ok else "Comparison Failed", expected=expected, actual=actual, comparison=comparison, notes=notes,
                     started_at=started_at, t0=t0)
