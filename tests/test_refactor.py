"""workbook/refactor.py: find & replace, duplicate "what changes?", and per-step merge (Q26, Q29). No browser."""
from __future__ import annotations

from pathlib import Path

import pytest

from regrunner.workbook.builder import BuildError, apply_ops, build_model
from regrunner.workbook.refactor import (apply_ops_for_hits, duplicate_candidates, find_replace_preview, merge_ops,
                                         mergeable_hits, most_used_values)
from regrunner.workbook.writer import WorkbookEditor
from tests.workbook_factory import build_steps_workbook


def two_destinations(sheet):
    sheet.header("Trip")
    sheet.add("SET", "Type destination", FindBy="xpath", FindBy_Value="//input[@id='dest']", Value="Italy")
    sheet.add("OUTPUT", "Check confirmation", FindBy="xpath", FindBy_Value="//h1", Expected_Value="Italy", Exact_Match="Y")


@pytest.fixture
def wb(tmp_path) -> Path:
    path = tmp_path / "wb.xlsx"
    build_steps_workbook(path, {"Book": two_destinations})
    editor = WorkbookEditor.open(path)
    apply_ops(editor, [{"op": "set_environments", "names": ["UAT", "PROD"], "production": ["PROD"],
                        "rows": [{"variable": "DOMAIN", "required": True,
                                 "values": {"UAT": "uat.travelex-insurance.test", "PROD": "www.travelex-insurance.com"}}]}])
    editor.save()
    return path


def test_find_replace_preview_whole_value_match(wb):
    editor = WorkbookEditor.open(wb)
    hits = find_replace_preview(editor, [{"find": "Italy", "replace": "Japan", "whole": True}])
    assert {(h["sheet"], h["row"], h["before"], h["after"]) for h in hits} == {
        ("Book", 3, "Italy", "Japan"), ("Book", 4, "Italy", "Japan")}


def test_find_replace_preview_partial_match_and_never_touches_headers(wb):
    editor = WorkbookEditor.open(wb)
    hits = find_replace_preview(editor, [{"find": "travelex", "replace": "qantas", "whole": False}])
    assert any(h["sheet"] == "_rr_environments" and h["after"] == "uat.qantas-insurance.test" for h in hits)
    assert all(h["row"] != 1 for h in hits)                         # row 1 is the header row on every sheet


def test_find_replace_preview_skips_formulas_and_empty_find(wb):
    editor = WorkbookEditor.open(wb)
    assert find_replace_preview(editor, [{"find": "COUNTA", "replace": "x"}]) == []   # Step_Number formulas untouched
    with pytest.raises(BuildError):
        find_replace_preview(editor, [{"find": "", "replace": "x"}])


def test_apply_ops_for_hits_builds_set_cell_ops_and_they_actually_apply(wb):
    editor = WorkbookEditor.open(wb)
    hits = find_replace_preview(editor, [{"find": "Italy", "replace": "Japan"}])
    ops = apply_ops_for_hits(hits)
    assert all(o["op"] == "set_cell" for o in ops)
    apply_ops(editor, ops)
    model = build_model(editor, with_problems=False)
    step = next(s for s in model["tests"][0]["steps"] if s["method"] == "SET")
    assert step["value"] == "Japan"


def test_most_used_values_counts_repeats_and_ignores_variables_and_formulas():
    model = {"tests": [{"steps": [
        {"value": "Italy", "expected": ""}, {"value": "", "expected": "Italy"},
        {"value": "{DESTINATION}", "expected": ""}, {"value": "=TODAY()", "expected": ""}, {"value": "x", "expected": ""},
    ]}]}
    assert most_used_values(model) == [{"value": "Italy", "count": 2}]


def test_duplicate_candidates_seeds_name_domain_and_repeated_text(wb):
    model = build_model(WorkbookEditor.open(wb), with_problems=False)
    model["name"] = "Travelex Regression.xlsx"
    rows = duplicate_candidates(model, "Qantas Regression")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"name", "domain", "text"}
    name_row = next(r for r in rows if r["kind"] == "name")
    assert name_row == {"kind": "name", "label": "Workbook name", "find": "Travelex Regression", "replace": "Qantas Regression", "whole": False}
    assert {r["find"] for r in rows if r["kind"] == "domain"} == {"uat.travelex-insurance.test", "www.travelex-insurance.com"}
    assert any(r["kind"] == "text" and r["find"] == "Italy" for r in rows)


def test_mergeable_hits_and_merge_ops_only_act_on_changed_rows():
    hits = [
        {"test": "Book", "row": 3, "kind": "changed",
         "before": {"method": "SET", "name": "Type destination", "nameAuto": False, "locator": "//input", "value": "Italy",
                    "expected": "", "enabled": True, "block": "Trip"},
         "after": {"method": "SET", "name": "Type destination", "nameAuto": False, "locator": "//input", "value": "Japan",
                   "expected": "", "enabled": True, "block": "Trip"}},
        {"test": "Book", "row": 5, "kind": "added", "before": None, "after": {"method": "CLICK"}},
    ]
    assert [h["row"] for h in mergeable_hits(hits)] == [3]
    ops = merge_ops(hits, {"Book:3": "theirs"})
    assert ops == [{"op": "update_step", "test": "Book", "row": 3,
                    "set": {"method": "SET", "locator": "//input", "value": "Italy",
                           "expected": "", "enabled": True, "block": "Trip", "name": "Type destination"}}]
    assert merge_ops(hits, {"Book:3": "mine"}) == []


def test_merge_ops_restores_auto_naming_instead_of_pinning_the_generated_name():
    """A step whose name is still auto-generated (nameAuto True) must not come out of a merge with that generated text
    frozen as a literal name - update_step treats any non-empty ``name`` as a manual rename."""
    hits = [{"test": "Book", "row": 3, "kind": "changed",
            "before": {"method": "SET", "name": "Type destination", "nameAuto": True, "locator": "//input", "value": "Italy",
                       "expected": "", "enabled": True, "block": "Trip"},
            "after": {"method": "SET", "name": "Type destination", "nameAuto": True, "locator": "//input", "value": "Japan",
                      "expected": "", "enabled": True, "block": "Trip"}}]
    ops = merge_ops(hits, {"Book:3": "theirs"})
    assert ops[0]["set"]["name"] == ""
