"""Running a concurrency scenario (Q35/Q36): its lanes start together, on one worker, and meet at sync points and order markers.

What a scenario is, and the ``_rr_scenarios`` table it is read from, is ``workbook/scenarios.py``.  Here:

* **Selection** (``pick``): a run that names a scenario (or one of its lanes: a "re-run failed" does) runs every lane of it; a plain run of the
  workbook includes the scenarios whose ``Execute`` is Y.  Each lane becomes a :class:`LaneCase`, an ordinary test case whose id is
  ``"<scenario> · <lane>"``: it has its own events, evidence folder and result, so everything that shows tests shows lanes.
* **One unit** (``Schedule`` groups, ``run_scenario``): the pool hands a scenario to a free worker as a whole; that worker runs every lane at the
  same time, each in its own browser context (its own cookies: two users signed in side by side), sharing the worker's browser.  Lanes are never
  handed to different workers, so a sync point can never wait for a lane that has no worker to run on.
* **Sync points and order markers** (:class:`Coordinator`): a lane that reaches a point waits there - on purpose, shown as a yellow "waiting"
  banner - until the others are there / the lane it must follow has done its part.  A lane that ends (passed, failed, stopped, crashed) counts as
  having reached every point it had left, so one failure never hangs the others.  A wait gives up after the scenario's time limit with no step
  started or finished by any lane it waits for; the waiting lane then stops (ERROR: the lanes could not be kept in step, so what it would do next
  would not test what the scenario is for).
* **Never re-run**: a lane is run once.  Retries, captcha windows and crash re-runs are whole-test re-runs; re-running one lane alone would not
  repeat the moment the lanes shared, so a lane the machine could not run is reported NOT_RUN with that said.

Sign-in codes need nothing special: ``totp.reserve_window`` already hands two logins with the same key different 30 s windows, lanes included;
the run says beforehand which lanes share a key (the wait is visible then, not a surprise).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field, replace
from typing import Any

from ..events import now_iso
from ..workbook import scenarios as S
from ..workbook.model import TestCase
from .patience import plain_seconds


class ScenarioError(ValueError):
    """A scenario that cannot run as written (a missing test, a block that is not there, waits that could never be met)."""


@dataclass
class LaneCase(TestCase):
    """One lane of a scenario: the lane's test with the lane's data row, under an id of its own."""
    group: str = ""                      # the scenario's name
    lane: str = ""                       # its letter
    label: str = ""                      # "agent Ana"
    base_id: str = ""                    # the test's own id (PostDeparture#2)

    __test__ = False

    def info(self) -> dict[str, Any]:
        return {"scenario": self.group, "key": self.lane, "label": self.label, "test": self.base_id, "sheet": self.sheet, "data_row": self.param_row}


@dataclass
class ScenarioPlan:
    name: str
    lanes: list[LaneCase]
    resolved: S.Resolved
    shared_sign_in: list[list[str]] = field(default_factory=list)
    notes: str = ""

    def describe(self) -> dict[str, Any]:
        """What the live view needs before any lane has reached anything (``run_started``'s ``scenarios``)."""
        return {"name": self.name, "notes": self.notes, "timeout_s": self.resolved.timeout,
                "lanes": [{"id": c.id, **c.info()} for c in self.lanes],
                "syncs": [{"name": n, "lanes": sorted(set(k))} for n, k in self.resolved.syncs.items()],
                "orders": [{"name": n, "first": a, "then": b} for n, (a, b) in self.resolved.orders.items()],
                "shared_sign_in": self.shared_sign_in}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Selection and planning (off the event loop, with the rest of the run's planning: engine/runner.py _load_and_plan)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _has_table(workbook) -> bool:
    return any(name.upper() == S.RR_SCENARIOS.upper() for name in workbook.data.sheets)


def pick(workbook, options, discovered: list[TestCase]) -> tuple[list[ScenarioPlan], list[str] | None]:
    """The scenarios this run takes part in, and ``options.tests`` without the names that were scenarios (None when no tests were named;
    ``[]`` when only scenarios were).  Named: a scenario's name, or a lane's id.  Not named: every scenario whose Execute is Y - unless the run
    picks by tag (scenarios have no tags)."""
    if not _has_table(workbook):
        return [], options.tests
    from ..workbook.writer import WorkbookEditor
    editor = WorkbookEditor.open(workbook.path)
    definitions = S.read_scenarios(editor)
    by_name = {d["name"].upper(): d for d in definitions}
    chosen: list[dict] = []
    rest: list[str] | None = None
    if options.tests:
        rest = []
        for name in options.tests:
            key = name.strip().upper()
            scenario = key.split(S.LANE_SEPARATOR.upper())[0].strip() if S.LANE_SEPARATOR.strip() in key else key
            found = by_name.get(key) or by_name.get(scenario)
            if found is None:
                rest.append(name)
            elif found not in chosen:
                chosen.append(found)
    elif not options.tags:
        chosen = [d for d in definitions if d["enabled"]]
    return [plan_scenario(editor, workbook, d, discovered) for d in chosen], rest


def plan_scenario(editor, workbook, definition: dict, discovered: list[TestCase]) -> ScenarioPlan:
    """The lanes of one scenario as test cases, and its points as rows.  Raises :class:`ScenarioError` when it cannot run as written."""
    from ..workbook import builder as B
    name = definition["name"]
    if not definition["lanes"]:
        raise ScenarioError(f'Scenario "{name}" has no lanes.')
    lanes: list[LaneCase] = []
    blocks_of: dict[str, list[dict] | None] = {}
    keys: dict[str, set[str]] = {}
    for lane in definition["lanes"]:
        sheet = lane["test"].strip().upper()
        own = [c for c in discovered if c.sheet.upper() == sheet and c.runnable]
        if not own:
            raise ScenarioError(f'Scenario "{name}", lane {lane["key"]}: there is no test "{lane["test"]}" listed in DataSheets.')
        base = next((c for c in own if c.param_row == lane["dataRow"]), None) if lane["dataRow"] else next((c for c in own if c.enabled), own[0])
        if base is None:                                             # a data row whose blnExecute is N: the scenario chose it, so it runs here
            first = own[0]
            if first.kind != "api" and not first.param_sheet:
                raise ScenarioError(f'Scenario "{name}", lane {lane["key"]}: {lane["test"]} has no Params sheet, so it has no data row {lane["dataRow"]}.')
            base = replace(first, id=f"{first.sheet}@{lane['dataRow']}", param_row=lane["dataRow"], enabled=True, param_enabled=True, scenario="")
        title = f"{name} · {lane['key']} · {lane['label'] or base.title}"
        case = LaneCase(**{**{f: getattr(base, f) for f in TestCase.__dataclass_fields__},
                           "id": S.lane_id(name, lane["key"]), "title": title, "enabled": True, "param_enabled": True, "tags": []},
                        group=name, lane=lane["key"], label=lane["label"], base_id=base.id)
        lanes.append(case)
        sheet_key = B._sheet_key(editor, base.sheet)
        if base.kind == "api" or sheet_key is None:
            blocks_of[lane["key"]] = []
            continue
        params = S._params_grid(editor, sheet_key)
        parsed = B.parse_test_sheet(editor, sheet_key, set(params.cols) if params is not None else set())
        blocks_of[lane["key"]] = parsed["blocks"]
        keys[lane["key"]] = S.sign_in_keys(parsed["steps"], params, base.param_row)
    resolved = S.resolve(definition, blocks_of)
    errors = [p["message"] for p in resolved.problems if p["severity"] == "error"]
    if errors:
        raise ScenarioError(f'Scenario "{name}" cannot run: {" ".join(errors)}')
    return ScenarioPlan(name=name, lanes=lanes, resolved=resolved, shared_sign_in=S.shared_sign_ins(keys), notes=definition.get("notes", ""))


def adjust_order(order, plans: list[ScenarioPlan]) -> None:
    """Lanes of one scenario start together: each waits for what any of them waits for (outside the scenario), never for one another - a lane
    that needs a value its sibling sets gets it while they run, not by waiting for the sibling to finish (which would never happen)."""
    for plan in plans:
        ids = {c.id for c in plan.lanes}
        union = sorted({d for i in ids for d in order.deps.get(i, []) if d not in ids})
        for i in ids:
            order.deps[i] = list(union)
            kept = {k: [p for p in v if p not in ids] for k, v in order.data.get(i, {}).items() if any(p not in ids for p in v)}
            if kept:
                order.data[i] = kept
            else:
                order.data.pop(i, None)
        order.after_stream = {t: w for t, w in order.after_stream.items() if t not in ids}
        for other, deps in order.deps.items():                       # an API test that waits for the rest of its stream waits for the lanes too: fine,
            if other not in ids and any(d in ids for d in deps):     # but never for only some of them (they finish together anyway)
                order.deps[other] = sorted(set(deps) | ids)


def groups_of(plans: list[ScenarioPlan]) -> dict[str, list[str]]:
    """``Schedule`` groups: lane id -> every lane id of its scenario."""
    return {c.id: [x.id for x in p.lanes] for p in plans for c in p.lanes}


def sign_in_note(plan: ScenarioPlan) -> str:
    if not plan.shared_sign_in:
        return ""
    groups = "; ".join(" and ".join(g) for g in plan.shared_sign_in)
    return (f'Scenario "{plan.name}": lanes {groups} sign in with the same one-time-code key. Each gets its own 30 s code window (a code works '
            "once), so one of them waits up to 30 s at that step.")


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Sync points and order markers
# ---------------------------------------------------------------------------------------------------------------------------------------------
class Coordinator:
    """Where every lane of one running scenario is, and who waits for whom.  Built inside ``run_scenario``'s coroutine (Python 3.9 binds an
    ``asyncio.Condition`` to the loop that is current when it is made)."""

    def __init__(self, plan: ScenarioPlan, bus, cancel: asyncio.Event, lane_cancelled=None):
        self.plan, self.bus, self.cancel = plan, bus, cancel
        self.lane_cancelled = lane_cancelled or (lambda test: False)      # did the person cancel this lane's test alone? (it stops waiting; it ends like a failed lane)
        self.changed = asyncio.Condition()
        self.keys = [c.lane for c in plan.lanes]
        self.test_of = {c.lane: c.id for c in plan.lanes}
        self.pos = {k: -1.0 for k in self.keys}                    # the highest row each lane has reached (-1: not started yet)
        self.ended = {k: "" for k in self.keys}                     # how each lane ended ("" = still going)
        now = time.monotonic()
        self.moved = {k: now for k in self.keys}                    # when each lane last started or finished a step
        self.waiting = {k: "" for k in self.keys}                   # the point a lane is held at right now
        self.points = {k: sorted((p for p in plan.resolved.points if p.lane == k), key=lambda p: p.at) for k in self.keys}
        self.done: dict[str, set[int]] = {k: set() for k in self.keys}
        self.timeline: dict[str, list[dict]] = {k: [] for k in self.keys}

    def hook(self, key: str) -> "LaneHook":
        return LaneHook(self, key)

    # -- what is where ----------------------------------------------------------------------------------------
    def reached(self, key: str, at: float) -> bool:
        return bool(self.ended[key]) or self.pos[key] >= at

    def _members(self, p: S.Point) -> list[S.Point]:
        return [q for q in self.plan.resolved.points if q.role == "sync" and q.item == p.item]

    def _first_of(self, p: S.Point) -> S.Point:
        return next(q for q in self.plan.resolved.points if q.role == "first" and q.item == p.item)

    def _emit(self, key: str, p: S.Point, state: str, message: str, *, reached=(), waiting=(), ended=(), waited: float | None = None) -> None:
        kind = "sync" if p.role == "sync" else "order"
        entry = {"item": p.item, "kind": kind, "role": p.role, "state": state, "at": now_iso(), "block": p.block, "message": message,
                 **({"waited_s": round(waited, 1)} if waited is not None else {})}
        self.timeline[key].append(entry)
        self.bus.emit("scenario_sync", test=self.test_of[key], scenario=self.plan.name, lane=key, sync=p.item, kind=kind, role=p.role,
                      state=state, reached=list(reached), waiting=list(waiting), ended=list(ended), message=message,
                      **({"waited_s": round(waited, 1)} if waited is not None else {}))

    def _where(self, p: S.Point) -> str:
        if p.role == "sync":
            return f"after {p.block}" if p.block else "before its first step"
        if p.role == "first":
            return f"finishing {p.block}" if p.block else "finishing"
        return f"before {p.block}" if p.block else "before its first step"

    # -- a lane moves -------------------------------------------------------------------------------------------
    async def advance(self, key: str, row: float, notice=None, timing=None) -> str:
        """The lane is about to run ``row``: deal with every point it reaches on the way (waiting where it must).  "" = go on; else why it stops."""
        self.moved[key] = time.monotonic()
        due = [(i, p) for i, p in enumerate(self.points[key]) if p.at <= row and i not in self.done[key]]
        for at in sorted({p.at for _, p in due}):
            group = [(i, p) for i, p in due if p.at == at]
            async with self.changed:
                self.pos[key] = max(self.pos[key], at)
                for i, _ in group:
                    self.done[key].add(i)
                self.changed.notify_all()
            for _, p in sorted(group, key=lambda ip: {"first": 0, "sync": 1, "then": 2}[ip[1].role]):
                if p.role == "first":
                    then = next((q.lane for q in self.plan.resolved.points if q.role == "then" and q.item == p.item), "")
                    self._emit(key, p, "done", f"{key} has done its part of {p.item}{': ' + then + ' may go on' if then else ''}.")
                    continue
                why = await self._hold(key, p, notice, timing)
                if why or self.cancel.is_set() or self.lane_cancelled(self.test_of[key]):
                    return why
        async with self.changed:
            self.pos[key] = max(self.pos[key], row)
            self.changed.notify_all()
        return ""

    def stepped(self, key: str) -> None:
        self.moved[key] = time.monotonic()

    async def end(self, key: str, status: str) -> None:
        """The lane has ended: it counts as having reached every point it had left (the others never wait for it)."""
        if self.ended[key]:
            return
        async with self.changed:
            self.ended[key] = status or "ENDED"
            self.moved[key] = time.monotonic()
            self.changed.notify_all()
        for i, p in enumerate(self.points[key]):
            if i in self.done[key] or p.role == "then":
                continue
            if p.role == "sync":
                self._emit(key, p, "ended", f"{key} ended ({self.ended[key]}) before {p.item}: the other lanes do not wait for it there.")
            else:
                self._emit(key, p, "ended", f"{key} ended ({self.ended[key]}) before doing its part of {p.item}: the lane after it is not held back.")

    def _state(self, key: str, p: S.Point) -> tuple[bool, list[str], list[str], list[str]]:
        """(released?, lanes there, lanes not there yet, lanes that ended without getting there)."""
        others = [q for q in self._members(p) if q.lane != key] if p.role == "sync" else [self._first_of(p)]
        there = [q.lane for q in others if not self.ended[q.lane] and self.pos[q.lane] >= q.at]
        gone = [q.lane for q in others if self.ended[q.lane] and not self.pos[q.lane] >= q.at]
        missing = [q.lane for q in others if not self.reached(q.lane, q.at)]
        return not missing, there, missing, gone

    async def _hold(self, key: str, p: S.Point, notice, timing) -> str:
        released, there, missing, gone = self._state(key, p)
        what = f"{p.item} ({self._where(p)})"
        if released:
            self._emit(key, p, "released", self._released_message(key, p, gone, 0.0), reached=there, ended=gone, waited=0.0)
            return ""
        self.waiting[key] = p.item
        self._emit(key, p, "waiting" if p.role == "then" else "arrived",
                   f"{key} is at {what}, waiting for {' and '.join(missing)}.", reached=there, waiting=missing, ended=gone)
        t0 = time.monotonic()
        wait_id = notice.begin("scenario_sync", f"Scenario {self.plan.name}: lane {key} waits at {p.item} for lane{'s' if len(missing) > 1 else ''} "
                                                f"{' and '.join(missing)} (steps between sync points run at the same time).") if notice else ""
        note, why = "", ""
        span = timing.span("wait", "scenario") if timing is not None else contextlib.nullcontext()
        try:
            with span:
                async with self.changed:
                    while True:
                        released, there, missing, gone = self._state(key, p)
                        if released or self.cancel.is_set() or self.lane_cancelled(self.test_of[key]):
                            break
                        quiet = time.monotonic() - max([t0] + [self.moved[m] for m in missing])
                        if quiet >= p.timeout:
                            stuck = [m for m in missing if self.waiting[m]]
                            why = (f'Scenario "{self.plan.name}": lane {key} gave up at {p.item} after {plain_seconds(time.monotonic() - t0)}: lane'
                                   f'{"s" if len(missing) > 1 else ""} {" and ".join(missing)} did not start or finish a step for {plain_seconds(p.timeout)}'
                                   + (f" (itself waiting at {', '.join(sorted({self.waiting[m] for m in stuck}))})" if stuck else "")
                                   + ". The lanes could not be kept in step, so the rest of this lane was not run (it would not test what the "
                                     "scenario is for). The time limit is the scenario's Timeout.")
                            break
                        try:
                            await asyncio.wait_for(self.changed.wait(), 0.5)
                        except asyncio.TimeoutError:
                            pass
        finally:
            self.waiting[key] = ""
            waited = time.monotonic() - t0
            if notice and wait_id:
                note = f"waited {plain_seconds(waited)} at {p.item} ({'timed out' if why else 'released'})" if not (self.cancel.is_set() or self.lane_cancelled(self.test_of[key])) else ""
                notice.end(wait_id, note)
        if why:
            self._emit(key, p, "timeout", why, reached=there, waiting=missing, ended=gone, waited=waited)
            return why
        if not (self.cancel.is_set() or self.lane_cancelled(self.test_of[key])):
            self._emit(key, p, "released", self._released_message(key, p, gone, waited), reached=there, ended=gone, waited=waited)
        return ""

    def _released_message(self, key: str, p: S.Point, gone: list[str], waited: float) -> str:
        after = f" after {plain_seconds(waited)}" if waited >= 0.5 else ""
        if p.role == "then":
            first = self._first_of(p).lane
            return (f"{first} ended ({self.ended[first]}) without doing its part of {p.item}: {key} goes on{after}." if gone
                    else f"{first} has done its part of {p.item}: {key} goes on{after}.")
        if gone:
            return f"{p.item}: released{after}; {' and '.join(gone)} ended before getting there ({', '.join(self.ended[g] for g in gone)})."
        return f"{p.item}: every lane is there, released{after}."


class LaneHook:
    """What a lane's test runner calls: ``before_step`` before each step (it may wait there), ``stepped`` after each, ``finish`` at the end."""

    def __init__(self, coordinator: Coordinator, key: str):
        self.coordinator, self.key = coordinator, key

    async def before_step(self, row: float, notice=None, timing=None) -> str:
        return await self.coordinator.advance(self.key, row, notice, timing)

    def stepped(self) -> None:
        self.coordinator.stepped(self.key)

    async def finish(self, status: str = "") -> None:
        await self.coordinator.end(self.key, status)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# One scenario on one worker
# ---------------------------------------------------------------------------------------------------------------------------------------------
async def run_scenario(engine, ctx, lanes: list[LaneCase], get_browser, n: int) -> None:
    """Run every lane of a scenario at the same time on worker ``n`` (the pool gave the worker the whole scenario: ``Schedule`` groups), then
    record each lane's result like any test's."""
    from .patience import WaitNotice
    plan = next(p for p in ctx.plan.scenarios if p.name == lanes[0].group)
    coordinator = Coordinator(plan, ctx.bus, ctx.cancel, ctx.test_cancelled)
    ctx.note(f'Scenario "{plan.name}": {len(lanes)} lanes ({", ".join(c.lane for c in lanes)}) start together on worker {n}.', "info")

    async def one(case: LaneCase) -> None:
        hook = coordinator.hook(case.lane)
        queued_s, deps_s = ctx.schedule.queued_s(case.id)
        res = None
        try:
            if case.kind == "api":                                    # an API lane has no steps to wait between: it meets its points before / after
                why = await hook.before_step(0, WaitNotice(ctx.bus, case.id, n))
                if why:
                    res = engine.not_run(ctx, case, why, n)
            if res is None and not ctx.cancel.is_set():
                res = await engine.run_one(ctx, case, get_browser, n, lane=hook)
            if res is None:
                res = engine.stopped(ctx, case, "The run was cancelled before this lane started.", "CANCELLED")
        except Exception as err:                                      # a runner bug in one lane must not take the others down
            res = engine.stopped(ctx, case, f"The runner failed on this lane: {type(err).__name__}: {err}", "ERROR")
        finally:
            await hook.finish(res.status if res is not None else "ERROR")
            await engine.pool.finished(ctx, case.id)
        res.lane = case.info()
        res.syncs = list(coordinator.timeline[case.lane])
        engine.record(ctx, case, res, queued_s, deps_s)

    await asyncio.gather(*(one(c) for c in lanes))
