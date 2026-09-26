# P04: Build tab UI (no live browser yet)

**Model:** Sonnet · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P04: Build tab UI (no live browser yet)`

The Build tab screens against the P02 API: everything except recording and API/XML building.

## Read first (only these)
- dev/plan/CONTRACT.md sections 2 and 3
- dev/designs/workbook-builder-canvas/README.md, then editor.py, workbook.py, dialogs.py (copy their markup)
- src/regrunner/web/static/js/views/shell.js, main.js, state.js, morph.js (how screens are built)
- dev/claude/AGENTS.md section 9 gotchas (data-key, morph.js, CSP)

## You own
- `web/static/js/views/build/*.js (new)`
- `web/static/js/views/shell.js (the Run · Build · Results tabs)`
- `web/static/app.css (a "Build" section at the end)`
- `tests/test_web_build.py (new)`

## Build
- Tabs Run · Build · Results in the header (Results can link to today's results screen until P06).
- Workbook map (tests as cards, calls/needs lines, run order, DataSheets settings) and variable map (set by / used by, jump to step).
- Test editor: block map, cards, inspector (web, check, call, legacy, wait), Excel grid toggle, multi-select + bulk edit, keyboard shortcuts (⌘ on Mac, Ctrl on Windows), data drawer with "Building with" row, problems panel, gate chips, add-step menu (recording items disabled until P08).
- Dialogs: new workbook, environments table, page fingerprint (editing only), file changed, history. Save to Excel + draft state in the header. Dark and light themes.

## Done when
- Opening a real-shaped synthetic workbook shows the map, editor and grid; an edit autosaves a draft; Save to Excel writes it.
- `test_web_build.py` (new) and `test_web_ui.py -k theme` pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
