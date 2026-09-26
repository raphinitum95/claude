"""Selector map (``selectors.yaml``), chain building and polling resolution with fallback."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .spec import Strategy, legacy_key, legacy_strategy, parse_locator_list


# ---------------------------------------------------------------------------------------------
# selectors.yaml
# ---------------------------------------------------------------------------------------------
@dataclass
class MapEntry:
    use: list[str]                    # generic locators, in priority order
    index: int | None = None          # overrides the sheet's Index (e.g. "(//x)[3]" -> css + index 2)
    source: str = "manual"            # manual | auto | harvest
    note: str = ""


class SelectorMap:
    """Project-wide overrides keyed by the *legacy* locator, so workbooks never need editing.

    ``selectors.yaml``::

        version: 1
        locators:
          "//input[@name='tripDepartureDate']":
            use: ['css=input[name="tripDepartureDate"]']
            source: auto
          "(//input[@name='insuredAge'])[3]":
            use: ['css=input[name="insuredAge"]']
            index: 2
    """

    def __init__(self, entries: dict[str, MapEntry] | None = None, path: Path | None = None):
        self.entries = entries or {}
        self.path = path

    @classmethod
    def load(cls, path: str | Path | None) -> "SelectorMap":
        if not path:
            return cls()
        path = Path(path)
        if not path.is_file():
            return cls(path=path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries: dict[str, MapEntry] = {}
        for key, value in (raw.get("locators") or {}).items():
            if isinstance(value, str):
                entries[str(key)] = MapEntry(use=[value])
            elif isinstance(value, list):
                entries[str(key)] = MapEntry(use=[str(v) for v in value])
            elif isinstance(value, dict):
                use = value.get("use") or []
                use = [use] if isinstance(use, str) else [str(u) for u in use]
                entries[str(key)] = MapEntry(use=use, index=value.get("index"),
                                             source=str(value.get("source", "manual")),
                                             note=str(value.get("note", "")))
        return cls(entries, path)

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path or self.path or "selectors.yaml")
        doc: dict[str, Any] = {"version": 1, "locators": {}}
        for key in sorted(self.entries):
            e = self.entries[key]
            item: dict[str, Any] = {"use": e.use, "source": e.source}
            if e.index is not None:
                item["index"] = e.index
            if e.note:
                item["note"] = e.note
            doc["locators"][key] = item
        header = ("# Generic locators that replace legacy XPaths at run time (workbooks are not modified).\n"
                  "# key   = the legacy FindBy_Value (raw XPath) or 'kind:value' for other FindBy types\n"
                  "# use   = generic locators tried first, in order; the legacy locator stays as a fallback\n"
                  "# index = replaces the sheet's Index when the generic locator already isolates the element\n")
        path.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        return path

    def lookup(self, key: str) -> MapEntry | None:
        return self.entries.get(key)

    def __len__(self) -> int:
        return len(self.entries)


def build_chain(findby: str, findby_value: str, locator_cell: str, selector_map: SelectorMap | None,
                *, legacy_fallback: bool = True) -> list[Strategy]:
    """Ordered strategies for one step: sheet ``Locator`` -> selector map -> legacy locator."""
    chain: list[Strategy] = []
    if locator_cell:
        chain.extend(parse_locator_list(locator_cell, "sheet"))
    legacy = legacy_strategy(findby, findby_value)
    if legacy is not None and selector_map is not None:
        entry = selector_map.lookup(legacy_key(findby, findby_value))
        if entry:
            for text in entry.use:
                for strategy in parse_locator_list(text, "map"):
                    chain.append(Strategy(strategy.kind, strategy.value, strategy.selector, "map",
                                          entry.index if entry.index is not None else strategy.index))
    if legacy is not None and (legacy_fallback or not chain):
        chain.append(legacy)
    return chain


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------
@dataclass
class Resolved:
    locator: Any                     # playwright Locator (already .nth()'d)
    strategy: Strategy
    position: int                    # index of the strategy in the chain (0 = primary)
    count: int                       # matches found by that strategy
    waited_ms: int = 0
    tried: list[str] = field(default_factory=list)

    @property
    def used_fallback(self) -> bool:
        return self.position > 0


class SelectorSyntaxError(Exception):
    """A locator that can never match because the selector itself is invalid."""


_SYNTAX_MARKERS = ("Unexpected token", "SyntaxError", "Unknown engine", "Invalid selector",
                   "is not a valid selector", "Failed to execute 'querySelectorAll'",
                   "Failed to execute 'evaluate'", "XPath")


async def resolve(scope, chain: list[Strategy], index: int, timeout_s: float,
                  poll_s: float = 0.1, give_up=None) -> Resolved | None:
    """Find the element, polling every ``poll_s``. The first strategy that matches wins.

    Every poll tries the chain in priority order, so a stale primary never delays a working
    fallback (the legacy runner polled once a second and only checked one locator).

    ``give_up(elapsed_s)`` (optional) is awaited after each fruitless round; returning True ends the
    search early.  Optional elements use it to stop as soon as the page has gone quiet.
    """
    started = time.monotonic()
    deadline = started + max(timeout_s, 0)
    syntax_error: SelectorSyntaxError | None = None
    while True:
        for position, strategy in enumerate(chain):
            want = strategy.index if strategy.index is not None else index
            try:
                base = scope.locator(strategy.selector)
                count = await base.count()
            except Exception as err:                # navigation in flight, frame detached, or a bad selector
                message = str(err)
                if any(marker in message for marker in _SYNTAX_MARKERS) and "Execution context" not in message:
                    syntax_error = SelectorSyntaxError(f"{strategy.describe()}: {message.splitlines()[0]}")
                continue
            if count > want:
                return Resolved(base.nth(want), strategy, position, count,
                                int((time.monotonic() - started) * 1000), [s.describe() for s in chain])
        elapsed = time.monotonic() - started
        if time.monotonic() >= deadline or (give_up is not None and syntax_error is None and await give_up(elapsed)):
            if syntax_error is not None:
                raise syntax_error
            return None
        await asyncio.sleep(poll_s)
