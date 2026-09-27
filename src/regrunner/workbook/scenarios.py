"""Concurrency scenarios (Q35/Q36): several tests - or one test twice with its own data row - run as one unit, in lanes, with sync points.

A scenario lives in the hidden ``_rr_scenarios`` table (CONTRACT.md 1.4), one row per item:

    Scenario | Item | Name | Lane | Test | DataRow | Block | Then | ThenBlock | Timeout | Execute | Notes

* ``Item = scenario``: the scenario itself.  ``Execute`` Y/N (blank = Y): a plain run of the workbook includes it; ``Timeout`` = how long a lane
  waits at a sync point or an order marker (seconds without the other lanes moving on, blank = 120); ``Notes`` = what it is for.
* ``Item = lane``: ``Lane`` = its letter (A, B...), ``Test`` = the test sheet, ``DataRow`` = the Params row (an API test: its data row) the lane
  uses (blank = the test's first enabled one), ``Name`` = a label ("agent Ana").
* ``Item = sync``: "all wait here".  One row per lane that takes part, all with the same ``Name``: ``Lane`` waits after block ``Block`` (blank =
  before its first step) until every other lane of the sync is there, or has ended.  ``Timeout`` overrides the scenario's.
* ``Item = order``: "A before B".  Lane ``Lane`` must finish block ``Block`` (blank = the whole lane) before lane ``Then`` starts block
  ``ThenBlock`` (blank = its first step).

Blocks are named by title (CONTRACT.md 1.5), ``Title#2`` for the second block with that title: rows move whenever a step is inserted, a block's
title does not.  A lane that fails, stops or times out *ends*, and an ended lane counts as arrived everywhere: one failure never hangs the others.

This module is the file format, the Build tab's board (``board``), its problems and its ops (``set_scenario`` / ``delete_scenario``, registered
into ``builder.EXTRA_OPS``).  Running a scenario is ``engine/scenario.py``.  Nothing here reads a secret's value: a shared sign-in is compared by
a hash of the key (``totp.fingerprint``), and only lane letters leave this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import builder as B
from .writer import WorkbookEditor

RR_SCENARIOS = B.RR_SCENARIOS
HEADERS = ("Scenario", "Item", "Name", "Lane", "Test", "DataRow", "Block", "Then", "ThenBlock", "Timeout", "Execute", "Notes")
ITEMS = ("scenario", "lane", "sync", "order")
DEFAULT_TIMEOUT_S = 120
LANE_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
END = float("inf")                   # a point at the end of a lane: reached only when the lane has ended
LANE_SEPARATOR = " · "               # a lane's test id in a run: "<scenario> · <lane>" (never "/": ids travel in URL paths)


def lane_id(scenario: str, key: str) -> str:
    return f"{scenario}{LANE_SEPARATOR}{key}"


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The table <-> plain definitions
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _num(value: Any) -> int | None:
    text = B.text_of(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def read_definitions(rows: list[list[Any]]) -> list[dict]:
    """The scenarios of a ``_rr_scenarios`` table (``rows`` = the sheet's rows, header first), in the order they first appear.
    Each: ``{name, enabled, timeout, notes, lanes: [{key, test, dataRow, label}], syncs: [{name, timeout, points: [{lane, block}]}],
    orders: [{name, timeout, first: {lane, block}, then: {lane, block}}]}``."""
    if not rows:
        return []
    header = {B.text_of(v).strip().upper(): i for i, v in enumerate(rows[0]) if B.text_of(v).strip()}

    def cell(r: list[Any], name: str) -> str:
        i = header.get(name.upper())
        return B.text_of(r[i]).strip() if i is not None and i < len(r) else ""

    out: dict[str, dict] = {}
    for r in rows[1:]:
        name = cell(r, "Scenario")
        item = cell(r, "Item").lower()
        if not name or item not in ITEMS:
            continue
        sc = out.setdefault(name.upper(), {"name": name, "enabled": True, "timeout": None, "notes": "", "lanes": [], "syncs": [], "orders": []})
        if item == "scenario":
            sc["enabled"] = cell(r, "Execute").upper() not in ("N", "NO", "FALSE", "0")
            sc["timeout"], sc["notes"] = _num(cell(r, "Timeout")), cell(r, "Notes")
        elif item == "lane":
            key = cell(r, "Lane").upper()
            if key and not any(l["key"] == key for l in sc["lanes"]):
                sc["lanes"].append({"key": key, "test": cell(r, "Test"), "dataRow": _num(cell(r, "DataRow")), "label": cell(r, "Name")})
        elif item == "sync":
            sync_name = cell(r, "Name") or f"Sync {len(sc['syncs']) + 1}"
            sync = next((s for s in sc["syncs"] if s["name"].upper() == sync_name.upper()), None)
            if sync is None:
                sync = {"name": sync_name, "timeout": None, "points": []}
                sc["syncs"].append(sync)
            sync["timeout"] = _num(cell(r, "Timeout")) or sync["timeout"]
            if cell(r, "Lane"):
                sync["points"].append({"lane": cell(r, "Lane").upper(), "block": cell(r, "Block")})
        elif item == "order":
            sc["orders"].append({"name": cell(r, "Name") or f"{cell(r, 'Lane').upper()} before {cell(r, 'Then').upper()}",
                                 "timeout": _num(cell(r, "Timeout")),
                                 "first": {"lane": cell(r, "Lane").upper(), "block": cell(r, "Block")},
                                 "then": {"lane": cell(r, "Then").upper(), "block": cell(r, "ThenBlock")}})
    return list(out.values())


def table_rows(definitions: list[dict]) -> list[list[Any]]:
    """The ``_rr_scenarios`` table (header first) that ``read_definitions`` reads back as ``definitions``."""
    rows: list[list[Any]] = [list(HEADERS)]

    def row(**cells: Any) -> None:
        rows.append([cells.get(h, None) for h in HEADERS])

    for sc in definitions:
        name = sc["name"]
        row(Scenario=name, Item="scenario", Timeout=sc.get("timeout") or None, Execute="Y" if sc.get("enabled", True) else "N",
            Notes=sc.get("notes") or None)
        for lane in sc.get("lanes", []):
            row(Scenario=name, Item="lane", Lane=lane["key"], Test=lane.get("test") or None, DataRow=lane.get("dataRow") or None,
                Name=lane.get("label") or None)
        for sync in sc.get("syncs", []):
            for p in sync.get("points", []):
                row(Scenario=name, Item="sync", Name=sync["name"], Lane=p["lane"], Block=p.get("block") or None, Timeout=sync.get("timeout") or None)
        for o in sc.get("orders", []):
            row(Scenario=name, Item="order", Name=o.get("name") or None, Lane=o["first"]["lane"], Block=o["first"].get("block") or None,
                Then=o["then"]["lane"], ThenBlock=o["then"].get("block") or None, Timeout=o.get("timeout") or None)
    return rows


def read_scenarios(editor: WorkbookEditor) -> list[dict]:
    name = B._sheet_key(editor, RR_SCENARIOS)
    return read_definitions(editor.rows(name)) if name else []


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Blocks as anchors
# ---------------------------------------------------------------------------------------------------------------------------------------------
def block_refs(blocks: list[dict]) -> list[str]:
    """How each block is named in the table: its title, ``Title#2`` for the second block with the same title..."""
    seen: dict[str, int] = {}
    out = []
    for b in blocks:
        k = b["title"].upper()
        seen[k] = seen.get(k, 0) + 1
        out.append(b["title"] if seen[k] == 1 else f"{b['title']}#{seen[k]}")
    return out


def find_block(blocks: list[dict], ref: str) -> int | None:
    """The index of the block ``ref`` names (case-insensitive), or None."""
    want = ref.strip().upper()
    for i, r in enumerate(block_refs(blocks)):
        if r.upper() == want:
            return i
    m = re.fullmatch(r"(.*)#1", want)
    return find_block(blocks, m.group(1)) if m else None


def after_block(blocks: list[dict], ref: str) -> float | None:
    """The row a lane reaches when it has finished block ``ref``: the first row of the next block (END after the last one).  Blank ref = 0
    (before the first step).  None = no such block."""
    if not ref.strip():
        return 0
    i = find_block(blocks, ref)
    if i is None:
        return None
    return blocks[i + 1]["firstRow"] if i + 1 < len(blocks) else END


def before_block(blocks: list[dict], ref: str) -> float | None:
    """The row a lane reaches when it is about to start block ``ref`` (blank = its first step).  None = no such block."""
    if not ref.strip():
        return 0
    i = find_block(blocks, ref)
    return None if i is None else blocks[i]["firstRow"]


@dataclass
class Point:
    """Where a lane meets a sync or an order marker: reached when the lane is about to run a row >= ``at`` (or has ended)."""
    lane: str
    at: float
    role: str                        # sync (wait until everyone is there) | first (A's part of "A before B") | then (B's part: wait for A)
    item: str                        # the sync's / marker's name
    block: str = ""                  # as written (for messages)
    timeout: float = DEFAULT_TIMEOUT_S


@dataclass
class Resolved:
    """A scenario with every block reference turned into rows: what the engine runs and what deadlock detection reads."""
    name: str
    timeout: float
    lanes: list[str]
    points: list[Point] = field(default_factory=list)
    syncs: dict[str, list[str]] = field(default_factory=dict)             # sync name -> the lanes in it
    orders: dict[str, tuple[str, str]] = field(default_factory=dict)      # marker name -> (first lane, then lane)
    problems: list[dict] = field(default_factory=list)


def resolve(definition: dict, blocks_of: dict[str, list[dict] | None]) -> Resolved:
    """``blocks_of``: lane key -> that lane's test's blocks (None: the test does not exist; [] for an API test, which has no blocks).  Problems
    say what cannot be resolved; the points that can be are kept."""
    timeout = float(definition.get("timeout") or DEFAULT_TIMEOUT_S)
    lanes = [l["key"] for l in definition.get("lanes", [])]
    out = Resolved(name=definition["name"], timeout=timeout, lanes=lanes)

    def problem(severity: str, kind: str, message: str) -> None:
        out.problems.append({"severity": severity, "kind": kind, "message": message})

    def at(lane: str, ref: str, where: str, how) -> float | None:
        if lane not in lanes:
            problem("error", "scenario_unknown_lane", f'{where} names lane {lane or "(none)"}, which this scenario does not have.')
            return None
        blocks = blocks_of.get(lane)
        if blocks is None:
            return None                                               # (the lane's own problem already says the test is missing)
        row = how(blocks, ref)
        if row is None:
            problem("error", "scenario_unknown_block", f'{where}: lane {lane}\'s test has no block called "{ref}".')
        return row

    for sync in definition.get("syncs", []):
        t = float(sync.get("timeout") or timeout)
        keys = []
        for p in sync.get("points", []):
            row = at(p["lane"], p.get("block", ""), sync["name"], after_block)
            if row is not None:
                out.points.append(Point(p["lane"], row, "sync", sync["name"], p.get("block", ""), t))
            keys.append(p["lane"])
        out.syncs[sync["name"]] = keys
        if len(set(keys)) < 2:
            problem("warning", "scenario_sync_one_lane", f'{sync["name"]} has {len(set(keys))} lane{"" if len(set(keys)) == 1 else "s"}: '
                                                         "a sync line needs at least two lanes to mean anything.")
    for o in definition.get("orders", []):
        t = float(o.get("timeout") or timeout)
        a, b = o["first"]["lane"], o["then"]["lane"]
        first = at(a, o["first"].get("block", ""), o["name"], lambda bl, ref: after_block(bl, ref) if ref.strip() else END)
        then = at(b, o["then"].get("block", ""), o["name"], before_block)
        if a == b and a:
            problem("warning", "scenario_order_same_lane", f'{o["name"]}: both ends are lane {a}; a lane runs its own steps in order anyway.')
        if first is not None and then is not None and a != b:
            out.points.append(Point(a, first, "first", o["name"], o["first"].get("block", ""), t))
            out.points.append(Point(b, then, "then", o["name"], o["then"].get("block", ""), t))
            out.orders[o["name"]] = (a, b)
    cycle = deadlock(out)
    if cycle:
        problem("error", "scenario_deadlock", f"These wait for each other and could never go on: {cycle}. Move a sync line or an order marker.")
    return out


def deadlock(resolved: Resolved) -> str:
    """A description of a set of waits that can never all be met ("" when there is none).  Each lane is a line of points in row order; a sync
    joins its points into one moment; an order marker says its first point comes before its then point.  A cycle = a deadlock."""
    points = resolved.points
    if not points:
        return ""
    parent = list(range(len(points)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_sync: dict[str, list[int]] = {}
    for i, p in enumerate(points):
        if p.role == "sync":
            by_sync.setdefault(p.item, []).append(i)
    for members in by_sync.values():
        for i in members[1:]:
            parent[root(i)] = root(members[0])
    edges: dict[int, set[int]] = {}

    def edge(a: int, b: int) -> None:
        ra, rb = root(a), root(b)
        if ra != rb:
            edges.setdefault(ra, set()).add(rb)

    for lane in resolved.lanes:
        own = sorted((i for i, p in enumerate(points) if p.lane == lane), key=lambda i: points[i].at)
        for x, y in zip(own, own[1:]):
            if points[x].at < points[y].at:
                edge(x, y)                                            # a lane meets its points in row order (equal rows: at the same moment)
    for name in resolved.orders:
        first = next(i for i, p in enumerate(points) if p.item == name and p.role == "first")
        then = next(i for i, p in enumerate(points) if p.item == name and p.role == "then")
        edge(first, then)
    state: dict[int, int] = {}
    stack: list[int] = []

    def visit(n: int) -> list[int] | None:
        state[n] = 1
        stack.append(n)
        for m in edges.get(n, ()):
            if state.get(m) == 1:
                return stack[stack.index(m):]
            if m not in state:
                found = visit(m)
                if found:
                    return found
        stack.pop()
        state[n] = 2
        return None

    for n in list(edges):
        if n not in state:
            found = visit(n)
            if found:
                names = []
                for r in found:
                    p = points[r]
                    label = p.item if p.role == "sync" else f'{p.item} (lane {p.lane})'
                    if label not in names:
                        names.append(label)
                return " → ".join(names)
    return ""


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Shared sign-ins (two lanes, one authenticator key: each gets its own 30 s code window)
# ---------------------------------------------------------------------------------------------------------------------------------------------
_SECRET_RE = re.compile(r"^\{SECRET:([A-Za-z0-9_]+)\}$", re.I)
_VAR_RE = re.compile(r"^\{([A-Za-z0-9_]+)\}$")


def sign_in_keys(steps: list[dict], params: Any, data_row: int | None) -> set[str]:
    """Hashes of the one-time-code keys a lane's GET_GOOGLE_TOKEN steps use (``params``: the test's Params grid, a ``builder._Grid``).  Two lanes
    with a hash in common sign in with the same authenticator: ``totp.reserve_window`` then gives them different code windows."""
    from ..totp import fingerprint
    out: set[str] = set()
    for s in steps:
        if s.get("method") != "GET_GOOGLE_TOKEN" or s.get("enabled") is False:
            continue
        value = str(s.get("value") or "").strip()
        m = _SECRET_RE.match(value)
        if m:
            out.add("secret:" + m.group(1).upper())                  # the same secret name in the same environment is the same key
            continue
        m = _VAR_RE.match(value)
        token = (m.group(1) if m else value).upper()
        if params is not None and data_row and token in params.cols:
            cell = params.raw(data_row, token)
            if cell:
                out.add(fingerprint(cell) if not B.is_formula(cell) else "formula:" + cell)
            continue
        if value:
            out.add(("var:" + token) if m else fingerprint(value))
    return out


def shared_sign_ins(keys_by_lane: dict[str, set[str]]) -> list[list[str]]:
    """Groups of lanes (two or more) that sign in with the same key."""
    groups: dict[str, list[str]] = {}
    for lane, keys in keys_by_lane.items():
        for k in keys:
            groups.setdefault(k, []).append(lane)
    out: list[list[str]] = []
    for lanes in groups.values():
        if len(lanes) > 1 and sorted(lanes) not in out:
            out.append(sorted(lanes))
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The Build tab's board (Workbook.scenarios, CONTRACT.md 2.1 / 2.9)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _params_grid(editor: WorkbookEditor, sheet: str) -> Any:
    _, rows = B._datasheets(editor)
    for d in rows:
        if d.sheet.upper() == sheet.upper() and d.param_sheet and B._sheet_key(editor, d.param_sheet):
            return B._Grid(editor, B._sheet_key(editor, d.param_sheet))
    return None


def board(editor: WorkbookEditor, tests: list[dict]) -> list[dict]:
    """``Workbook.scenarios``: each definition plus, per lane, its test's kind / blocks / data-row label, the shared sign-ins and the problems.
    ``tests``: the model's tests (their blocks are already worked out)."""
    by_id = {t["id"].upper(): t for t in tests}
    test_ids = set(by_id)
    out = []
    for sc in read_scenarios(editor):
        problems: list[dict] = []
        blocks_of: dict[str, list[dict] | None] = {}
        keys_by_lane: dict[str, set[str]] = {}
        lanes = []
        seen: dict[tuple[str, int | None], str] = {}
        for lane in sc["lanes"]:
            t = by_id.get(lane["test"].upper()) if lane["test"] else None
            row = lane["dataRow"]
            info = {**lane, "kind": t["kind"] if t else "", "found": t is not None, "sheet": t["sheet"] if t else lane["test"],
                    "dataLabel": "", "dataEnabled": None, "blocks": [], "steps": 0}
            if t is None:
                problems.append({"severity": "error", "kind": "scenario_unknown_test",
                                 "message": f'Lane {lane["key"]}: there is no test called "{lane["test"] or "(none)"}".', "lane": lane["key"]})
                blocks_of[lane["key"]] = None
            else:
                rows = {r["row"]: r for r in t["dataRows"]}
                used = row or t["buildingWith"]
                if row and row not in rows:
                    problems.append({"severity": "error", "kind": "scenario_bad_data_row",
                                     "message": f'Lane {lane["key"]}: {t["id"]} has no data row {row}.', "lane": lane["key"]})
                elif used in rows:
                    info["dataLabel"], info["dataEnabled"] = rows[used]["label"], rows[used]["enabled"]
                info["dataRow"] = row
                info["usesRow"] = used
                refs = block_refs(t["blocks"])
                info["blocks"] = [{"ref": ref, "title": b["title"], "kind": b["kind"], "start": b["start"], "end": b["end"], "count": b["count"],
                                   "firstRow": b["firstRow"], "lastRow": b["lastRow"], "gate": b.get("gate", ""),
                                   "sideEffects": any(s["sideEffects"] for s in t["steps"][b["start"] - 1:b["end"]])}
                                  for ref, b in zip(refs, t["blocks"])]
                info["steps"] = len(t["steps"])
                blocks_of[lane["key"]] = t["blocks"]
                if t["kind"] == "web":
                    keys_by_lane[lane["key"]] = sign_in_keys(t["steps"], _params_grid(editor, t["sheet"]), used)
                twin = seen.get((t["id"].upper(), used))
                if twin:
                    problems.append({"severity": "warning", "kind": "scenario_same_data_row", "lane": lane["key"],
                                     "message": f"Lanes {twin} and {lane['key']} run {t['id']} with the same data row: give each its own row "
                                                "(its own user, its own data) or they will do exactly the same thing."})
                seen[(t["id"].upper(), used)] = lane["key"]
            lanes.append(info)
        if sc["name"].upper() in test_ids:
            problems.append({"severity": "error", "kind": "scenario_name_taken",
                             "message": f'"{sc["name"]}" is also the name of a test: a run could not tell them apart. Rename the scenario.'})
        if len(sc["lanes"]) < 2:
            problems.append({"severity": "warning", "kind": "scenario_one_lane", "message": "A scenario needs at least two lanes to run anything at the same time."})
        resolved = resolve(sc, blocks_of)
        problems.extend(resolved.problems)
        shared = shared_sign_ins(keys_by_lane)
        for group in shared:
            problems.append({"severity": "info", "kind": "scenario_shared_sign_in",
                             "message": f"Lanes {' and '.join(group)} sign in with the same one-time-code key. Each gets its own 30 s code window "
                                        "(a code works once), so the scenario takes up to 30 s longer at that point."})
        out.append({**sc, "timeout": sc["timeout"], "timeoutUsed": resolved.timeout, "lanes": lanes, "sharedSignIn": shared, "problems": problems})
    return out


def scenario_problems(model: dict) -> list[dict]:
    """The scenarios' problems in the model's Problem shape (CONTRACT.md 2.7; ``test`` is empty, ``scenario`` names it)."""
    out = []
    for sc in model.get("scenarios") or []:
        for i, p in enumerate(sc.get("problems", [])):
            out.append({"id": f"{p['kind']}:{sc['name']}:{p.get('lane', '')}:{i}", "severity": p["severity"], "kind": p["kind"],
                        "message": f'Scenario "{sc["name"]}": {p["message"]}', "test": "", "row": None, "n": None, "variable": "",
                        "scenario": sc["name"]})
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Ops (CONTRACT.md 3.1; registered into builder.EXTRA_OPS)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _clean(sc: dict) -> dict:
    """A definition from the UI, checked and normalised (letters upper-case, rows as numbers, names trimmed)."""
    name = str(sc.get("name") or "").strip()
    if not name:
        raise B.BuildError("A scenario needs a name.")
    if LANE_SEPARATOR.strip() in name or "/" in name:
        raise B.BuildError('A scenario name cannot contain "·" or "/".')
    lanes = []
    for lane in sc.get("lanes") or []:
        key = str(lane.get("key") or "").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{0,3}", key):
            raise B.BuildError(f"A lane is named by a letter (A, B...), not {lane.get('key')!r}.")
        if any(l["key"] == key for l in lanes):
            raise B.BuildError(f"There are two lanes {key}.")
        row = lane.get("dataRow")
        lanes.append({"key": key, "test": str(lane.get("test") or "").strip(), "dataRow": B._int(row, "A data row") if row not in (None, "") else None,
                      "label": str(lane.get("label") or "").strip()})
    syncs = []
    for s in sc.get("syncs") or []:
        sname = str(s.get("name") or "").strip() or f"Sync {len(syncs) + 1}"
        points = [{"lane": str(p.get("lane") or "").strip().upper(), "block": str(p.get("block") or "").strip()} for p in s.get("points") or []]
        syncs.append({"name": sname, "timeout": _timeout(s.get("timeout")), "points": [p for p in points if p["lane"]]})
    orders = []
    for o in sc.get("orders") or []:
        first, then = o.get("first") or {}, o.get("then") or {}
        a, b = str(first.get("lane") or "").strip().upper(), str(then.get("lane") or "").strip().upper()
        if not a or not b:
            raise B.BuildError("An order marker needs a lane at each end.")
        orders.append({"name": str(o.get("name") or "").strip() or f"{a} before {b}", "timeout": _timeout(o.get("timeout")),
                       "first": {"lane": a, "block": str(first.get("block") or "").strip()},
                       "then": {"lane": b, "block": str(then.get("block") or "").strip()}})
    return {"name": name, "enabled": bool(sc.get("enabled", True)), "timeout": _timeout(sc.get("timeout")), "notes": str(sc.get("notes") or "").strip(),
            "lanes": lanes, "syncs": syncs, "orders": orders}


def _timeout(value: Any) -> int | None:
    if value in (None, ""):
        return None
    seconds = B._int(value, "A time limit")
    if seconds < 5:
        raise B.BuildError("A time limit under 5 s would give up before a page has even loaded.")
    return seconds


def _write(editor: WorkbookEditor, definitions: list[dict]) -> None:
    editor.ensure_rr_sheet(RR_SCENARIOS)
    editor.write_table(B._sheet_key(editor, RR_SCENARIOS), table_rows(definitions))


def op_set_scenario(editor: WorkbookEditor, op: dict) -> dict:
    """``{op: "set_scenario", scenario: {name, enabled?, timeout?, notes?, lanes, syncs, orders}, rename?: old name}``: the whole scenario is
    replaced (a new one is added at the end)."""
    sc = _clean(op.get("scenario") or {})
    old = str(op.get("rename") or "").strip().upper() or sc["name"].upper()
    existing = read_scenarios(editor)
    if any(s["name"].upper() == sc["name"].upper() for s in existing) and sc["name"].upper() != old:
        raise B.BuildError(f'A scenario called "{sc["name"]}" already exists.', "exists", 409)
    if any(t.upper() == sc["name"].upper() for t in editor.sheet_names()):
        raise B.BuildError(f'"{sc["name"]}" is the name of a sheet: a run could not tell the scenario from the test. Pick another name.')
    at = next((i for i, s in enumerate(existing) if s["name"].upper() == old), None)
    if at is None:
        existing.append(sc)
    else:
        existing[at] = sc
    _write(editor, existing)
    return {"op": "set_scenario", "name": sc["name"]}


def op_delete_scenario(editor: WorkbookEditor, op: dict) -> dict:
    name = str(op.get("name") or "").strip().upper()
    existing = read_scenarios(editor)
    kept = [s for s in existing if s["name"].upper() != name]
    if len(kept) == len(existing):
        raise B.BuildError(f"No scenario called {op.get('name')!r}.", "not_found", 404)
    _write(editor, kept)
    return {"op": "delete_scenario", "name": op.get("name")}


OPS = {"set_scenario": op_set_scenario, "delete_scenario": op_delete_scenario}
B.EXTRA_OPS.update(OPS)
