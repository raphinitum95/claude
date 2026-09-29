# CONTEXT: recorder feedback tally (naming, dates, checks, selectors)

Hand-off brief for an agent that can see the user's local runs and recordings. Nothing below has been changed in code yet.
Read `AGENTS.md` first (rules, tests). This file only adds this piece of work.

## Why this exists
The previous session (cloud) audited the Build tab's Record feature from the code alone. The user's real recordings live on their
machine, and the cloud container does not have them. **Two of the previous session's claims were wrong because they were made
without looking at a recording** (items 2 and 4 in the table). Do not repeat that: open the recording first.

## Step 0 for you: get the evidence
The user's example is a workbook they call **"qantas widget"**. It is not in this repo (`workbooks/` only has `qantas-test 2.xlsx` and
`UAT DT_Qantas StandAlone_Staff Daily Regression_v1.1.xlsx`, neither with the recorded widget steps). Find it on the user's machine
(likely a Build-tab draft under `runs/.build/<stem>/` or a saved workbook) and read **steps 5, 6, 7** (the date picker steps) plus every
step whose `FindBy_Value` is a bare tag such as `input` or `div.item`.

## The tally (user's words in quotes)

| # | Item | Status | Where in code |
|---|---|---|---|
| 1 | Step names are too generic ("field", "link click"). They should always contain the input name and/or something descriptive. | Agreed. User: "not sure that solves all the issues but lets start there". Not started. | `workbook/builder.py:288` `auto_name` (falls back to "the element"); `build/locators.py:114` `element_name` (reads ariaLabel, label, text, value, placeholder, title, alt; never `name`/`id`); `build/recorder.py:102` `field_label` (does fall back to name/id, but only names the *variable*). Two naming rules exist; unify them: id/name, then label, then nearby heading, then position. |
| 2 | Calendar clicks ("click next", "14") should become one relative date ("5 days from today"). | User first reported it, then disputed the previous session's reading of the code (that the collapse to one PICK_DATE step happens but stores an absolute date, never an offset from today): "categorically not true", pointing at steps 5, 6, 7 of the Qantas widget workbook. Which part was wrong is not known (collapse itself, or the absolute date). Read those rows before changing anything. | `build/recorder.py:838` `_date_picked`, `:757` `_typed` (PICK_DATE), `engine/checks.py:187` (dates a PICK_DATE accepts), `engine/actions.py:1599-1720`. `TODAY()+N` formulas already work in the workbook (`workbook/formula.py`). Idea: compute picked date minus today at record time and offer `=TEXT(TODAY()+5,"dd/mm/yyyy")` in the data row. |
| 3 | A date typed straight into a date field should also record as a dynamic date, not the literal value. | Understood, not started. Same fix as item 2. | `build/recorder.py:761` (`is_date_field` and `looks_like_date` decide PICK_DATE). |
| 4 | "Can I check or pick while recording?" | **User says the existing Check/Pick does nothing while recording.** The docs say it should work (pill has Rec, Pick, Check, Save, Wait until; a check while recording is inserted after the recorder's cursor). Treat as a bug and reproduce. Suspect: the overlay only records in browse mode (`overlay.js:601`, `recording = st.rec && st.mode === 'browse'`), so choosing Check leaves recording; check `setMode` (`overlay.js:721`) and the server-side mode routing in `build/session.py` `_on_call`. | `build/overlay.js`, `build/recorder.py` (check/save/wait cards), `build/session.py`, `web/record_api.py`, `views/build/record.js`. |
| 5 | Checks are not dynamic. Example: type "alb" in a multi-select, a list shows "Albania"; the check "this item on the DOM says Albania" passes even when the list is not showing. | Agreed. User's simpler design: **"this locator and visible", then get item N**. Not started. Needs a new check keyword in the engine. | `build/recorder.py:154-260` `CHECK_KINDS`/`check_kinds`/`check_step` (every kind is anchored to the picked element's own locator, so text checks pass vacuously). New kind: list locator must be visible, then the Nth item's text is X (also worth: list contains X / has no X). Engine side: `engine/actions.py` + `engine/checks.py`, `workbook/builder.py` (`CHECK_KEYWORDS`, `auto_name`). |
| 6 | Selectors are far too generic: "should be specific to what I'm choosing", not something that "can belong to absolutely anything". | Reported by user with the same workbook. Cause **suspected, not confirmed** (see below). Not started. | `build/locators.py:200` `candidates`, `:283` `choose`. |

### Suspected cause of item 6
`candidates()` always ends with two positional fallbacks: `tag.stableclass` and bare `tag`, both flagged `index_needed` (matched as "the Nth
one on the page"). `choose()` prefers a unique candidate, then **any positional one**, and only then the element's own `cssPath`
(`primary = unique[0] if unique else positional[0] if positional else path[0]`). So an element with no stable id, name, aria-label or unique
text gets `input` #7 or `div.item` #3 instead of its specific path. Widget parts (calendar days, dropdown options) usually have no id or
label, so they are probably the worst hit. Likely fix: prefer a parent-anchored locator (nearest ancestor with a stable id/class, plus the
element's text or its position inside that parent) over a bare tag + index; keep bare tag + index only as a last resort and flag it in the UI.
Confirm against the recording which steps really got a bare tag.

### Other gaps the previous session noticed (not yet raised by the user)
- `CHOOSE_SUGGESTION` stores the literal text ("Albania"), not "the first suggestion", and is not linked to the typed "alb".
- Other recorded values that are really relative (a range end, "tomorrow") have the same problem as dates.
- Number checks (greater than, less than, between) are prefilled with the number on the page right now, a snapshot rather than an intent.
- Text checks copy whatever is on the page right now as the expected text.

## Constraints that apply (from AGENTS.md)
- Never run a real workbook against a real site. Verify on the local mock site (`tests/site/`, e.g. `widgets.html`, `build_record*.html`).
- Server-side changes (`recorder.py`, `session.py`, `record_api.py`) need the user to restart the UI; `overlay.js` is read at server start too. JS views only need a page reload.
- Tests to run: `test_build_recorder.py` (fast), `test_build_recording.py`, `test_web_build_record.py`, `test_build_locators.py` (fast), `test_checks.py` (fast), `test_engine_gates.py`, `test_outcome.py`; plus `test_keys_events_config.py` if a keyword or event is added. Update the task router in AGENTS.md if a module or test file is added.
- Keep replies to the user short (ADHD); list the files changed so they can copy them to the work computer.

## Suggested order
1. Get the recording and confirm items 2, 4 and 6 against it (do not trust the code reading above).
2. Item 1 (naming), agreed starting point.
3. Item 6 (selectors) and item 4 (Check/Pick while recording), the two the user calls broken.
4. Items 2-3 (relative dates), then item 5 (list check).
