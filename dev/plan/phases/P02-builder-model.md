# P02: Builder model, contract, problems engine, build API

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P02: Builder model, contract, problems engine, build API`

The in-memory model the Build UI edits, the JSON it sees, and the server routes. This phase **writes `dev/plan/CONTRACT.md` for real**; waves 3+ depend on it.

## Read first (only these)
- dev/plan/CONTRACT.md (outline to replace)
- dev/designs/CONTEXT_workbook_builder_design.md (skim Q1, Q3, Q14, Q21, Q26–31, Q37–39, Q42–44, Q53)
- dev/claude/CONTEXT_workbook_builder_engineering.md sections 1, 3 "Problems engine", 4
- src/regrunner/workbook/writer.py (from P01), model.py, lint.py, web/app.py `create_app` (only to add one line)
- dev/designs/workbook-builder-canvas/data.py (the example step shape)

## You own
- `src/regrunner/workbook/builder.py (new)`
- `src/regrunner/lint.py`
- `src/regrunner/web/build_api.py (new) + one line in web/app.py`
- `dev/plan/CONTRACT.md`
- `tests/test_builder_model.py, tests/test_build_api.py (new)`

## Build
- Model: workbook → tests → blocks → steps, variables (labels, secret flag, needs/provides, set-by/used-by index), environments table, fingerprints, legacy rows. Blocks auto-generated from PAGE for old sheets, stored in `BLOCK`.
- Automatic step names (Q38) from method + target + value, with override flag.
- Edits as small operations (insert/move/delete/update step, bulk edit, split/merge/rename block, rename variable everywhere) with undo; draft autosave; save to Excel via P01.
- Problems engine (live lint on the model): unset variable, missing expected value, last-run locator miss, unmapped template variable, side-effect step on PROD, missing environment value. Never blocks saving.
- Routes under `/api/build/` with the existing security checks. Write the final CONTRACT.md: file format additions, JSON shapes with field names, endpoints, event names.

## Done when
- CONTRACT.md is complete enough that P03, P04 and P05 can start without asking.
- Model loads every real workbook present and the synthetic ones; round trip through the model changes nothing.
- `test_builder_model.py`, `test_build_api.py`, `test_web_api.py` pass. **Restart UI** noted in PR.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
