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
- 2026-09-27 · Review: the branch had forked before P10 merged, so qa-regression (P10's API/XML building) was merged into it, resolving
  conflicts in `AGENTS.md` and `CONTRACT.md` (P10's API editor section plus P11's templates/duplicate/find-replace/merge sections, in that
  order; test counts refreshed to the real post-merge numbers: 584 passed / 915 collected). Found and fixed a real bug in `merge_ops`: it
  copied the disk version's *displayed* name (`step["name"] or step["autoName"]`) straight into every merged step's `update_step.set.name`,
  and `update_step` treats any non-empty `name` it receives as a manual rename (turns `nameAuto` off) - so picking "theirs" on a step whose
  name was still auto-generated silently pinned that generated text as a literal name from then on, even when naming had nothing to do with
  what was merged. Fix: `_summary()` (`builder.py`) now also reports `nameAuto`; `merge_ops` sends `name: ""` (which `update_step` reads as
  "keep auto-naming") when the disk version's name was still auto, and the literal name otherwise. `builder.py` is therefore touched by this
  phase after all, by one field on one function. New test: `test_merge_ops_restores_auto_naming_instead_of_pinning_the_generated_name`.
  Everything else in the diff matched CONTRACT.md and AGENTS.md's hard rules (Python 3.9-safe, no secrets touched, no OS-level input, tests
  named as sentences). Merged into qa-regression.
