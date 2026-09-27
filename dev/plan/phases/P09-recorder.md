# P09: Build session II: recorder, check/save this, typed → variable

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P09: Build session II: recorder, check/save this, typed → variable`

Recording and the "Check this" flow.

## Read first (only these)
- dev/designs/CONTEXT_workbook_builder_design.md Q6–9, Q34, Q41, Q51, Q53
- dev/designs/workbook-builder-canvas/record.py

## You own
- `src/regrunner/build/recorder.py`
- `build/overlay.js`
- `web/static/js/views/build/record*.js`

## Build
- Record toggle: actions become steps at the cursor; no fixed waits; switch window/frame/back added automatically; widget patterns collapse (date picker, autocomplete).
- Typed text → variable prompt (name from label, value into active Params row, reuse matching variable); password fields → secret.
- Check this / Save this from the live element with every check kind, prefilled from the page; recorder proposes a page fingerprint when the URL changes.

## Done when
- Mock-site browser tests for each recorder behaviour.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
- 2026-09-27 · `build/recorder.py` + overlay (Rec/Check/Save/Wait pill, trusted-only recording, page-side locator counts, cards, prompts) + session wiring; mock pages `build_record*.html`; `tests/test_build_recording.py` (13 browser tests) green · next: fast tests, `/record|check|save|prompt` routes, Build tab `record.js`, docs
- 2026-09-27 · fast tests (`test_build_recorder.py`), routes (`web/record_api.py`: record/check/save/prompt), Build tab `views/build/record.js` + `test_web_build_record.py`, CONTRACT.md 3 + events.py + AGENTS.md · next: PR into qa-regression
