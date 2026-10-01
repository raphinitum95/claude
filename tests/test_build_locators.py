"""From a picked element to a locator (build/locators.py, P08): pure logic, no browser."""
from __future__ import annotations

from regrunner.build import locators as L
from regrunner.selectors.spec import parse_backup_locators


def button(**extra) -> dict:
    return L.to_desc({"tag": "button", "kind": "button", "text": "Choose", "classes": ["choose"], "cssPath": "body > div > div:nth-of-type(3) > button",
                      "context": {"kind": "card", "tag": "div", "heading": "Max", "headingTag": "h3", "classes": ["card", "plan-card"]}, **extra})


def checked(cands: list[L.Candidate], results: dict[str, tuple[int, int]]) -> list[L.Candidate]:
    """Fill in what the live check would have found: {how: (count, position)}; anything not listed finds nothing."""
    for c in cands:
        c.count, c.position = results.get(c.how, (0, -1))
    return cands


def test_generated_ids_and_classes_are_never_trusted_but_readable_ones_are():
    assert all(L.stable_id(v) for v in ("firstName", "pay-button", "card--max", "btnSubmit"))
    assert not any(L.stable_id(v) for v in ("ember1234", "react-select-3-input", "field-12", ":r1:", "a1b2c3d4e5f6", "id with space", "x" * 61))
    assert L.stable_classes(["card", "active", "css-1x2y3z", "Button_root__a1B2c", "is-open", "plan-card", "sc-bdVaJa"]) == ["card", "plan-card"]


def test_candidates_go_from_the_most_stable_to_the_most_fragile():
    desc = L.to_desc({"tag": "input", "kind": "field", "id": "firstName", "name": "first_name", "placeholder": "Jane", "label": "First name",
                      "classes": ["fld"], "cssPath": "#firstName"})
    hows = [c.how for c in L.candidates(desc)]
    assert hows[0] == "id" and hows.index("attribute") < hows.index("text") < hows.index("position") < hows.index("path")
    assert L.candidates(desc)[0].findby == "BY_ID" and L.candidates(desc)[0].value == "firstName"
    tid = L.candidates(L.to_desc({"tag": "button", "text": "Pay now", "testid": {"attr": "data-testid", "value": "pay-now"}}))[0]
    assert (tid.findby, tid.value, tid.how) == ("BY_CSSSELECTOR", '[data-testid="pay-now"]', "testid")


def test_an_element_that_is_read_is_never_found_by_the_text_it_shows_now():
    desc = L.to_desc({"tag": "span", "text": "87302884", "classes": ["quote-number"], "context": {"heading": "Your quote", "tag": "div", "headingTag": "h2"}})
    assert any("87302884" in c.value for c in L.candidates(desc))
    read = L.candidates(desc, own_text=False)
    assert read and not any("87302884" in c.value for c in read)
    assert any(c.how == "context" and "quote-number" in c.value for c in read)           # (still found through its container, by its class)


def test_a_button_that_is_not_unique_by_its_text_is_found_through_its_cards_heading():
    cands = L.candidates(button())
    forms = {c.how: c.value for c in cands}
    assert forms["text"] == "//button[normalize-space(.)='Choose']"
    context = [c.value for c in cands if c.how == "context"]
    assert context[0] == ("//h3[normalize-space(.)='Max']/ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]"
                          "//button[normalize-space(.)='Choose']")
    choice = L.choose(checked(cands, {"text": (3, 2), "context": (1, 0), "position": (3, 2), "path": (1, 0)}))
    assert choice.primary.how == "context" and choice.to_json()["index"] == 0
    backups = choice.to_json()["backups"]
    assert backups[0].startswith("xpath=//h3") and "css=button.choose >> nth=2" in backups and len(backups) <= L.MAX_BACKUPS
    assert [s.kind for s in parse_backup_locators(L.backups_json(backups))] == ["xpath"] * (len(backups) - 2) + ["css", "css"]


def test_when_nothing_finds_the_element_alone_its_position_among_matches_is_used():
    cands = L.candidates(L.to_desc({"tag": "span", "text": "", "classes": ["price"]}))
    choice = L.choose(checked(cands, {"position": (3, 1)}))
    assert choice.primary.value == "span.price" and choice.to_json()["index"] == 1
    assert not L.choose(checked(L.candidates(L.to_desc({"tag": "span"})), {})).ok


def test_plain_words_describe_the_element_and_its_container_and_name_variables():
    words = L.plain_words(button())
    assert L.describe(words) == "button “Choose” inside card “Max”"
    assert [w["role"] for w in words] == ["kind", "name", "context-kind", "context"]
    assert L.describe(L.plain_words(button(), {"context": "PLAN"})) == "button “Choose” inside card {PLAN}"


def test_a_word_made_a_variable_only_keeps_the_locators_that_carry_it():
    cands = L.candidates(button(), context_as="{PLAN}")
    assert cands and all("{PLAN}" in c.value for c in cands)
    assert cands[0].selector({"plan": "Basic"}).startswith("xpath=//h3[normalize-space(.)='Basic']")
    by_name = L.candidates(button(), name_as="{ACTION}")
    assert by_name[0].value == "//button[normalize-space(.)='{ACTION}']"


def test_the_words_of_a_stored_locator_are_read_back_for_the_step_card():
    stored = ("//h3[normalize-space(.)='{PLAN}']/ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]"
              "//button[normalize-space(.)='Choose']")
    words = L.words_of_locator("BY_XPATH", stored)
    assert [(w["text"], w["variable"]) for w in words] == [("button", ""), ("Choose", ""), ("inside card", ""), ("{PLAN}", "PLAN")]
    assert L.words_of_locator("XPATH", "//a[normalize-space(.)='Next page']") == [
        {"text": "link", "role": "kind", "variable": ""}, {"text": "Next page", "role": "name", "variable": ""}]
    assert L.words_of_locator("BY_XPATH", "//label[normalize-space(.)='First name']/following::input[1]")[1]["text"] == "First name"
    assert L.words_of_locator("BY_ID", "firstName") == [] and L.words_of_locator("BY_XPATH", "//div[@id='x']/span") == []


def test_what_the_page_sends_is_trimmed_to_known_keys_and_sizes():
    desc = L.to_desc({"tag": "button" * 200, "evil": "x", "classes": ["a"] * 50, "context": {"heading": "h", "junk": 1}, "testid": "nope"})
    assert "evil" not in desc and len(desc["tag"]) == 500 and len(desc["classes"]) == 20
    assert set(desc["context"]) == {"kind", "tag", "heading", "headingTag", "id", "classes"} and desc["testid"] is None
    assert L.to_desc("not a dict") == {}


def test_an_id_shared_by_a_few_elements_beats_a_class_position_and_a_page_wide_tag():
    desc = L.to_desc({"tag": "input", "id": "cmp-Input", "classes": ["inputField"], "placeholder": "Enter destinations", "cssPath": "body > div > input"})
    cands = L.candidates(desc)
    choice = L.choose(checked(cands, {"id": (3, 1), "attribute": (3, 1), "position": (40, 7), "path": (1, 0)}))
    assert choice.primary.how == "id" and choice.to_json()["index"] == 1 and choice.primary.value == "cmp-Input"


def test_a_name_shared_with_many_elements_is_not_a_locator():
    desc = L.to_desc({"tag": "a", "text": "Albania", "cssPath": "body > ul > li > a"})
    choice = L.choose(checked(L.candidates(desc), {"text": (500, 425), "position": (500, 425), "path": (1, 0)}))
    assert choice.primary.how == "path"


def test_the_inputs_of_a_repeatable_set_are_told_apart_by_their_duplication_id():
    desc = L.to_desc({"tag": "input", "name": "insuredAge", "placeholder": "Age", "dataIds": {"data-cmp-duplication-input-id": "t2"}})
    cands = L.candidates(desc)
    assert cands[0].value == 'input[name="insuredAge"][data-cmp-duplication-input-id="t2"]'
    choice = L.choose(checked(cands, {"attribute": (1, 0)}))
    assert choice.primary.value == cands[0].value and choice.to_json()["index"] == 0
