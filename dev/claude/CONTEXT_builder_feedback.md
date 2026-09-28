# Workbook Builder: the user's feedback after trying it (2026-09-28)

The user tried the Build tab after P11 and listed what got in the way. They asked for it as a running tally, actioned in batches.
Batch 1 (items 1-8) is done on branch `claude/adoring-dijkstra-hcvotu`; items 9-17 are next. Each line says what the user asked for and
what was found in the code, so the next session does not have to re-derive it.

## Batch 1: done

1. **Element picker you can find.** The inspector shows "On which element" for every step whose method acts on an element (`Step.element`,
   new in CONTRACT.md 2.3), even before it has one: FindBy select, a locator field you can type or paste into (an empty FindBy is guessed
   from the text: `//` = XPath, `#`/`.`/`[`/space = CSS, a bare word = id), and "Pick on the page" (opens the site first when needed).
2. **"All workbooks"** (`#/build/all`): a page of workbook cards (the whole card opens one), reached from the header's grid button and the
   top of the rail. `S.build.listing` shows it over whatever workbook is loaded.
3. **Download** (`GET /api/workbooks/{name}/download`): header button beside Save and on each workbook card; with unsaved edits it asks to
   save first.
4. **"Production" column wording.** No screenshot came, so this is the wording fix: "Is it production?" with "Production" / "Not production"
   beside each tick, in the new-workbook dialog and (new) in the Environments dialog, where it could not be changed before.
5. **Closing the build window by hand** now closes the session (`BuildSession._page_closed` -> `_close_if_windowless` after
   `WINDOWLESS_GRACE_S`); the browser used to keep running with no window, so the Build tab still said "open" and Pick had no page.
6. **Done on the pill** stops picking and recording (`kind: "done"`); `Recorder.finish` keeps a `summary` (count, rows, first/last step);
   the Build tab jumps to the first recorded step and shows "Recorded N steps (steps X-Y)" with Show them / Remove them (one undoable edit).
7. **"Open the site" opens the environment's Domain** (`BuildSession.domain`, the `DOMAIN` row of `_rr_environments`) when the test has no
   Open step; none set = blank page + a notice with a link to Environments. Recording an empty test starts it with `OPEN {DOMAIN}`.
8. **"Selected" bar** wraps inside its column (`.bulk-bar` in app.css) instead of overflowing a narrow window.

## Batch 2: to do (items 9-19)

9. **Run plan Timeline** (Run tab, `views/newrun.js` `timelineView`): cut off and unreadable on small screens. Scroll sideways at least, test
   names stay readable.
10. **Page change while recording**: add the ASSERT_PAGE gate + fingerprint automatically (today `Recorder._propose_fingerprint` only
    proposes it as a prompt), shown as a normal step with undo; reuse a known fingerprint. Ask the user first if they never saw the prompt
    at all (that would be a bug of its own).
11. **New page (block)**: "Start new page here" on a step and in the add-step menu (the `split_block` op exists, no UI calls it), "New page"
    at the end of the block strip, recording starts a new block on a page change (goes with 10). Also check: `move_steps` without `before`
    moves the steps to the end of the test, so "Move to block..." into an existing block that is not the last looks wrong (verify first).
12. **Variables tab you can edit**: add / rename / edit / delete variables there (Params columns, environment values per environment,
    secrets). Today `variableMap` in `views/build/workbook.js` is read-only; Environments stays for domains and which one is production.
13. **API headers**: "+ Header" adds an empty row typed into directly (today two `window.prompt`s in `api_editor.js`), and a header's name
    can be changed after it is created.
14. **API checks**: a whole-response check with an "ignore these fields" list (timestamps, ids), as well as the per-value ones (needs an
    engine change in `engine/api_runner.py` as well as the UI); add a check by hand without Send now (type the path and expected); "New
    variable" in Insert variable; a clear warning that Send now is a real request.
15. **Status never checked**: an API test with `RES_STATUS_CD_EXP` but no `compare` row in `InputOutput` never checks the status (seen in
    `qantas-test 2.xlsx` PolicySearch). A builder problem that offers to add the compare row.
16. **One "API test" kind**: no API vs XML choice. `Content-Type` is just a header row, `application/json` by default, edited like any other;
    the builder writes `JSON_FORMAT` from it (or from what the response looks like). Use the `<>` icon, not the cloud. Existing XML tests
    open as API tests with their XML Content-Type.
17. **Test map cards clickable as a whole** (`views/build/workbook.js` `testCard`): today only the title opens the test; the run toggle and
    other buttons on the card keep doing only their own job.
18. **Run tab environment picker for builder workbooks**: no "Workbook default" choice; offer the environments the workbook's own
    `_rr_environments` table defines (today `views/newrun.js` `envDefs` is a fixed Workbook default / QA / UAT / PROD list).
19. **Results tab stays the Results tab**: a solo run opened from the Results history (`views/results/history.js` `itemUrl`, also
    `results/batch.js` and `results/test.js` links, `results/actions.js` after a re-run) goes to `#/run/<id>`, which switches to the Run
    tab. Show that run inside the Results tab instead.

Also told the user: `workbooks/qantas-test 2.xlsx` is saved with Global Environment = PROD.
