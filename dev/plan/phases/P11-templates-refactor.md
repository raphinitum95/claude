# P11: Templates, copy/paste, duplicate, rename, computed values, file watch

**Model:** Sonnet · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P11: Templates, copy/paste, duplicate, rename, computed values, file watch`

The productivity features around editing.

## Read first (only these)
- dev/designs/CONTEXT_workbook_builder_design.md Q15–17, Q23, Q26, Q29, Q30, Q37
- dev/designs/workbook-builder-canvas/dialogs.py (template, duplicate, file changed, history)

## You own
- `src/regrunner/workbook/templates.py`
- `workbook/refactor.py`
- `workbook/formula.py (new functions)`
- `web/static/js/views/build/dialogs*.js`

## Build
- Shared template library file next to the workbooks; insert = copy with a variable-mapping dialog (exact, close match, create column).
- Copy/paste and duplicate at step, block, test, workbook level; "What changes?" panel; workbook-wide find and replace with a preview of every hit.
- Value builder writing real Excel formulas (`TODAY`, `NOW`, `TEXT`, `RANDBETWEEN`... added to `formula.py`).
- External change → reload or per-step merge; Excel lock → "close it in Excel", save waits.

## Done when
- `test_formula.py` + new tests pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
