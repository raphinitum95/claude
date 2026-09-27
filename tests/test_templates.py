"""workbook/templates.py: the shared template library (Q15-17). No browser."""
from __future__ import annotations

from pathlib import Path

import pytest

from regrunner.workbook.builder import BuildError, build_model
from regrunner.workbook.templates import (get_template, insert_template_ops, list_templates, match_variables,
                                          save_as_template, templates_path)
from regrunner.workbook.writer import WorkbookEditor
from tests.workbook_factory import build_steps_workbook


def buy_flow(sheet):
    sheet.header("Traveler")
    sheet.add("SET", "Type first name", FindBy="xpath", FindBy_Value="//input[@id='first']", Value="FIRST_NAME")
    sheet.add("SET", "Type last name", FindBy="xpath", FindBy_Value="//input[@id='last']", Value="LAST_NAME")
    sheet.add("CLICK", "Click Continue", FindBy="xpath", FindBy_Value="//button[@id='go']")


@pytest.fixture
def model(tmp_path) -> tuple[dict, Path]:
    path = tmp_path / "wb.xlsx"
    build_steps_workbook(path, {"Buy": buy_flow}, params={"Buy": {"FIRST_NAME": "Jane", "LAST_NAME": "Doe"}})
    return build_model(WorkbookEditor.open(path), with_problems=False), tmp_path


def test_library_is_empty_before_it_exists(tmp_path):
    assert list_templates(templates_path(tmp_path)) == []


def test_save_as_template_extracts_the_row_range_and_templatizes_params_tokens(model):
    m, workbooks_dir = model
    t = next(x for x in m["tests"] if x["id"] == "Buy")
    first, last = t["steps"][0], t["steps"][1]                    # Type first name, Type last name (Click Continue excluded)
    lib = templates_path(workbooks_dir)
    result = save_as_template(m, lib, test_id="Buy", from_row=first["row"], to_row=last["row"], name="Traveler form",
                              description="First and last name")
    assert result == {"name": "Traveler form", "count": 2}

    templates = list_templates(lib)
    assert [tpl["name"] for tpl in templates] == ["Traveler form"]
    tpl = templates[0]
    assert tpl["description"] == "First and last name"
    assert tpl["count"] == 2
    assert sorted(tpl["variables"]) == ["FIRST_NAME", "LAST_NAME"]  # the bare Params tokens became {TOKEN}
    values = [s["value"] for s in tpl["steps"]]
    assert values == ["{FIRST_NAME}", "{LAST_NAME}"]
    assert get_template(lib, "Traveler form")["count"] == 2


def test_save_as_template_refuses_a_duplicate_name(model):
    m, workbooks_dir = model
    t = next(x for x in m["tests"] if x["id"] == "Buy")
    lib = templates_path(workbooks_dir)
    save_as_template(m, lib, test_id="Buy", from_row=t["steps"][0]["row"], to_row=t["steps"][0]["row"], name="Dup")
    with pytest.raises(BuildError) as err:
        save_as_template(m, lib, test_id="Buy", from_row=t["steps"][0]["row"], to_row=t["steps"][0]["row"], name="Dup")
    assert err.value.kind == "exists"


def test_match_variables_exact_close_match_and_no_match():
    variables = [{"token": "FIRST_NAME", "key": "FIRST_NAME", "label": "First name"},
                {"token": "DATE_OF_BIRTH", "key": "DATE_OF_BIRTH", "label": "Date of birth"}]
    rows = match_variables(["FIRST_NAME", "FIRSTNAME", "EMERGENCY_PHONE"], variables)
    by_tok = {r["templateVar"]: r for r in rows}
    assert by_tok["FIRST_NAME"]["mine"] == "FIRST_NAME" and by_tok["FIRST_NAME"]["how"] == "same name"
    assert by_tok["FIRSTNAME"]["mine"] == "FIRST_NAME" and "close match" in by_tok["FIRSTNAME"]["how"]
    assert by_tok["EMERGENCY_PHONE"]["mine"] is None and by_tok["EMERGENCY_PHONE"]["how"] == "no match"


def test_insert_template_ops_rewrites_mapped_and_unmapped_tokens():
    template = {"steps": [{
        "method": "SET", "name": "Type first name", "nameAuto": False, "page": "", "output": "", "outputProperty": "",
        "onFail": "stop", "timeout": None, "enabled": True, "sideEffects": False, "notes": "", "match": "",
        "value": "{FIRST_NAME}", "expected": "",
        "locator": {"findBy": "xpath", "value": "//input[@id='first']", "index": 0, "name": "", "backups": []},
    }]}
    ops = insert_template_ops(template, mapping={"FIRST_NAME": "FNAME"}, test_id="Buy", param_sheet="Params_1", after=10)
    assert ops == [{"op": "insert_step", "test": "Buy", "after": 10,
                    "step": {"method": "SET", "name": "Type first name", "page": "", "findBy": "xpath",
                            "locator": "//input[@id='first']", "locatorName": "", "value": "{FNAME}", "expected": "",
                            "match": "", "output": "", "outputProperty": "", "onFail": "stop", "timeout": None,
                            "enabled": True, "sideEffects": False, "notes": ""}}]


def test_insert_template_ops_creates_a_column_when_mapping_says_so_and_marks_unmapped_when_it_cannot():
    template = {"steps": [{
        "method": "SET", "name": "", "nameAuto": True, "page": "", "output": "", "outputProperty": "",
        "onFail": "stop", "timeout": None, "enabled": True, "sideEffects": False, "notes": "", "match": "",
        "value": "{FIRST_NAME}", "expected": "",
        "locator": {"findBy": "xpath", "value": "//input", "index": 0, "name": "", "backups": []},
    }]}
    with_params = insert_template_ops(template, mapping={"FIRST_NAME": None}, test_id="Buy", param_sheet="Params_1", after=1)
    assert with_params[0] == {"op": "add_variable", "token": "FIRST_NAME", "sheet": "Params_1"}
    assert with_params[1]["step"]["value"] == "{FIRST_NAME}"

    without_params = insert_template_ops(template, mapping={"FIRST_NAME": None}, test_id="Buy", param_sheet=None, after=1)
    assert without_params == [{"op": "insert_step", "test": "Buy", "after": 1,
                               "step": {"method": "SET", "nameAuto": True, "page": "", "findBy": "xpath",
                                       "locator": "//input", "locatorName": "", "value": "{?FIRST_NAME}", "expected": "",
                                       "match": "", "output": "", "outputProperty": "", "onFail": "stop", "timeout": None,
                                       "enabled": True, "sideEffects": False, "notes": ""}}]
