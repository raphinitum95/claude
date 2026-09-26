"""Which tests of a run wait for which.

Tests run side by side, but one may need what another produces: ``Purchase`` writes ``DT_Policy_Out`` into its row of the parameter sheet and
``ViewPolicy`` types it.  Two things put a test behind another:

* **data** - a test reads a parameter that a test of the run with the *same parameter row* sets (found by a dry run of every test, no browser),
  and that test comes earlier in the DataSheets list (the legacy runner ran them in that order, so a later test never fed an earlier one);
* **chains** - an order fixed by hand: ``[Purchase#1, ViewPolicy#1, Cancellation#1]`` means each waits for the one before it, whatever happened to it.
  Data cannot say that ViewPolicy comes before Cancellation (both only read the policy number), a chain can.

Streams that do not touch each other (row 3's tests and row 5's) still run in parallel.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..workbook.api import referenced_cells


@dataclass
class Flow:
    """What one test does with parameters (a dry run, no browser)."""
    id: str
    index: int                                     # position in the DataSheets list: the order the legacy runner ran them in
    kind: str = "ui"
    param_sheet: str | None = None
    param_row: int = 0
    sheet: str = ""
    reads: dict[str, dict[str, Any]] = field(default_factory=dict)      # PARAMETER -> {param, rows, blank}
    sets: set[str] = field(default_factory=set)                          # PARAMETERS its steps set
    writes: set[tuple] = field(default_factory=set)                      # an API test: the cells (sheet, row, column) its response can fill in

    @classmethod
    def of(cls, case, index: int, runtime=None) -> "Flow":
        flow = cls(id=case.id, index=index, kind=case.kind, param_sheet=case.param_sheet, param_row=case.param_row, sheet=case.sheet)
        if runtime is not None and case.kind != "api":
            flow.reads, flow.sets = dict(runtime.reads), set(runtime.sets)
            for info in flow.reads.values():                             # a Params cell that is =PurchaseUS!FB3 reads what an API test fills in
                key = info.get("key")
                raw = runtime.params_sheet.data.cells.get((key[1], key[2])) if key and runtime.params_sheet is not None else None
                if raw is not None and raw.formula:
                    info["cells"] = referenced_cells(raw.formula, runtime.book)
        elif runtime is not None:                                        # an API row reads cells of other sheets (=AgentPortal_Params!R3)
            flow.writes = runtime.output_cells()
            for item in runtime.cell_reads():
                flow.reads[f"{item['param'].upper()}@{item['key'][0]}!{item['key'][1]}"] = {
                    "param": item["param"], "rows": [], "blank": item["blank"], "source": item["source"], "key": item["key"]}
        return flow


def analyse(workbook) -> list[Flow]:
    """A ``Flow`` for every runnable test of the workbook, in DataSheets order."""
    flows = []
    for index, case in enumerate(workbook.discover()):
        if not case.runnable:
            continue
        runtime = workbook.runtime(case)
        if case.kind != "api":
            runtime.plan()
        flows.append(Flow.of(case, index, runtime))
    return flows


@dataclass
class Order:
    deps: dict[str, list[str]] = field(default_factory=dict)              # test -> the tests it waits for (data + chains + API after UI)
    data: dict[str, dict[str, list[str]]] = field(default_factory=dict)   # test -> {PARAMETER: tests that set it}: what it cannot run without
    streams: list[dict[str, Any]] = field(default_factory=list)           # tests that hang together: {tests, levels, params}
    notes: list[dict[str, Any]] = field(default_factory=list)             # what to tell the person before the run
    chains: list[list[str]] = field(default_factory=list)                 # the chains in effect (members of this run only)
    cells: dict[str, dict[str, tuple]] = field(default_factory=dict)      # test -> {PARAMETER: the cell (sheet, row, column) it reads}: to see whether it got set
    after_ui: list[str] = field(default_factory=list)                     # API tests nobody chained: they start after every UI test of the run

    def as_dict(self) -> dict[str, Any]:
        return {"deps": self.deps, "data": self.data, "streams": self.streams, "notes": self.notes, "chains": self.chains, "after_ui": self.after_ui}


def plan_order(flows: list[Flow], selected: list[str], chains: list[list[str]] | None = None) -> Order:
    """``flows``: every test of the workbook (unselected ones are only used to say what could set an empty parameter); ``selected``: this run's test ids."""
    chosen = set(selected)
    sel = sorted((f for f in flows if f.id in chosen), key=lambda f: f.index)
    by_id = {f.id: f for f in flows}
    order = Order(deps={f.id: [] for f in sel})

    def depends_on(a: str, b: str) -> bool:
        """Does ``a`` wait for ``b``, directly or through others?"""
        seen, todo = set(), [a]
        while todo:
            for d in order.deps.get(todo.pop(), []):
                if d == b:
                    return True
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        return False

    # chains first: a person's order beats what the data suggests
    for chain in chains or []:
        for unknown in [t for t in chain if t not in by_id]:
            order.notes.append({"kind": "chain_unknown", "test": unknown, "message": f"The chain names {unknown}, which is not a test of this workbook."})
        members = [t for t in dict.fromkeys(chain) if t in chosen]
        if len(members) < 2:
            continue
        order.chains.append(members)
        for before, after in zip(members, members[1:]):
            if depends_on(before, after):
                order.notes.append({"kind": "conflict", "test": after, "message": f"{after} cannot wait for {before}: {before} already waits for {after}. The chain is ignored there."})
            elif before not in order.deps[after]:
                order.deps[after].append(before)

    # data: a test that reads what a test of the run (same parameter row) sets waits for it.  A UI test only waits for tests that come earlier in
    # DataSheets (the legacy order); an API test names the cell it reads, so whoever sets it comes first.
    for f in sel:
        for info in f.reads.values():
            param = info["param"].upper()
            sheet, row = (info["key"][0], info["key"][1]) if info.get("key") else (f.param_sheet, f.param_row)
            same = lambda q: (q.kind != "api" and q.id != f.id and (f.kind == "api" or q.index < f.index) and str(q.param_sheet or "").upper() == str(sheet or "").upper()
                              and q.param_row == row and param in q.sets)
            producers = [q.id for q in sel if same(q)]
            foreign = set(map(tuple, info.get("cells") or []))               # cells of API sheets this parameter's formula reads
            fed = [q for q in sel if q.kind == "api" and q.id != f.id and q.writes & foreign]
            for q in fed:
                if q.id not in producers:
                    producers.append(q.id)
            if producers:
                order.data.setdefault(f.id, {})[param] = producers
                order.cells.setdefault(f.id, {})[param] = (sorted(fed[0].writes & foreign)[0] if fed
                                                           else tuple(info["key"]) if info.get("key") else None)
                for q in producers:
                    if q in order.deps[f.id]:
                        continue
                    if depends_on(q, f.id):
                        order.notes.append({"kind": "conflict", "test": f.id, "message": f"{f.id} uses {info['param']}, which {q} sets, but a chain puts {f.id} "
                                                                                       f"before {q}. It will not wait for it."})
                    else:
                        order.deps[f.id].append(q)
                order.notes.append({"kind": "waits", "test": f.id, "param": info["param"], "on": producers, "blank": info["blank"],
                                    "message": f"{f.id} waits for {' and '.join(producers)}, which set{'s' if len(producers) == 1 else ''} {info['param']}."})
            elif info["blank"]:
                available = [q.id for q in flows if q.id not in chosen and q.kind != "api" and (f.kind == "api" or q.index < f.index)
                             and str(q.param_sheet or "").upper() == str(sheet or "").upper() and q.param_row == row and param in q.sets]
                available += [q.id for q in flows if q.id not in chosen and q.kind == "api" and q.id != f.id and q.writes & foreign]
                where = f" ({info['source'].split(' (')[0]})" if info.get("source") and f.kind == "api" else ""
                order.notes.append({"kind": "missing", "test": f.id, "param": info["param"], "available": available,
                                    "message": f"{f.id} uses {info['param']}{where}, which is empty and nothing in this run sets it."
                                               + (f" {' / '.join(available)} does: add it to the run, or you will be asked for the value." if available
                                                  else " You will be asked for the value when the step is reached.")})

    # streams: the tests that hang together (data + chains), in the order they will run in
    explicit = {t: list(d) for t, d in order.deps.items()}
    ids = [f.id for f in sel]
    chained = {t for chain in order.chains for t in chain}
    ui = [f.id for f in sel if f.kind != "api"]
    feeders = {p for named in order.data.values() for producers in named.values() for p in producers if by_id[p].kind == "api"}   # API tests a UI test reads from
    order.after_ui = [f.id for f in sel if f.kind == "api" and f.id not in chained and f.id not in feeders and ui]
    for t in order.after_ui:                                  # an API test reads what the UI tests produced: unless somebody chained it, it goes after all of them
        order.deps[t] = list(dict.fromkeys(order.deps[t] + [u for u in ui if u != t]))
    links: dict[str, set[str]] = {t: set() for t in ids}
    for t in ids:
        for d in explicit[t]:
            links[t].add(d)
            links[d].add(t)
    seen: set[str] = set()
    level: dict[str, int] = {}

    def level_of(t: str, group: set[str]) -> int:
        if t not in level:
            level[t] = 0                                       # (guards a cycle the checks above should have made impossible)
            level[t] = 1 + max([level_of(d, group) for d in order.deps[t] if d in group] or [-1])
        return level[t]

    for t in ids:
        if t in seen or not links[t]:
            continue
        group, todo = [], [t]
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            group.append(x)
            todo.extend(links[x])
        members = set(group)
        group.sort(key=lambda x: (level_of(x, members), by_id[x].index))
        params = sorted({info["param"] for x in group for info in by_id[x].reads.values() if info["param"].upper() in order.data.get(x, {})})
        order.streams.append({"tests": group, "levels": {x: level_of(x, members) for x in group}, "params": params})
        tops: dict[int, list[str]] = {}
        for x in group:
            tops.setdefault(level_of(x, members), []).append(x)
        for lvl, same_level in tops.items():
            if lvl >= 1 and len(same_level) >= 2:
                order.notes.append({"kind": "parallel", "test": same_level[0], "tests": same_level,
                                    "message": f"{' and '.join(same_level)} run at the same time (nothing puts one before the other). If the order matters - "
                                               "cancelling a policy before viewing it - set a chain."})
    if order.after_ui:
        order.notes.append({"kind": "after_ui", "test": order.after_ui[0], "tests": order.after_ui,
                            "message": f"{' and '.join(order.after_ui)} {'starts' if len(order.after_ui) == 1 else 'start'} after every UI test of the run "
                                       "(an API test reads what those tests produce). Put it in a chain to choose where it runs."})
    return order


# -- chains that are remembered ------------------------------------------------------------------------------------------------------------------------
def chains_file(workbook_path: Path) -> Path:
    """Where the web UI keeps the chains of a workbook: beside it, hidden, never inside the workbook."""
    return workbook_path.parent / ".chains" / f"{workbook_path.name}.json"


def clean_chains(raw: Any) -> list[list[str]]:
    out: list[list[str]] = []
    for chain in raw if isinstance(raw, list) else []:
        ids = [str(x).strip() for x in chain if str(x).strip()] if isinstance(chain, list) else []
        if len(ids) >= 2:
            out.append(list(dict.fromkeys(ids)))
    return out


def load_chains(cfg, workbook_path: Path) -> tuple[list[list[str]], str]:
    """``(chains, where they came from)``: saved from the web UI, else ``chains:`` in config.yaml (by file name, or ``*``), else none."""
    saved = chains_file(workbook_path)
    if saved.is_file():
        try:
            return clean_chains(json.loads(saved.read_text(encoding="utf-8"))), "saved"
        except (OSError, ValueError):
            pass
    for key in (workbook_path.name, "*"):
        if key in cfg.chains:
            return clean_chains(cfg.chains[key]), "config"
    return [], "none"


def save_chains(workbook_path: Path, chains: list[list[str]]) -> None:
    target = chains_file(workbook_path)
    chains = clean_chains(chains)
    if not chains:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(chains, indent=1), encoding="utf-8")
    tmp.replace(target)
