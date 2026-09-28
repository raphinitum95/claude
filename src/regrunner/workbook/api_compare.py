"""The whole-response check of an API test (``compare_response``, feedback item 14): the entire response body against an expected body, except
the fields the person says change on every call (a timestamp, a generated id).

Comparing the whole body catches what a handful of value checks miss (a field that disappeared, one that appeared, a list that grew), but a real
response always carries values that differ from one call to the next.  So the check takes an "ignore these fields" list, each entry one of:

* a field name on its own (``timestamp``, ``id``, ``@id``): that field wherever it is, at any depth;
* a JSONPath (``$.meta.requestId``, ``$.items[*].id``, ``$.items.id``): that node and everything under it.  A list index may be left out
  (``$.items.id`` = the ``id`` of every item) or written as ``[*]`` / ``[2]``; a legacy dotted path (``meta.requestId``) reads the same way;
* an XPath (``/Envelope/Body/Quote/@created``, ``/Envelope/Body/Plan[2]/Price``, ``//Stamp``): likewise, positions optional, ``//name``
  anywhere.

JSON is compared as data (key order does not matter; list order does; ``1`` equals ``1.0``); XML as elements (namespaces dropped like every
other reading of a response: tag, attributes, trimmed text, children in order); anything else as text with its white space squeezed.  Pure
functions: no network, no workbook.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from .api_template import xml_to_tree

MAX_DIFFERENCES = 50                    # differences kept for the report (the count is always the real one)
_STEP = re.compile(r"\[\s*(\*|-?\d+|'[^']*'|\"[^\"]*\")\s*\]|\.?([^.\[\]/]+)")


@dataclass
class ResponseComparison:
    differences: list[str] = field(default_factory=list)      # "$.plan.price: expected 12.5, got 13" (the first MAX_DIFFERENCES)
    count: int = 0                                            # how many there are in all
    ignored: int = 0                                          # how many nodes the ignore list left out
    problem: str = ""                                         # the expected body could not be read (not JSON / XML): the check fails with it

    @property
    def same(self) -> bool:
        return not self.problem and self.count == 0

    def add(self, text: str) -> None:
        self.count += 1
        if len(self.differences) < MAX_DIFFERENCES:
            self.differences.append(text)


def ignore_list(text: str | list | None) -> list[str]:
    """``"timestamp; $.meta.id"`` (as the ``ignore_in_response`` row holds it; ``;``, ``,`` or new lines between) -> the entries."""
    if isinstance(text, list):
        items = text
    else:
        items = re.split(r"[;\n,]", str(text or ""))
    return [i.strip() for i in items if str(i).strip()]


# -- the ignore list, as patterns ---------------------------------------------------------------------------------------------------------------
# A node's path is a list of steps: a key / tag (str), a list index or an element's position (int, from 0 for JSON and from 1 for XML), an
# attribute ("@id").  A pattern is the same list with "*" for any index / tag, or ("name", <field>) for a field name matched anywhere.
def _pattern(entry: str, xml: bool) -> tuple:
    e = entry.strip()
    if e.startswith("//"):
        return ("name", e[2:].split("/")[-1])
    if not re.search(r"[.\[\]/$]", e):
        return ("name", e)
    steps: list[Any] = []
    if xml or e.startswith("/"):
        for part in [p for p in e.split("/") if p]:
            m = re.match(r"^([^\[]+)(?:\[\s*(\*|\d+)\s*\])?$", part.strip())
            if not m:
                steps.append(part.strip())
                continue
            steps.append(m.group(1).split(":")[-1])                       # (a namespace prefix is dropped, like the response's)
            if m.group(2):
                steps.append("*" if m.group(2) == "*" else int(m.group(2)))
        return ("path", steps)
    e = e[1:] if e.startswith("$") else e
    for m in _STEP.finditer(e):
        index, name = m.group(1), m.group(2)
        if index is not None:
            steps.append("*" if index == "*" else index[1:-1] if index[:1] in "'\"" else int(index))
        elif name is not None and name.strip():
            steps.append(name.strip())
    return ("path", steps)


def _matches(pattern: tuple, node: list) -> bool:
    kind, value = pattern
    if kind == "name":
        want = value.lstrip("@").lower()
        return any(s.lstrip("@").lower() == want for s in node if isinstance(s, str))
    return _prefix(value, node)


def _prefix(pat: list, node: list) -> bool:
    """Does ``pat`` name ``node`` or one of its parents?  An index the pattern leaves out matches every index."""
    if not pat:
        return True
    if not node:
        return False
    head, step = pat[0], node[0]
    if isinstance(step, int):
        if head == "*" or (isinstance(head, int) and head == step):
            return _prefix(pat[1:], node[1:])
        return _prefix(pat, node[1:]) if isinstance(head, str) else False
    if isinstance(head, str) and (head == step or head == "*" and not step.startswith("@")):
        return _prefix(pat[1:], node[1:])
    return False


# -- JSON -------------------------------------------------------------------------------------------------------------------------------------
def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "…"


def _json_path(steps: list) -> str:
    out = "$"
    for s in steps:
        out += f"[{s}]" if isinstance(s, int) else f".{s}" if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s) else "['" + s + "']"
    return out


def _same_scalar(a: Any, b: Any) -> bool:
    numbers = (int, float)
    if isinstance(a, numbers) and isinstance(b, numbers) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return type(a) is type(b) and a == b


def _diff_json(exp: Any, act: Any, steps: list, patterns: list, out: ResponseComparison) -> None:
    if steps and any(_matches(p, steps) for p in patterns):
        out.ignored += 1
        return
    where = _json_path(steps)
    if isinstance(exp, dict) and isinstance(act, dict):
        for key in list(exp) + [k for k in act if k not in exp]:
            here = steps + [str(key)]
            if key not in act or key not in exp:
                if any(_matches(p, here) for p in patterns):
                    out.ignored += 1
                elif key not in act:
                    out.add(f"{_json_path(here)}: missing (expected {_shown(exp[key])})")
                else:
                    out.add(f"{_json_path(here)}: not expected (got {_shown(act[key])})")
                continue
            _diff_json(exp[key], act[key], here, patterns, out)
    elif isinstance(exp, list) and isinstance(act, list):
        for i in range(max(len(exp), len(act))):
            here = steps + [i]
            if i >= len(act) or i >= len(exp):
                if any(_matches(p, here) for p in patterns):
                    out.ignored += 1
                elif i >= len(act):
                    out.add(f"{_json_path(here)}: missing (the list has {len(act)} items, {len(exp)} expected)")
                else:
                    out.add(f"{_json_path(here)}: not expected (the list has {len(act)} items, {len(exp)} expected)")
                continue
            _diff_json(exp[i], act[i], here, patterns, out)
    elif isinstance(exp, (dict, list)) or isinstance(act, (dict, list)):
        out.add(f"{where}: expected {_shown(exp)}, got {_shown(act)}")
    elif not _same_scalar(exp, act):
        out.add(f"{where}: expected {_shown(exp)}, got {_shown(act)}")


# -- XML --------------------------------------------------------------------------------------------------------------------------------------
def _xml_path(steps: list) -> str:
    out = ""
    for s in steps:
        out += (f"[{s}]" if s > 1 else "") if isinstance(s, int) else f"/{s}"          # (a first position is left out, like XPath)
    return out or "/"


def _positions(children: list[ET.Element]) -> list[int]:
    seen: dict[str, int] = {}
    out = []
    for c in children:
        seen[c.tag] = seen.get(c.tag, 0) + 1
        out.append(seen[c.tag])
    return out


def _diff_xml(exp: ET.Element, act: ET.Element, steps: list, patterns: list, out: ResponseComparison) -> None:
    if any(_matches(p, steps) for p in patterns):
        out.ignored += 1
        return
    where = _xml_path(steps)
    if exp.tag != act.tag:
        out.add(f"{where}: expected <{exp.tag}>, got <{act.tag}>")
        return
    for name in list(exp.attrib) + [n for n in act.attrib if n not in exp.attrib]:
        here = steps + ["@" + name]
        if any(_matches(p, here) for p in patterns):
            out.ignored += 1
        elif name not in act.attrib:
            out.add(f"{_xml_path(here)}: missing (expected {_shown(exp.attrib[name])})")
        elif name not in exp.attrib:
            out.add(f"{_xml_path(here)}: not expected (got {_shown(act.attrib[name])})")
        elif exp.attrib[name] != act.attrib[name]:
            out.add(f"{_xml_path(here)}: expected {_shown(exp.attrib[name])}, got {_shown(act.attrib[name])}")
    e_text, a_text = (exp.text or "").strip(), (act.text or "").strip()
    if e_text != a_text and not (len(exp) and len(act) and not e_text and not a_text):
        out.add(f"{where}: expected {_shown(e_text)}, got {_shown(a_text)}")
    e_kids, a_kids = list(exp), list(act)
    e_pos, a_pos = _positions(e_kids), _positions(a_kids)
    for i in range(max(len(e_kids), len(a_kids))):
        kid = e_kids[i] if i < len(e_kids) else a_kids[i]
        here = steps + [kid.tag, (e_pos if i < len(e_kids) else a_pos)[i]]
        if i >= len(a_kids) or i >= len(e_kids):
            if any(_matches(p, here) for p in patterns):
                out.ignored += 1
            elif i >= len(a_kids):
                out.add(f"{_xml_path(here)}: missing")
            else:
                out.add(f"{_xml_path(here)}: not expected")
            continue
        _diff_xml(e_kids[i], a_kids[i], here, patterns, out)


# -- the check --------------------------------------------------------------------------------------------------------------------------------
def compare_response(expected: str, actual_text: str, *, ignore: str | list | None = None, actual_data: Any = None,
                     actual_is_json: bool | None = None) -> ResponseComparison:
    """The expected body (as typed in the expected column, ``{NAME}``s already filled in) against the response.  ``actual_data``: the response
    as JSON when it is JSON (read once by the runner); otherwise it is parsed here.  The result says every difference the ignore list does not
    cover."""
    out = ResponseComparison()
    expected = (expected or "").strip()
    actual_text = actual_text or ""
    if actual_is_json is None:
        try:
            actual_data = json.loads(actual_text) if actual_text.strip() else None
            actual_is_json = actual_data is not None
        except ValueError:
            actual_is_json = False
    entries = ignore_list(ignore)
    if actual_is_json:
        try:
            wanted = json.loads(expected) if expected else None
        except ValueError as err:
            out.problem = f"the expected response is not valid JSON ({err}), and the response is JSON"
            return out
        _diff_json(wanted, actual_data, [], [_pattern(e, False) for e in entries], out)
        return out
    act_tree = xml_to_tree(actual_text)
    if act_tree is not None and len(act_tree):
        exp_tree = xml_to_tree(expected)
        if exp_tree is None or not len(exp_tree):
            out.problem = "the expected response is not valid XML, and the response is XML"
            return out
        _diff_xml(exp_tree[0], act_tree[0], [exp_tree[0].tag], [_pattern(e, True) for e in entries], out)
        return out
    squeeze = lambda t: " ".join(t.split())
    if squeeze(expected) != squeeze(actual_text):
        out.add(f"the response text differs: expected {_shown(squeeze(expected))}, got {_shown(squeeze(actual_text))}")
    return out
