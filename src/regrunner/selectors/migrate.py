"""``regrunner selectors audit|migrate``: score every locator in a workbook and convert what is safe."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..workbook.model import Workbook
from .resolve import MapEntry, SelectorMap
from .spec import legacy_key, legacy_strategy
from .xpath2css import score_xpath, xpath_to_css


@dataclass
class LocatorUse:
    key: str
    findby: str
    value: str
    uses: int = 0
    indexes: set[int] = field(default_factory=set)
    tests: set[str] = field(default_factory=set)
    steps: list[str] = field(default_factory=list)
    score: int = 0
    label: str = ""
    reasons: list[str] = field(default_factory=list)
    css: str | None = None
    entry_index: int | None = None
    skipped_reason: str = ""


def collect(workbook: Workbook, tests: list[str] | None = None) -> list[LocatorUse]:
    found: dict[str, LocatorUse] = {}
    for case in workbook.discover():
        if not case.is_ui or (tests and case.id not in tests and case.sheet not in tests):
            continue
        runtime = workbook.runtime(case)
        for row in range(2, runtime.total_rows + 1):
            step = runtime.prepare_row(row)
            if step is None:
                continue
            if step.findby_value and legacy_strategy(step.findby, step.findby_value):
                key = legacy_key(step.findby, step.findby_value)
                use = found.setdefault(key, LocatorUse(key, step.findby, step.findby_value))
                use.uses += 1
                use.indexes.add(step.index)
                use.tests.add(case.id)
                if len(use.steps) < 3 and step.name not in use.steps:
                    use.steps.append(step.name)
            runtime.record(step, "PASSED", "", "")
    for use in found.values():
        if legacy_strategy(use.findby, use.value).kind == "xpath":
            use.score, use.label, use.reasons = score_xpath(use.value)
            conv = xpath_to_css(use.value)
            if conv is None:
                use.skipped_reason = "no provably equivalent CSS (text, position or attribute case rules)"
            elif conv.nth is not None and use.indexes != {0}:
                use.skipped_reason = "positional XPath used with a non-zero Index"
            else:
                use.css, use.entry_index = conv.locator, conv.nth
        else:
            use.score, use.label, use.reasons = 90, "strong", [f"{use.findby} locator"]
    return sorted(found.values(), key=lambda u: (u.score, -u.uses))


def merge_into_map(uses: list[LocatorUse], selector_map: SelectorMap, *, min_score: int = 0,
                   include_positional: bool = False) -> int:
    """Add auto conversions; never overwrites an entry someone wrote by hand.

    Positional XPaths (``(//x)[3]``) convert to "CSS + index", which is equivalent but exactly as
    layout-dependent, so they are left out unless ``include_positional`` is set.
    """
    added = 0
    for use in uses:
        if use.css is None or use.key in selector_map.entries or use.score < min_score:
            continue
        if use.entry_index is not None and not include_positional:
            continue
        selector_map.entries[use.key] = MapEntry(use=[use.css], index=use.entry_index, source="auto")
        added += 1
    return added
