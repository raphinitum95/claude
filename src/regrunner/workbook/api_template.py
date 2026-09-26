"""The template flavour of an API test: ``Replace`` fills the request template, ``Output`` reads values out of the response.

The legacy web-service runner built a request from a template file (JSON, or XML) and the ``InputOutput`` rows:

* ``Replace | placeholder | column``: every ``placeholder`` in the template is swapped for the text of that column of the test's row;
* ``Output | a/b[2]/c | column``: the response is turned into elements (a JSON key is an element) and the path is looked for in it.

Nothing here touches the network or the workbook: plain functions, tested on their own.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from .sheet import ErrorText, cell_text


def replacement_text(value: Any) -> str:
    """What goes into the template for a cell value: the legacy runner used Python's ``str()`` of the cell, so a TRUE cell is ``True``."""
    if isinstance(value, bool):
        return "True" if value else "False"
    return cell_text(value)


def apply_replacements(data: Any, replace: Mapping[str, str], values: Mapping[str, Any]) -> tuple[Any, int]:
    """The legacy ``replace_string`` for a JSON request: the template is written out as text, every ``Replace`` placeholder in it is swapped for the
    text of its column (in the order of the InputOutput rows; a column the sheet does not have is skipped - InputOutput serves several sheets)
    and the result is read back.  Returns ``(request, number of placeholders filled)``; ``ValueError`` says what could not be done."""
    text = json.dumps(data)
    filled = 0
    for placeholder, column in replace.items():
        key = column.strip().upper()
        if not placeholder or key not in values:
            continue
        count = text.count(placeholder)
        if not count:
            continue
        value = values[key]
        if isinstance(value, ErrorText):
            raise ValueError(f"the {column} cell evaluates to {value.code}" + (f" ({value.detail})" if value.detail else ""))
        text = text.replace(placeholder, json.dumps(replacement_text(value))[1:-1])         # (escaped: a quote in a value must not break the JSON)
        filled += count
    return json.loads(text), filled


def json_to_tree(data: Any, lower: bool = False) -> ET.Element:
    """The response as ``Output`` paths see it (the legacy ``json_to_xml``): a key is an element, a value is its text, the items of a list follow
    one another inside the element of their key (no element per item), ``None`` / ``True`` are the text ``None`` / ``True``.  ``lower``: the
    legacy runner parsed it as HTML (Global ``isHTMLParsing``), which writes every element name in lower case - that is why ``Output`` paths are
    lower case."""
    root = ET.Element("root")

    def text_of(value: Any) -> str:
        return "None" if value is None else str(value)

    def fill(parent: ET.Element, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                fill(ET.SubElement(parent, str(key).lower() if lower else str(key)), value)
        elif isinstance(node, list):
            for item in node:
                fill(parent, item)
        else:
            parent.text = (parent.text or "") + text_of(node)

    fill(root, data)
    return root


def xml_to_tree(text: str) -> ET.Element | None:
    """An XML response for ``Output`` paths (namespaces dropped); ``None`` when it is not XML."""
    try:
        parsed = ET.fromstring(text.strip())
    except ET.ParseError:
        return None
    for element in parsed.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.rsplit("}", 1)[1]
    root = ET.Element("root")
    root.append(parsed)
    return root


def _blank(text: str) -> bool:
    return text.strip().upper() in ("", "NONE")


def output_values(root: ET.Element, paths: Mapping[str, str], *, strip: bool = False) -> list[tuple[str, str, str]]:
    """``(path, column, value)`` for every ``Output`` path that finds something, in InputOutput order (the legacy ``input_value_to_sheet``): the path is
    looked for anywhere in the response (``//path``); several matches are joined with ``;``; ``path/index:=N`` takes the N-th match (from 0); an
    element with no text, or a path that finds nothing, stores nothing."""
    found: list[tuple[str, str, str]] = []
    for path, column in paths.items():
        node, index = path, None
        if "/index:=" in path:
            node, _, raw = path.partition("/index:=")
            index = int(raw) if raw.strip().isdigit() else None
        try:
            matches = root.findall(".//" + node)
        except Exception:                                        # an expression that cannot be read: skipped, like the legacy runner
            continue
        if index is not None:
            matches = matches[index:index + 1]
        joined = ""
        for element in matches:
            value = element.text if element.text is not None else "None"
            if strip:
                value = value.strip()
            joined = value if _blank(joined) else f"{joined};{value}"
        if not _blank(joined):
            found.append((path, column, joined))
    return found
