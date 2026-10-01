# Brief: unique (generated) variables with numbered copies

Status: **built 2026-10-01** (branch `claude/unique-variables`, from `qa-regression`); see "As built" at the end. Design agreed with the user the same day. Read this whole file before starting; the decisions below were talked
through with the user one by one and are settled. The words used here (`#N`, "copy", "make unique") are working names, not law: pick
plain UI wording, but keep the behaviour.

## What the user wants (in their words, condensed)

Some variables must be different on every run so the site never sees the same data twice: `firstName = qafirst`, `lastName = qalast`.
With "make unique" ticked, a run uses `qafirst` + random characters (`qalastsofdij`). One variable can have several copies in one run
(traveller 1, 2, 3 all start with `qalast` but differ), and every copy must be usable later in the same run: type traveller 1's last name
into a policy lookup, check the travellers page shows the last traveller's name. Generic: names were only the example (emails, references...).

## Decisions

1. **"Make unique"** is a setting of a variable (Variables screen), next to its base value. With it: a format choice (letters only / letters
   and numbers / numbers only) and a length. **Letters only is the default for anything that looks like a name** (sites reject digits in
   name fields). Value = base value + random part.
2. **Copies are numbered: #1, #2, #3...** A step that types/sets the variable always names a number: `{lastName#4}`.
   - At run time, setting #4: if #4 already exists in this run, use that value; if not, generate it, store it, use it ("get or create").
   - The number is chosen **while building**, never at run time. The Set UI offers "the ones that exist" (every number the workbook already
     uses for that variable) or **"add a new one"** = the next free number. So the numbering is the same on every run.
   - Deleting the steps that used #3 leaves a gap (#2, #4). **Never renumber** (it would silently change what other steps point at).
3. **Checks/reads** pick **first / last / number N**. "Last" exists only for checks/reads, never for Set. "Last" = the highest number filled
   *in this run*. A check (or any read) of a copy that was never created in this run **fails** with a plain cause, e.g.
   "lastName #2 was never created in this run" (its own failure cause in the Results tab, not "expected '' but found ...").
4. **"Which one?" is asked only** when the variable has "make unique" AND the workbook uses more than one number. With only one, the step is
   still saved **pinned to #1** (so adding #2 later never changes it) and shows a warning like: "Only one lastName exists, so this uses #1.
   If more get added later, this check stays on #1."
5. **The person never types `{lastName#2}`**: a GUI choice (use first / use last / use #3 / add a new one). The `#` text is only what is
   written in the cell.
6. **Scope = one run = one workbook.** Values are shared by every test of that run (test 1 makes them, test 2 uses them); never across
   workbooks, not even in the same batch. **Same run = same values** (a whole-test re-run inside the run, `NOT_RUN` / WAF / crash re-runs,
   reuses them); **a new run = new values**.
7. **Two tests creating the same copy at the same time**: which one "wins" is the user's problem (they should order the tests). The runner
   only guarantees one value per copy: both tests get the same value, never two different ones.
8. Recorder: typing into a field while recording should offer the same Set choice (existing copy / add a new one) for a unique variable.
   The check card (Check / Save / Wait until) offers first / last / #N for its Expected value.

## Where it lands in the code (pointers, check before trusting)

- Names: `INLINE_RE`/`TOKEN_RE` in `workbook/variables.py` and `workbook/builder.py` (kept identical) do not allow `#` today; the formula
  token regex in `workbook/formula.py` (`_TOKEN_RE`) too. Suggested cell forms: `{lastName#2}`, `{lastName#first}`, `{lastName#last}`.
  Plain `{lastName}` must keep today's meaning for existing workbooks.
- Declaration: `_rr_variables` (`declared_variables`, `variables.py`; columns TOKEN / SECRET / ENVSPECIFIC). Add the unique settings there
  (e.g. UNIQUE, FORMAT, LENGTH); writes go through `workbook/writer.py` only. Contract shapes: `dev/plan/CONTRACT.md` (update it).
- Run-wide pool: `VariablePool` (`variables.py`), one per run (`RunCtx.pool`, `engine/runner.py`). Needs per-variable numbered copies, and
  get-or-create under a lock (asyncio: create the Lock inside a coroutine, Python 3.9 rule). Lookup: `TestRuntime.value_of` /
  `_substitute_inline` (`workbook/model.py`).
- Generation: use the system random source (not the workbook's seeded `rng` behind `RANDBETWEEN`). Mask nothing (not secrets), but record
  the generated values in events/results so the Results test page can show "lastName #1 = qalast...".
- Ordering: Needs/Provides (`engine/order.py`) should treat "sets lastName#N" / "reads lastName#N" like any other variable, so a reader
  waits for the test that creates it.
- Failure cause for a missing copy: `web/results_api.py` `cause_of` already has "a step read a variable nothing had set"; reuse or extend it.
- Builder: Variables screen (`web/variables_api.py`, `views/build/variables.js`, `builder.add_variable`); the inline-variable picker and
  inspector (`views/build/editor.js`); a builder problem for a read of a number no step sets (`lint.builder_problems`).
- Recorder: `build/recorder.py` (`variable_choices`, `check_step`, `token_for`), `views/build/record.js`.

## Tests to write

Fast: pool get-or-create, first/last/#N, gaps, missing-copy failure text, generation format/length, `{x#n}` parsing next to plain `{x}`.
Mock site: one workbook, two tests: test 1 sets #1 and #2, test 2 types #1 and checks #last; a second run gets different values; a
re-run inside the run keeps them. Builder: "add a new one" takes the next free number, deleting leaves a gap, the single-copy warning.

## As built (2026-10-01)

- Cells: `{NAME#2}`, `{NAME#first}`, `{NAME#last}` (case-insensitive). "Makes" = the Value column of a step that is not a check
  (`variables.makes_copies`); everything else reads. `_rr_variables` columns `Unique | UniqueBase | UniqueFormat | UniqueLength`
  (format `letters` / `mixed` / `digits`; blank = letters for a name-like token, else mixed; length 8). Base = UniqueBase, else the variable's
  own value for the test (Params row / pool / environment), else nothing.
- Engine: `VariablePool.copies` (one per run; tests share one event loop and nothing awaits between "exists?" and "make", so one value per
  copy without a lock). A made copy is a `variable_set` event / `sets` entry with cell `unique copy` and a step note. Needs/Provides:
  `NAME#N` for a number, `NAME#*` for first/last (waits for every test that makes a copy). API requests read copies, never make one.
- A step that could not run because of a variable (copy or plain `{NAME}`) now keeps that reason instead of "Comparison Failed"
  (`StepOut.not_run`), which also changes the message of an Output step whose Expected_Value used an unknown `{NAME}`.
- Builder: model `Variable.unique` / `copies` / `copiesMade`, uses form `copy`; problems `not_unique_variable` (error), `copy_never_made`
  (warning); rename carries `#N`. UI: Variables screen card "Make unique each run" + new kind "New each run"; "Use a variable" beside a
  step's Value / Expected (`views/build/varpick.js`); the check card lists first / last / #N ("New each run (which copy)"); the recorder's
  typed-value card has "New each run…" (Build tab only, not the in-page card).
- Not built: copies in IF conditions and page fingerprints (stay as written), a "page shows every copy" check, per-loop-pass copies.
