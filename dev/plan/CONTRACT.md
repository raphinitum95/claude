# Contract between the pieces (owned by P02)

Waves 3+ build against this file. **Do not change it silently**: a needed change goes in your PR description, and the review session updates
this file. Code that implements it: `workbook/builder.py` (model, ops, file-format constants), `lint.py` (`builder_problems`), `web/build_api.py`
(routes). Paths are under `src/regrunner/` unless they start with `dev/` or `tests/`.

Rules that hold everywhere: existing workbooks load and run unchanged; everything that writes a workbook goes through `workbook/writer.py`
(`WorkbookEditor`, never openpyxl `save`); only the new runner has to understand the additions (the legacy Windows runner does not).

---

## 1. Workbook file format additions

### 1.1 New step columns (test sheets)

Added **on first use** after the last header (`WorkbookEditor.add_column`), never pre-created. Headers are matched case-insensitively like
every other column. Readers that do not know them ignore them.

| Column | Values | Meaning | Written by | Read by |
|---|---|---|---|---|
| `BLOCK` | text | Block (map node) title of the step. Blank = same block as the step above. Once any step of a sheet has a value, blocks come from this column only (see 1.5) | P02 ops, P04 | P02 model, P06 (where a test stopped) |
| `SIDE_EFFECTS` | `Y` / blank | The step has real consequences (Purchase, Pay, Submit order). Build-mode replays pause before it; any environment marked production **blocks** it; normal runs are unchanged | P02 ops, P09 (suggests) | P03/P07 engine, P05 plan |
| `BACKUP_LOCATORS` | JSON list of strings, e.g. `["css=#pay", "text=Pay now"]` | Other ways to find the element. On a primary miss the step **still fails**; the engine probes the backups and reports what they found | P08/P09 | P07 engine, P06 card |
| `STEP_NAME_AUTO` | `Y` / blank | `Y`: `Step_Name` is generated (Q38) and is rewritten whenever the step changes. Blank: the name was typed by a person and is kept | P02 ops | P02 model |

Existing columns keep their legacy meaning. How the builder maps them is in 2.3 (`Step` fields).

### 1.2 Variables inside cells

| Form | Where | Meaning |
|---|---|---|
| `TOKEN` (the whole cell equals a `Params` header, any case) | any column except the result columns | **Legacy, unchanged**: replaced by the test's Params value (`workbook/model.py`) |
| `{TOKEN}` inside text | `Value`, `FindBy_Value`, `Expected_Value`, `Locator`, `Page`, `BACKUP_LOCATORS`, IF conditions | **New (P03)**: replaced inline. Lookup order: the test's Params row → the run's shared variable pool (values other tests set, Q21) → the environment table for the run's environment (1.4). Unknown = the step fails with "variable X has no value" (never types the token) |
| `{SECRET:NAME}` | same | **New (P03)**: value from `secrets.env` key `RR_SECRET_<ENV>_<NAME>`, falling back to `RR_SECRET_<NAME>`. Never written to the workbook, events, logs, results or reports (masked `••••••`) |
| `{?NAME}` | anywhere | A template placeholder that was not mapped when the template was inserted (P11). Always a problem (`unmapped_template_variable`); the engine fails the step |

Token names: `[A-Za-z_][A-Za-z0-9_]*`, compared case-insensitively. New variables the builder creates are UPPER_SNAKE (`FIRST_NAME`).
`builder.TOKEN_RE`, `INLINE_RE`, `SECRET_RE`, `UNMAPPED_RE` are the regexes.

A step **sets** a variable when its `Output_Value` cell names it (whole-cell token or `{TOKEN}`). That is how `OUTPUT` saves today and how
`SET_VARIABLE` works (below). The value goes into the test's Params row when the column exists (legacy) **and** into the run's shared pool (P03).

### 1.3 New keywords (`Method` column)

`builder.NEW_KEYWORDS` lists them. P03 implements the first group, P07 the second. Until a keyword is implemented the engine keeps treating it
as unknown (lint says so); the builder can already create it.

| Keyword | Columns used | Semantics | Phase |
|---|---|---|---|
| `SET_VARIABLE` | `Output_Value` = variable, `Value` = text / `{TOKEN}`s / formula | Put a value in the shared pool (and the Params cell when it exists) | P03 |
| `IF` | `Value` = condition (grammar below) | Steps until the matching `ELSE`/`END_IF` run only when true. **Variables only**, never step results | P03 |
| `ELSE`, `END_IF` | none | Close the branch / the IF. Nesting allowed | P03 |
| `ITERATION_START` | `Value` = Params sheet name (blank = the test's own) | Repeat the steps up to `ITERATION_END` once per enabled row of that sheet; inside, `{TOKEN}` reads that row | P03 |
| `ITERATION_END` | none | End of the loop | P03 |
| `CALL_TEST` | `Value` = test id (`Sheet` or `Sheet#n`) | Run that test to completion (own browser context; none for API), then continue. Its variables land in the shared pool. A failed called test fails this step | P03 |
| `ASSERT_PAGE` | `Value` = fingerprint name (1.4) | Page-arrival gate: URL part AND landmark must hold within the step timeout. **Failure is always a hard stop**, whatever `Ignore_not_existing_object` says | P07 |
| `WAIT_UNTIL` | element; `Output_Property` = `SHOWN` / `GONE` / `TEXT`; `Expected_Value` for `TEXT` (Exact_Match/Contains as usual); `Timeout` = limit | Wait on evidence, never a fixed time | P07 |
| `DISMISS_IF_SHOWN` | element = the close button | Click it if it shows within the timeout; **always logged** "appeared" / "did not appear"; never fails because it did not appear | P07 |
| `PICK_DATE` | element = the date field, `Value` = date | Smart date-picker step (Q51) | P07 |
| `CHOOSE_SUGGESTION` | element = the input, `Value` = text to type, `Expected_Value` = suggestion to choose (blank = `Value`) | Autocomplete step (Q51) | P07 |
| `CHECK_VALUE` | element, `Expected_Value`, Exact_Match/Contains | Field's current value | P07 |
| `CHECK_REGEX` | element, `Expected_Value` = pattern | Text matches the pattern (Python `re`, search) | P07 |
| `CHECK_COMPARE` | element, `Output_Property` = `GT`/`GE`/`LT`/`LE`/`EQ`/`NE`/`BETWEEN`, `Expected_Value` = number (`a;b` for BETWEEN) | Number read from the element's text | P07 |
| `CHECK_COUNT` | element, `Output_Property` operator as above (blank = `EQ`), `Expected_Value` = count | How many elements match | P07 |
| `CHECK_ENABLED` | element, `Expected_Value` = `Y`/`N` | Enabled state (aria-disabled counts) | P07 |
| `CHECK_CHECKED` | element, `Expected_Value` = `Y`/`N` | Ticked state | P07 |
| `CHECK_SELECTED` | element, `Expected_Value` = option text | Selected option of a `<select>` | P07 |
| `CHECK_DATE_FORMAT` | element, `Expected_Value` = format such as `dd/mm/yyyy` | Text is a date in that format | P07 |

**IF condition grammar** (`builder.parse_condition(text) -> Condition`, shared by the engine, lint and the UI):
`{A} is filled` · `{A} is empty` · `{A} = x` · `{A} != x` · `{A} contains x` · `{A} > n` · `{A} >= n` · `{A} < n` · `{A} <= n`.
The right side may itself be `{B}`. Comparison is text, case-insensitive; `> >= < <=` compare numbers. Anything else is a parse error (a problem).

**Legacy rows** (Q28), `builder.legacy_reason(...)`: a formula in `blnExecute`, or a method in `builder.LEGACY_METHODS`
(`GO_TO_ROW`, `SNAGIT_SCREENSHOT`, `DB_*`, `SEND_EMAIL`, `FILE_COMPARE`, `RUN_SCRIPT`, ...). The builder shows them as locked cards with a
plain-language reason; ops can move, delete, disable-by-grid (`set_cell`) and re-block them, `update_step` refuses them. Their cells are kept
byte-for-byte (the writer never re-renders an untouched cell).

### 1.4 Hidden runner sheets (`_rr_` prefix, created on first write, `state="hidden"`)

Each is a plain table: row 1 = headers (exactly these, case-insensitive on read), one row per item. Written with `WorkbookEditor.write_table`.

**`_rr_variables`**: `Token | Label | Secret | EnvSpecific | Notes`
- `Label`: the friendly name shown everywhere (Q37). Blank = generated from the token (`DT_FirstName_IN` → "First name").
- `Secret`: `Y` = value is secret (Q42): shown as `••••` in the UI, lives in `secrets.env`.
- `EnvSpecific`: `Y` = the value comes from the environment table (1.4) rather than Params.

**`_rr_environments`**: `Variable | Required | Secret | <env 1> | <env 2> | ...` (default envs `QA | UAT | PROD`).
- One special row whose `Variable` is `#PRODUCTION`: `Y` under each environment that is production (typed PROD confirmation, side-effect steps
  blocked). Without the row, an environment named `PROD` or `PRODUCTION` is production.
- `Required = Y` (always for `DOMAIN`): a run in an environment where the cell is empty **refuses to start** (P03 preflight + server, P05 UI).
- `Secret = Y`: the cell holds `{SECRET:NAME}`, never a value.
- Workbooks without this sheet: the builder shows the legacy `Environments` sheet (`Environment | Parameter | Value`) read-only as the table
  (`environments.source = "legacy"`), with no required rows. The engine keeps reading the legacy sheet for API tests as today.

**`_rr_fingerprints`** (Q53): `Name | UrlContains | Landmark | LandmarkText | Notes`
- `Name`: what `ASSERT_PAGE` names ("Payment page"). Unique, case-insensitive.
- `UrlContains`: text the URL must contain (may use `{DOMAIN}` etc.). `Landmark`: a locator (same syntax as `FindBy_Value`, `css=`/`xpath=`/
  `text=` prefixes allowed) that must be visible. `LandmarkText`: optional text the landmark must contain. Both URL and landmark must hold.

**`_rr_scenarios`** (reserved for P12): P12 defines the columns and writes them here before building on them.

Sheet names starting `_rr_` are never tests, Params or anything the legacy runner reads.

### 1.5 Blocks (Q14)

`builder.derive_blocks` decides the blocks of a test; the model always has them, stored or not.
- **Stored** (any step has a `BLOCK` value): consecutive steps with the same title form a block; a blank `BLOCK` continues the block above.
- **Derived** (old sheets): a *section row* starts a block titled with its text. A section row = no `Method`, a non-flag text in column A, nothing
  else (the real workbooks use these: "Open Site", "Trip Details"). A change of a real page name in `Page` also starts one (browser names such as
  `chrome`, `Application`, and Params tokens are not page names). Before any of those the title is "Start".
- In both modes: a `CALL_TEST` step is its own block (`kind: call`); `SWITCHTOWINDOW` starts a `window` block that ends at
  `SWITCHTOMAINWINDOW`/`CLOSE` (the block after it has `returnsTo`); `ITERATION_START` starts a `loop` block that ends at `ITERATION_END`.
- The first block op on a test (rename, split, merge, move to block) **materialises** blocks: the `BLOCK` column is written for every step, so
  from then on the column is the truth. Section rows stay where they are.

---

## 2. Builder model (JSON the server sends the Build UI)

All keys camelCase. `row` = 1-based sheet row (changes when rows are inserted/deleted: re-read the model after every edit). `n` = 1-based step
number within the test (section rows and empty rows are not steps). Rows are the only identity ops use.

### 2.1 `Workbook`
```
{ name: "qantas.xlsx", version: 7, environment: "UAT",          // environment the problems were computed for (?env= or Global!Environment)
  globals: { Environment: "UAT", ... },                           // Global sheet as written (formulas as "=...")
  sheets: [ { name, hidden, role } ],                             // role: test | params | datasheets | global | environments | inputoutput | runner | other
  tests: [Test], variables: [Variable], environments: Environments, fingerprints: [Fingerprint],
  scenarios: [],                                                  // P12
  problems: [Problem], problemCounts: { error, warning, info },
  status: Status }
```

### 2.2 `Test`
```
{ id: "Purchase", sheet: "Purchase", kind: "web" | "api" | "xml" | "other",
  listed: true,                  // has a DataSheets row (false: a keyword sheet nobody runs)
  dataSheetsRow: 3 | null, enabled: true, paramSheet: "AgentPortal_Params" | null, tags: ["smoke"], comment: "",
  dataRows: [ { row: 2, enabled: true, label: "NE · Basic" } ],   // Params rows (web) or data rows (api); label from Notes/Scenario/TC_Name
  buildingWith: 2 | null,        // first enabled data row: the default for "Building with" (Q24)
  blocks: [Block], steps: [Step],
  needs: ["POLICY_NO"], provides: ["QUOTE_ID"],                  // UPPER tokens (Q21), see 2.5
  calls: ["policySearch"],                                        // tests it CALL_TESTs
  columns: ["blnExecute", ...],                                   // row-1 headers as written, for the grid view
  lastRun: { runId, status, when } | null }
```
API/XML tests have `steps: []` and `blocks: []` in P02 (their editor is P10); `dataRows` lists their data rows.

### 2.3 `Step`
```
{ row: 14, n: 12, method: "SET",           // UPPER, stripped
  kind: "nav" | "act" | "input" | "check" | "save" | "wait" | "call" | "flow" | "legacy" | "other" | "empty",
  name: "Enter last name", nameAuto: false, autoName: "Type {DT_LastName_IN} into last name",
  block: "Trip Details", page: "",
  locator: { findBy: "xpath", value: "//input[@name='lastName']", index: 0, name: "", // name = Locator column (selectors.yaml key)
             backups: [], plainWords: [] },                        // plainWords: P08 fills ([{text, role, variable}])
  target: "last name field",                                       // plain-words target used in names
  value: "DT_LastName_IN", expected: "", match: "exact" | "contains" | "",
  saveAs: "" ,                                                     // variable Output_Value names ("" when Output_Value is not a variable)
  output: "",                                                      // Output_Value as written
  outputProperty: "", onFail: "stop" | "continue",                 // continue = Ignore_not_existing_object Y
  timeout: 5 | null, enabled: true | false | null,                 // flag condition: the flag's value in the buildingWith row;
                                                                   // null = a formula decides at run time (see condition)
  condition: null | { kind: "formula" | "flag", text: "=IF(...)" | "bln687809" },
  sideEffects: false, context: "" | "frame: card" | "window 2",
  flow: [ { kind: "if" | "else" | "loop", row: 40 } ],             // enclosing IF/ELSE/loop, outermost first
  call: "" ,                                                       // CALL_TEST target
  legacy: "" | "why it is locked",
  uses: [ { token: "DT_LASTNAME_IN", column: "VALUE", form: "cell" | "inline" | "secret" | "flag" } ],
  sets: ["DT_POLICYNUMBER"], notes: "",
  lastResult: null | { status: "PASSED" | "FAILED", error: "", runId, when, locatorMiss: false },
  problems: ["error" | "warning" | "info", ...] }                  // severities of the problems on this step (dots)
```
Field → column mapping for writes (`builder.FIELD_COLUMNS`): `name`→`Step_Name`, `method`→`Method`, `page`→`Page`, `findBy`→`FindBy`,
`locator`→`FindBy_Value`, `index`→`Index`, `locatorName`→`Locator`, `value`→`Value`, `expected`→`Expected_Value`,
`match`→`Exact_Match`/`Contains`, `saveAs`/`output`→`Output_Value`, `outputProperty`→`Output_Property`, `onFail`→`Ignore_not_existing_object`,
`timeout`→`Timeout`, `enabled`→`blnExecute` (`Y`/`N`), `sideEffects`→`SIDE_EFFECTS`, `backups`→`BACKUP_LOCATORS`, `block`→`BLOCK`,
`notes`→`Notes`, `nameAuto`→`STEP_NAME_AUTO`. A missing column is added on first write.

### 2.4 `Block`
```
{ id: "b3", title: "Payment", kind: "page" | "window" | "call" | "loop",
  firstRow, lastRow, start: 40, end: 57,          // step numbers n (inclusive)
  count: 18, stored: true,                        // stored = from the BLOCK column
  headerRow: 39 | null, page: "", gate: "Payment page" | "",   // gate = fingerprint of a leading ASSERT_PAGE
  returnsTo: "" , call: "", dot: "" | "error" | "warning" | "info" }
```

### 2.5 `Variable`
```
{ token: "DT_FirstName_IN", key: "DT_FIRSTNAME_IN", label: "First name", labelSet: false,
  kind: "data" | "flag" | "env" | "set",         // flag = used as blnExecute; env = environment table; set = only ever set by steps
  secret: false, envSpecific: false,
  sources: [ { sheet: "USClaimsParams", column: "DT_FirstName_IN" } ],
  setBy:  [ { test, row, n } ], usedBy: [ { test, row, n, column } ],
  neededBy: ["ViewPolicy"], providedBy: ["Purchase"] }
```
`needs` of a test: a token its steps use before any of its own steps sets it, that is not an environment variable or a secret, and whose
Params cell is empty in some enabled data row (or that has no Params column at all). `provides`: tokens its steps set. P03 orders tests so that
providers run before the tests that need them; the builder warns when a need has no provider (`unset_variable`).

### 2.6 `Environments`, `Fingerprint`
```
Environments { source: "rr" | "legacy" | "none", names: ["QA","UAT","PROD"], production: ["PROD"],
               rows: [ { variable: "DOMAIN", required: true, secret: false, values: { QA: "...", UAT: "...", PROD: "" } } ] }
Fingerprint  { name: "Payment page", urlContains: "/purchase/payment", landmark: "css=h1", landmarkText: "Payment details", notes: "",
               usedBy: [ { test, row, n } ] }
```

### 2.7 `Problem` (Q31; never blocks saving)
```
{ id: "unset_variable:Purchase:14:POLICY_NO", severity: "error" | "warning" | "info", kind, message, test: "Purchase" | "", row: 14 | null,
  n: 12 | null, variable: "" }
```
`kind` is one of: `unset_variable`, `missing_expected`, `last_run_locator_miss`, `unmapped_template_variable`, `side_effect_on_prod`,
`side_effect_suggested`, `missing_environment_value`, `unknown_method`, `missing_locator`, `unknown_test`, `unknown_fingerprint`,
`bad_condition`, `unbalanced_flow`. Legacy rows are not problems (their card says why they are locked). New kinds may be added (the UI shows unknown kinds by severity and message).

### 2.8 `Status`
```
{ version: 7, modified: true, hasDraft: true, draftSaved: "2026-09-26T14:03:00", externalChange: false, locked: false,
  canUndo: true, canRedo: false, file: "qantas.xlsx" }
```
`externalChange`: the file on disk changed since the builder opened it (Q29): offer reload (drops the draft) or save anyway (`force`).
`locked`: Excel has it open (`~$name.xlsx`): saving answers 423 "Close it in Excel to save".

---

## 3. Server endpoints (`web/build_api.py`, all under `/api/build/`)

Same security as every route: localhost Host; POST/PUT/DELETE need header `X-Requested-With: regrunner` and a local Origin. Errors are
`{error, kind, ...}` with an HTTP status. `{name}` is the workbook file name in `workbooks/`. `?env=` picks the environment for problems.

| Method + path | Body | Answer |
|---|---|---|
| `GET /api/build/keywords` | | `{groups: [{group: "Do", methods: [{method, label, element, kind}]}], newKeywords: [...], legacy: [...]}` |
| `POST /api/build/workbooks` | `{name, environments: [{name, domain, production}], from?: "other.xlsx"}` | `{name, model}` (201). New workbook (Q45) or copy of `from` |
| `GET /api/build/workbooks/{name}` | | `Workbook` (opens the draft if there is one) |
| `GET /api/build/workbooks/{name}/status` | | `Status` |
| `POST /api/build/workbooks/{name}/edit` | `{version, ops: [Op]}` | `{model, applied}`. One call = one undo step; autosaves the draft. 409 `stale` when `version` is not the current one; 422 `op` (nothing applied) when an op is invalid, with `index` of the failing op |
| `POST /api/build/workbooks/{name}/undo` · `/redo` | | `{model}` |
| `POST /api/build/workbooks/{name}/save` | `{force?: false}` | `{status, backup}`. 409 `changed_outside` unless `force`; 423 `locked` |
| `POST /api/build/workbooks/{name}/reload` | | `{model}`: drop the draft and the undo history, take the file on disk |
| `GET /api/build/workbooks/{name}/history` | | `[{id, when, size}]` saved backups, newest first (`id` is the backup file name) |
| `GET /api/build/workbooks/{name}/diff?against=<id>\|disk` | | `{changes: [{test, kind: added\|removed\|changed\|test_added\|test_removed, row, n, before, after}]}` current model vs a backup / the file on disk |
| `POST /api/build/workbooks/{name}/restore` | `{id}` | `{model}`: the backup becomes the current (unsaved, undoable) content |
| `GET /api/build/workbooks/{name}/variables` | | `[Variable]` |
| `GET /api/build/workbooks/{name}/problems` | | `{problems, problemCounts}` |
| `GET /api/build/workbooks/{name}/environments` | | `Environments` |
| `GET /api/build/workbooks/{name}/fingerprints` | | `[Fingerprint]` |
| `GET /api/build/workbooks/{name}/sheets/{sheet}` | | `{name, headers, rows}` raw cells as written (formulas `"=..."`) for the Excel-grid view |

Reserved for later phases (they add them in their own modules, same prefix): templates `/api/build/templates*` (P11); build session
`/api/build/session/{name}/start|record|pick|check|save|run-to-here|run-step|run-next|close` (P08/P09); API send `/api/build/api/send` (P10);
scenarios `/api/build/workbooks/{name}/scenarios*` (P12). Runs and batches stay under `/api/runs`, `/api/batches` (P05/P06).
One build document per workbook per server (`BuildStore`); a run of the same workbook uses its own copy of the file, so they coexist.

### 3.1 Ops (`builder.apply_ops`)

Each op is `{op: "...", ...}`; `test` is the sheet name; rows are current sheet rows (ops in one call see the rows as earlier ops left them).

| op | fields | effect |
|---|---|---|
| `insert_step` | `test, before?: row, after?: row, step: {Step fields}` | new row (neither = after the last step). Defaults: `enabled` Y, `nameAuto` true, `block` = the block it lands in. `Step_Number` formula copied from the row above |
| `update_step` | `test, row, set: {Step fields}` | refused on legacy rows. `name` sets `nameAuto` false; `nameAuto: true` regenerates the name |
| `delete_steps` | `test, rows: [..]` | |
| `move_steps` | `test, rows: [..], before?: row, block?: title` | keeps their order; no `before` = to the end; `block` re-blocks them |
| `bulk_edit` | `test, rows, set: {timeout, enabled, onFail, page, block, sideEffects}` | legacy rows take only `block` |
| `rename_block` | `test, row, title` | row = any step of the block |
| `split_block` | `test, row, title` | the block splits above `row`; `row..end` becomes `title` |
| `merge_blocks` | `test, row` | the block of `row` joins the block before it |
| `rename_variable` | `from, to` | every Params header, whole-cell token, `{TOKEN}`, `{SECRET:TOKEN}` (also inside formulas' text), `_rr_variables`, `_rr_environments` |
| `set_variable` | `token, label?, secret?, envSpecific?, notes?` | upsert in `_rr_variables` |
| `add_variable` | `token, label?, sheet: paramsSheet, value?` | new Params column (+ label); `value` goes in every data row |
| `set_cell` | `sheet, row, column: header \| number, value` | grid view and data drawer; `=` starts a formula |
| `set_environments` | `names, production, rows` (the `Environments` shape) | rewrites `_rr_environments` |
| `set_fingerprint` | `name, urlContains, landmark, landmarkText?, notes?, rename?: old name` | upsert |
| `delete_fingerprint` | `name` | |
| `set_test` | `test, enabled?, paramSheet?, tags?, comment?` | DataSheets row (added when the sheet is not listed) |
| `add_test` | `name, kind: "web", paramSheet?` | new keyword sheet with the 26 standard columns + DataSheets row (+ Params sheet with `blnExecute` and one `Y` row when named and missing) |

---

## 4. Events (new types go through `events.py`, `runstate.js`, `reporting/from_events.py`)

Names are fixed here; the owning phase fixes the fields and documents them in `events.py`'s docstring. Every event carries `test` and, when it is
about a step, `step` and `row` like `step_started`. Secrets never appear in any field.

| Event | Fields (minimum) | Emitted by |
|---|---|---|
| `variable_set` (exists) | `name, value (masked if secret), test, row` | P03 also for `SET_VARIABLE` / pool writes |
| `call_started` / `call_finished` | `test, step, row, called, status` | P03 `CALL_TEST` |
| `branch_taken` | `test, step, row, condition, result (true/false)` | P03 `IF` |
| `iteration_started` | `test, step, row, sheet, iteration, of` | P03 loops |
| `env_missing` | `environment, variables: [..]` | P03 preflight: the run refuses to start |
| `page_gate` | `test, step, row, fingerprint, passed, url, landmark_found` | P07 `ASSERT_PAGE` (failed = hard stop) |
| `popup_dismissed` | `test, step, row, appeared (bool)` | P07 `DISMISS_IF_SHOWN` |
| `side_effect_paused` / `side_effect_blocked` | `test, step, row, name, environment` | P07/P08 (paused in build replays, blocked on production) |
| `backup_locator_suggestion` | `test, step, row, locator, matches, screenshot` | P07 on a primary miss |
| `scenario_sync` | `scenario, lane, sync, reached, waiting` | P12 |
| `build_session_*` | `build_session_started`, `_step_recorded`, `_replay_progress`, `_closed` | P08/P09 (build-session stream, not a run) |
