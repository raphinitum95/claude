"""A small, dependable Excel formula engine.

The legacy runner used real Excel (COM) as its formula engine.  We cannot (and do not want to)
depend on Excel, so this module parses and evaluates the subset of Excel formulas that keyword
workbooks actually use: string building, IF/IFS/AND/OR gating, date arithmetic with TEXT(),
cell references (including cross-sheet and ranges) and a handful of text/number helpers.

Adding a function is a three-line change: decorate a callable with ``@function("NAME")``.
Unknown functions raise ``ExcelError('#NAME?')`` so a gap is visible rather than silent.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Callable, Iterable, Protocol

from .textfmt import format_text, to_datetime, to_serial


class ExcelError(Exception):
    """An Excel error value such as ``#VALUE!`` (propagates like Excel errors do)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code} {detail}".strip())
        self.code = code
        self.detail = detail


class ExcelDate(float):
    """A serial-number result that Excel would display as a date (TODAY, NOW, DATE)."""


@dataclass
class RangeValue:
    """A rectangular block of cell values, row-major."""

    rows: list[list[Any]]

    def flat(self) -> Iterable[Any]:
        for row in self.rows:
            yield from row


class EvalContext(Protocol):
    """What the evaluator needs from its host (see ``sheet.BookState``)."""

    def get_cell(self, sheet: str | None, row: int, col: int) -> Any: ...
    def get_range(self, sheet: str | None, r1: int, c1: int, r2: int, c2: int) -> RangeValue: ...
    def now(self) -> datetime: ...
    def randint(self, low: int, high: int) -> int: ...


# ---------------------------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------------------------
_REF = r"(?:(?:'[^']+'|[A-Za-z_][A-Za-z0-9_\.]*)!)?\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?"
_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<string>"(?:[^"]|"")*")
      | (?P<number>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)
      | (?P<func>[A-Za-z_][A-Za-z0-9_\.]*)(?=\()
      | (?P<ref>""" + _REF + r""")(?![A-Za-z0-9_\(])
      | (?P<bool>TRUE|FALSE)(?![A-Za-z0-9_\(])
      | (?P<op><>|<=|>=|[=<>&+\-*/^%(),:;])
    )""",
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class Token:
    kind: str
    text: str


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ExcelError("#NAME?", f"cannot parse near {text[pos:pos + 12]!r}")
        pos = m.end()
        kind = m.lastgroup
        tokens.append(Token(kind, m.group(kind)))
    return tokens


# ---------------------------------------------------------------------------------------------
# Parser  (precedence, low -> high: comparison, &, + -, * /, ^, unary -, %)
# ---------------------------------------------------------------------------------------------
class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def accept_op(self, *ops: str) -> str | None:
        tok = self.peek()
        if tok and tok.kind == "op" and tok.text in ops:
            self.i += 1
            return tok.text
        return None

    def parse(self):
        node = self.comparison()
        if self.peek() is not None:
            raise ExcelError("#NAME?", f"unexpected {self.peek().text!r}")
        return node

    def comparison(self):
        node = self.concat()
        while (op := self.accept_op("=", "<>", "<", ">", "<=", ">=")):
            node = ("cmp", op, node, self.concat())
        return node

    def concat(self):
        node = self.additive()
        while self.accept_op("&"):
            node = ("concat", node, self.additive())
        return node

    def additive(self):
        node = self.term()
        while (op := self.accept_op("+", "-")):
            node = ("arith", op, node, self.term())
        return node

    def term(self):
        node = self.power()
        while (op := self.accept_op("*", "/")):
            node = ("arith", op, node, self.power())
        return node

    def power(self):
        node = self.unary()
        while self.accept_op("^"):
            node = ("arith", "^", node, self.unary())
        return node

    def unary(self):
        if self.accept_op("-"):
            return ("neg", self.unary())
        if self.accept_op("+"):
            return self.unary()
        node = self.primary()
        while self.accept_op("%"):
            node = ("arith", "/", node, ("num", 100.0))
        return node

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise ExcelError("#NAME?", "unexpected end of formula")
        if tok.kind == "number":
            self.take()
            return ("num", float(tok.text))
        if tok.kind == "string":
            self.take()
            return ("str", tok.text[1:-1].replace('""', '"'))
        if tok.kind == "bool":
            self.take()
            return ("bool", tok.text.upper() == "TRUE")
        if tok.kind == "ref":
            self.take()
            return _parse_ref(tok.text)
        if tok.kind == "func":
            self.take()
            name = tok.text.upper()
            if name.startswith("_XLFN."):
                name = name[6:]
            if not self.accept_op("("):
                raise ExcelError("#NAME?", "expected (")
            args = []
            if not self.accept_op(")"):
                while True:
                    args.append(self.comparison())
                    if self.accept_op(",", ";"):
                        continue
                    if self.accept_op(")"):
                        break
                    raise ExcelError("#NAME?", "expected , or )")
            return ("call", name, args)
        if self.accept_op("("):
            node = self.comparison()
            if not self.accept_op(")"):
                raise ExcelError("#NAME?", "expected )")
            return node
        raise ExcelError("#NAME?", f"unexpected {tok.text!r}")


_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def col_to_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def index_to_col(index: int) -> str:
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _parse_ref(text: str):
    sheet = None
    if "!" in text:
        sheet, text = text.rsplit("!", 1)
        sheet = sheet.strip("'")
    parts = text.split(":")
    cells = []
    for part in parts:
        m = _CELL.match(part)
        if not m:
            raise ExcelError("#REF!", part)
        cells.append((int(m.group(2)), col_to_index(m.group(1))))
    if len(cells) == 1:
        return ("cell", sheet, cells[0][0], cells[0][1])
    (r1, c1), (r2, c2) = cells
    return ("range", sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))


@lru_cache(maxsize=8192)
def parse_formula(formula: str):
    """Parse ``=...`` (leading ``=`` optional) into an AST.  Cached: workbooks repeat formulas."""
    body = formula[1:] if formula.startswith("=") else formula
    return _Parser(tokenize(body)).parse()


# ---------------------------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------------------------
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d-%b-%Y", "%m-%d-%Y", "%Y/%m/%d",
                 "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def parse_date_text(text: str) -> float | None:
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return to_serial(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def to_number(value: Any) -> float:
    if isinstance(value, RangeValue):
        raise ExcelError("#VALUE!", "range used as a number")
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return to_serial(value)
    if isinstance(value, date):
        return to_serial(datetime(value.year, value.month, value.day))
    if isinstance(value, str):
        try:
            return float(value.replace(",", "")) if value.strip() else 0.0
        except ValueError:
            serial = parse_date_text(value)
            if serial is not None:
                return serial
    raise ExcelError("#VALUE!", f"{value!r} is not a number")


def number_to_text(number: float) -> str:
    if isinstance(number, float) and math.isnan(number):
        raise ExcelError("#NUM!")
    if float(number).is_integer():
        return str(int(number))
    return repr(round(float(number), 12)).rstrip("0").rstrip(".") if "e" not in repr(number) else repr(number)


def to_text(value: Any) -> str:
    if isinstance(value, RangeValue):
        raise ExcelError("#VALUE!", "range used as text")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return number_to_text(value)
    if isinstance(value, (datetime, date)):
        return number_to_text(to_number(value))
    return str(value)


def to_bool(value: Any) -> bool:
    if isinstance(value, str):
        low = value.strip().upper()
        if low == "TRUE":
            return True
        if low == "FALSE":
            return False
        raise ExcelError("#VALUE!", f"{value!r} is not a boolean")
    if value is None:
        return False
    return bool(to_number(value))


def _type_rank(v: Any) -> int:
    if isinstance(v, bool):
        return 2
    if isinstance(v, str):
        return 1
    return 0


def compare(op: str, a: Any, b: Any) -> bool:
    """Excel comparison semantics: blanks adopt the other side's type, text compares case-insensitively."""
    if a is None:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0)
    if b is None:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0)
    if isinstance(a, (datetime, date)):
        a = to_number(a)
    if isinstance(b, (datetime, date)):
        b = to_number(b)
    ra, rb = _type_rank(a), _type_rank(b)
    if ra != rb:
        ka, kb = ra, rb
    elif ra == 1:
        ka, kb = a.casefold(), b.casefold()
    else:
        ka, kb = a, b
    if op == "=":
        return ka == kb
    if op == "<>":
        return ka != kb
    if op == "<":
        return ka < kb
    if op == ">":
        return ka > kb
    if op == "<=":
        return ka <= kb
    return ka >= kb


# ---------------------------------------------------------------------------------------------
# Function registry
# ---------------------------------------------------------------------------------------------
_FUNCS: dict[str, Callable[..., Any]] = {}
_LAZY: dict[str, Callable[..., Any]] = {}  # receive unevaluated args + evaluator (IF, IFS, IFERROR)


def function(name: str, lazy: bool = False):
    def deco(fn):
        (_LAZY if lazy else _FUNCS)[name.upper()] = fn
        return fn
    return deco


def _scalars(args: Iterable[Any]) -> Iterable[Any]:
    for a in args:
        if isinstance(a, RangeValue):
            yield from a.flat()
        else:
            yield a


def _numbers(args: Iterable[Any], *, skip_text: bool) -> list[float]:
    out = []
    for a in args:
        if isinstance(a, RangeValue):
            out.extend(float(v) for v in a.flat() if isinstance(v, (int, float)) and not isinstance(v, bool))
        elif skip_text or not isinstance(a, str):
            out.append(to_number(a))
    return out


@function("IF", lazy=True)
def _if(ev, args):
    if len(args) < 2:
        raise ExcelError("#VALUE!")
    if to_bool(ev(args[0])):
        return ev(args[1])
    return ev(args[2]) if len(args) > 2 else False


@function("IFS", lazy=True)
def _ifs(ev, args):
    for i in range(0, len(args) - 1, 2):
        if to_bool(ev(args[i])):
            return ev(args[i + 1])
    raise ExcelError("#N/A")


@function("IFERROR", lazy=True)
def _iferror(ev, args):
    try:
        return ev(args[0])
    except ExcelError:
        return ev(args[1])


@function("AND")
def _and(*args):
    return all(to_bool(v) for v in _scalars(args) if v is not None and v != "")


@function("OR")
def _or(*args):
    return any(to_bool(v) for v in _scalars(args) if v is not None and v != "")


@function("NOT")
def _not(a):
    return not to_bool(a)


@function("TEXT")
def _text(value, fmt):
    fmt = to_text(fmt)
    if isinstance(value, str):
        try:
            number = to_number(value)
        except ExcelError:
            return value
    else:
        number = to_number(value)
    return format_text(number, fmt)


@function("TODAY")
def _today_placeholder():  # replaced at evaluation time (needs ctx) - see Evaluator._call
    raise AssertionError


@function("NOW")
def _now_placeholder():
    raise AssertionError


@function("DATE")
def _date(y, m, d):
    y, m, d = int(to_number(y)), int(to_number(m)), int(to_number(d))
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return ExcelDate(to_serial(datetime(y, m, 1) + timedelta(days=d - 1)))


@function("YEAR")
def _year(v): return to_datetime(to_number(v)).year
@function("MONTH")
def _month(v): return to_datetime(to_number(v)).month
@function("DAY")
def _day(v): return to_datetime(to_number(v)).day
@function("HOUR")
def _hour(v): return to_datetime(to_number(v)).hour
@function("MINUTE")
def _minute(v): return to_datetime(to_number(v)).minute
@function("SECOND")
def _second(v): return to_datetime(to_number(v)).second


@function("CHAR")
def _char(n):
    n = int(to_number(n))
    if not 1 <= n <= 255:
        raise ExcelError("#VALUE!")
    return bytes([n]).decode("cp1252", errors="replace")


@function("CODE")
def _code(s): return ord(to_text(s)[:1] or "\0")


@function("RANDBETWEEN")
def _randbetween_placeholder(a, b):
    raise AssertionError


@function("COUNTA")
def _counta(*args):
    return sum(1 for v in _scalars(args) if v is not None and v != "")


@function("COUNT")
def _count(*args):
    return sum(1 for v in _scalars(args) if isinstance(v, (int, float)) and not isinstance(v, bool))


@function("SUM")
def _sum(*args): return sum(_numbers(args, skip_text=False))
@function("MIN")
def _min(*args):
    nums = _numbers(args, skip_text=False)
    return min(nums) if nums else 0
@function("MAX")
def _max(*args):
    nums = _numbers(args, skip_text=False)
    return max(nums) if nums else 0


@function("ABS")
def _abs(v): return abs(to_number(v))
@function("INT")
def _int(v): return math.floor(to_number(v))


@function("ROUND")
def _round(v, digits=0):
    factor = 10 ** int(to_number(digits))
    return math.floor(abs(to_number(v)) * factor + 0.5) / factor * (1 if to_number(v) >= 0 else -1)


@function("SUBSTITUTE")
def _substitute(text, old, new, instance=None):
    text, old, new = to_text(text), to_text(old), to_text(new)
    if not old:
        return text
    if instance is None:
        return text.replace(old, new)
    n, idx, start = int(to_number(instance)), -1, 0
    for _ in range(n):
        idx = text.find(old, start)
        if idx < 0:
            return text
        start = idx + len(old)
    return text[:idx] + new + text[idx + len(old):]


@function("RIGHT")
def _right(text, n=1):
    n = int(to_number(n))
    return to_text(text)[-n:] if n > 0 else ""


@function("LEFT")
def _left(text, n=1): return to_text(text)[:int(to_number(n))]


@function("MID")
def _mid(text, start, n):
    s = int(to_number(start)) - 1
    return to_text(text)[max(s, 0): max(s, 0) + int(to_number(n))]


@function("LEN")
def _len(text): return len(to_text(text))
@function("UPPER")
def _upper(text): return to_text(text).upper()
@function("LOWER")
def _lower(text): return to_text(text).lower()
@function("TRIM")
def _trim(text): return re.sub(r" +", " ", to_text(text)).strip()
@function("EXACT")
def _exact(a, b): return to_text(a) == to_text(b)


@function("FIND")
def _find(needle, hay, start=1):
    idx = to_text(hay).find(to_text(needle), int(to_number(start)) - 1)
    if idx < 0:
        raise ExcelError("#VALUE!")
    return idx + 1


@function("SEARCH")
def _search(needle, hay, start=1):
    idx = to_text(hay).lower().find(to_text(needle).lower(), int(to_number(start)) - 1)
    if idx < 0:
        raise ExcelError("#VALUE!")
    return idx + 1


@function("CONCATENATE")
def _concatenate(*args): return "".join(to_text(a) for a in args)
@function("CONCAT")
def _concat(*args): return "".join(to_text(a) for a in _scalars(args))


@function("REPT")
def _rept(text, n): return to_text(text) * int(to_number(n))
@function("VALUE")
def _value(v): return to_number(v)
@function("ISBLANK")
def _isblank(v): return v is None or v == ""
@function("ISNUMBER")
def _isnumber(v): return isinstance(v, (int, float)) and not isinstance(v, bool)
@function("ISTEXT")
def _istext(v): return isinstance(v, str)


_NUMBER_TEXT = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


@function("NUMBERVALUE")
def _numbervalue(text, decimal=None, group=None):
    """Text -> number the way Excel does it, whatever the locale: spaces are ignored, ``group`` separators before the decimal
    point are dropped, trailing ``%`` divides by 100 each, "" is 0, anything else is #VALUE!."""
    dec = "." if decimal is None else (to_text(decimal)[:1] or ".")
    grp = ("," if dec == "." else ".") if group is None else to_text(group)[:1]
    if dec == grp:
        raise ExcelError("#VALUE!", "NUMBERVALUE: the decimal and group separators are the same")
    s = "".join(to_text(text).split())
    percents = len(s) - len(s.rstrip("%"))
    s = s.rstrip("%")
    if not s:
        return 0.0
    whole, point, fraction = s.partition(dec)
    if dec in fraction or (grp and grp in fraction):
        raise ExcelError("#VALUE!", f"NUMBERVALUE: {to_text(text)!r} is not a number")
    plain = (whole.replace(grp, "") if grp else whole) + ("." + fraction if point else "")
    if not _NUMBER_TEXT.match(plain):
        raise ExcelError("#VALUE!", f"NUMBERVALUE: {to_text(text)!r} is not a number")
    return float(plain) / (100 ** percents)


def _wildcard(pattern: str) -> "re.Pattern[str]":
    """Excel's ``*`` / ``?`` / ``~`` wildcards for exact-match lookups."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "~" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)


@function("VLOOKUP")
def _vlookup(lookup, table, index, approximate=True):
    """First column of ``table`` is searched; the cell ``index`` columns across on that row is returned.

    Exact (``FALSE``/0): first equal key, text case-insensitive, ``*`` ``?`` wildcards.  Approximate (default, ``TRUE``): the last
    key that is <= the lookup value, keys assumed ascending.  No match is ``#N/A``.  An empty result cell reads as 0, like Excel.
    """
    if not isinstance(table, RangeValue):
        raise ExcelError("#VALUE!", "VLOOKUP: the second argument must be a range")
    column = int(to_number(index))
    if column < 1:
        raise ExcelError("#VALUE!", "VLOOKUP: the column number must be 1 or more")
    if not table.rows or column > len(table.rows[0]):
        raise ExcelError("#REF!", "VLOOKUP: the column number is beyond the table")
    if isinstance(lookup, RangeValue):
        raise ExcelError("#VALUE!", "VLOOKUP: the lookup value must be a single cell")
    if lookup is None:
        raise ExcelError("#N/A", "VLOOKUP: the lookup cell is empty")
    wanted = to_number(lookup) if isinstance(lookup, (datetime, date)) else lookup
    hit = None
    if not to_bool(approximate):
        pattern = _wildcard(wanted) if isinstance(wanted, str) and any(c in wanted for c in "*?~") else None
        for row in table.rows:
            key = row[0]
            if key is None:
                continue
            if pattern is not None and isinstance(key, str):
                if pattern.match(key):
                    hit = row
                    break
            elif _type_rank(key) == _type_rank(wanted) and compare("=", key, wanted):
                hit = row
                break
    else:
        for row in table.rows:
            key = row[0]
            if key is None or _type_rank(key) != _type_rank(wanted):
                continue
            if compare("<=", key, wanted):
                hit = row
            else:
                break
    if hit is None:
        raise ExcelError("#N/A", "VLOOKUP: no match")
    found = hit[column - 1]
    return 0 if found is None else found


# ---------------------------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------------------------
class Evaluator:
    """Evaluates parsed formulas against an ``EvalContext``."""

    def __init__(self, ctx: EvalContext):
        self.ctx = ctx

    def evaluate(self, formula: str) -> Any:
        return self._ev(parse_formula(formula))

    # -- node dispatch ------------------------------------------------------------------------
    def _ev(self, node) -> Any:
        kind = node[0]
        if kind in ("num", "str", "bool"):
            return node[1]
        if kind == "cell":
            return self.ctx.get_cell(node[1], node[2], node[3])
        if kind == "range":
            return self.ctx.get_range(node[1], node[2], node[3], node[4], node[5])
        if kind == "neg":
            return -to_number(self._ev(node[1]))
        if kind == "concat":
            return to_text(self._ev(node[1])) + to_text(self._ev(node[2]))
        if kind == "cmp":
            return compare(node[1], self._ev(node[2]), self._ev(node[3]))
        if kind == "arith":
            a, b = to_number(self._ev(node[2])), to_number(self._ev(node[3]))
            op = node[1]
            if op == "+": return a + b
            if op == "-": return a - b
            if op == "*": return a * b
            if op == "/":
                if b == 0:
                    raise ExcelError("#DIV/0!")
                return a / b
            return a ** b
        if kind == "call":
            return self._call(node[1], node[2])
        raise ExcelError("#NAME?", f"bad node {kind}")

    def _call(self, name: str, args: list) -> Any:
        if name in _LAZY:
            return _LAZY[name](self._ev, args)
        if name == "TODAY":
            now = self.ctx.now()
            return ExcelDate(to_serial(datetime(now.year, now.month, now.day)))
        if name == "NOW":
            return ExcelDate(to_serial(self.ctx.now()))
        if name == "RANDBETWEEN":
            low, high = int(to_number(self._ev(args[0]))), int(to_number(self._ev(args[1])))
            return self.ctx.randint(low, high)
        fn = _FUNCS.get(name)
        if fn is None:
            raise ExcelError("#NAME?", f"unsupported function {name}")
        return fn(*[self._ev(a) for a in args])


def collapse(value: Any) -> Any:
    """A single-cell view of an evaluation result (top-left of a range; errors become text)."""
    if isinstance(value, RangeValue):
        return value.rows[0][0] if value.rows and value.rows[0] else None
    return value
