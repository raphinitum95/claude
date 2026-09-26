"""A failed step also saves the whole page: the window-sized screenshot misses what is below the fold (the agent portal's Start Medical Assessment button needed a scroll)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import openpyxl
import pytest

from regrunner.lint import lint
from regrunner.workbook import Workbook
from tests.test_failure_capture import build, click, run, step_named
from tests.workbook_factory import build_workbook


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    i = 2
    while i < len(data):
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise AssertionError("no size in the JPEG")


MISSING = lambda i: ("Click", f"missing {i}", click(f"//a[@id='nope{i}']", timeout=1))                  # noqa: E731


@pytest.mark.browser
async def test_a_failed_step_gets_a_screenshot_of_the_whole_page(site, make_cfg, tmp_path):
    wb = build(tmp_path / "wb.xlsx", site, "/tall.html", [("Exist", "fine", {"FindBy": "xpath", "FindBy_Value": "//h1", "Index": 0, "Timeout": 2}), MISSING(1)])
    result, events, _ = await run(make_cfg, wb)
    run_dir = tmp_path / "runs" / result.run_id
    bad, good = step_named(result, "missing 1"), step_named(result, "fine")
    assert good.screenshot_full is None and bad.screenshot_full and (run_dir / bad.screenshot_full).is_file()
    (w, viewport_h), (fw, full_h) = jpeg_size(run_dir / bad.screenshot), jpeg_size(run_dir / bad.screenshot_full)
    assert full_h > 3 * viewport_h and fw == w                                                # the whole 3200 px page, not the 1080 px window
    saved = json.loads((run_dir / "results.json").read_text())
    assert next(s for s in saved["tests"][0]["steps"] if s["name"] == "missing 1")["screenshot_full"] == bad.screenshot_full
    assert next(e for e in events if e["type"] == "step_failed")["screenshot_full"] == bad.screenshot_full
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert 'data-full="1"' in report and "whole page (scroll)" in report                     # shown in the report as a second thumbnail


@pytest.mark.browser
async def test_it_can_be_switched_off_and_is_kept_for_the_first_failures_only(site, make_cfg, tmp_path):
    rows = [MISSING(i) for i in range(1, 4)]
    off, _, _ = await run(make_cfg, build(tmp_path / "a.xlsx", site, "/tall.html", rows), **{"failure_capture.full_page_screenshot": False, "runner.stop_after_failed_steps": 0})
    assert all(s.screenshot_full is None for s in off.tests[0].steps)
    capped, _, _ = await run(make_cfg, build(tmp_path / "b.xlsx", site, "/tall.html", rows), **{"failure_capture.full_page_max_per_test": 2, "runner.stop_after_failed_steps": 0})
    assert [bool(step_named(capped, f"missing {i}").screenshot_full) for i in range(1, 4)] == [True, True, False]


def numbers_copy(tmp_path: Path, site: str) -> Path:
    path = tmp_path / "numbers.xlsx"
    build_workbook(path, base_url=site)
    wb = openpyxl.load_workbook(path)
    wb.create_sheet("Export Summary", 0).append(["Table", "Note"])                            # what Apple Numbers adds when it exports to .xlsx
    wb.save(path)
    return path


def test_a_workbook_saved_through_apple_numbers_is_flagged(tmp_path, site):
    book = Workbook(numbers_copy(tmp_path, site), seed=1)
    book.discover()
    (note,) = [w for w in book.warnings if "Apple Numbers" in w]
    assert "replaces formulas" in note and "TODAY()+1" in note and "Excel" in note
    assert any("Apple Numbers" in f.message and f.severity == "warning" for f in lint(book))         # `regrunner lint` and the run's own warnings say it too


def test_an_ordinary_workbook_is_not(tmp_path, site):
    path = tmp_path / "plain.xlsx"
    build_workbook(path, base_url=site)
    book = Workbook(path, seed=1)
    book.discover()
    assert not any("Numbers" in w for w in book.warnings)
