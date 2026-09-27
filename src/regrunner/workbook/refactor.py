"""Duplicate ("what changes?"), workbook-wide find and replace, and per-step merge of an outside edit (Q26, Q29).

Copy/paste of a step, a block or a whole test is composed entirely from the existing ``insert_step`` / ``add_variable`` /
``set_cell`` ops (a ``Step`` from the model already carries the same field names ``insert_step`` takes), so it needs no
Python of its own and lives in the Build tab's JS. What genuinely needs a server-side pass over the raw workbook - because
the model only shows *parsed steps*, not every literal cell of every sheet - lives here:

* ``find_replace_preview`` / hits -> ``set_cell`` ops: the mechanism behind both the free-form find & replace box and the
  "What changes?" panel's pre-filled rows (a duplicate's domain, environment and repeated text values are just find/replace
  pairs the user can tick on or off).
* ``duplicate_candidates``: guesses those rows from the model that is already loaded.
* ``merge_ops``: turns a person's per-row "theirs / mine" picks on a ``diff(against="disk")`` result into ``update_step``
  ops, so the workbook-changed-on-disk dialog can offer a per-step merge and not just reload-or-overwrite.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .builder import BuildError, INLINE_RE, RESULT_COLUMNS, _Grid, is_formula, text_of
from .writer import WorkbookEditor

_SKIP_HEADERS = RESULT_COLUMNS | {"STEP_NUMBER"}
_MIN_VALUE_LEN = 3


@dataclass
class Pair:
    find: str
    replace: str
    whole: bool = True


def _pairs(raw: list[dict]) -> list[Pair]:
    out = []
    for p in raw or []:
        find = str(p.get("find") or "")
        if not find:
            raise BuildError("Find text cannot be empty.")
        out.append(Pair(find, str(p.get("replace") or ""), bool(p.get("whole", True))))
    if not out:
        raise BuildError("Say what to find.")
    return out


def _matches(cell_text: str, pair: Pair) -> bool:
    if pair.whole:
        return cell_text.strip() == pair.find
    return pair.find in cell_text


def _replace(cell_text: str, pair: Pair) -> str:
    if pair.whole:
        return pair.replace
    return cell_text.replace(pair.find, pair.replace)


def find_replace_preview(editor: WorkbookEditor, pairs: list[dict]) -> list[dict]:
    """Every cell that matches one of ``pairs`` (``{find, replace, whole}``), across every sheet including the hidden
    ``_rr_*`` runner tables (a duplicate's domain lives in ``_rr_environments``).  Never touches row 1 (headers are
    structure, not data), the result columns of a test sheet, or a formula's literal text."""
    ps = _pairs(pairs)
    hits: list[dict] = []
    for sheet in editor.sheet_names():
        grid = _Grid(editor, sheet)
        skip_cols = {grid.cols[h] for h in _SKIP_HEADERS if h in grid.cols}
        for r in range(2, grid.max_row + 1):
            row = grid.rows[r - 1]
            for c, value in enumerate(row, start=1):
                if c in skip_cols or is_formula(value):
                    continue
                cell_text = text_of(value)
                if not cell_text:
                    continue
                for i, pair in enumerate(ps):
                    if _matches(cell_text, pair):
                        after = _replace(cell_text, pair)
                        if after != cell_text:
                            header = grid.header_names[c - 1] if c - 1 < len(grid.header_names) else ""
                            hits.append({"pair": i, "sheet": sheet, "row": r, "column": c, "header": header,
                                        "before": cell_text, "after": after})
                        break
    return hits


def apply_ops_for_hits(hits: list[dict]) -> list[dict]:
    """``set_cell`` ops for the hits a person kept ticked on."""
    return [{"op": "set_cell", "sheet": h["sheet"], "row": h["row"], "column": h["column"], "value": h["after"]} for h in hits]


# ---------------------------------------------------------------------------------------------
# Duplicate: "What changes?" (Q26)
# ---------------------------------------------------------------------------------------------
def most_used_values(model: dict, *, top: int = 8, min_count: int = 2) -> list[dict]:
    """The Value / Expected_Value text steps repeat most often (quoted literals, not ``{VAR}``\\ s or formulas):
    candidates for "this brand name / destination / plan appears N times, want to change it too?"."""
    counts: Counter[str] = Counter()
    for t in model.get("tests", []):
        for s in t.get("steps", []):
            for text in (s.get("value"), s.get("expected")):
                v = str(text or "").strip()
                if len(v) >= _MIN_VALUE_LEN and not INLINE_RE.fullmatch(v) and not is_formula(v) and not v.startswith("//"):
                    counts[v] += 1
    return [{"value": v, "count": c} for v, c in counts.most_common(top) if c >= min_count]


def duplicate_candidates(model: dict, new_name: str) -> list[dict]:
    """Seed rows for the "What changes?" panel: workbook name, each environment's domain, and repeated text values -
    each already the shape ``find_replace_preview`` takes, with ``replace`` left for the person to fill in."""
    rows: list[dict] = []
    old_name = re.sub(r"\.xlsx$", "", model.get("name") or "", flags=re.I)
    if old_name and new_name and old_name != new_name:
        rows.append({"kind": "name", "label": "Workbook name", "find": old_name, "replace": new_name, "whole": False})
    env = model.get("environments") or {}
    for row in env.get("rows", []):
        if row.get("variable", "").upper() == "DOMAIN":
            for name, value in row.get("values", {}).items():
                if value:
                    rows.append({"kind": "domain", "label": f"{name} domain", "find": value, "replace": "", "whole": True})
    for item in most_used_values(model):
        rows.append({"kind": "text", "label": f"“{item['value']}” ({item['count']} uses)", "find": item["value"],
                    "replace": "", "whole": True})
    return rows


# ---------------------------------------------------------------------------------------------
# Merge a per-step "theirs vs mine" pick into ops (file changed on disk, Q29)
# ---------------------------------------------------------------------------------------------
_MERGE_FIELDS = ("method", "name", "locator", "value", "expected", "enabled", "block")


def merge_ops(hits: list[dict], picks: dict[str, str]) -> list[dict]:
    """``hits``: the ``changes`` list of ``BuildDocument.diff("disk")`` (``before`` = the version on disk, ``after`` = the
    open draft). ``picks``: ``{"<test>:<row>": "theirs" | "mine"}``. Only ``kind == "changed"`` hits can be merged this
    way (an add/remove is a bigger structural difference than one cell: reload or save-anyway covers those)."""
    ops: list[dict] = []
    for h in hits:
        if h.get("kind") != "changed" or h.get("before") is None:
            continue
        key = f"{h['test']}:{h['row']}"
        if picks.get(key) != "theirs":
            continue
        before = h["before"]
        ops.append({"op": "update_step", "test": h["test"], "row": h["row"], "set": {f: before[f] for f in _MERGE_FIELDS}})
    return ops


def mergeable_hits(hits: list[dict]) -> list[dict]:
    """The subset of a diff a per-step merge can act on (see ``merge_ops``); the rest still needs reload/save-anyway."""
    return [h for h in hits if h.get("kind") == "changed" and h.get("before") is not None]
