"""The plain-logic side of the new check and widget steps (CONTRACT.md 1.3, P07): numbers read from a page, comparison operators, date formats,
Y/N cells, the dates a ``PICK_DATE`` step is given.  No browser here, so all of it is tested fast (``tests/test_checks.py``); the handlers that read
the page are in ``engine/actions.py``.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from ..workbook.sheet import cell_text

OPERATORS = {"GT": ">", "GE": ">=", "LT": "<", "LE": "<=", "EQ": "=", "NE": "!=", "BETWEEN": "between"}
_SYMBOLS = {">": "GT", ">=": "GE", "<": "LT", "<=": "LE", "=": "EQ", "==": "EQ", "!=": "NE", "<>": "NE"}

# A number as a page shows it: "$1,234.50", "-12", "1 234,5" is not supported (a comma is a thousands separator, as on the sites under test).
_NUMBER = re.compile(r"[-−]?\s?\d[\d,]*(?:\.\d+)?|[-−]?\.\d+")


def operator_of(text: str, default: str = "EQ") -> str:
    """``Output_Property`` of CHECK_COMPARE / CHECK_COUNT as an operator name (``GT``...); symbols (``>=``) work too.  ValueError when unknown."""
    raw = (text or "").strip().upper()
    if not raw:
        return default
    if raw in OPERATORS:
        return raw
    if raw in _SYMBOLS:
        return _SYMBOLS[raw]
    raise ValueError(f"{text!r} is not a comparison: use GT, GE, LT, LE, EQ, NE or BETWEEN")


def parse_number(text: str) -> float | None:
    """The first number in ``text`` ("Total: $1,234.50" -> 1234.5), or None when there is none."""
    m = _NUMBER.search(text or "")
    if m is None:
        return None
    raw = m.group(0).replace("−", "-").replace(",", "").replace(" ", "")
    try:
        return float(raw)
    except ValueError:
        return None


def expected_numbers(op: str, expected: Any) -> tuple[float, float | None]:
    """The number(s) a comparison is made against: ``a`` or, for BETWEEN, ``a;b``.  ValueError when they are not numbers."""
    text = cell_text(expected).strip()
    if op == "BETWEEN":
        parts = [p for p in re.split(r"\s*[;|]\s*", text) if p.strip()]
        if len(parts) != 2:
            raise ValueError(f"BETWEEN needs two numbers in Expected_Value, as 'low;high' (it is {text!r})")
        low, high = parse_number(parts[0]), parse_number(parts[1])
        if low is None or high is None:
            raise ValueError(f"BETWEEN needs two numbers in Expected_Value, as 'low;high' (it is {text!r})")
        return (low, high) if low <= high else (high, low)
    number = parse_number(text)
    if number is None:
        raise ValueError(f"Expected_Value must be a number to compare with (it is {text!r})")
    return number, None


def compare(op: str, actual: float, low: float, high: float | None = None) -> bool:
    if op == "BETWEEN":
        return low <= actual <= (high if high is not None else low)
    return {"GT": actual > low, "GE": actual >= low, "LT": actual < low, "LE": actual <= low,
            "EQ": actual == low, "NE": actual != low}[op]


def describe(op: str, low: float, high: float | None = None) -> str:
    """``> 20`` / ``between 1 and 5``, for notes."""
    if op == "BETWEEN":
        return f"between {number_text(low)} and {number_text(high if high is not None else low)}"
    return f"{OPERATORS[op]} {number_text(low)}"


def number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def yes_no(value: Any) -> bool | None:
    """``Y``/``N`` (and yes/no, true/false, 1/0) -> bool; None when the cell says neither."""
    text = cell_text(value).strip().upper()
    if text in ("Y", "YES", "TRUE", "1", "ON"):
        return True
    if text in ("N", "NO", "FALSE", "0", "OFF"):
        return False
    return None


# -- date formats ------------------------------------------------------------------------------------------------------------------------------
# Excel-style tokens (case does not matter): yyyy yy mmmm mmm mm m dd d, and for times hh h nn ss (mm right after hh / before ss = minutes).
_TOKENS = re.compile(r"yyyy|yy|mmmm|mmm|mm|m|dd|d|hh|h|nn|ss|am/pm", re.I)
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def _format_parts(fmt: str) -> list[tuple[str, str]]:
    """``dd/mm/yyyy`` -> [("tok","dd"), ("lit","/"), ...], with minutes told apart from months."""
    parts: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKENS.finditer(fmt):
        if m.start() > pos:
            parts.append(("lit", fmt[pos:m.start()]))
        parts.append(("tok", m.group(0).lower()))
        pos = m.end()
    if pos < len(fmt):
        parts.append(("lit", fmt[pos:]))
    toks = [i for i, (k, _) in enumerate(parts) if k == "tok"]
    for n, i in enumerate(toks):                               # mm after an hour or before seconds is minutes (Excel's rule)
        if parts[i][1] in ("mm", "m"):
            before = parts[toks[n - 1]][1] if n > 0 else ""
            after = parts[toks[n + 1]][1] if n + 1 < len(toks) else ""
            if before in ("hh", "h") or after == "ss":
                parts[i] = ("tok", "nn")
    return parts


_PATTERNS = {"yyyy": r"(?P<y>\d{4})", "yy": r"(?P<y2>\d{2})", "mmmm": r"(?P<mon>[A-Za-z]+)", "mmm": r"(?P<mon>[A-Za-z]{3})",
             "mm": r"(?P<m>\d{2})", "m": r"(?P<m>\d{1,2})", "dd": r"(?P<d>\d{2})", "d": r"(?P<d>\d{1,2})", "hh": r"(?P<h>\d{2})",
             "h": r"(?P<h>\d{1,2})", "nn": r"(?P<n>\d{2})", "ss": r"(?P<s>\d{2})", "am/pm": r"(?P<ap>[AaPp][Mm])"}


def date_format_error(fmt: str) -> str:
    """Why ``fmt`` cannot be used as a date format ("" when it can)."""
    parts = _format_parts(fmt.strip())
    toks = [v for k, v in parts if k == "tok"]
    if not toks:
        return f"{fmt!r} has no date parts (use dd, mm, yyyy... as in dd/mm/yyyy)"
    groups = [_PATTERNS[t].split(">")[0][4:] for t in toks]
    if len(groups) != len(set(groups)):
        return f"{fmt!r} names the same part twice"
    return ""


def matches_date_format(text: str, fmt: str) -> tuple[bool, str]:
    """Is ``text`` a real date written exactly in ``fmt``?  Returns (ok, why not)."""
    error = date_format_error(fmt)
    if error:
        raise ValueError(error)
    text = (text or "").strip()
    pattern = "".join(re.escape(v) if k == "lit" else _PATTERNS[v] for k, v in _format_parts(fmt.strip()))
    m = re.fullmatch(pattern, text)
    if m is None:
        return False, f"{text!r} is not written as {fmt}"
    g = m.groupdict()
    year = int(g["y"]) if g.get("y") else (2000 + int(g["y2"]) if g.get("y2") else 2000)
    if g.get("mon"):
        name = g["mon"].lower()
        month = next((i + 1 for i, full in enumerate(_MONTHS) if full == name or full[:3] == name), 0)
        if not month:
            return False, f"{g['mon']!r} is not a month"
    else:
        month = int(g["m"]) if g.get("m") else 1
    day = int(g["d"]) if g.get("d") else 1
    try:
        date(year, month, day)
    except ValueError:
        return False, f"{text!r} is not a real date"
    hour = int(g["h"]) if g.get("h") else 0
    if g.get("ap"):
        if not 1 <= hour <= 12:
            return False, f"{text!r} has an hour that is not on a 12-hour clock"
    elif hour > 23:
        return False, f"{text!r} is not a real time"
    if (g.get("n") and int(g["n"]) > 59) or (g.get("s") and int(g["s"]) > 59):
        return False, f"{text!r} is not a real time"
    return True, ""


def format_date(value: date, fmt: str) -> str:
    """``value`` written in an Excel-style date format (``dd/mm/yyyy``, ``d mmm yyyy``...)."""
    out = []
    for kind, v in _format_parts(fmt):
        if kind == "lit":
            out.append(v)
            continue
        out.append({"yyyy": f"{value.year:04d}", "yy": f"{value.year % 100:02d}", "mmmm": _MONTHS[value.month - 1].title(),
                    "mmm": _MONTHS[value.month - 1][:3].title(), "mm": f"{value.month:02d}", "m": str(value.month),
                    "dd": f"{value.day:02d}", "d": str(value.day)}.get(v, "00"))
    return "".join(out)


def looks_like_date_format(text: str) -> bool:
    """A field's placeholder such as ``DD/MM/YYYY`` (then a date is typed in that shape)."""
    text = (text or "").strip()
    return bool(text) and bool(re.fullmatch(r"[dmy]{1,4}([ ./-][dmy]{1,4}){2}", text, re.I)) and "y" in text.lower()


# -- dates a PICK_DATE step is given ---------------------------------------------------------------------------------------------------------
_DATE_INPUTS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y",
                "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%a %d %b %Y",
                "%A, %d %B %Y", "%A, %B %d, %Y")


def parse_date(value: Any) -> date:
    """The date in a ``PICK_DATE`` Value: a date cell, ``2027-03-15``, ``15/03/2027`` (day first, as on the sites under test), ``15 Mar 2027``,
    an Excel date number.  ValueError when it is none of those."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = cell_text(value).strip()
    if not text:
        raise ValueError("Value is empty: give the date to pick (e.g. 15/03/2027 or 2027-03-15)")
    for fmt in _DATE_INPUTS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        serial = float(text)
    except ValueError:
        serial = 0.0
    if 20000 <= serial <= 80000:                                # an Excel date number (1954..2119)
        return date(1899, 12, 30) + timedelta(days=int(serial))
    raise ValueError(f"{text!r} is not a date this step understands (use 15/03/2027, 2027-03-15 or 15 Mar 2027)")


def date_texts(value: date) -> list[str]:
    """How a calendar may name ``value`` in a day cell's ``aria-label`` / ``title`` / ``data-date``, most specific first."""
    month, mon = _MONTHS[value.month - 1].title(), _MONTHS[value.month - 1][:3].title()
    d, y = value.day, value.year
    return [value.isoformat(), f"{d:02d}/{value.month:02d}/{y}", f"{value.month:02d}/{d:02d}/{y}", f"{d} {month} {y}", f"{month} {d}, {y}",
            f"{month} {d} {y}", f"{d} {mon} {y}", f"{mon} {d}, {y}", f"{d}-{mon}-{y}"]


def month_index(text: str) -> tuple[int, int] | None:
    """``March 2027`` / ``Mar 2027`` / ``2027-03`` (a calendar's heading) -> (year, month), or None."""
    text = (text or "").strip()
    m = re.search(r"\b([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text)
    if m:
        name = m.group(1).lower()
        month = next((i + 1 for i, full in enumerate(_MONTHS) if full.startswith(name)), 0)
        if month:
            return int(m.group(2)), month
    m = re.search(r"\b(\d{4})-(\d{2})\b", text)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    return None
