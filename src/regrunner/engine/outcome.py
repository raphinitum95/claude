"""Pass/fail rules - a faithful port of the legacy ``GUI_Functions.validateresults``.

Rules (verified against the legacy source):

* A step starts PASSED. Any error message fails it, **unless** ``Ignore_not_existing_object=Y`` -
  then every error (missing element, click intercepted, ...) is swallowed.
* Element actions on a missing element fail with "Object was not found" (again unless ignored).
* ``Exact_Match=Y``: ``str(expected) == str(actual)`` exactly; both blank counts as equal.
* ``Contains=Y``: case-insensitive, trimmed substring test.
* With neither flag, expected/actual are NOT compared - the step only captures the value.
* An Exact_Match / Contains mismatch fails the step even when errors are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..workbook.model import PreparedStep, is_blank
from ..workbook.sheet import cell_text

PASSED, FAILED = "PASSED", "FAILED"


@dataclass
class StepOut:
    """What an action reported back (mutated by handlers)."""

    output: Any = None                 # legacy "OV": captured text / URL / count ...
    error: str = ""
    obj_exists: bool | None = None     # None: not an element action or not attempted
    notes: list[str] = field(default_factory=list)
    locator: str = ""                  # description of the strategy that found the element
    fallback_used: bool = False
    locator_origin: str = ""           # sheet | map | auto | legacy: where the locator that matched came from
    handle: Any = field(default=None, repr=False)   # handle on the element acted on (for the screenshot highlight)
    target: Any = field(default=None, repr=False)   # Playwright locator of the element the step resolved (what a failure is diagnosed against)
    detail: str = ""                   # the browser's whole error when ``error`` keeps only its first line (Playwright's call log says *why* a click could not happen)
    secret: bool = False               # the output is something a person typed in for the run (a password / code): never shown in reports or events
    hard: bool = False                 # the error is not about a missing element (an empty parameter...): Ignore_not_existing_object does not swallow it


@dataclass
class Verdict:
    status: str
    error: str = ""
    ignored_error: str = ""            # error swallowed by Ignore_not_existing_object (kept for the report)
    comparison: str = ""               # "exact" | "contains" | ""


def normalize_expected(value: Any) -> str:
    return cell_text(value).replace("\r\n", "\n")


def compare_ok(step: PreparedStep, actual: str) -> tuple[bool, str]:
    """Apply Exact_Match / Contains. Returns (ok, mode)."""
    expected = normalize_expected(step.expected)
    if step.exact_match:
        if is_blank(expected) and is_blank(actual):
            return True, "exact"
        return expected == actual, "exact"
    if step.contains:
        return expected.upper().strip() in actual.upper().strip(), "contains"
    return True, ""


def evaluate(step: PreparedStep, out: StepOut, *, element_action: bool, actual: str) -> Verdict:
    status, error, ignored = PASSED, out.error or "", ""
    ignore = step.ignore_missing
    if error:
        if ignore and not out.hard:
            ignored, error = error, ""
        else:
            status = FAILED
    if element_action and out.obj_exists is False:
        if ignore:
            ignored = ignored or "Object was not found"
        else:
            status = FAILED
            error = f"{error}-Object was not found" if error else "Object was not found"
    ok, mode = compare_ok(step, actual)
    if not ok:
        status, error = FAILED, "Comparison Failed"
    return Verdict(status, error, ignored, mode)
