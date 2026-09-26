"""Selector harvesting: learn stable locators from the live DOM.

When ``selectors.harvest`` is on, every element found through a *legacy* locator is inspected and
the most resilient locator that uniquely identifies it (test id > id > name > aria/placeholder) is
recorded.  A suggestion is only produced when

* the candidate matches exactly one element in that frame (so it cannot pick a different element
  than the XPath did), and
* it is clearly more stable than the XPath it would replace, and
* *every* observed use of that XPath - across all tests and Index values - agrees on it.

``regrunner selectors apply RUN`` then merges the suggestions into ``selectors.yaml``.  This is how
position/text-based XPaths get replaced by generic ones without hand-editing 1,400 rows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .resolve import MapEntry, SelectorMap
from .spec import css_string, legacy_key
from .xpath2css import score_xpath

_INSPECT_JS = """el => {
  const attr = n => el.getAttribute(n);
  return { tag: el.tagName.toLowerCase(), id: el.id || '', name: attr('name') || '',
           testid: attr('data-testid') || attr('data-test') || attr('data-test-id') || '',
           aria: attr('aria-label') || '', placeholder: attr('placeholder') || '' };
}"""
_GENERATED = re.compile(r"[0-9a-f]{8,}|[-_]\d{4,}", re.IGNORECASE)
MIN_GAIN = 10          # a candidate must beat the legacy locator's score by this much


class HarvestStore:
    """Collects observations across tests (single event loop -> no locking needed)."""

    def __init__(self):
        self.observations: dict[str, list[dict[str, Any]]] = {}

    async def record(self, scope, res, step) -> None:
        key = legacy_key(step.findby, step.findby_value)
        legacy_score = score_xpath(step.findby_value)[0] if step.findby.upper().endswith("XPATH") else 90
        best: dict[str, Any] | None = None
        try:
            info = await res.locator.evaluate(_INSPECT_JS, timeout=1500)
        except Exception:
            return
        tag = info["tag"]
        candidates = []
        if info["testid"]:
            candidates.append(("testid", f'css=[data-testid={css_string(info["testid"])}]', 95))
        if info["id"] and not _GENERATED.search(info["id"]):
            candidates.append(("id", f'css=[id={css_string(info["id"])}]', 92))
        if info["name"]:
            candidates.append(("name", f'css={tag}[name={css_string(info["name"])}]', 90))
        if info["aria"]:
            candidates.append(("aria", f'css={tag}[aria-label={css_string(info["aria"])}]', 70))
        if info["placeholder"]:
            candidates.append(("placeholder", f'css={tag}[placeholder={css_string(info["placeholder"])}]', 60))
        for kind, selector, score in candidates:
            if score < legacy_score + MIN_GAIN:
                continue
            try:
                unique = await scope.locator(selector).count() == 1
            except Exception:
                continue
            if unique:
                best = {"use": selector, "kind": kind, "score": score}
                break
        self.observations.setdefault(key, []).append(
            {"index": step.index, "step": step.name, "legacy_score": legacy_score, "candidate": best})

    def suggestions(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Consolidate observations into safe suggestions plus a {key: reason} map of what was skipped."""
        safe: dict[str, dict[str, Any]] = {}
        skipped: dict[str, str] = {}
        for key, obs in self.observations.items():
            candidates = {o["candidate"]["use"] for o in obs if o["candidate"]}
            if any(o["candidate"] is None for o in obs):
                skipped[key] = "no unique, clearly more stable locator for at least one use"
            elif len(candidates) > 1:
                skipped[key] = "the same XPath targets different elements in different steps"
            else:
                first = obs[0]["candidate"]
                safe[key] = {"use": [first["use"]], "index": 0, "score": first["score"], "kind": first["kind"],
                             "legacy_score": obs[0]["legacy_score"], "uses": len(obs), "example_step": obs[0]["step"]}
        return safe, skipped

    def save(self, path: Path) -> None:
        safe, skipped = self.suggestions()
        path.write_text(json.dumps({"suggestions": safe, "skipped": skipped}, indent=2, ensure_ascii=False),
                        encoding="utf-8")


def apply_suggestions(suggestions_path: Path, selector_map: SelectorMap, *, min_score: int = 85,
                      only: set[str] | None = None) -> int:
    """Merge harvested suggestions (score >= ``min_score``, optionally just ``only`` these keys). Returns how many."""
    data = json.loads(suggestions_path.read_text(encoding="utf-8")).get("suggestions", {})
    added = 0
    for key, s in data.items():
        if s["score"] < min_score or key in selector_map.entries or (only is not None and key not in only):
            continue
        selector_map.entries[key] = MapEntry(use=s["use"], index=s.get("index"), source="harvest",
                                             note=f'{s["kind"]} on the live DOM (XPath scored {s["legacy_score"]})')
        added += 1
    return added
