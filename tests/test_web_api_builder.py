"""The API / XML test editor in a real browser (P10): a new API test from the New test dialog, Send now against the mock purchase API, a click on
a value in the response tree that becomes a check / a save of "the item where ...", and a pasted cURL command."""
from __future__ import annotations

import pytest

from tests.test_web_build import build_copy, js_until, open_ui  # noqa: F401  (fixture)
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


async def view(web, wb: str, test: str) -> dict:
    async with web.aclient() as c:
        r = await c.get(f"/api/build/api/{wb}/tests/{test}")
        assert r.status_code == 200, r.text
        return r.json()


async def edit(web, wb: str, *ops) -> dict:
    async with web.aclient() as c:
        r = await c.post(f"/api/build/workbooks/{wb}/edit", json={"ops": list(ops)})
        assert r.status_code == 200, r.text
        return r.json()


async def test_a_new_api_test_is_made_from_the_new_test_dialog_and_opens_in_the_api_editor(web, build_copy):
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}")
    try:
        await js_until(page, "!!document.querySelector('[data-act=\"build-new-test\"]')")
        await page.locator('[data-act="build-new-test"]').first.click()
        await page.locator('[data-input="build-nt-name"]').fill("Quote")
        await page.get_by_role("button", name="API test").click()                                # (one kind: no JSON / XML choice)
        await page.get_by_role("button", name="Create test").click()
        await js_until(page, "location.hash.includes('/test/Quote')")
        await js_until(page, "!!document.querySelector('[data-change=\"build-api-url\"]')")
        await page.locator('[data-change="build-api-url"]').fill(web.site + "policy/purchase/v2")
        await page.locator('[data-change="build-api-url"]').blur()
        await js_until(page, "!document.querySelector('[data-act=\"build-undo\"]').disabled", timeout=10)
        v = await view(web, build_copy, "Quote")
        assert v["url"] == web.site + "policy/purchase/v2" and v["format"] == "json"
        assert [(h["name"], h["value"]) for h in v["headers"]] == [("Content-Type", "application/json")]      # a header row like any other
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_send_now_shows_the_answer_and_a_clicked_value_in_a_list_becomes_a_save_of_the_item_where(web, build_copy):
    await edit(web, build_copy, {"op": "api_add_test", "name": "Buy", "format": "json", "method": "POST", "url": web.site + "policy/purchase/v2",
                                 "headers": [["apiKey", "KEY-123"]], "body": '{"lastName": "{LastName_IN}"}'},
               {"op": "api_set_value", "test": "Buy", "row": 2, "column": "LastName_IN", "value": "Smith"},
               {"op": "api_set_value", "test": "Buy", "row": 2, "column": "WHO", "value": "Duplicate"})
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/Buy")
    try:
        await js_until(page, "!!document.querySelector('[data-act=\"build-api-send\"]')")
        assert await page.locator('[data-change="build-api-header"][data-name="apiKey"]').input_value() == "••••••"   # a key typed in the sheet: hidden
        await page.locator('[data-act="build-api-send"]').first.click()
        await js_until(page, "document.querySelectorAll('[data-act=\"build-api-node\"]').length > 3", timeout=30)
        assert (await page.locator(".pill").first.inner_text()).strip() == "200"
        await page.locator('[data-act="build-api-node"][title$="policyResponses[1].policyDetail.policyNumber"]').click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-api-pop-add\"]')")
        path = await page.locator('[data-input="build-api-pop-path-text"]').input_value()
        assert path == "$.purchaseResponse.policyResponses[?(@.policyDetail.policyHolder.firstName=='{WHO}')].policyDetail.policyNumber"
        await page.get_by_role("button", name="Save as variable").click()
        await page.locator('[data-input="build-api-pop-var"]').fill("POLICY_NO")
        await page.locator('[data-act="build-api-pop-add"]').click()
        await js_until(page, "[...document.querySelectorAll('.scard')].some(e => e.textContent.includes('POLICY_NO'))", timeout=10)
        v = await view(web, build_copy, "Buy")
        assert [(s["path"], s["column"]) for s in v["saves"]] == [(path, "POLICY_NO")]
        await page.locator('[data-act="build-api-check-status"]').click()
        await js_until(page, "[...document.querySelectorAll('.scard')].some(e => e.textContent.includes('status is 200'))", timeout=10)
        await page.locator('[data-act="build-api-send"]').first.click()
        await js_until(page, "!!document.querySelector('.scard .pdot')", timeout=30)               # the check says how it went on the last send
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_a_pasted_curl_command_replaces_the_request_with_the_workbooks_names(web, build_copy):
    await edit(web, build_copy, {"op": "api_add_test", "name": "Lookup", "format": "json", "url": "http://placeholder.invalid/"})
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/Lookup")
    try:
        await js_until(page, "!!document.querySelector('[data-act=\"build-api-tab\"]')")
        await page.get_by_role("tab", name="Paste cURL").click()
        await page.locator('[data-input="build-api-curl"]').fill(
            "curl 'https://h.test/policy/v4/P-100' -H 'Authorization: Bearer tok-1' -H 'Accept: application/json'")
        await page.get_by_role("button", name="Read it").click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-api-curl-use\"]')")
        assert "tok-1" not in await page.content()
        await page.locator('[data-act="build-api-curl-use"]').click()
        await js_until(page, "!!document.querySelector('[data-change=\"build-api-url\"]')", timeout=10)
        v = await view(web, build_copy, "Lookup")
        assert v["url"] == "https://h.test/policy/v4/P-100" and v["method"] == "GET"
        assert {h["name"]: h["value"] for h in v["headers"]} == {"Authorization": "Bearer {SECRET:AUTHORIZATION}", "Accept": "application/json",
                                                                 "Content-Type": "application/json"}          # (the new test's own row stays)
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_headers_are_typed_into_the_table_and_renamed_and_checks_and_a_new_variable_are_added_by_hand_below_a_real_request_warning(web, build_copy):
    """Feedback items 13 and 14: "+ Header" is an empty row typed into, a header's name can change, a check (a path, or the whole response
    with fields left out) is added without sending anything, "New variable" is in Insert variable, and Send now says it is a real request."""
    await edit(web, build_copy, {"op": "api_add_test", "name": "Quote", "method": "GET", "url": web.site + "policy/quote/v1"})
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/Quote")
    try:
        await js_until(page, "!!document.querySelector('[data-act=\"build-api-add-header\"]')")
        warning = await page.locator('[data-key="send-warning"]').inner_text()
        assert "Send now sends a real request" in warning and "real transactions" in warning
        await page.locator('[data-act="build-api-add-header"]').click()
        await page.locator('[data-input="build-api-new-header-value"]').fill("abc")
        await page.locator('[data-input="build-api-new-header-name"]').fill("x-trace")
        await page.locator('[data-input="build-api-new-header-name"]').press("Tab")
        await js_until(page, "!!document.querySelector('[data-change=\"build-api-header\"][data-name=\"x-trace\"]')", timeout=10)
        assert ("x-trace", "abc") in [(h["name"], h["value"]) for h in (await view(web, build_copy, "Quote"))["headers"]]
        name = page.locator('[data-change="build-api-header-name"][data-name="x-trace"]')
        await name.fill("x-request-id")
        await name.press("Tab")
        await js_until(page, "!!document.querySelector('[data-change=\"build-api-header-name\"][data-name=\"x-request-id\"]')", timeout=10)
        headers = [(h["name"], h["value"]) for h in (await view(web, build_copy, "Quote"))["headers"]]
        assert ("x-request-id", "abc") in headers and "x-trace" not in dict(headers)

        await page.locator('[data-act="build-api-hand"][data-val="path"]').click()
        await page.locator('[data-input="build-api-hand-path"]').fill("$.plan.code")
        await page.locator('[data-input="build-api-hand-expected"]').fill("Basic")
        await page.locator('[data-act="build-api-hand-add"]').click()
        await js_until(page, "[...document.querySelectorAll('.scard')].some(e => e.textContent.includes('$.plan.code is Basic'))", timeout=10)
        await page.locator('[data-act="build-api-hand"][data-val="whole"]').click()
        await page.locator('textarea[data-input="build-api-hand-expected"]').fill('{"plan": {"code": "Basic", "price": 12.5}}')
        await page.locator('[data-input="build-api-hand-ignore"]').fill("quoteId; createdAt; items")
        await page.locator('[data-act="build-api-hand-add"]').click()
        await js_until(page, "[...document.querySelectorAll('.scard')].some(e => e.textContent.includes('whole response is as expected (ignoring 3)'))",
                       timeout=10)

        await page.locator('[data-act="build-api-sel"][data-io=""]').first.click()                 # back to the request
        await page.locator('[data-act="build-api-var-menu"]').click()
        await page.locator('[data-act="build-api-new-var"]').click()
        await page.locator('[data-input="build-api-new-var-name"]').fill("PLAN")
        await page.locator('[data-input="build-api-new-var-value"]').fill("Basic")
        await page.locator('[data-act="build-api-new-var-add"]').click()
        await js_until(page, "(document.querySelector('[data-change=\"build-api-body\"]') || {}).value === '{PLAN}'", timeout=10)
        v = await view(web, build_copy, "Quote")
        assert v["body"]["text"] == "{PLAN}" and v["rowValues"]["PLAN"] == "Basic"

        await page.locator('[data-act="build-api-send"]').first.click()
        await js_until(page, "document.querySelectorAll('.scard .pdot').length === 2", timeout=30)       # both checks pass on the real answer
        assert await page.locator('.scard .pdot[title="Passed on the last send"]').count() == 2
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_an_expected_status_nothing_checks_is_said_in_the_editor_and_one_click_adds_the_check(web, build_copy):
    """Feedback item 15: RES_STATUS_CD_EXP with no compare row is never checked; the editor says so and fixes it."""
    await edit(web, build_copy, {"op": "api_add_test", "name": "Lookup", "method": "GET", "url": web.site + "policy/quote/v1"},
               {"op": "api_set_value", "test": "Lookup", "row": 2, "column": "RES_STATUS_CD_EXP", "value": "200"})
    pw, browser, page = await open_ui(web, f"/#/build/{build_copy}/test/Lookup")
    try:
        await js_until(page, "!!document.querySelector('[data-act=\"build-api-fix-status\"]')")
        assert "The status is never checked." in await page.locator('[data-key="status-unchecked"]').inner_text()
        await page.locator('[data-act="build-api-fix-status"]').click()
        await js_until(page, "!document.querySelector('[data-act=\"build-api-fix-status\"]')", timeout=10)
        v = await view(web, build_copy, "Lookup")
        assert v["statusUnchecked"] is None and [(c["what"], c["expectedValue"]) for c in v["checks"]] == [("status", "200")]
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
