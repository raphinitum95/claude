"""Conservative XPath -> CSS conversion plus a "how brittle is this locator" score.

Only *provably equivalent* shapes are converted:

    //tag[@a='v' and @b]//child[contains(@class,'x')]   ->   tag[a="v"][b] child[class*="x"]
    (//input[@name='age'])[2]                            ->   input[name="age"]   with nth=1

Anything involving visible text (``text()``, ``contains(.,..)``), positions inside a step
(``div[2]``), ``or``, axes or functions is *not* converted - a wrong "equivalent" would silently
change what a regression test verifies, and precision matters more than migration coverage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .spec import css_string

_NAME = r"[A-Za-z_][\w-]*"
_LIT = r"""('[^']*'|"[^"]*")"""
# HTML attributes whose *values* CSS compares ASCII-case-insensitively (per the HTML spec), unlike
# XPath.  Chromium has no ``s`` (case-sensitive) flag, so converting e.g. ``@type='SUBMIT'`` would
# also match ``type="submit"`` and change what the step targets.  These stay XPath.
CASE_INSENSITIVE_VALUE_ATTRS = frozenset({
    "accept", "accept-charset", "align", "alink", "axis", "bgcolor", "charset", "checked", "clear",
    "codetype", "color", "compact", "declare", "defer", "dir", "direction", "disabled", "enctype",
    "face", "frame", "hreflang", "http-equiv", "lang", "language", "link", "media", "method",
    "multiple", "nohref", "noresize", "noshade", "nowrap", "readonly", "rel", "rev", "rules", "scope",
    "scrolling", "selected", "shape", "target", "text", "type", "valign", "valuetype", "vlink",
})
_ATOMS = [
    (re.compile(rf"^@({_NAME})\s*=\s*{_LIT}$"), "eq"),
    (re.compile(rf"^@({_NAME})$"), "has"),
    (re.compile(rf"^contains\(\s*@({_NAME})\s*,\s*{_LIT}\s*\)$"), "contains"),
    (re.compile(rf"^starts-with\(\s*@({_NAME})\s*,\s*{_LIT}\s*\)$"), "starts"),
]


@dataclass(frozen=True)
class Conversion:
    css: str
    nth: int | None = None       # 0-based, from a "(//x)[N]" wrapper

    @property
    def locator(self) -> str:
        return f"css={self.css}"


def _split_top(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside quotes/brackets/parens."""
    parts, depth, quote, buf = [], 0, "", []
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "[(":
            depth += 1
            buf.append(ch)
        elif ch in "])":
            depth -= 1
            buf.append(ch)
        elif depth == 0 and text.startswith(sep, i):
            parts.append("".join(buf))
            buf = []
            i += len(sep)
            continue
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _predicate_to_css(pred: str) -> str | None:
    out = []
    for atom in _split_top(pred.strip(), " and "):
        atom = atom.strip()
        for regex, kind in _ATOMS:
            m = regex.match(atom)
            if not m:
                continue
            attr = m.group(1)
            if kind == "has":
                out.append(f"[{attr}]")
                break
            literal = m.group(2)[1:-1]
            if kind in ("contains", "starts") and literal == "":
                return None             # CSS [a*=""] matches nothing; XPath contains(@a,'') is true
            if attr.lower() in CASE_INSENSITIVE_VALUE_ATTRS and re.search(r"[A-Za-z]", literal):
                return None
            op = {"eq": "=", "contains": "*=", "starts": "^="}[kind]
            out.append(f"[{attr}{op}{css_string(literal)}]")
            break
        else:
            return None
    return "".join(out)


def xpath_to_css(xpath: str) -> Conversion | None:
    """Return an equivalent CSS selector, or ``None`` when no *provably* equivalent one exists."""
    text = xpath.strip()
    nth = None
    wrapped = re.fullmatch(r"\((.*)\)\[(\d+)\]", text, re.DOTALL)
    if wrapped:
        text, nth = wrapped.group(1).strip(), int(wrapped.group(2)) - 1
        if nth < 0:
            return None
    if not text.startswith("//") or text.startswith("///"):
        return None
    pos, pieces = 0, []
    while pos < len(text):
        if text.startswith("//", pos):
            combinator, pos = " ", pos + 2
        elif text.startswith("/", pos):
            combinator, pos = " > ", pos + 1
        else:
            return None
        m = re.match(rf"({_NAME}|\*)", text[pos:])
        if not m:
            return None
        tag = m.group(1)
        pos += m.end()
        css = "" if tag == "*" else tag
        predicates = ""
        while pos < len(text) and text[pos] == "[":
            depth, quote, j = 0, "", pos
            while j < len(text):
                ch = text[j]
                if quote:
                    if ch == quote:
                        quote = ""
                elif ch in "'\"":
                    quote = ch
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            else:
                return None
            converted = _predicate_to_css(text[pos + 1:j])
            if converted is None:
                return None
            predicates += converted
            pos = j + 1
        if not css and not predicates:
            css = "*"
        pieces.append((combinator, css + predicates))
    if not pieces:
        return None
    selector = ""
    for i, (combinator, part) in enumerate(pieces):
        selector += part if i == 0 else combinator + part
    return Conversion(selector, nth)


# ---------------------------------------------------------------------------------------------
# Brittleness score (used by `regrunner selectors audit`)
# ---------------------------------------------------------------------------------------------
_GENERATED = re.compile(r"[0-9a-f]{8,}|[-_]\d{4,}", re.IGNORECASE)


def score_xpath(xpath: str) -> tuple[int, str, list[str]]:
    """Return ``(score 0-100, label, reasons)``; higher means more resilient to layout change."""
    reasons: list[str] = []
    score = 40
    ids = re.findall(r"@id\s*=\s*['\"]([^'\"]+)['\"]", xpath)
    names = re.findall(r"@name\s*=\s*['\"]([^'\"]+)['\"]", xpath)
    testids = re.findall(r"@data-(?:test|testid|test-id|cmp-[\w-]+)\s*=", xpath)
    if ids:
        generated = any(_GENERATED.search(i) for i in ids)
        score = max(score, 60 if generated else 92)
        reasons.append("id looks auto-generated" if generated else "anchored on id")
    if names:
        score = max(score, 90)
        reasons.append("anchored on name")
    if testids:
        score = max(score, 90)
        reasons.append("anchored on data attribute")
    if not (ids or names or testids):
        if re.search(r"@(?:class|type|value|placeholder|href|for|role|aria-[\w-]+)\s*=", xpath) or \
                re.search(r"contains\(@", xpath):
            score = 55
            reasons.append("anchored on class/type/other attribute")
        else:
            score = 20
            reasons.append("no stable attribute")
    if re.search(r"text\(\)|contains\(\s*\.|normalize-space", xpath):
        score = min(score, 30)
        reasons.append("depends on visible text")
    if re.search(r"\)\[\d+\]|\[\d+\]|position\(\)|last\(\)", xpath):
        score -= 15
        reasons.append("depends on element position")
    if re.search(r"ancestor|following|preceding|sibling|parent::|/\.\./", xpath):
        score -= 15
        reasons.append("depends on document structure")
    score = max(0, min(100, score))
    label = "strong" if score >= 85 else "ok" if score >= 55 else "weak"
    return score, label, reasons
