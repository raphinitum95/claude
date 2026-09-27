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
- 2026-09-27 · Done: shared template library (`workbook/templates.py`, `templates.xlsx`: save a row range as a template, `match_variables`
  exact/close/no-match, `insert_template_ops` - unmapped tokens become `{?TOKEN}` per CONTRACT 1.2); duplicate/find-replace/merge
  (`workbook/refactor.py`: `find_replace_preview`, `duplicate_candidates` for the "What changes?" panel, `merge_ops` for a per-step pick
  against `diff("disk")` - none of this needed a new op kind, everything resolves to the existing `insert_step`/`add_variable`/`set_cell`/
  `update_step`); two new routes modules (`web/templates_api.py`, `web/refactor_api.py`, both sharing `build_api.py`'s `BuildStore` via a
  one-line change to `create_app`'s capture of `register_build_routes`'s return value); two new formula functions (`CHOOSE`, `TEXTJOIN`)
  for the value builder; Build tab UI (`dialogs.js`: templates library/save/insert-with-mapping, duplicate "what changes?", find & replace,
  value builder, a real per-step merge added to the existing file-changed dialog; small, named touches to `actions.js`/`editor.js`/
  `workbook.js`/`icons.js`/`state.js` to wire buttons and a copy/paste clipboard - copy/paste itself needed no Python, a `Step`'s fields
  already match `insert_step`'s). Not built: deleting a template (`WorkbookEditor` has no way to remove a sheet - a real P01 gap, documented
  as `unsupported` 400 rather than faked) and copy/paste of a whole test or workbook-level "computed value" cross-checking beyond what the
  value builder's own preview shows. Tests: `test_formula.py` (+2), `test_templates.py`, `test_refactor.py`, `test_templates_api.py`,
  `test_refactor_api.py` (all fast/no-browser), `test_web_build_p11.py` (browser: save-as-template + insert with mapping, duplicate, find &
  replace, value builder, merge-from-disk). `pytest -m "not browser"` 552 passed (was 531 before this phase); `builder.py` untouched.
