# P10: API/XML building

**Model:** Opus · **Branch/PR:** the session's branch → PR into `qa-regression` titled `P10: API/XML building`

Build API and XML tests in the UI.

## Read first (only these)
- dev/designs/CONTEXT_workbook_builder_design.md Q18, Q19
- dev/designs/workbook-builder-canvas/api.py (ApiEditor, ApiImport)
- workbook/api.py, api_template.py, engine/api_runner.py

## You own
- `src/regrunner/build/api_builder.py`
- `web/static/js/views/build/api*.js`
- `engine/api_runner.py (XML part)`

## Build
- Form (method, URL, headers, body with variable picker), Send now with the environment's values, response tree: click a value → check/save; JSON path / XPath written but editable; arrays ask "this item" or "item where …".
- Paste cURL, import a Postman collection, fill from existing API template files. XML/XPath evaluation (check lxml installs on Python 3.9; else stdlib).

## Done when
- `test_api_tests.py`, `test_api_purchase_flavour.py` + new tests against the mock `/policy/purchase/v2` API pass.

## Progress
<!-- one line per checkpoint: date · what's done · what's next -->
