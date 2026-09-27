"""Shared template library (Q15-17): named groups of steps saved from one test and inserted into others.

Saving a section as a template is an enhanced copy-paste: inserting one *copies* its steps, and later edits to either side
never spread to the other. The library is one workbook, ``templates.xlsx`` next to the real workbooks, one sheet per
template using the same 26 step columns a test sheet has. A template step writes ``{TOKEN}`` for every variable it read
from Params in the source test (CONTRACT.md 1.2), so inserting it anywhere means mapping those tokens onto the target
workbook's own variables (exact name, a close match, or a brand new Params column); anything left unmapped becomes
``{?TOKEN}``, which the builder already treats as a problem (``unmapped_template_variable``).

This module only ever produces *ops* for ``workbook/builder.py``'s existing ``apply_ops`` (``add_variable``, ``insert_step``):
inserting a template never needs a new op kind, so the file this touches stays entirely within ``BuildDocument.apply``'s
normal undo/draft flow.
"""
from __future__ import annotations

import difflib
import io
import re
import zipfile
from pathlib import Path
from typing import Any

from .builder import FIELD_COLUMNS, INLINE_RE, STANDARD_COLUMNS, TOKEN_RE, BuildError, _Ops, make_token, parse_test_sheet, text_of
from .writer import WorkbookEditor

TEMPLATES_FILE = "templates.xlsx"
META_SHEET = "_rr_templates_meta"
_RESERVED_SHEETS = {"SHEET1", META_SHEET.upper()}

# A minimal, valid .xlsx package (mirrors builder.new_workbook's bootstrap): one blank sheet, nothing else.  Kept local
# rather than importing builder's private ``_NEW_PARTS`` so this module does not depend on another phase's internals.
_EMPTY_PARTS = {
    "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>',
    "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
    "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<bookViews><workbookView/></bookViews><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
    "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>',
    "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><dimension ref="A1"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/><sheetData/>'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>',
}


def templates_path(workbooks_dir: str | Path) -> Path:
    return Path(workbooks_dir) / TEMPLATES_FILE


def _bootstrap(path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for part, text in _EMPTY_PARTS.items():
            z.writestr(part, text)
    WorkbookEditor(path, buf.getvalue(), None).save_as(path)


def open_library(path: str | Path, *, create: bool = True) -> WorkbookEditor:
    """The shared template library, opened for editing.  ``create``: bootstrap an empty one if it does not exist yet."""
    path = Path(path)
    if not path.is_file():
        if not create:
            raise FileNotFoundError(str(path))
        _bootstrap(path)
    return WorkbookEditor.open(path)


# ---------------------------------------------------------------------------------------------
# Metadata (description per template): a small hidden table, same shape idea as builder's _rr_ tables
# ---------------------------------------------------------------------------------------------
def _read_meta(editor: WorkbookEditor) -> dict[str, str]:
    name = next((s for s in editor.sheet_names() if s.upper() == META_SHEET.upper()), None)
    if name is None:
        return {}
    rows = editor.rows(name)
    if not rows:
        return {}
    header = {text_of(v).strip().upper(): i for i, v in enumerate(rows[0])}
    ni, di = header.get("NAME"), header.get("DESCRIPTION")
    out: dict[str, str] = {}
    for r in rows[1:]:
        if ni is None or ni >= len(r):
            continue
        nm = text_of(r[ni]).strip()
        if nm:
            out[nm.upper()] = text_of(r[di]).strip() if di is not None and di < len(r) else ""
    return out


def _write_meta(editor: WorkbookEditor, name: str, description: str) -> None:
    editor.ensure_rr_sheet(META_SHEET)
    current = _read_meta(editor)
    current[name.upper()] = description
    rows = [["Name", "Description"]] + [[n, d] for n, d in current.items()]
    editor.write_table(META_SHEET, rows)


# ---------------------------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------------------------
def list_templates(path: str | Path) -> list[dict]:
    """Every template in the library (``[]`` if the library does not exist yet)."""
    path = Path(path)
    if not path.is_file():
        return []
    editor = WorkbookEditor.open(path)
    meta = _read_meta(editor)
    out = []
    for name in editor.sheet_names():
        if name.upper() in _RESERVED_SHEETS or name.upper().startswith("_RR_"):
            continue
        parsed = parse_test_sheet(editor, name, variables=set())
        tokens = sorted({u["token"] for s in parsed["steps"] for u in s["uses"] if u["form"] == "inline"})
        out.append({"name": name, "description": meta.get(name.upper(), ""), "count": len(parsed["steps"]),
                    "variables": tokens, "steps": parsed["steps"]})
    out.sort(key=lambda t: t["name"].lower())
    return out


def get_template(path: str | Path, name: str) -> dict:
    for t in list_templates(path):
        if t["name"].upper() == str(name).upper():
            return t
    raise BuildError(f"No template called {name!r}.", "not_found", 404)


def delete_template(path: str | Path, name: str) -> None:
    """Not supported yet: ``WorkbookEditor`` has no way to remove a sheet.  Remove it with Excel, or overwrite it by
    saving a new template with the same name once ``save_as_template`` allows replacing (it does not yet either)."""
    editor = open_library(path, create=False)
    if not any(s.upper() == str(name).upper() for s in editor.sheet_names()):
        raise BuildError(f"No template called {name!r}.", "not_found", 404)
    raise BuildError(f"Deleting a template is not supported yet. Remove the {name!r} sheet from {Path(path).name} in "
                     "Excel instead.", "unsupported", 400)


# ---------------------------------------------------------------------------------------------
# Saving a section as a template
# ---------------------------------------------------------------------------------------------
def _templatize(value: str, uses: list[dict]) -> str:
    """The whole-cell Params token this cell equals (if any) written as ``{TOKEN}``; anything already ``{TOKEN}`` or plain
    text is left as it is."""
    v = str(value or "")
    for u in uses:
        if u["form"] == "cell" and v.strip().upper() == u["token"]:
            return "{" + u["token"] + "}"
    return v


def _template_fields(step: dict) -> dict:
    uses = step.get("uses") or []
    fields: dict[str, Any] = {
        "method": step["method"], "page": step["page"], "findBy": step["locator"]["findBy"],
        "locator": _templatize(step["locator"]["value"], uses), "locatorName": step["locator"]["name"],
        "value": _templatize(step["value"], uses), "expected": _templatize(step["expected"], uses),
        "match": step["match"], "output": step["output"], "outputProperty": step["outputProperty"],
        "onFail": step["onFail"], "timeout": step["timeout"], "enabled": step["enabled"] if step["enabled"] is not None else True,
        "sideEffects": step["sideEffects"], "notes": step["notes"],
    }
    if step["locator"]["index"]:
        fields["index"] = step["locator"]["index"]
    if not step["nameAuto"] and step["name"]:
        fields["name"] = step["name"]
    else:
        fields["nameAuto"] = True
    return fields


def save_as_template(model: dict, library_path: str | Path, *, test_id: str, from_row: int, to_row: int, name: str,
                     description: str = "") -> dict:
    """Save the steps of ``test_id`` between ``from_row`` and ``to_row`` (inclusive) as a template called ``name``."""
    name = str(name or "").strip()
    if not name:
        raise BuildError("A template needs a name.")
    test = next((t for t in model["tests"] if t["id"] == test_id), None)
    if test is None:
        raise BuildError(f"No test called {test_id!r} in this workbook.", "not_found", 404)
    steps = [s for s in test["steps"] if int(from_row) <= s["row"] <= int(to_row)]
    if not steps:
        raise BuildError("No steps in that range.")
    editor = open_library(library_path)
    if editor.has_sheet(name):
        raise BuildError(f"A template called {name!r} already exists.", "exists", 409)
    editor.add_sheet(name)
    for c, h in enumerate(STANDARD_COLUMNS, start=1):
        editor.set(name, 1, c, h)
    ops = _Ops(editor)
    for i, step in enumerate(steps, start=2):
        ops.write_fields(name, i, _template_fields(step))
    _write_meta(editor, name, description)
    editor.save()
    return {"name": name, "count": len(steps)}


# ---------------------------------------------------------------------------------------------
# Inserting: mapping the template's variables onto the target workbook, then ops for /edit
# ---------------------------------------------------------------------------------------------
def match_variables(template_tokens: list[str], workbook_variables: list[dict]) -> list[dict]:
    """One row per template token: ``mine`` names the workbook variable to use (``None`` = create a new one), ``how``
    explains why (Q15-17's mapping dialog: exact, close match, or no match)."""
    by_token = {v["key"]: v for v in workbook_variables}
    by_label = {v["label"].lower(): v for v in workbook_variables}
    labels = list(by_label)
    out = []
    for tok in template_tokens:
        key = tok.upper()
        if key in by_token:
            out.append({"templateVar": tok, "label": by_token[key]["label"], "mine": by_token[key]["token"], "how": "same name"})
            continue
        guess_label = re.sub(r"_", " ", key).strip().lower()
        close = difflib.get_close_matches(guess_label, labels, n=1, cutoff=0.6)
        if close:
            v = by_label[close[0]]
            out.append({"templateVar": tok, "label": v["label"], "mine": v["token"], "how": f"close match: {v['token']}"})
            continue
        out.append({"templateVar": tok, "label": tok, "mine": None, "how": "no match"})
    return out


def insert_template_ops(template: dict, *, mapping: dict[str, str | None], test_id: str, param_sheet: str | None,
                        after: int | None = None, before: int | None = None) -> list[dict]:
    """Ops for the existing ``/edit`` endpoint (``add_variable`` for a mapping that creates a new column, then
    ``insert_step`` for every template step, its ``{TVAR}``\\ s rewritten to the mapped token or ``{?TVAR}``)."""
    if after is None and before is None:
        raise BuildError("Say where to insert the template (after or before a row).")
    ops: list[dict] = []
    create_cols: dict[str, str] = {}
    for tok, mapped in mapping.items():
        if mapped:
            continue
        col = make_token(tok)
        if param_sheet:
            ops.append({"op": "add_variable", "token": col, "sheet": param_sheet})
        create_cols[tok.upper()] = col if param_sheet else None

    def rewrite(text: str) -> str:
        def sub(m: "re.Match[str]") -> str:
            tok = m.group(1).upper()
            mapped = mapping.get(tok) or create_cols.get(tok)
            return "{" + mapped + "}" if mapped else "{?" + tok + "}"
        return INLINE_RE.sub(sub, text or "")

    anchor = int(after) if after is not None else int(before) - 1
    for i, step in enumerate(template["steps"]):
        fields = dict(_template_fields(step))
        for key in ("value", "expected", "locator"):
            if fields.get(key):
                fields[key] = rewrite(fields[key])
        ops.append({"op": "insert_step", "test": test_id, "after": anchor + i, "step": fields})
    return ops
