"""Excel ``TEXT(value, format)`` emulation (dates, times and the common number formats).

Only what real workbooks use is implemented; anything exotic falls back to plain text so a
formatting gap can never crash a run.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_EPOCH = datetime(1899, 12, 30)
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_TOKEN = re.compile(
    r'"(?:[^"]*)"|\\.|\[[^\]]*\]|y+|mmmmm|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|am/pm|a/p|'
    r'0+\.?0*%?|#,##0(?:\.0+)?|.',
    re.IGNORECASE,
)


def to_datetime(serial: float) -> datetime:
    return _EPOCH + timedelta(days=float(serial))


def to_serial(dt: datetime) -> float:
    delta = dt - _EPOCH
    return delta.days + delta.seconds / 86400.0 + delta.microseconds / 86400e6


def _is_date_format(fmt: str) -> bool:
    stripped = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", fmt)
    return bool(re.search(r"[ymdhs]", stripped, re.IGNORECASE)) and not re.search(r"^[#0,.%\s]+$", stripped)


class _Parts:
    """Calendar fields for a serial number, reproducing Excel's 1900 calendar quirks.

    Excel treats serial 0 as "January 0, 1900" and invents a Feb 29, 1900 (serial 60), so dates
    below serial 61 are shifted one day relative to the proleptic Gregorian calendar.
    """

    def __init__(self, serial: float):
        whole = int(serial // 1)
        frac = serial - whole
        seconds = int(round(frac * 86400))
        if whole >= 61:
            base = _EPOCH + timedelta(days=whole)
            self.year, self.month, self.day = base.year, base.month, base.day
            self._weekday = base.weekday()
        elif whole == 60:
            self.year, self.month, self.day, self._weekday = 1900, 2, 29, 2
        else:                                   # serial 0..59 -> Jan 0 .. Feb 28, 1900
            n = max(whole, 0)
            if n <= 31:
                self.year, self.month, self.day = 1900, 1, n
            else:
                self.year, self.month, self.day = 1900, 2, n - 31
            self._weekday = (n + 5) % 7
        self.hour, rem = divmod(seconds, 3600)
        self.minute, self.second = divmod(rem, 60)

    def weekday(self) -> int:
        return self._weekday


def format_text(value: float, fmt: str) -> str:
    """Return ``TEXT(value, fmt)`` for a numeric ``value``."""
    if fmt == "":
        return ""
    if fmt.lower() == "general":
        return _general(value)
    if _is_date_format(fmt):
        return _format_datetime(_Parts(value), fmt)
    return _format_number(value, fmt)


def _general(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return repr(round(float(value), 10)).rstrip("0").rstrip(".")


def _format_datetime(dt, fmt: str) -> str:
    tokens = _TOKEN.findall(fmt)
    lowered = [t.lower() for t in tokens]
    has_ampm = any(t in ("am/pm", "a/p") for t in lowered)
    out: list[str] = []
    for i, (tok, low) in enumerate(zip(tokens, lowered)):
        if low in ("m", "mm"):
            # "m" directly after an hour token or directly before a seconds token means minutes.
            prev = next((lowered[j] for j in range(i - 1, -1, -1) if lowered[j] not in (":", " ")), "")
            nxt = next((lowered[j] for j in range(i + 1, len(lowered)) if lowered[j] not in (":", " ")), "")
            is_minute = prev in ("h", "hh") or nxt in ("s", "ss")
            if is_minute:
                out.append(f"{dt.minute:02d}" if low == "mm" else str(dt.minute))
            else:
                out.append(f"{dt.month:02d}" if low == "mm" else str(dt.month))
        elif low.startswith("y") and set(low) == {"y"}:          # y / yy = 2 digits; yyy and longer (Excel: yyyyy too) = 4
            out.append(f"{dt.year:04d}" if len(low) >= 3 else f"{dt.year % 100:02d}")
        elif low == "mmmm":
            out.append(_MONTHS[dt.month - 1])
        elif low == "mmmmm":
            out.append(_MONTHS[dt.month - 1][0])
        elif low == "mmm":
            out.append(_MONTHS[dt.month - 1][:3])
        elif low == "dddd":
            out.append(_DAYS[dt.weekday()])
        elif low == "ddd":
            out.append(_DAYS[dt.weekday()][:3])
        elif low == "dd":
            out.append(f"{dt.day:02d}")
        elif low == "d":
            out.append(str(dt.day))
        elif low in ("hh", "h"):
            hour = dt.hour % 12 or 12 if has_ampm else dt.hour
            out.append(f"{hour:02d}" if low == "hh" else str(hour))
        elif low == "ss":
            out.append(f"{dt.second:02d}")
        elif low == "s":
            out.append(str(dt.second))
        elif low in ("am/pm", "a/p"):
            marker = "AM" if dt.hour < 12 else "PM"
            out.append(marker if low == "am/pm" else marker[0])
        elif tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            out.append(tok[1:-1])
        elif tok.startswith("\\") and len(tok) == 2:
            out.append(tok[1])
        elif tok.startswith("["):
            continue
        else:
            out.append(tok)
    return "".join(out)


def _format_number(value: float, fmt: str) -> str:
    percent = fmt.strip().endswith("%")
    if percent:
        value *= 100
    decimals = 0
    if "." in fmt:
        decimals = len(re.sub(r"[^0#]", "", fmt.split(".", 1)[1]))
    thousands = "," in fmt
    text = f"{value:,.{decimals}f}" if thousands else f"{value:.{decimals}f}"
    min_digits = re.sub(r'"[^"]*"|\\.', "", fmt.split(".", 1)[0]).count("0")          # "000" -> at least three integer digits
    if min_digits > 1:
        sign, digits = ("-", text[1:]) if text.startswith("-") else ("", text)
        whole, point, fraction = digits.replace(",", "").partition(".")
        whole = whole.zfill(min_digits)
        if thousands:
            whole = re.sub(r"\B(?=(\d{3})+(?!\d))", ",", whole)
        text = sign + whole + point + fraction
    prefix = re.match(r'^[^#0,.]*', fmt).group(0).replace('"', "").replace("\\", "")
    suffix = "%" if percent else ""
    return f"{prefix}{text}{suffix}"
