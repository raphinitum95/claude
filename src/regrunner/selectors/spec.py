"""Locator strategies: how a step finds its element.

A step is resolved through an ordered *chain* of strategies, so a brittle XPath can be replaced by
a generic locator (id / name / css / role / test id ...) without touching the workbook and without
losing the old XPath as a safety net:

    1. ``Locator`` column in the sheet (optional, per row, ``a || b || c`` = try in that order)
    2. ``selectors.yaml`` entry keyed by the legacy locator (optional, project-wide)
    3. the legacy ``FindBy`` / ``FindBy_Value`` pair (unless ``selectors.legacy_fallback: false``)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Legacy FindBy vocabulary (identical to the Selenium runner).
FINDBY_ALIASES = {
    "id": ("BY_ID", "ID", "HTML ID", "HTMLID"),
    "name": ("BY_NAME", "NAME"),
    "xpath": ("BY_XPATH", "XPATH"),
    "linktext": ("BY_LINKTEXT", "LINKTEXT", "LTEXT"),
    "partiallinktext": ("BY_PARTIALLINKTEXT", "PARTIALLINKTEXT", "PLTEXT"),
    "tag": ("BY_TAGNAME", "TAG_NAME", "TAGNAME"),
    "class": ("BY_CLASSNAME", "CLASS_NAME", "CLASSNAME"),
    "css": ("BY_CSSSELECTOR", "CSS_SELECTOR", "CSSSELECTOR"),
}
_FINDBY_LOOKUP = {alias: kind for kind, aliases in FINDBY_ALIASES.items() for alias in aliases}


def css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


@dataclass(frozen=True)
class Strategy:
    kind: str                 # css | xpath | id | name | text | role | label | placeholder | testid | ...
    value: str                # as authored (for display/keys)
    selector: str             # Playwright selector string
    origin: str = "legacy"    # sheet | map | legacy | auto
    index: int | None = None  # overrides the sheet's Index when set (map entries whose CSS is unique)

    def describe(self) -> str:
        return f"{self.kind}={self.value}"


def legacy_strategy(findby: str, value: str) -> Strategy | None:
    """The Selenium-compatible locator for a ``FindBy``/``FindBy_Value`` pair."""
    kind = _FINDBY_LOOKUP.get(findby.upper().strip())
    if kind is None or value == "":
        return None
    if kind == "xpath":
        return Strategy("xpath", value, f"xpath={value}")
    if kind == "id":
        return Strategy("id", value, f"css=[id={css_string(value)}]")
    if kind == "name":
        return Strategy("name", value, f"css=[name={css_string(value)}]")
    if kind == "css":
        return Strategy("css", value, f"css={value}")
    if kind == "tag":
        return Strategy("css", value, f"css={value}")
    if kind == "class":
        return Strategy("css", f".{value}", f"css=[class~={css_string(value)}]")
    if kind == "linktext":
        return Strategy("xpath", value, f"xpath=//a[normalize-space(.)={xpath_literal(value.strip())}]")
    return Strategy("xpath", value, f"xpath=//a[contains(normalize-space(.), {xpath_literal(value)})]")


def legacy_key(findby: str, value: str) -> str:
    """Stable lookup key for ``selectors.yaml`` (raw XPath, or ``kind:value`` for other FindBy)."""
    kind = _FINDBY_LOOKUP.get(findby.upper().strip(), "xpath")
    return value if kind == "xpath" else f"{kind}:{value}"


_SHORTHAND_ENGINES = {
    "css": lambda v: f"css={v}",
    "xpath": lambda v: f"xpath={v}",
    "id": lambda v: f"css=[id={css_string(v)}]",
    "name": lambda v: f"css=[name={css_string(v)}]",
    "testid": lambda v: f"css=[data-testid={css_string(v)}]",
    "tag": lambda v: f"css={v}",
    "class": lambda v: f"css=[class~={css_string(v)}]",
    "placeholder": lambda v: f"css=[placeholder={css_string(v)}]",
    "title": lambda v: f"css=[title={css_string(v)}]",
    "alt": lambda v: f"css=[alt={css_string(v)}]",
    "text": lambda v: f"text={v}",
    "role": lambda v: f"role={v}",
}
_PW_PASSTHROUGH = ("text=", "role=", "internal:", "data-testid=", "data-test-id=", "data-test=", "nth=", "has-text=",
                   "text-is=")


def parse_locator(text: str, origin: str = "sheet") -> Strategy:
    """Parse one generic locator.

    Accepted forms: ``kind=value`` (css, xpath, id, name, testid, tag, class, placeholder,
    title, alt, text, role), bare CSS (``#id``, ``.class``, ``[name="x"]``, ``input[name=x]``), bare
    XPath (``//div`` or ``(//div)[2]``), or any raw Playwright selector.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty locator")
    if text.startswith(("//", "(", "./", "..")):
        return Strategy("xpath", text, f"xpath={text}", origin)
    m = re.match(r"^([A-Za-z_][A-Za-z_-]*)\s*=\s*(.*)$", text, re.DOTALL)
    if m and m.group(1).lower() in _SHORTHAND_ENGINES:
        kind, value = m.group(1).lower(), m.group(2)
        if kind in ("text", "role"):
            return Strategy(kind, value, f"{kind}={value}", origin)
        return Strategy(kind, value, _SHORTHAND_ENGINES[kind](value), origin)
    if text.startswith(_PW_PASSTHROUGH):
        return Strategy(text.split("=", 1)[0], text, text, origin)
    return Strategy("css", text, f"css={text}", origin)


def parse_locator_list(text: str, origin: str = "sheet") -> list[Strategy]:
    """``a || b || c`` -> strategies in priority order."""
    return [parse_locator(part, origin) for part in re.split(r"\s*\|\|\s*", text.strip()) if part.strip()]
