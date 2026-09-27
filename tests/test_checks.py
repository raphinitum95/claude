"""The plain logic behind the new check and widget steps (engine/checks.py, CONTRACT.md 1.3): numbers read from a page, comparison operators,
date formats, Y/N cells, the dates PICK_DATE understands, and the workbook parts the safety steps read (engine/gates.py).  No browser."""
from __future__ import annotations

from datetime import date, datetime

import openpyxl
import pytest

from regrunner.engine import checks
from regrunner.engine.gates import has_side_effects, is_production, read_fingerprints
from regrunner.selectors.spec import parse_backup_locators
from regrunner.workbook.model import PreparedStep
from regrunner.workbook.sheet import WorkbookData
from regrunner.workbook.variables import EnvironmentTable


@pytest.mark.parametrize("text,number", [("Total: $1,234.50", 1234.5), ("-12 points", -12.0), ("3", 3.0), (".5 kg", 0.5), ("none", None), ("", None)])
def test_the_first_number_on_the_page_is_read_with_thousands_separators_and_currency_ignored(text, number):
    assert checks.parse_number(text) == number


def test_operators_accept_names_and_symbols_and_blank_means_equal():
    assert [checks.operator_of(t) for t in ("gt", ">=", "<", "le", "", "!=", "between")] == ["GT", "GE", "LT", "LE", "EQ", "NE", "BETWEEN"]
    with pytest.raises(ValueError, match="not a comparison"):
        checks.operator_of("bigger")


def test_between_takes_low_and_high_in_either_order_and_includes_both_ends():
    low, high = checks.expected_numbers("BETWEEN", "10;5")
    assert (low, high) == (5, 10)
    assert checks.compare("BETWEEN", 5, low, high) and checks.compare("BETWEEN", 10, low, high) and not checks.compare("BETWEEN", 10.5, low, high)
    assert checks.describe("BETWEEN", low, high) == "between 5 and 10"
    with pytest.raises(ValueError, match="two numbers"):
        checks.expected_numbers("BETWEEN", "7")
    with pytest.raises(ValueError, match="must be a number"):
        checks.expected_numbers("GT", "lots")


def test_each_operator_compares_as_its_name_says():
    assert checks.compare("GT", 21, 20) and not checks.compare("GT", 20, 20)
    assert checks.compare("GE", 20, 20) and checks.compare("LT", 19, 20) and checks.compare("LE", 20, 20)
    assert checks.compare("EQ", 20, 20.0) and checks.compare("NE", 19, 20)


def test_y_and_n_cells_read_as_true_and_false_and_anything_else_as_unknown():
    assert [checks.yes_no(v) for v in ("Y", "no", True, "1", "maybe", "")] == [True, False, True, True, None, None]


@pytest.mark.parametrize("text,fmt,ok", [
    ("15/03/2027", "dd/mm/yyyy", True), ("5/3/2027", "dd/mm/yyyy", False), ("5/3/2027", "d/m/yyyy", True),
    ("31/02/2027", "dd/mm/yyyy", False), ("2027-03-15", "yyyy-mm-dd", True), ("15 Mar 2027", "d mmm yyyy", True),
    ("15 Mrz 2027", "d mmm yyyy", False), ("15 March 2027", "d mmmm yyyy", True), ("15/03/2027 14:30", "dd/mm/yyyy hh:mm", True),
    ("15/03/2027 24:30", "dd/mm/yyyy hh:mm", False), (" 15/03/2027 ", "dd/mm/yyyy", True), ("15-03-2027", "dd/mm/yyyy", False),
])
def test_a_date_must_be_real_and_written_exactly_in_the_format(text, fmt, ok):
    assert checks.matches_date_format(text, fmt)[0] is ok


def test_a_format_without_date_parts_is_refused_with_a_reason():
    assert "no date parts" in checks.date_format_error("abc")
    with pytest.raises(ValueError):
        checks.matches_date_format("x", "---")


@pytest.mark.parametrize("value", ["2027-03-15", "15/03/2027", "15 Mar 2027", "March 15, 2027", "15-Mar-2027", date(2027, 3, 15),
                                   datetime(2027, 3, 15, 0, 0), "2027-03-15 00:00:00", "46461"])
def test_pick_date_understands_the_usual_ways_of_writing_a_date_day_first(value):
    assert checks.parse_date(value) == date(2027, 3, 15)


def test_pick_date_refuses_what_is_not_a_date():
    with pytest.raises(ValueError, match="not a date"):
        checks.parse_date("next tuesday")
    with pytest.raises(ValueError, match="empty"):
        checks.parse_date("")


def test_a_date_is_written_in_the_shape_a_placeholder_shows():
    assert checks.looks_like_date_format("DD/MM/YYYY") and not checks.looks_like_date_format("Departure date")
    assert checks.format_date(date(2027, 3, 5), "DD/MM/YYYY") == "05/03/2027"
    assert checks.format_date(date(2027, 3, 5), "d mmm yyyy") == "5 Mar 2027"


def test_a_calendar_heading_gives_its_month():
    assert checks.month_index("March 2027") == (2027, 3) and checks.month_index("Sep 2026") == (2026, 9)
    assert checks.month_index("2027-11") == (2027, 11) and checks.month_index("Monday 2027") is None


def test_backup_locators_are_read_from_json_or_one_per_line_and_bad_ones_are_left_out():
    assert [s.describe() for s in parse_backup_locators('["css=#pay", "text=Pay now", ""]')] == ["css=#pay", "text=Pay now"]
    assert [s.describe() for s in parse_backup_locators("#pay\n//button[@id='x'] || id=go")] == ["css=#pay", "xpath=//button[@id='x']", "id=go"]
    assert parse_backup_locators("") == [] and parse_backup_locators("[]") == []


def test_production_comes_from_the_environment_table_and_a_prod_name_always_counts():
    table = EnvironmentTable(source="rr", names=["QA", "LIVE"], production=["LIVE"])
    assert is_production(table, "live") and not is_production(table, "QA")
    assert is_production(EnvironmentTable(), "PROD") and is_production(None, "production") and not is_production(None, "")


def test_a_side_effect_step_is_one_whose_side_effects_cell_says_y():
    assert has_side_effects(PreparedStep(row=2, values={"SIDE_EFFECTS": "Y"}))
    assert not has_side_effects(PreparedStep(row=2, values={"SIDE_EFFECTS": ""})) and not has_side_effects(PreparedStep(row=2, values={}))


def test_page_fingerprints_are_read_by_name_whatever_the_case(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "_rr_fingerprints"
    ws.append(["Name", "UrlContains", "Landmark", "LandmarkText", "Notes"])
    ws.append(["Payment page", "/pay", "css=h1", "Payment details", ""])
    ws.append(["", "/ignored", "", "", ""])
    wb.save(tmp_path / "f.xlsx")
    found = read_fingerprints(WorkbookData.load(tmp_path / "f.xlsx"))
    assert list(found) == ["PAYMENT PAGE"]
    assert found["PAYMENT PAGE"].url_contains == "/pay" and found["PAYMENT PAGE"].landmark_text == "Payment details"


class _Asker:
    """Answers a side-effect question the way a person would on the run screen."""

    def __init__(self, answer: str):
        self.answer, self.asked = answer, []

    async def ask(self, test, step, question, **kw):
        self.asked.append(question)
        return self.answer


def _side_effect_ctx(tmp_path, *, environment: str, mode: str, asker=None):
    from types import SimpleNamespace
    from regrunner.config import Config
    from regrunner.engine.actions import StepContext
    events: list = []
    runtime = SimpleNamespace(environment=environment, env_table=EnvironmentTable(source="rr", names=["UAT", "LIVE"], production=["LIVE"]))
    ctx = StepContext(step=PreparedStep(row=7, values={"METHOD": "CLICK", "STEP_NAME": "Pay now", "SIDE_EFFECTS": "Y"}), session=SimpleNamespace(),
                      cfg=Config(base_dir=tmp_path), selector_map=None, review=None, test_dir=tmp_path, seq=3, asker=asker, runtime=runtime,
                      emit=lambda type_, **f: events.append({"type": type_, **f}), side_effects=mode)
    return ctx, events


async def test_a_build_mode_replay_asks_before_a_side_effect_step_and_runs_it_only_on_yes(tmp_path):
    from regrunner.engine.actions import ActionError, side_effect_gate
    yes = _Asker("yes")
    ctx, events = _side_effect_ctx(tmp_path, environment="UAT", mode="ask", asker=yes)
    await side_effect_gate(ctx)
    assert "Run it for real?" in yes.asked[0] and '"Pay now"' in yes.asked[0] and not ctx.out.stop
    assert [e["type"] for e in events] == ["side_effect_paused"] and events[0]["row"] == 7 and events[0]["name"] == "Pay now"
    ctx, _ = _side_effect_ctx(tmp_path, environment="UAT", mode="ask", asker=_Asker("no thanks"))
    with pytest.raises(ActionError, match="chose not to run it"):
        await side_effect_gate(ctx)
    assert ctx.out.hard and "were not run" in ctx.out.stop


async def test_a_side_effect_step_is_never_run_on_production_even_when_a_person_would_say_yes(tmp_path):
    from regrunner.engine.actions import ActionError, side_effect_gate
    asker = _Asker("yes")
    ctx, events = _side_effect_ctx(tmp_path, environment="LIVE", mode="ask", asker=asker)
    with pytest.raises(ActionError, match="Blocked"):
        await side_effect_gate(ctx)
    assert asker.asked == [] and [e["type"] for e in events] == ["side_effect_blocked"] and ctx.out.hard and ctx.out.stop


async def test_a_normal_run_does_not_ask_before_a_side_effect_step(tmp_path):
    from regrunner.engine.actions import side_effect_gate
    asker = _Asker("no")
    ctx, events = _side_effect_ctx(tmp_path, environment="UAT", mode="run", asker=asker)
    await side_effect_gate(ctx)
    assert asker.asked == [] and events == []
