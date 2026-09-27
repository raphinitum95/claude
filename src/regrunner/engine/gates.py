"""What the safety steps of the new runner read from the workbook (CONTRACT.md 1.1 / 1.4, P07).

* **Page fingerprints** (``_rr_fingerprints``: ``Name | UrlContains | Landmark | LandmarkText | Notes``): what ``ASSERT_PAGE`` checks.  Both the URL
  part and the landmark must hold; a failed gate is always a hard stop (Q53).
* **Production**: an environment the workbook's ``_rr_environments`` marks production (the ``#PRODUCTION`` row; without it, one named ``PROD`` /
  ``PRODUCTION``).  A step with ``SIDE_EFFECTS=Y`` never runs there (Q13).
* **Side-effect steps** (``SIDE_EFFECTS=Y``: Purchase, Pay, Submit order...): blocked on production, paused for a person in build-mode replays
  (``TestRunner(side_effects="ask")``, P08), and run as usual in a normal run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..workbook.model import is_true
from ..workbook.sheet import WorkbookData, cell_text

RR_FINGERPRINTS = "_rr_fingerprints"                    # same name as builder.RR_FINGERPRINTS (the builder imports the engine, not the other way)
SIDE_EFFECTS_COLUMN = "SIDE_EFFECTS"
PRODUCTION_NAMES = ("PROD", "PRODUCTION")
SIDE_EFFECT_MODES = ("run", "ask")                      # run: a normal run (unchanged); ask: a build-mode replay asks before each one


@dataclass(frozen=True)
class Fingerprint:
    name: str
    url_contains: str = ""
    landmark: str = ""                                  # a locator (css= / xpath= / text= ... as in FindBy_Value)
    landmark_text: str = ""


def read_fingerprints(data: WorkbookData) -> dict[str, Fingerprint]:
    """``_rr_fingerprints`` by UPPER name ({} when the workbook has none)."""
    sheet = data.sheet(RR_FINGERPRINTS)
    if sheet is None or "NAME" not in sheet.headers:
        return {}

    def text(row: int, header: str) -> str:
        col = sheet.headers.get(header)
        cell = sheet.cells.get((row, col)) if col else None
        return "" if cell is None else (cell.formula or cell_text(cell.value)).strip()
    out: dict[str, Fingerprint] = {}
    for r in range(2, sheet.max_row + 1):
        name = text(r, "NAME")
        if name and name.upper() not in out:
            out[name.upper()] = Fingerprint(name, text(r, "URLCONTAINS"), text(r, "LANDMARK"), text(r, "LANDMARKTEXT"))
    return out


def is_production(env_table: Any, environment: str) -> bool:
    """Is ``environment`` production for this workbook?  Its environment table says so; a name such as PROD always counts (never less safe)."""
    env = (environment or "").upper().strip()
    if not env:
        return False
    if env_table is not None and env_table.is_production(env):
        return True
    return env in PRODUCTION_NAMES


def has_side_effects(step) -> bool:
    return is_true(step.values.get(SIDE_EFFECTS_COLUMN))
