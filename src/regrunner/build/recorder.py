"""Recording in the build window, and "Check this / Save this" (P09; Q6-Q9, Q34, Q41-Q42, Q51, Q53).

The overlay (``overlay.js``) tells the build session what a person does on the page; this module turns it into steps of the test being edited:

* **Record** (Q6): while it is on, clicks, typing, choices and ticks become steps **at the cursor** (after the step selected when recording
  started, then after each recorded step), with the locator worked out the same way as a pick (``locators.py``).  Only the person's own
  actions count: the overlay sends events the browser marks ``isTrusted`` (never a site's script), proves itself with the session's key, and
  nothing is recorded while a replay drives the page.  No fixed waits are ever added (Q41): the engine waits on evidence.
* **Windows, frames and Back** (Q34): an action in another window or frame first gets its ``SWITCHTOWINDOW`` / ``SWITCHTOMAINWINDOW`` /
  ``SWITCHTOFRAME`` / ``SWITCHTODEFAULT`` step; the browser's Back button becomes a ``BACK`` step.
* **Typed text becomes a variable** (Q7): the name comes from the field's label (``{FIRST_NAME}``), the value goes into the test's Params sheet
  (an existing variable whose value in the "Building with" row matches is reused); a prompt offers keep / fixed text / rename.  A password field
  makes a **secret** (Q42): the step says ``{SECRET:NAME}`` and the value goes to ``secrets.env`` (``RR_SECRET_<ENV>_<NAME>``) - never to the
  workbook, the log, an event or the Build tab.
* **Widgets collapse** (Q51): the clicks through a calendar become one ``PICK_DATE`` step, typing plus a click on a suggestion one
  ``CHOOSE_SUGGESTION`` step; "Keep raw clicks" puts the raw steps back.
* **Page fingerprints** (Q53): when a recorded action loads another URL, the recorder proposes a fingerprint (URL part + the page's main heading)
  and an ``ASSERT_PAGE`` gate after that action.
* **Check / Save / Wait until** (Q8, Q41): an element picked in those modes gets a card with every check the engine has (``check_kinds``),
  prefilled from the live page; adding one writes the step.

Every write is an ordinary builder op (``BuildDocument.apply``), so each recorded step can be undone like any other edit.
"""
from __future__ import annotations

import asyncio
import hmac
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import load_env_file
from ..engine import checks
from ..engine.session import FrameStep
from ..workbook.builder import SIDE_EFFECT_WORDS, BuildError, auto_name, describe_target, make_token, read_fingerprints
from ..workbook.sheet import cell_text
from ..workbook.variables import secret_value
from . import locators as L

if TYPE_CHECKING:                                     # pragma: no cover
    from .session import BuildSession

WIDGET_CLICKS = 15                                    # a calendar is given up (its clicks written as they were) after this many clicks...
WIDGET_S = 120.0                                      # ...or this long
SUGGESTION_S = 30.0                                   # a click on a suggestion this soon after typing makes one CHOOSE_SUGGESTION step
MAX_PROMPTS = 12
FINISHED_LABEL_S = 8.0                                # the pill says what a recording wrote for this long after it stops
DATE_FORMATS = ("dd/mm/yyyy", "d/m/yyyy", "yyyy-mm-dd", "dd-mm-yyyy", "dd.mm.yyyy", "d mmm yyyy", "dd mmm yyyy", "d mmmm yyyy", "mmm d, yyyy",
                "dd/mm/yy")
_NUMBER = re.compile(r"-?\d[\d,]*(\.\d+)?")
_SECRET_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Pure helpers (fast tests: tests/test_build_recorder.py)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def is_field(desc: dict) -> bool:
    return desc.get("kind") in ("field", "textbox", "dropdown", "checkbox", "radio")


def is_date_field(desc: dict) -> bool:
    """A field that takes a date: a browser date field, or a DD/MM/YYYY-style placeholder."""
    return (desc.get("type") or "").lower() in ("date", "datetime-local") or checks.looks_like_date_format(desc.get("placeholder") or "")


_GENERIC_TARGETS = {"the element", "link", "field", "button", "list", "box", "label", "image", "frame", "heading", "item", "option", "table"}


def looks_like_date(text: str) -> bool:
    try:
        checks.parse_date(text)
        return True
    except ValueError:
        return False


RELATIVE_DATE_DAYS = (-30, 800)                       # a date this close to today is "N days from today"; further away (a birth date) stays as typed


def relative_date(text: str, today: Any = None) -> str:
    """``=TEXT(TODAY()+5,"dd/mm/yyyy")`` for a date 5 days from today, in the shape ``text`` was written in ("" when it is not a date, or is
    so far from today that it is a fixed date on purpose): the recorded test then picks "5 days from today" on any day it is run."""
    from datetime import date
    try:
        picked = checks.parse_date(text)
    except ValueError:
        return ""
    days = (picked - (today or date.today())).days
    fmt = guess_date_format(text)
    if not fmt or not RELATIVE_DATE_DAYS[0] <= days <= RELATIVE_DATE_DAYS[1]:
        return ""
    offset = "" if days == 0 else f"+{days}" if days > 0 else str(days)
    return f'=TEXT(TODAY(){offset},"{fmt}")'


def guess_date_format(text: str) -> str:
    """The format ``text`` is written in (``15/03/2027`` -> ``dd/mm/yyyy``), or "" when it is not a date this knows."""
    text = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            if checks.matches_date_format(text, fmt)[0]:
                return fmt
        except ValueError:
            continue
    return ""


def number_in(text: str) -> str:
    """The first number of ``text`` as the engine reads it (``Total: $1,234.50`` -> ``1234.5``), or ""."""
    value = checks.parse_number(text or "")
    return checks.number_text(value) if value is not None else ""


def pattern_of(text: str) -> str:
    """A regular expression that fits ``text`` and its siblings: digit runs become ``\\d+`` (``REF-12345`` -> ``REF-\\d+``)."""
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    return "^" + "".join(r"\d+" if part.isdigit() else re.escape(part) for part in re.split(r"(\d+)", text) if part) + "$"


def field_label(desc: dict) -> str:
    """What a person calls a field: its label, aria-label, placeholder, name or id."""
    for key in ("label", "ariaLabel", "placeholder", "title"):
        text = L.short_text(desc.get(key) or "")
        if text and not checks.looks_like_date_format(text):
            return text
    for key in ("name", "id"):
        value = str(desc.get(key) or "")
        if value and L.stable_id(value):
            return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)          # firstName -> first Name
    return ""


def token_for(label: str, taken: set[str], fallback: str = "VALUE", avoid: set[str] | None = None) -> str:
    """An UPPER_SNAKE variable name for ``label`` not in ``taken`` (upper names): ``First name`` -> ``FIRST_NAME``, then ``FIRST_NAME_2``...
    ``avoid``: texts a cell of the step already holds (its locator ``card``): a Params header equal to a whole cell replaces that cell when the
    test runs (the legacy rule, CONTRACT.md 1.2), so such a name gets ``_VALUE`` (``CARD_VALUE``)."""
    try:
        base = make_token(label)
    except BuildError:
        base = fallback
    base = base[:40].rstrip("_") or fallback
    if base.upper() in {a.upper() for a in avoid or ()}:
        base = f"{base}_VALUE"
    token, n = base, 2
    while token.upper() in taken:
        token, n = f"{base}_{n}", n + 1
    return token


def save_token_for(desc: dict, taken: set[str]) -> str:
    """A name for a value saved from an element: a field's label; else the container's heading + a stable class / the element's short text
    (``$148.20`` in card ``Max`` with class ``price`` -> ``MAX_PRICE``)."""
    if is_field(desc):
        return token_for(field_label(desc) or "value", taken)
    words = []
    heading = L.short_text((desc.get("context") or {}).get("heading") or "")
    if heading:
        words.append(heading)
    classes = L.stable_classes(desc.get("classes") or [])
    name = L.element_name(desc)
    if classes:
        words.append(classes[0])
    elif desc.get("id") and L.stable_id(desc["id"]):
        words.append(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", desc["id"]))
    elif name and len(name.split()) <= 3 and not _NUMBER.search(name):
        words.append(name)
    if not words:
        words.append(L.kind_word(desc) + " text")
    return token_for(" ".join(words), taken, "SAVED_VALUE")


# Check kinds (Q8): id -> (group, label).  The order is the card's.
CHECK_KINDS = (
    ("text_is", "Text", "Text is"), ("text_contains", "Text", "Text contains"),
    ("shown", "Shown or gone", "It shows"), ("gone", "Shown or gone", "It is gone"),
    ("value", "Control state", "Field value"), ("ticked", "Control state", "Ticked"), ("selected", "Control state", "Selected option"),
    ("enabled", "Control state", "Enabled"),
    ("gt", "Numbers & patterns", "Greater than"), ("lt", "Numbers & patterns", "Less than"), ("between", "Numbers & patterns", "Between"),
    ("regex", "Numbers & patterns", "Matches pattern"), ("date_format", "Numbers & patterns", "Date format"),
    ("count", "Numbers & patterns", "Item count"),
    ("list_item", "List", "List shows item N"),
)
WAIT_KINDS = (("wait_shown", "Wait until", "It shows"), ("wait_gone", "Wait until", "It is gone"), ("wait_text", "Wait until", "Its text is"))
SAVE_KINDS = (("save", "Save", "Save as a variable"),)
ALL_KINDS = {k for k, _, _ in CHECK_KINDS + WAIT_KINDS + SAVE_KINDS}


def _shown_text(desc: dict) -> str:
    cur = desc.get("current") or {}
    if desc.get("kind") == "dropdown" and cur.get("selected"):
        return str(cur["selected"])
    if desc.get("kind") in ("field", "textbox"):
        return str(cur.get("value") or "")
    return str(desc.get("text") or "")


def check_kinds(desc: dict, purpose: str = "check", similar: int | None = None) -> list[dict]:
    """The card's choices for an element: ``[{id, group, label, enabled, expected, why}]``, the expected value prefilled from the live page.
    ``similar`` = how many elements like it there are (for Item count)."""
    cur = desc.get("current") or {}
    text = _shown_text(desc)
    kind = desc.get("kind")
    field = is_field(desc)
    interactive = field or kind in ("button", "link")
    number = number_in(text)
    fmt = guess_date_format(text)
    out = []

    def add(kid: str, group: str, label: str, enabled: bool, expected: str, why: str = "") -> None:
        out.append({"id": kid, "group": group, "label": label, "enabled": bool(enabled), "expected": expected if enabled else "",
                    "why": "" if enabled else why})
    if purpose == "wait":
        for kid, group, label in WAIT_KINDS:
            add(kid, group, label, kid != "wait_text" or bool(text), text if kid == "wait_text" else "", "it shows no text")
        return out
    if purpose == "save":
        add("save", "Save", "Save as a variable", True, "")
        return out
    for kid, group, label in CHECK_KINDS:
        if kid in ("text_is", "text_contains"):
            add(kid, group, label, bool(text), text, "it shows no text")
        elif kid in ("shown", "gone"):
            add(kid, group, label, True, "")
        elif kid == "value":
            add(kid, group, label, kind in ("field", "textbox", "dropdown"), str(cur.get("value") or ""), "not a field")
        elif kid == "ticked":
            add(kid, group, label, kind in ("checkbox", "radio"), "Y" if cur.get("checked") else "N", "not a check box or option")
        elif kid == "selected":
            add(kid, group, label, kind == "dropdown", str(cur.get("selected") or ""), "not a dropdown")
        elif kid == "enabled":
            add(kid, group, label, interactive, "N" if cur.get("enabled") is False else "Y", "not a control")
        elif kid in ("gt", "lt"):
            add(kid, group, label, bool(number), number, "no number in its text")
        elif kid == "between":
            add(kid, group, label, bool(number), f"{number};{number}", "no number in its text")
        elif kid == "regex":
            add(kid, group, label, bool(text), pattern_of(text), "it shows no text")
        elif kid == "date_format":
            add(kid, group, label, bool(fmt), fmt, "its text is not a date")
        elif kid == "count":
            add(kid, group, label, similar is not None, str(similar or ""), "nothing like it to count")
        elif kid == "list_item":
            add(kid, group, label, kind in ("element", "item", "text") or desc.get("tag") in ("ul", "ol", "div", "table", "tbody", "section"),
                text.split("\n")[0][:80] if text else "", "not a list")
    return out


def check_step(kind: str, desc: dict, locator: dict, expected: str, *, token: str = "", similar: dict | None = None) -> dict:
    """The step (builder ``Step`` fields) for a check / wait / save of an element.  ``locator`` = the pick's ``Choice.to_json()``;
    ``similar`` = the locator of every element like it (Item count)."""
    if kind not in ALL_KINDS:
        raise BuildError(f"{kind!r} is not a check this card knows.", "check", 400)
    expected = str(expected if expected is not None else "")
    fields: dict[str, Any] = {"findBy": locator.get("findBy") or "", "locator": locator.get("value") or "",
                              "index": locator.get("index") or None, "backups": locator.get("backups") or []}
    prop = "VALUE" if desc.get("kind") in ("field", "textbox") else "INNERTEXT"

    def need(what: str) -> None:
        if not expected.strip():
            raise BuildError(f"Say what {what} to expect.", "expected", 400)
    if kind in ("text_is", "text_contains"):
        need("text")
        fields.update(method="OUTPUT", outputProperty=prop, expected=expected, match="exact" if kind == "text_is" else "contains")
    elif kind == "shown":
        fields.update(method="EXIST")
    elif kind == "gone":
        fields.update(method="NOT_EXIST")
    elif kind == "value":
        fields.update(method="CHECK_VALUE", expected=expected, match="exact")
    elif kind == "ticked":
        fields.update(method="CHECK_CHECKED", expected="Y" if checks.yes_no(expected) is not False else "N")
    elif kind == "selected":
        need("option")
        fields.update(method="CHECK_SELECTED", expected=expected)
    elif kind == "enabled":
        fields.update(method="CHECK_ENABLED", expected="N" if checks.yes_no(expected) is False else "Y")
    elif kind in ("gt", "lt", "between"):
        need("number")
        op = {"gt": "GT", "lt": "LT", "between": "BETWEEN"}[kind]
        try:
            checks.expected_numbers(op, expected)
        except ValueError as err:
            raise BuildError(str(err), "expected", 400) from None
        fields.update(method="CHECK_COMPARE", outputProperty=op, expected=expected)
    elif kind == "regex":
        need("pattern")
        try:
            re.compile(expected)
        except re.error as err:
            raise BuildError(f"That pattern is not a regular expression: {err}", "expected", 400) from None
        fields.update(method="CHECK_REGEX", expected=expected)
    elif kind == "date_format":
        need("date format")
        error = checks.date_format_error(expected)
        if error:
            raise BuildError(error, "expected", 400)
        fields.update(method="CHECK_DATE_FORMAT", expected=expected)
    elif kind == "list_item":
        need("item text")
        fields.update(method="CHECK_LIST_ITEM", outputProperty="1", expected=expected, match="exact")
    elif kind == "count":
        need("count")
        sim = similar or locator
        fields.update(method="CHECK_COUNT", findBy=sim.get("findBy") or fields["findBy"], locator=sim.get("value") or fields["locator"],
                      index=None, backups=[], expected=expected)
    elif kind == "wait_shown":
        fields.update(method="WAIT_UNTIL", outputProperty="SHOWN")
    elif kind == "wait_gone":
        fields.update(method="WAIT_UNTIL", outputProperty="GONE")
    elif kind == "wait_text":
        need("text")
        fields.update(method="WAIT_UNTIL", outputProperty="TEXT", expected=expected, match="contains")
    elif kind == "save":
        if not token:
            raise BuildError("Give the variable a name.", "token", 400)
        fields.update(method="OUTPUT", outputProperty=prop)
    if token:
        token = token.strip().strip("{}").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            raise BuildError("A variable name is letters, digits and _ (such as PLAN_PRICE).", "token", 400)
        if fields["method"] != "OUTPUT":
            raise BuildError("Only a text check or a save can also save the value.", "token", 400)
        fields["saveAs"] = "{" + token + "}"
    return fields


def fingerprint_name(heading: str, path: str, taken: set[str]) -> str:
    base = L.short_text(heading)[:40].strip() or (path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip() or "Home")
    base = base if base.lower().endswith("page") else f"{base} page"
    name, n = base, 2
    while name.upper() in taken:
        name, n = f"{base} {n}", n + 1
    return name


def url_path(url: str) -> str:
    m = re.match(r"^[a-z][a-z0-9+.-]*://[^/?#]*(/[^?#]*)?", url or "", re.I)
    return ((m.group(1) or "/") if m else "").rstrip("/") or "/"


def store_secret(path: Path, key: str, value: str, *, replace: bool = False) -> str:
    """Put ``key=value`` in ``secrets.env`` (a line added, the file created when missing) and load it, so replays see it.  Returns ``same`` when
    it was already there with that value, ``added`` when written, ``differs`` (and writes nothing) when the key holds another value.
    ``replace`` (the Variables tab's "new value" for a secret): a key holding another value gets this one instead (``replaced``); every
    other line of the file stays as it is."""
    if not _SECRET_KEY.match(key):
        raise BuildError(f"{key!r} cannot be a secrets.env key.", "secret", 400)
    if "\n" in value or "\r" in value:
        raise BuildError("A secret cannot hold a line break.", "secret", 400)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    quoted = f'"{value}"' if value != value.strip() else value
    for i, line in enumerate(lines):
        k, sep, v = line.strip().partition("=")
        if sep and k.strip() == key and not line.strip().startswith("#"):
            if v.strip().strip('"').strip("'") == value:
                return "same"
            if not replace:
                return "differs"
            lines[i] = f"{key}={quoted}"
            _write_secrets(path, lines)
            return "replaced"
    _write_secrets(path, lines + [f"{key}={quoted}"])
    return "added"


def _write_secrets(path: Path, lines: list[str]) -> None:
    """Write ``lines`` as secrets.env (through a temporary file, so a crash never leaves half of it) and load it into this process."""
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    load_env_file(path)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The recorder of one build session
# ---------------------------------------------------------------------------------------------------------------------------------------------
class Recorder:
    """Recording state of a ``BuildSession``: on/off, the cursor, where the person is (window + frame), the prompts, a widget in progress.
    Everything it is sent is handled in order, one at a time (``_lock``)."""

    def __init__(self, session: "BuildSession"):
        self.s = session
        self.on = False
        self.cursor: int | None = None               # new steps go after this row (None: after the last step)
        self.count = 0                               # steps recorded since recording was switched on
        self.prompts: list[dict] = []
        self._lock: asyncio.Lock | None = None
        self._page = None                            # where the recorded steps have taken the test: the window...
        self._frame = None                           # ...and the frame (None = the window's page itself)
        self._urls: dict[int, str] = {}              # the last URL each window showed (id(page) -> url)
        self._widget: dict | None = None             # clicks through a calendar, not written yet
        self._cal: dict | None = None                # a calendar opened by a click on anything (not a read-only field): its opener + held clicks
        self._last: dict | None = None               # the last step written (for a suggestion to join a typing step)
        self._version = -1                           # the document version right after the recorder's last write
        self.recorded: list[int] = []                # the rows this recording wrote (kept right as rows move), for the summary
        self._auto_gate: dict | None = None          # the page check added on the last arrival (a redirect right after it retargets it)
        self.summary: dict | None = None             # what the last recording wrote, once it is over (the Build tab shows it and jumps there)

    # -- small helpers -----------------------------------------------------------------------------------------------------------------
    @property
    def lock(self) -> asyncio.Lock:
        assert self._lock is not None, "BuildSession.start makes the recorder's lock"
        return self._lock

    def trusted(self, payload: Any) -> bool:
        """The overlay proves a call is its own with the session's key (a site's script cannot read it)."""
        return isinstance(payload, dict) and isinstance(payload.get("key"), str) and hmac.compare_digest(payload["key"], self.s.key)

    def replaying(self) -> bool:
        task = self.s._task
        return task is not None and not task.done()

    def _test(self) -> str:
        return self.s.test_id

    def _steps(self) -> list[dict]:
        return self.s._steps()

    def _param_rows(self) -> tuple[str | None, list[str], list[Any]]:
        """The test's Params sheet: (its name, headers, the "Building with" row's cells)."""
        sheet = self.s._meta.get("paramSheet") or ""
        if not sheet:
            return None, [], []
        with self.s.doc.lock:
            editor = self.s.doc.editor
            real = next((n for n in editor.sheet_names() if n.upper() == sheet.upper()), None)
            rows = editor.rows(real) if real else []
        if not rows:
            return real, [], []
        headers = [cell_text(h).strip() for h in rows[0]]
        row = self.s.data_row or 2
        cells = rows[row - 1] if 0 < row - 1 < len(rows) else []
        return real, headers, list(cells)

    def _variables_now(self) -> dict[str, str]:
        """Params header -> its value in the "Building with" row (variables a typed value or an expected value can reuse)."""
        _, headers, cells = self._param_rows()
        out = {}
        for i, h in enumerate(headers):
            if h and h.upper() != "BLNEXECUTE":
                out[h] = cell_text(cells[i]).strip() if i < len(cells) and cells[i] is not None else ""
        return out

    def state(self) -> dict:
        return {"on": self.on, "cursor": {"row": self.cursor, "n": self.s._n_of(self.cursor)} if self.cursor else None, "count": self.count,
                "prompts": [self._public(p) for p in self.prompts], "widget": bool(self._widget), "summary": self.summary}

    @staticmethod
    def _public(prompt: dict) -> dict:
        return {k: v for k, v in prompt.items() if not k.startswith("_")}

    def overlay_prompts(self) -> list[dict]:
        return [{k: prompt.get(k) for k in ("id", "kind", "text", "detail", "choices", "ref", "token", "tag")} for prompt in self.prompts[-3:]]

    def label(self) -> str:
        n = self.s._n_of(self.cursor) if self.cursor else None
        total = len(self._steps())
        return f"● Recording · after step {n} of {total}" if n else f"● Recording · {total} steps"

    # -- on / off ----------------------------------------------------------------------------------------------------------------------
    async def start(self, after: int | None = None) -> None:
        if self.s.status == "closed" or self.s._browser is None:
            raise BuildError("The build browser is closed. Open it again.", "closed", 409)
        if self.replaying():
            raise BuildError("A replay is going. Wait for it (or stop it) before recording.", "busy", 409)
        steps = self._steps()
        if after is not None and not any(st["row"] == after for st in steps):
            raise BuildError(f"Row {after} is not a step of {self._test()}.", "step", 400)
        self.cursor = after if after is not None else (steps[-1]["row"] if steps else None)
        self.on, self.count, self._widget, self._last = True, 0, None, None
        self.recorded, self.summary, self._auto_gate = [], None, None
        self.s.mode, self.s.pick_for = "browse", None
        if not steps:
            await self._open_first()
        runner = self.s._runner
        session = runner.session if runner is not None else None
        pages = self.s._open_pages()
        self._page = session.page if session is not None and session.is_open else (pages[-1] if pages else None)
        frame = getattr(session, "_frame", None) if session is not None else None
        self._frame = frame if frame is not None and self._page is not None and frame is not self._page.main_frame else None
        for page in pages:
            self._urls[id(page)] = page.url
        self.s.emit("log", level="info", message=f"recording {self._test()} after step {self.s._n_of(self.cursor) or 'the last'}")
        self.s.touch()
        await self.s.broadcast({"card": None})

    def resync(self) -> None:
        """After a replay: recording carries on from the window and frame the replay left the test in."""
        runner = self.s._runner
        session = runner.session if runner is not None else None
        if not self.on or session is None or not session.is_open:
            return
        self._page = session.page
        frame = getattr(session, "_frame", None)
        self._frame = frame if frame is not None and frame is not self._page.main_frame else None
        for page in self.s._open_pages():
            self._urls[id(page)] = page.url

    async def _open_first(self) -> None:
        """An empty test recorded from the window the build session opened on the Domain: its first step opens the Domain, so the recorded
        test runs on its own (an address typed in the browser's address bar is not recorded)."""
        domain = await asyncio.to_thread(self.s.domain)
        if not domain:
            return
        applied = await self._apply([self._insert_op({"method": "OPEN", "page": "Chrome", "value": "{DOMAIN}"}, None)])
        row = next(a["row"] for a in applied if a.get("op") == "insert_step")
        self.cursor = row
        self.count += 1
        self.recorded.append(row)
        self.s.emit("build_session_step_recorded", test=self._test(), step=self.s._n_of(row), row=row, method="OPEN", name="Open {DOMAIN}",
                    what="open")

    def finish(self) -> None:
        """Recording is over (the pill's Done or Rec, the Build tab's Rec, or the window closed): keep what it wrote, as step numbers now."""
        if not self.on:
            return
        self.on = False
        numbers = {st["row"]: st["n"] for st in self._steps()}
        rows = sorted({r for r in self.recorded if r in numbers})
        self.summary = {"id": uuid.uuid4().hex[:8], "test": self._test(), "count": len(rows), "rows": rows,
                        "first": numbers[rows[0]] if rows else None, "last": numbers[rows[-1]] if rows else None, "at": time.monotonic()}

    def just_finished(self) -> bool:
        return self.summary is not None and time.monotonic() - self.summary["at"] < FINISHED_LABEL_S

    def finished_label(self) -> str:
        n = self.summary["count"] if self.summary else 0
        if not n:
            return "Recording stopped: no steps recorded"
        where = f"step {self.summary['first']}" if n == 1 else f"steps {self.summary['first']}-{self.summary['last']}"
        return f"✓ Recorded {n} step{'s' if n != 1 else ''} ({where})"

    async def stop(self) -> None:
        if not self.on:
            return
        async with self.lock:
            await self._flush_widget()
            self.finish()
        self.s.emit("log", level="info", message=f"recording stopped: {self.count} step{'s' if self.count != 1 else ''} recorded")
        self.s.touch()
        await self.s.broadcast()

    # -- what the overlay sends ---------------------------------------------------------------------------------------------------------
    async def handle(self, source: dict, payload: dict) -> None:
        """A recorded action (``kind: rec``) or a new document (``hello``), from the overlay, in the order they happened."""
        async with self.lock:
            if not self.on or self.replaying() or self.s.status == "closed":
                if payload.get("kind") == "hello" and payload.get("top") and isinstance(source, dict) and source.get("page") is not None:
                    self._urls[id(source["page"])] = str(payload.get("url") or "")
                return
            try:
                if payload.get("kind") == "hello":
                    await self._arrived(source, payload)
                else:
                    await self._action(source, payload)
            except BuildError as err:
                self.s.emit("log", level="warning", message=f"not recorded: {err}")
            except Exception as err:                                      # (the page must never see an error; the Build tab gets it)
                self.s.emit("log", level="warning", message=f"not recorded: {(str(err).splitlines() or [err])[0]}")
            self.s.touch()
            await self.s.broadcast()

    async def _action(self, source: dict, p: dict) -> None:
        what = str(p.get("what") or "")
        frame, page = source.get("frame"), source.get("page")
        desc = L.to_desc(p.get("element"))
        if frame is None or page is None or (what != "back" and not desc):
            return
        if what == "cal-click" and self._widget is not None:
            what = "click"                                             # (a read-only date field's own calendar handling has it)
        if what == "cal-click":
            await self._calendar_click(frame, page, desc, p)
            return
        self._cal = None
        w = self._widget
        if w is not None and time.monotonic() - w["started"] > WIDGET_S:
            await self._flush_widget()
            w = None
        if what == "date-open":
            await self._flush_widget()
            loc = await self._locate(frame, desc, p)
            self._widget = {"field": desc, "loc": loc, "frame": frame, "page": page, "clicks": [], "started": time.monotonic(),
                            "ref": p.get("ref")}
            return
        if what == "click" and w is not None and page is w["page"] and len(w["clicks"]) < WIDGET_CLICKS:
            w["clicks"].append((desc, await self._locate(frame, desc, p)))
            return
        if what == "date-picked" and w is not None and page is w["page"] and (p.get("ref") == w["ref"] or not w["ref"]):
            await self._date_picked(w, str(p.get("value") or ""))
            return
        await self._flush_widget()
        if what == "click":
            if p.get("option") and await self._suggestion(frame, page, desc, p):
                return
            await self._click(frame, page, desc, p)
        elif what == "type":
            await self._typed(frame, page, desc, p, str(p.get("value") or ""), secret=bool(p.get("secret")))
        elif what == "date-picked":
            await self._typed(frame, page, desc, p, str(p.get("value") or ""), secret=False, method="PICK_DATE")
        elif what == "select":
            await self._typed(frame, page, desc, p, str(p.get("value") or ""), secret=False, method="SELECT")
        elif what == "toggle":
            loc = await self._locate(frame, desc, p)
            method = "TICK" if p.get("checked") or desc.get("kind") == "radio" else "UNTICK"
            await self._write(frame, page, {"method": method, **self._loc_fields(loc)}, "toggle")
        elif what == "key":
            loc = await self._locate(frame, desc, p)
            key = re.sub(r"[^A-Z]", "", str(p.get("key") or "ENTER").upper()) or "ENTER"
            await self._write(frame, page, {"method": "SPECIALKEY", "value": "{" + key + "}", **self._loc_fields(loc)}, "key")
        elif what == "back":
            await self._write(None, page, {"method": "BACK"}, "back")

    # -- locating --------------------------------------------------------------------------------------------------------------------------
    async def _locate(self, frame, desc: dict, p: dict) -> dict:
        """The most stable locator for the element: counted in the page as the event happened (``checks``: the page may have navigated away
        since), else here on the live page.  Same choice as a pick (``locators.choose``)."""
        cands = L.candidates(desc)
        seen = {}
        for c in p.get("checks") or []:
            if isinstance(c, dict):
                try:
                    seen[(str(c.get("findBy")), str(c.get("value")))] = (int(c.get("count", 0)), int(c.get("position", -1)))
                except (TypeError, ValueError):
                    continue
        missing = []
        for cand in cands:
            if (cand.findby, cand.value) in seen:
                cand.count, cand.position = seen[(cand.findby, cand.value)]
            else:
                missing.append(cand)
        ref = str(p.get("ref") or "")
        if missing and ref and frame is not None and not frame.is_detached():
            await self.s._check(frame, missing, ref=ref)
        choice = L.choose(cands)
        if choice.primary is None:
            raise BuildError(f"no locator finds only the {L.describe(L.plain_words(desc))}", "locator", 422)
        return choice.to_json()

    @staticmethod
    def _loc_fields(loc: dict) -> dict:
        return {"findBy": loc["findBy"], "locator": loc["value"], "index": loc.get("index") or None, "backups": loc.get("backups") or []}

    # -- where the person is: windows and frames (Q34) -----------------------------------------------------------------------------------
    async def _frame_steps(self, frame, page) -> list[dict]:
        """The switch steps that take the test from where it is (``_page`` / ``_frame``) to ``frame`` of ``page``."""
        steps: list[dict] = []
        pages = [pg for pg in self.s._open_pages() if not pg.is_closed()]
        if page is not self._page:
            if pages and page is pages[0]:
                steps.append({"method": "SWITCHTOMAINWINDOW"})
            else:
                index = pages.index(page) if page in pages else -1
                steps.append({"method": "SWITCHTOWINDOW", "value": "-1" if index in (-1, len(pages) - 1) else str(index)})
            self._page, self._frame = page, None
        target = None if frame is None or frame is page.main_frame else frame
        if target is not self._frame:
            if self._frame is not None:
                steps.append({"method": "SWITCHTODEFAULT"})
            chain = []
            f = target
            while f is not None and f is not page.main_frame:
                chain.insert(0, f)
                f = f.parent_frame
            for f in chain:
                name = f.name
                if name:
                    steps.append({"method": "SWITCHTOFRAME", "value": name})
                else:
                    index = 0
                    try:
                        handle = await f.frame_element()
                        index = await handle.evaluate("e => Array.from(e.ownerDocument.querySelectorAll('iframe, frame')).indexOf(e)")
                    except Exception:
                        pass
                    steps.append({"method": "SWITCHTOFRAME", "index": max(0, int(index))})
            self._frame = target
        return steps

    async def _follow(self, steps: list[dict]) -> None:
        """The replay's own session goes where the recorded switch steps say, so "Run next" carries on in the right window and frame."""
        runner = self.s._runner
        session = runner.session if runner is not None else None
        if session is None or not session.is_open:
            return
        for st in steps:
            try:
                method = st["method"]
                if method == "SWITCHTOMAINWINDOW":
                    session.switch_to_main_window()
                elif method == "SWITCHTOWINDOW":
                    session.switch_to_window(st.get("value") or "-1")
                elif method == "SWITCHTODEFAULT":
                    session.switch_to_default()
                elif method == "SWITCHTOFRAME":
                    step = FrameStep("name", st["value"]) if st.get("value") else FrameStep("index", int(st.get("index") or 0))
                    await session.switch_to_frame(step, 3.0)
            except Exception:
                return

    # -- writing steps ----------------------------------------------------------------------------------------------------------------------
    def _named(self, fields: dict, desc: dict | None) -> dict:
        """The step with a name that says *which* element it acts on, when the builder's own sentence (made from the locator alone) would
        not: a bare ``a`` #425 reads "Click link", the recorder knows it is the "Albania" link.  A sentence the builder can already make
        well stays automatic (it follows variable renames)."""
        if not desc or fields.get("name") or not fields.get("method"):
            return fields
        target = L.descriptive_target(desc)
        if not target:
            return fields
        if describe_target(str(fields.get("locator") or ""), "") not in _GENERIC_TARGETS:
            return fields
        variables = {h.upper() for h in self._variables_now()}
        value = str(fields.get("value") or "")
        name = auto_name(str(fields["method"]), target=target, value=value, expected=str(fields.get("expected") or ""), variables=variables)
        return {**fields, "name": name}

    def _insert_op(self, fields: dict, after: int | None) -> dict:
        op = {"op": "insert_step", "test": self._test(), "step": {k: v for k, v in fields.items() if v not in (None, "", [])}}
        if after is not None:
            op["after"] = after
        return op

    async def _apply(self, ops: list[dict]) -> list[dict]:
        applied = await asyncio.to_thread(self.s.doc.apply, ops, None)
        self._version = self.s.doc.version
        return applied

    def _shift(self, at: int, by: int = 1) -> None:
        """Rows at or below ``at`` moved down by ``by`` (a row was inserted there): keep what points at them right."""
        def moved(row):
            return row + by if isinstance(row, int) and row >= at else row
        self.cursor = moved(self.cursor)
        self.recorded = [moved(r) for r in self.recorded]
        if self._auto_gate is not None:
            self._auto_gate["row"] = moved(self._auto_gate["row"])
        for p in self.prompts:
            p["row"] = moved(p.get("row"))
            p["_after"] = moved(p.get("_after"))
        if self._last is not None:
            self._last["row"] = moved(self._last.get("row"))

    async def _write(self, frame, page, fields: dict, what: str, *, extra_ops: list[dict] | None = None, prompt: dict | None = None,
                     desc: dict | None = None) -> int:
        """Insert the step (after its switch steps) at the cursor: one edit, one undo step."""
        switches = await self._frame_steps(frame, page) if page is not None else []
        ops = list(extra_ops or [])
        after = self.cursor
        for st in switches:
            ops.append(self._insert_op(st, after))
            after = None if after is None else after + 1
        ops.append(self._insert_op(self._named(fields, desc), after))
        applied = await self._apply(ops)
        rows = [a["row"] for a in applied if a.get("op") == "insert_step"]
        row = rows[-1]
        for r in rows:
            self._shift(r)
        self.recorded.extend(rows)
        self.cursor = row
        self.count += len(rows)
        await self._follow(switches)
        await self._advance(row)
        n = self.s._n_of(row)
        for r in rows:
            step = next((st for st in self._steps() if st["row"] == r), None)
            self.s.emit("build_session_step_recorded", test=self._test(), step=self.s._n_of(r), row=r, method=step["method"] if step else "",
                        name=(step["name"] or step["autoName"]) if step else "", what=what if r == row else "switch")
        self._last = {"row": row, "what": what, "fields": dict(fields), "at": time.monotonic(), "page": page, "frame": frame, "desc": desc,
                      "version": self._version}
        if prompt is not None:
            prompt.update(row=row, n=n, _version=self._version, _ops=ops)
            self._add_prompt(prompt)
        return row

    async def _advance(self, row: int) -> None:
        """The window is now past the recorded step: the replay carries on after it, and it does not count as an earlier step that changed."""
        s = self.s
        if s._runner is None:
            return
        s.cursor_row, s.next_row = row, row + 1
        try:
            s._prefix = await asyncio.to_thread(s._signature, row)
        except BuildError:
            s._prefix = ""
        s._stale = None

    def _add_prompt(self, prompt: dict) -> None:
        prompt.setdefault("id", uuid.uuid4().hex[:10])
        self.prompts.append(prompt)
        del self.prompts[:-MAX_PROMPTS]

    # -- actions ------------------------------------------------------------------------------------------------------------------------------
    async def _click(self, frame, page, desc: dict, p: dict) -> None:
        loc = await self._locate(frame, desc, p)
        fields = {"method": "CLICK", **self._loc_fields(loc)}
        name = L.element_name(desc)
        prompt = None
        if name and SIDE_EFFECT_WORDS.search(name):
            fields["sideEffects"] = True                                    # Q13: replays will ask before running it again
            prompt = {"kind": "side", "text": f"“{name}” looks like it has real consequences: flagged “has side effects”.",
                      "detail": "Replays stop and ask before it; production blocks it.", "choices": ["unflag", "dismiss"]}
        await self._write(frame, page, fields, "click", prompt=prompt, desc=desc)

    async def _typed(self, frame, page, desc: dict, p: dict, value: str, *, secret: bool, method: str = "", loc: dict | None = None) -> None:
        """Typing (Q7), a choice in a dropdown, a date: the value becomes a variable (a secret for a password field)."""
        loc = loc or await self._locate(frame, desc, p)
        if not method:
            method = "PICK_DATE" if is_date_field(desc) and looks_like_date(value) else ("CLEAR" if value == "" else "SET")
        fields = {"method": method, **self._loc_fields(loc)}
        if method == "CLEAR":
            await self._write(frame, page, fields, "type", desc=desc)
            return
        label = field_label(desc) or ("password" if secret else "value")
        if secret:
            token, how = await asyncio.to_thread(self._secret_for, label, value)
            fields["value"] = "{SECRET:" + token + "}"
            ops = [{"op": "set_variable", "token": token, "label": label, "secret": True}]
            where = f"RR_SECRET_{self.s.environment}_{token}" if self.s.environment else f"RR_SECRET_{token}"
            prompt = {"kind": "secret", "token": token, "text": f"Password field → secret variable {token}.",
                      "detail": (f"Stored in secrets.env as {where} ({self.s.environment or 'every environment'} only); shown as ••••."
                                 if how != "same" else f"secrets.env already holds it as {where}; shown as ••••."), "choices": ["dismiss"],
                      "ref": p.get("ref")}
            await self._write(frame, page, fields, "type", extra_ops=ops, prompt=prompt, desc=desc)
            return
        sheet, headers, _ = self._param_rows()
        dynamic = relative_date(value) if method == "PICK_DATE" else ""          # Q51: "5 days from today", not the day it was recorded on
        if not sheet:
            fields["value"] = dynamic or value
            await self._write(frame, page, fields, "type", desc=desc)
            return
        now = self._variables_now()
        reuse = next((h for h, v in now.items() if v == value and value != ""), None) if not dynamic else None
        ops: list[dict] = []
        if reuse:
            token, tag = reuse, "reused"
            detail = f"{sheet} row {self.s.data_row} already holds “{value}”, so the variable {reuse} is used."
        else:
            avoid = {str(v) for v in (loc.get("value"), desc.get("id"), desc.get("name"), loc.get("findBy")) if v}
            token, tag = token_for(label, {h.upper() for h in headers}, avoid=avoid), "new"
            ops = [{"op": "add_variable", "token": token, "label": label, "sheet": sheet, "value": dynamic or value}]
            detail = (f"New variable {token} in {sheet}: the date you picked ({value}) is kept as today plus/minus days ({dynamic}), so it stays in the "
                      "future whenever the test runs. Choose “fixed” to keep exactly that day." if dynamic else
                      f"New variable {token} in {sheet}, “{value}” in each data row: change a row's value to try other data.")
        fields["value"] = "{" + token + "}"
        prompt = {"kind": "variable", "token": token, "tag": tag, "text": f"You typed “{value}”: kept as the variable {{{token}}}.",
                  "detail": detail, "choices": ["keep", "fixed", "rename"], "ref": p.get("ref"), "_value": value, "_cell": dynamic or value, "_label": label}
        await self._write(frame, page, fields, "type", extra_ops=ops, prompt=prompt, desc=desc)

    def _secret_for(self, label: str, value: str) -> tuple[str, str]:
        """A secret variable for ``value``: an existing one when secrets.env already holds this value, else a new name (never another value
        overwritten).  Returns (token, "same" | "added")."""
        env = (self.s.environment or "").upper()
        path = self.s.cfg.base_dir / "secrets.env"
        load_env_file(path)
        base = token_for(label, set(), "PASSWORD")
        token, n = base, 2
        while n < 50:
            key = f"RR_SECRET_{env}_{token}" if env else f"RR_SECRET_{token}"
            held = secret_value(token, env)
            if held == value:
                return token, "same"
            if held is None and store_secret(path, key, value) == "added":
                return token, "added"
            token, n = f"{base}_{n}", n + 1
        raise BuildError("secrets.env already has too many secrets with that name.", "secret", 409)

    async def _suggestion(self, frame, page, desc: dict, p: dict) -> bool:
        """A click on a suggestion right after typing in a field: the typing step becomes one CHOOSE_SUGGESTION step (Q51)."""
        last = self._last
        if (last is None or last["what"] != "type" or last["fields"].get("method") != "SET" or page is not last["page"]
                or time.monotonic() - last["at"] > SUGGESTION_S or self.s.doc.version != self._version):
            return False
        text = L.short_text(desc.get("text") or L.element_name(desc))
        if not text:
            return False
        click = self._loc_fields(await self._locate(frame, desc, p))
        await self._apply([{"op": "update_step", "test": self._test(), "row": last["row"],
                            "set": {"method": "CHOOSE_SUGGESTION", "expected": text}}])
        last["fields"] = {**last["fields"], "method": "CHOOSE_SUGGESTION", "expected": text}
        last["what"] = "suggestion"
        self.s.emit("build_session_step_recorded", test=self._test(), step=self.s._n_of(last["row"]), row=last["row"],
                    method="CHOOSE_SUGGESTION", name=f"choose {text}", what="suggestion")
        self._add_prompt({"kind": "widget", "widget": "suggestion", "row": last["row"], "n": self.s._n_of(last["row"]),
                          "text": f"2 steps became one: choose “{text}” from the suggestions.", "detail": "Typing, then a click on the suggestion.",
                          "choices": ["raw", "dismiss"], "_raw": [{"method": "CLICK", **click}], "_version": self._version})
        return True

    async def _date_picked(self, w: dict, value: str) -> None:
        """The calendar's clicks set the field: one PICK_DATE step instead (Q51), its date a variable like typed text."""
        self._widget = None
        if not looks_like_date(value):
            self._widget = w
            await self._flush_widget()
            return
        raw = [{"method": "CLICK", **self._loc_fields(w["loc"])}] + [{"method": "CLICK", **self._loc_fields(loc)} for _, loc in w["clicks"]]
        await self._typed(w["frame"], w["page"], w["field"], {"ref": w["ref"]}, value, secret=False, method="PICK_DATE", loc=w["loc"])
        prompt = self.prompts[-1] if self.prompts and self.prompts[-1].get("row") == self.cursor else None
        name = L.element_name(w["field"]) or "the date field"
        widget = {"kind": "widget", "widget": "date", "row": self.cursor, "n": self.s._n_of(self.cursor),
                  "text": f"{len(raw)} clicks became one step: pick date {('{' + prompt['token'] + '}') if prompt else value} in {name}.",
                  "detail": "The calendar's clicks are not kept (the engine opens the calendar itself).", "choices": ["raw", "dismiss"],
                  "_raw": raw, "_version": self._version}
        self._add_prompt(widget)

    async def _calendar_click(self, frame, page, desc: dict, p: dict) -> None:
        """A click inside a calendar that something other than a read-only field opened (a "Depart" box, an icon).  The click that opened it was
        already written as a CLICK; the month buttons are held back, and the click on a day turns the opener into one PICK_DATE step with the
        day as a date variable (a second day in the same calendar, such as a return date, is another PICK_DATE on the same opener)."""
        cal = self._cal
        last = self._last
        if cal is None:
            if last is None or last.get("what") != "click" or last.get("page") is not page or last.get("desc") is None:
                await self._click(frame, page, desc, p)                 # nothing opened it that we saw: written as it was
                return
            cal = self._cal = {"row": last["row"], "fields": dict(last["fields"]), "desc": last["desc"], "frame": last["frame"], "page": page,
                               "clicks": [], "opened": True}
        loc = await self._locate(frame, desc, p)
        cal["clicks"].append((desc, loc))
        day = str(p.get("date") or "")
        if not day:
            return                                                       # (Next month, Previous month...)
        try:
            picked = checks.parse_date(day)
        except ValueError:
            return
        value = f"{picked:%d/%m/%Y}"
        fields = cal["fields"]
        opener = {"findBy": fields.get("findBy"), "value": fields.get("locator"), "index": fields.get("index"), "backups": fields.get("backups") or []}
        raw = [{"method": "CLICK", **{k: v for k, v in fields.items() if k in ("findBy", "locator", "index", "backups")}}] \
            + [{"method": "CLICK", **self._loc_fields(loc)} for _, loc in cal["clicks"]]
        if cal["opened"]:                                                # the opener's own CLICK step goes: PICK_DATE opens the calendar itself
            row = cal["row"]
            await self._apply([{"op": "delete_steps", "test": self._test(), "rows": [row]}])
            self._shift(row + 1, -1)
            self.recorded = [r for r in self.recorded if r != row]
            self.count -= 1
            if self.cursor == row:
                self.cursor = row - 1 if row > 2 else None
            cal["opened"] = False
        cal["clicks"] = []
        await self._typed(cal["frame"], page, cal["desc"], {"ref": None}, value, secret=False, method="PICK_DATE", loc=opener)
        prompt = self.prompts[-1] if self.prompts and self.prompts[-1].get("row") == self.cursor else None
        name = L.element_name(cal["desc"]) or L.descriptive_target(cal["desc"]) or "the date field"
        self._add_prompt({"kind": "widget", "widget": "date", "row": self.cursor, "n": self.s._n_of(self.cursor),
                          "text": f"{len(raw)} clicks became one step: pick date {('{' + prompt['token'] + '}') if prompt else value} in {name}.",
                          "detail": "The calendar's clicks are not kept (the engine opens the calendar itself).", "choices": ["raw", "dismiss"],
                          "_raw": raw, "_version": self._version})

    async def _flush_widget(self) -> None:
        """A calendar that never set its field (or was left): its clicks are written as they were."""
        w, self._widget = self._widget, None
        if w is None:
            return
        for desc, loc in [(w["field"], w["loc"])] + w["clicks"]:
            await self._write(w["frame"], w["page"], {"method": "CLICK", **self._loc_fields(loc)}, "click", desc=desc)

    # -- a new page (Q34 Back, Q53 fingerprints) ------------------------------------------------------------------------------------------
    async def _arrived(self, source: dict, p: dict) -> None:
        page, frame = source.get("page"), source.get("frame")
        if page is None or not p.get("top"):
            return
        url = str(p.get("url") or "")
        prev = self._urls.get(id(page))
        self._urls[id(page)] = url
        await self._flush_widget()
        if p.get("nav") == "back_forward" and prev is not None:
            await self._write(None, page, {"method": "BACK"}, "back")
            return
        if prev is not None and url_path(prev) == url_path(url):
            return
        if prev is None:
            return                          # a window's first page (the one recording started on, or a new window): no page check here - a new
                                            # window's check would land before its SWITCHTOWINDOW step and look at the wrong window
        await self._propose_fingerprint(frame, page, url, p.get("heading") if isinstance(p.get("heading"), dict) else None)

    async def _propose_fingerprint(self, frame, page, url: str, heading: dict | None) -> None:
        """A recorded action loaded another page: the test gets a check that it arrived there (ASSERT_PAGE with the page's fingerprint: URL
        part + main heading, saved in ``_rr_fingerprints``, or the one already known for that URL) and the steps from here on go on a new page
        (block) named after it.  Added straight away, as an ordinary edit (Undo, or "Remove the check" on the card beside it, takes it back);
        a redirect straight after it (no action recorded in between) moves that same check to the page it ended on instead of adding another."""
        with self.s.doc.lock:
            existing = read_fingerprints(self.s.doc.editor)
        path = url_path(url)
        known = next((f for f in existing if f.get("urlContains") and re.sub(r"\{[^}]*\}", "", f["urlContains"]) in url), None)
        landmark, text = "", ""
        if heading and heading.get("element"):
            desc = L.to_desc(heading["element"])
            text = L.short_text(desc.get("text") or "")
            try:
                loc = await self._locate(frame, desc, heading)
                landmark = self._landmark(loc)
            except BuildError:
                landmark = ""
        if known is not None:
            prompt = {"kind": "gate_added", "exists": True, "name": known["name"], "urlContains": known.get("urlContains") or "",
                      "landmark": known.get("landmark") or "", "landmarkText": known.get("landmarkText") or ""}
        else:
            name = fingerprint_name(text, path, {f["name"].upper() for f in existing})
            prompt = {"kind": "gate_added", "exists": False, "name": name, "urlContains": path, "landmark": landmark, "landmarkText": text}
        again = self._auto_gate
        if again is not None and again["count"] == self.count and self._step_is(again["row"], "ASSERT_PAGE"):
            await self._retarget_gate(again, prompt)
            return
        after = self.cursor
        prompt.update(row=after, n=self.s._n_of(after) if after else None, _after=after)
        applied = await self._gate(prompt, {}, new_block=True)
        row = next(a["row"] for a in reversed(applied) if a.get("op") == "insert_step")
        self._auto_gate = {"row": row, "count": self.count, "prompt": prompt}
        await self._advance(row)                    # the window is on that page already: the check counts as done, and starting the new page
                                                    # (it writes the page column of the steps above) is not an "earlier step that changed"
        self._gate_prompt(prompt, row)

    def _gate_prompt(self, prompt: dict, row: int) -> None:
        name = prompt["name"]
        n = self.s._n_of(row)
        detail = (f"URL contains {prompt['urlContains']}" + (f" AND heading “{prompt['landmarkText']}” shows." if prompt.get("landmark") else ".")
                  if not prompt.get("exists") else "The page's fingerprint was already saved.")
        prompt.update(row=row, n=n, choices=["dismiss", "edit", "ungate"], detail=detail,
                      text=f"New page: step {n} checks the test arrived at “{name}”, and the steps after it are on the page “{name}”.")
        self.prompts = [p for p in self.prompts if p is not prompt]
        self._add_prompt(prompt)

    def _step_is(self, row: int | None, method: str) -> bool:
        step = next((st for st in self._steps() if st["row"] == row), None)
        return step is not None and step["method"] == method

    async def _retarget_gate(self, gate: dict, prompt: dict) -> None:
        """A redirect right after the last page check: that check (and its page's name) now follow the page the redirect ended on."""
        name = prompt["name"]
        ops = [] if prompt.get("exists") else [{"op": "set_fingerprint", "name": name, "urlContains": prompt["urlContains"],
                                                "landmark": prompt.get("landmark") or "", "landmarkText": prompt.get("landmarkText") or ""}]
        ops.append({"op": "update_step", "test": self._test(), "row": gate["row"], "set": {"value": name, "block": name}})
        await self._apply(ops)
        await self._advance(gate["row"])
        old = gate["prompt"]
        old.clear()
        old.update(prompt)
        self._gate_prompt(old, gate["row"])

    async def _ungate(self, prompt: dict) -> list[dict]:
        """"Remove the check" on an automatic page check: the ASSERT_PAGE step goes (its fingerprint stays saved for later)."""
        self._expect(prompt["row"], "ASSERT_PAGE")
        row = prompt["row"]
        applied = await self._apply([{"op": "delete_steps", "test": self._test(), "rows": [row]}])
        self._shift(row + 1, -1)
        self.recorded = [r for r in self.recorded if r != row]
        if self.cursor == row:
            self.cursor = row - 1 if row > 2 else None
        if self._auto_gate is not None and self._auto_gate["row"] == row:
            self._auto_gate = None
        s = self.s
        if s._runner is not None and s.cursor_row is not None and s.cursor_row >= row:
            await self._advance(s.cursor_row - 1 if s.cursor_row > row else max(row - 1, 2))
        return applied

    async def _regate(self, prompt: dict, fields: dict) -> list[dict]:
        """The fingerprint of an automatic page check, edited on its card: saved under its (new) name, and the check follows the name."""
        self._expect(prompt["row"], "ASSERT_PAGE")
        name = str(fields.get("name") or prompt["name"]).strip()
        if not name:
            raise BuildError("A page fingerprint needs a name.", "fingerprint", 400)
        ops = [{"op": "set_fingerprint", "name": name, "urlContains": str(fields.get("urlContains", prompt.get("urlContains")) or ""),
                "landmark": str(fields.get("landmark", prompt.get("landmark")) or ""),
                "landmarkText": str(fields.get("landmarkText", prompt.get("landmarkText")) or ""),
                **({"rename": prompt["name"]} if name.upper() != prompt["name"].upper() else {})}]
        if name != prompt["name"]:
            ops.append({"op": "update_step", "test": self._test(), "row": prompt["row"], "set": {"value": name}})
        applied = await self._apply(ops)
        s = self.s
        if s._runner is not None and s.cursor_row is not None and s.cursor_row >= prompt["row"]:
            await self._advance(s.cursor_row)       # (only the check's name changed: the window is where it was)
        return applied

    @staticmethod
    def _landmark(loc: dict) -> str:
        """A locator in ``_rr_fingerprints``'s Landmark syntax (``id=``, ``css=``, ``xpath=``)."""
        kind = {"BY_ID": "id", "BY_CSSSELECTOR": "css", "BY_XPATH": "xpath"}.get(loc.get("findBy"), "css")
        value = loc.get("value") or ""
        index = loc.get("index") or 0
        if index and kind == "xpath":
            return f"xpath=({value})[{index + 1}]"
        if index:
            return f"css={value} >> nth={index}"
        return f"{kind}={value}"

    # -- answering a prompt ------------------------------------------------------------------------------------------------------------------
    async def answer(self, prompt_id: str, choice: str, *, token: str = "", fields: dict | None = None) -> list[dict]:
        async with self.lock:
            prompt = next((p for p in self.prompts if p["id"] == prompt_id), None)
            if prompt is None:
                raise BuildError("That question has gone (answered already, or too old).", "prompt", 409)
            allowed = prompt.get("choices", []) + ["dismiss", "keep"] + (["regate"] if "edit" in prompt.get("choices", []) else [])
            if choice not in allowed:
                raise BuildError(f"{choice!r} is not an answer to that question.", "prompt", 400)
            applied: list[dict] = []
            if choice in ("fixed", "rename"):
                applied = await self._revise_variable(prompt, choice, token)
            elif choice == "raw":
                applied = await self._keep_raw(prompt)
            elif choice == "gate":
                applied = await self._gate(prompt, fields or {})
            elif choice == "ungate":
                applied = await self._ungate(prompt)
            elif choice == "regate" and prompt.get("kind") == "gate_added":
                applied = await self._regate(prompt, fields or {})
            elif choice == "unflag":
                self._expect(prompt["row"], "CLICK")
                applied = await self._apply([{"op": "update_step", "test": self._test(), "row": prompt["row"], "set": {"sideEffects": False}}])
            self.prompts = [p for p in self.prompts if p["id"] != prompt_id]
            self.s.touch()
        await self.s.broadcast()
        return applied

    def _expect(self, row: int, method: str) -> None:
        """The prompt's step must still be at its row (edits since may have moved it): else the Build tab's editor is the place to change it."""
        step = next((st for st in self._steps() if st["row"] == row), None)
        if step is None or step["method"] != method:
            raise BuildError("That step has moved or changed since: change it in the editor.", "prompt", 409)

    def _latest(self, prompt: dict) -> bool:
        """Is the edit that wrote the prompt's step still the last edit of the workbook (then it can be taken back cleanly)?"""
        return prompt.get("_version") == self.s.doc.version == self._version

    async def _revise_variable(self, prompt: dict, choice: str, token: str) -> list[dict]:
        if prompt.get("kind") != "variable":
            raise BuildError("Only a typed value can be kept as fixed text or renamed.", "prompt", 400)
        value = prompt["_value"]
        if choice == "rename":
            token = token.strip().strip("{}").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
                raise BuildError("A variable name is letters, digits and _ (such as FIRST_NAME).", "token", 400)
        sheet, headers, _ = self._param_rows()
        header = next((h for h in headers if token and h.upper() == token.upper()), None)
        new_value = value if choice == "fixed" else "{" + (header or token) + "}"
        add = [] if choice == "fixed" or header else [{"op": "add_variable", "token": token, "label": prompt["_label"], "sheet": sheet,
                                                         "value": prompt.get("_cell", value)}]
        if self._latest(prompt):
            # nothing else changed since: take the recorded edit back and write it again the new way (no unused column is left behind)
            await asyncio.to_thread(self.s.doc.undo)
            ops = [op for op in prompt["_ops"] if op.get("op") != "add_variable"]
            ops[-1] = {**ops[-1], "step": {**ops[-1]["step"], "value": new_value}}
            applied = await self._apply(add + ops)
            row = applied[-1]["row"]
            if self._last is not None and self._last.get("row") == prompt["row"]:
                self._last.update(row=row, fields=ops[-1]["step"], version=self._version)
            prompt["row"] = row
        else:
            self._expect(prompt["row"], prompt["_ops"][-1]["step"]["method"])
            applied = await self._apply(add + [{"op": "update_step", "test": self._test(), "row": prompt["row"], "set": {"value": new_value}}])
        return applied

    async def _keep_raw(self, prompt: dict) -> list[dict]:
        raw = prompt.get("_raw") or []
        row = prompt["row"]
        self._expect(row, "CHOOSE_SUGGESTION" if prompt.get("widget") == "suggestion" else "PICK_DATE")
        if prompt.get("widget") == "suggestion":
            ops = [{"op": "update_step", "test": self._test(), "row": row, "set": {"method": "SET", "expected": ""}},
                   self._insert_op(raw[0], row)]
            applied = await self._apply(ops)
            self._shift(row + 1)
            if self.cursor == row:
                self.cursor = row + 1
            return applied
        # a date: the PICK_DATE step goes, the calendar's clicks come back in its place
        ops = [{"op": "delete_steps", "test": self._test(), "rows": [row]}]
        after = row - 1
        for r in raw:
            ops.append(self._insert_op(r, after))
            after += 1
        applied = await self._apply(ops)
        self._shift(row + 1, len(raw) - 1)
        if self.cursor == row:
            self.cursor = row + len(raw) - 1
        return applied

    async def _gate(self, prompt: dict, fields: dict, *, new_block: bool = False) -> list[dict]:
        name = str(fields.get("name") or prompt["name"]).strip()
        if not name:
            raise BuildError("A page fingerprint needs a name.", "fingerprint", 400)
        ops = []
        if not prompt.get("exists") or fields:
            ops.append({"op": "set_fingerprint", "name": name,
                        "urlContains": str(fields.get("urlContains", prompt.get("urlContains")) or ""),
                        "landmark": str(fields.get("landmark", prompt.get("landmark")) or ""),
                        "landmarkText": str(fields.get("landmarkText", prompt.get("landmarkText")) or ""),
                        **({"rename": prompt["name"]} if prompt.get("exists") and name.upper() != prompt["name"].upper() else {})})
        after = prompt.get("_after")
        ops.append(self._insert_op({"method": "ASSERT_PAGE", "value": name, **({"block": name} if new_block else {})}, after))
        applied = await self._apply(ops)
        row = applied[-1]["row"]
        self._shift(row)
        if self.on:
            self.recorded.append(row)
        if self.cursor is not None and after is not None and self.cursor == after:
            self.cursor = row
        self.s.emit("build_session_step_recorded", test=self._test(), step=self.s._n_of(row), row=row, method="ASSERT_PAGE",
                    name=f"Arrived at {name}", what="gate")
        return applied

    # -- Check this / Save this / Wait until (Q8, Q41) ------------------------------------------------------------------------------------
    def card(self, pick: dict) -> dict:
        """The card beside an element picked in Check / Save / Wait mode (and in the Build tab's panel)."""
        desc = pick.get("desc") or {}
        purpose = pick.get("purpose") or "check"
        similar = pick.get("similar") or {}
        kinds = check_kinds(desc, purpose, similar.get("matches"))
        chosen = next((k["id"] for k in kinds if k["enabled"]), "")
        now = self._variables_now()
        text = _shown_text(desc)
        variables = [{"token": h, "value": v} for h, v in now.items() if v and v in {k["expected"] for k in kinds}]
        taken = {h.upper() for h in now}
        n = self._next_n()
        title = {"check": "Check this", "save": "Save this", "wait": "Wait until"}[purpose]
        return {"id": uuid.uuid4().hex[:8], "title": f"{title}: {pick.get('text', '')}", "ok": bool(pick.get("ok")),
                "lines": [] if pick.get("ok") else ["No locator finds only this element. Pick the element around it."],
                "form": {"purpose": purpose, "kinds": kinds, "chosen": chosen, "variables": variables,
                         "token": save_token_for(desc, taken) if purpose == "save" else "", "text": text[:200], "n": n}}

    def _next_n(self) -> int:
        row = self._after()
        steps = self._steps()
        if row is None:
            return len(steps) + 1
        n = self.s._n_of(row)
        return (n or len(steps)) + 1

    def _after(self) -> int | None:
        """Where a check goes: after the recorder's cursor while recording, else after the step it was picked for / the last step."""
        if self.on and self.cursor:
            return self.cursor
        pick = self.s.pick or {}
        if pick.get("for"):
            return pick["for"]
        steps = self._steps()
        return steps[-1]["row"] if steps else None

    async def add_check(self, kind: str, expected: str = "", token: str = "", after: int | None = None) -> list[dict]:
        pick = self.s.pick
        if not pick or not pick.get("ok"):
            raise BuildError("Pick an element first (Check, Save or Wait until, then click it on the page).", "pick", 409)
        similar = pick.get("similar")
        if kind == "count" and not similar:
            raise BuildError("Nothing like this element could be counted on the page.", "check", 422)
        fields = check_step(kind, pick["desc"], pick["locator"], expected, token=token, similar=similar)
        async with self.lock:
            if after is None and self.on:
                frame = self.s._picked_frame
                page = frame.page if frame is not None and not frame.is_detached() else None
                row = await self._write(frame, page, fields, kind)
            else:
                at = after if after is not None else self._after()
                applied = await self._apply([self._insert_op(fields, at)])
                row = applied[-1]["row"]
                self._shift(row)
                self.s.emit("build_session_step_recorded", test=self._test(), step=self.s._n_of(row), row=row, method=fields["method"],
                            name=kind, what=kind)
            if self.s.pick is pick:
                self.s.pick = {**pick, "for": row, "forN": self.s._n_of(row), "added": {"row": row, "n": self.s._n_of(row), "kind": kind}}
            self.s.touch()
        await self.s.broadcast({"card": None})
        return [{"op": "insert_step", "test": self._test(), "row": row}]

    async def similar(self, frame, desc: dict) -> dict | None:
        """Every element like the picked one (same tag and stable classes; Item count): ``{findBy, value, matches}``."""
        tag = str(desc.get("tag") or "").lower()
        classes = L.stable_classes(desc.get("classes") or [])
        if not tag:
            return None
        value = tag + "".join("." + L._css_ident(c) for c in classes)
        cand = L.Candidate("BY_CSSSELECTOR", value, "position", index_needed=True)
        await self.s._check(frame, [cand])
        return {"findBy": "BY_CSSSELECTOR", "value": value, "matches": max(cand.count, 0)} if cand.count > 0 else None
