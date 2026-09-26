# P01: Excel writer + round-trip fidelity

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P01: Excel writer + round-trip fidelity`

Nothing writes workbook sheets today except `engine/order.py` `save_chains`. Build the writer everything else stands on.

## Read first (only these)
- dev/claude/CONTEXT_workbook_builder_engineering.md section 1 "Workbook writing"
- src/regrunner/workbook/sheet.py, model.py (how sheets are read)
- src/regrunner/engine/order.py `save_chains` (the one existing writer)

## You own
- `src/regrunner/workbook/writer.py (new)`
- `src/regrunner/workbook/sheet.py (write side only)`
- `tests/test_workbook_roundtrip.py (new)`

## Build
- Load → save → diff every cell, formula, style, data validation, merged cell, hidden sheet and column width against the original. Use **copies** of the real workbooks in `workbooks/` as read-only fixtures (skip when missing, marker `realworkbook`), plus synthetic ones from `tests/workbook_factory.py`.
- Decide what openpyxl loses (cached formula values, images, comments...). Keep formulas intact; if Excel users would see stale values, write the cached values back or document the gap in the PR.
- API: open a workbook for editing, change cells/rows (insert, delete, move), add a column after the existing ones, add/read hidden `_rr_*` sheets, save to a new path, save with a timestamped backup (`backups/<name>.<yyyy-mm-dd_hhmm>.xlsx`), autosave a draft next to it.
- Detect external changes (mtime + hash) and Excel's lock file `~$name.xlsx`; saving while locked returns a clear "close it in Excel" error.
- Legacy rows the builder does not create (GO_TO_ROW, formula blnExecute, SNAGIT_SCREENSHOT...) must survive byte-for-byte.

## Done when
- Round-trip test passes on all real workbooks present and on synthetic ones (only intended differences).
- `test_model.py`, `test_real_workbook.py`, `test_run_order.py` still pass.
- Never write to files in `workbooks/`: work on copies in a temp dir.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
2026-09-26 · writer.py + test_workbook_roundtrip.py done (41 tests: 4 real workbooks + synthetic), AGENTS.md updated · next: PR into qa-regression
