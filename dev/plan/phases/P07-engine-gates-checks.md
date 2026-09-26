# P07: Engine II: gates, waits, popups, side effects, backup locators, checks, widgets

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P07: Engine II: gates, waits, popups, side effects, backup locators, checks, widgets`

The rest of the new keywords and safety rules.

## Read first (only these)
- dev/plan/CONTRACT.md
- dev/claude/CONTEXT_workbook_builder_engineering.md section 2 (remaining bullets)
- AGENTS.md section 3 rows for clicks, page ready, outcome, selectors

## You own
- `engine/actions.py (new handlers)`
- `engine/session.py`
- `engine/outcome.py`
- `src/regrunner/selectors/*`

## Build
- `ASSERT_PAGE` with workbook fingerprints (URL part AND landmark): **always a hard stop**, even with Ignore_not_existing_object; reports which part failed; later steps not run.
- `WAIT_UNTIL` (shows / gone / text is), `DISMISS_IF_SHOWN` (always logged appeared / did not), extra check kinds, `PICK_DATE`, `CHOOSE_SUGGESTION`.
- Side-effect steps: PROD always blocks them; build-mode replays ask first (reuse `engine/ask.py`); full runs unchanged.
- Backup locators: on a primary miss the step still FAILS; probe backups and put "backup found N matches + screenshot + proposed locator" in detail/diagnosis. Never heal silently.

## Done when
- Mock-site tests per behaviour; `test_outcome.py`, `test_page_ready.py`, `test_click_and_load.py`, `test_selectors.py`, `test_keys_events_config.py` pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
