"""Result data model (what ``results.json`` and the reports are built from)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def variables_of(test: dict[str, Any]) -> list[dict[str, Any]]:
    """The parameters a test set (from its ``variables`` in results.json): one per name, with what the cell holds at the end of the test."""
    latest: dict[str, dict[str, Any]] = {}
    for item in test.get("variables", []):
        latest[str(item.get("name", "")).upper()] = item
    return list(latest.values())


@dataclass
class StepRecord:
    seq: int
    row: int
    name: str
    action: str
    status: str                          # PASSED | FAILED
    error: str = ""
    ignored_error: str = ""              # swallowed by Ignore_not_existing_object
    expected: str = ""
    actual: str = ""
    comparison: str = ""                 # exact | contains | ""
    value: str = ""
    locator: str = ""
    locator_origin: str = ""             # sheet | map | auto | legacy
    fallback_used: bool = False
    notes: list[str] = field(default_factory=list)
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    screenshot: str | None = None        # path relative to the run folder
    screenshot_full: str | None = None   # failed steps: the whole page, not only what fits the window
    box: dict[str, float] | None = None  # the acted-on element on that screenshot, in % of the viewport
    sets: list[dict[str, str]] = field(default_factory=list)   # parameters this step set: [{name, value, stored, cell}] (a secret is masked)
    detail: str = ""                     # the browser's whole error when ``error`` keeps only its first line (Playwright's call log: why a click could not happen)
    diagnosis: dict[str, Any] | None = None   # failed steps: what the page looked like (see engine/failure_capture.py)


@dataclass
class TestResult:
    __test__ = False
    id: str
    title: str
    sheet: str = ""
    scenario: str = ""
    description: str = ""
    status: str = "QUEUED"               # PASSED | FAILED | ERROR | CANCELLED | NOT_RUN (the machine could not run it: never a pass or a fail)
    started_at: str = ""
    ended_at: str = ""
    duration_s: float = 0.0
    total_steps: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    review: list[dict[str, Any]] = field(default_factory=list)
    attempt: int = 1
    attempts: list[dict[str, Any]] = field(default_factory=list)   # earlier attempts (retries)
    blocked: str = ""                    # set when the site's WAF blocked this attempt (HTTP 403 / 429): why
    captcha: str = ""                    # set when a captcha challenge stopped this attempt: what it was and why nobody could get past it
    infra: str = ""                      # set when the machine, not the site, ended this attempt (the browser crashed / ran out of memory / disconnected, the driver died)
    variables: list[dict[str, Any]] = field(default_factory=list)   # every parameter this test set: [{name, value, stored, cell, seq, row, step, by_hand}]


@dataclass
class RunResult:
    run_id: str
    workbook: str
    environment: str
    started_at: str
    ended_at: str = ""
    duration_s: float = 0.0
    status: str = "RUNNING"              # PASSED | FAILED | CANCELLED | ERROR
    workers: int = 1
    seed: int | None = None
    config: dict[str, Any] = field(default_factory=dict)
    tests: list[TestResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    partial: bool = False                # rebuilt from events.jsonl after the run stopped without finishing
    browser: dict[str, Any] = field(default_factory=dict)   # the browser every test of the run used (browsers.identity: name, engine, version, headless)

    @property
    def summary(self) -> dict[str, Any]:
        steps = sum(len(t.steps) for t in self.tests)
        return {
            "tests": len(self.tests),
            "passed": sum(t.status == "PASSED" for t in self.tests),
            "failed": sum(t.status == "FAILED" for t in self.tests),
            "errored": sum(t.status in ("ERROR", "CANCELLED") for t in self.tests),
            "not_run": sum(t.status == "NOT_RUN" for t in self.tests),
            "steps": steps,
            "steps_failed": sum(t.failed for t in self.tests),
            "review_items": sum(len(t.review) for t in self.tests),
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary"] = self.summary
        return data

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)


def load_run_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
