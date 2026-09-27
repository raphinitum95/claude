"""Paths into an API response: JSONPath (``$.plans[?(@.code=='Basic')].eligible``) and XPath (``/Envelope/Body/Result/@id``).

The legacy runner only knew dotted JSON paths (``a.b.[0].c``, ``workbook/api.py``) and element paths searched anywhere in the response
(``a/b[2]/c``, ``workbook/api_template.py``).  The Workbook Builder (P10) writes paths the person can read and edit - a JSON path that starts with
``$`` and may pick "the item where code = {PLAN}", an XPath that may start at the document or end on an attribute - so the runner reads those too.
Legacy paths keep going through the legacy functions; only a path in the new forms comes here (``is_json_path`` / ``is_extended_xpath``).

Pure functions on parsed data: no network, no workbook.  XPath is the standard library's ``ElementTree`` subset (lxml is not a dependency: the
work computer cannot always install wheels) plus a trailing ``/@attr`` or ``/text()`` step and namespace prefixes (dropped, like the response's).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

MISSING = object()

# -- JSONPath ----------------------------------------------------------------------------------------------------------------------------------
_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$-]*")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILTER = re.compile(r"""^\?\(\s*@((?:\.[A-Za-z_][A-Za-z0-9_-]*|\[['"][^'"]*['"]\])+)\s*(==|!=)\s*(.+?)\s*\)$""")


def is_json_path(path: str) -> bool:
    """A JSONPath the legacy dotted reader cannot read: it starts with ``$`` or uses ``[n]`` / ``['key']`` / ``[?(...)]`` right after a name."""
    p = (path or "").strip()
    return p.startswith("$") or bool(re.search(r"[A-Za-z0-9_\]]\[", p))


def _parse(path: str) -> list[tuple[str, Any]]:
    """``$.a['b c'][0][?(@.k=='v')]`` -> ``[("key", "a"), ("key", "b c"), ("index", 0), ("filter", (["k"], "==", "v"))]``.  ``ValueError`` if unreadable."""
    p = (path or "").strip()
    if p.startswith("$"):
        p = p[1:]
    out: list[tuple[str, Any]] = []
    i = 0
    while i < len(p):
        ch = p[i]
        if ch == ".":
            i += 1
            if i < len(p) and p[i] == "[":                           # a.[0] (the legacy spelling) is a.[0]
                continue
            m = _NAME.match(p, i)
            if not m:
                raise ValueError(f"a name is expected after '.' at {i + 1}")
            out.append(("key", m.group(0)))
            i = m.end()
        elif ch == "[":
            end = _closing(p, i)
            inner = p[i + 1:end].strip()
            i = end + 1
            if inner.isdigit() or (inner.startswith("-") and inner[1:].isdigit()):
                out.append(("index", int(inner)))
            elif inner == "*":
                out.append(("all", None))
            elif inner[:1] in ("'", '"') and inner[-1:] == inner[:1]:
                out.append(("key", inner[1:-1]))
            elif inner.startswith("?"):
                m = _FILTER.match(inner)
                if not m:
                    raise ValueError(f"only [?(@.key=='value')] filters are understood, not [{inner}]")
                keys = [k for k in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)|\[['\"]([^'\"]*)['\"]\]", m.group(1))]
                out.append(("filter", ([a or b for a, b in keys], m.group(2), _literal(m.group(3)))))
            else:
                raise ValueError(f"[{inner}] is not an index, a 'key' or a filter")
        else:
            m = _NAME.match(p, i)                                      # a path without the leading $. (plans[0].code)
            if not m or out:
                raise ValueError(f"unexpected {ch!r} at {i + 1}")
            out.append(("key", m.group(0)))
            i = m.end()
    return out


def _closing(p: str, i: int) -> int:
    quote = ""
    depth = 0
    for j in range(i, len(p)):
        c = p[j]
        if quote:
            if c == quote:
                quote = ""
        elif c in ("'", '"'):
            quote = c
        elif c == "[" or c == "(":
            depth += 1
        elif c == "]" or c == ")":
            depth -= 1
            if depth == 0 and c == "]":
                return j
    raise ValueError("a '[' is not closed")


def _literal(text: str) -> Any:
    t = text.strip()
    if len(t) >= 2 and t[0] in ("'", '"') and t[-1] == t[0]:
        return t[1:-1]
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if low == "null":
        return None
    try:
        return int(t) if re.fullmatch(r"-?\d+", t) else float(t)
    except ValueError:
        return t


def _same(value: Any, wanted: Any) -> bool:
    """A filter compares loosely, the way a person reads the response: ``'5' == 5``, ``'true' == True``, text trimmed."""
    if value is None or wanted is None:
        return value is wanted
    if isinstance(value, bool) or isinstance(wanted, bool):
        return str(value).strip().lower() == str(wanted).strip().lower()
    if isinstance(value, (int, float)) or isinstance(wanted, (int, float)):
        try:
            return float(value) == float(wanted)
        except (TypeError, ValueError):
            return False
    return str(value).strip() == str(wanted).strip()


def json_path_all(data: Any, path: str) -> list[Any]:
    """Every value ``path`` finds (a filter or ``[*]`` can find several), in document order.  ``ValueError`` for a path that cannot be read."""
    nodes = [data]
    for kind, arg in _parse(path):
        found: list[Any] = []
        for node in nodes:
            if kind == "key":
                if isinstance(node, dict) and arg in node:
                    found.append(node[arg])
            elif kind == "index":
                if isinstance(node, list) and -len(node) <= arg < len(node):
                    found.append(node[arg])
            elif kind == "all":
                found.extend(node if isinstance(node, list) else list(node.values()) if isinstance(node, dict) else [])
            else:
                keys, op, wanted = arg
                for item in node if isinstance(node, list) else []:
                    value: Any = item
                    for k in keys:
                        value = value.get(k, MISSING) if isinstance(value, dict) else MISSING
                    if value is MISSING:
                        continue
                    if _same(value, wanted) == (op == "=="):
                        found.append(item)
        nodes = found
    return nodes


def json_path_first(data: Any, path: str) -> Any:
    """The first value ``path`` finds, ``MISSING`` when none (a JSON ``null`` is ``None``)."""
    try:
        found = json_path_all(data, path)
    except ValueError:
        return MISSING
    return found[0] if found else MISSING


def json_path_of(steps: list) -> str:
    """The JSONPath of a node from its keys / indexes: ``["plan", "code"]`` -> ``$.plan.code``, ``["a b", 0]`` -> ``$['a b'][0]``."""
    out = "$"
    for step in steps:
        if isinstance(step, int):
            out += f"[{step}]"
        elif _IDENT.match(str(step)):
            out += f".{step}"
        else:
            out += "['" + str(step).replace("'", "\\'") + "']"
    return out


def filter_literal(value: Any) -> str:
    """How a value is written inside ``[?(@.key==...)]``: text quoted, numbers and true/false as they are, ``{NAME}`` quoted (it is filled in first)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "") + "'"


# -- XPath -----------------------------------------------------------------------------------------------------------------------------------------
_PREFIX = re.compile(r"(?<![\w'\"@.:-])([A-Za-z_][\w.-]*):(?=[A-Za-z_*])")


def is_extended_xpath(path: str) -> bool:
    """An XPath the legacy ``Output`` reader (``.//`` + path in ElementTree) would read differently: it starts at the document (``/a``), ends on
    an attribute or ``text()``, or names a namespace prefix."""
    p = (path or "").strip()
    return p.startswith("/") or "/@" in p or p.startswith("@") or p.endswith("text()") or bool(_PREFIX.search(_outside_quotes(p)))


def _outside_quotes(text: str) -> str:
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", text)


def _drop_prefixes(path: str) -> str:
    parts = re.split(r"('[^']*'|\"[^\"]*\")", path)
    return "".join(part if i % 2 else _PREFIX.sub("", part) for i, part in enumerate(parts))


def xpath_all(root: ET.Element, path: str) -> list[str]:
    """The text of everything ``path`` finds in ``root`` (the wrapper ``xml_to_tree`` / ``json_to_tree`` make: the document element is its child).

    ``/a/b`` starts at the document element; ``//b`` and a path with no leading slash (``b/c``, the legacy ``Output`` form) look anywhere.  A last
    step ``@name`` gives that attribute, ``text()`` the element's text (the default).  ``ValueError`` for an expression ElementTree cannot read."""
    p = _drop_prefixes((path or "").strip())
    attr = ""
    m = re.search(r"/?@([\w.-]+)$", p)
    if m:
        attr, p = m.group(1), p[:m.start()]
    elif p.endswith("/text()"):
        p = p[:-len("/text()")]
    if p.startswith("//"):
        expr = ".//" + p[2:]
    elif p.startswith("/"):
        expr = "./" + p[1:]
    elif p in ("", "."):
        expr = "./*"
    else:
        expr = ".//" + p
    try:
        found = root.findall(expr)
    except (SyntaxError, KeyError, TypeError) as err:
        raise ValueError(f"{path!r} is not an XPath this runner can read ({err})") from None
    if attr:
        return [e.attrib[attr] for e in found if attr in e.attrib]
    return [e.text if e.text is not None else "" for e in found]


def xpath_of(steps: list[tuple[str, int, int]], attr: str = "") -> str:
    """The XPath of an element from its ``(tag, position among same-tag siblings from 1, how many such siblings)``: the position is written only
    when there are several (``/Envelope/Body/Plans/Plan[2]/Code``); ``attr`` ends it on an attribute."""
    out = "".join(f"/{tag}" + (f"[{pos}]" if count > 1 else "") for tag, pos, count in steps)
    return out + (f"/@{attr}" if attr else "")
