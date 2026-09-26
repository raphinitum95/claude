# P03: Engine I: shared variables, IF, loops, CALL_TEST, environments, secrets

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P03: Engine I: shared variables, IF, loops, CALL_TEST, environments, secrets`

Make the new flow keywords run, exactly as the builder writes them.

## Read first (only these)
- dev/plan/CONTRACT.md sections 1 and 4
- dev/claude/CONTEXT_workbook_builder_engineering.md section 2 (first five bullets)
- dev/claude/AGENTS.md section 3 rows for keywords, test loop, order, config

## You own
- `src/regrunner/engine/actions.py (new handlers only)`
- `engine/test_runner.py`
- `engine/order.py, engine/schedule.py`
- `workbook/model.py`
- `config.py`
- `preflight.py`

## Build
- Workbook-wide variable pool across tests in a run; order by Needs/Provides (extend `order.py` chains).
- Implement `SET_VARIABLE`, `JSON_READ` (response checks), `IF/ELSE/END_IF` on variables only, `ITERATION_START/END` per data row, `CALL_TEST` (run the other test to completion, own context or none for API, then resume).
- Environment-variables table (`_rr_environments`): filled from the chosen environment; a missing **required** value blocks the run with a clear error (preflight **and** server side).
- Secrets `{SECRET:NAME}` from `secrets.env` per environment, masked everywhere (events, logs, results, reports). Audit every place a step value is echoed.

## Done when
- New mock-site tests for each keyword, named as sentences.
- `test_keys_events_config.py`, `test_run_order.py`, `test_variables_set.py`, `test_model.py`, `test_py39_compat.py` pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
