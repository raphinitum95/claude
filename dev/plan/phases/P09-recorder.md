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
