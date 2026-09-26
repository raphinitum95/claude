from __future__ import annotations

import time

import pytest
from playwright.async_api import async_playwright

from regrunner.selectors.resolve import MapEntry, SelectorMap, SelectorSyntaxError, build_chain, resolve
from regrunner.selectors.spec import legacy_key, legacy_strategy, parse_locator, parse_locator_list
from regrunner.selectors.xpath2css import score_xpath, xpath_to_css


# ---- parsing --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,selector", [
    ("//div[@id='a']", "xpath=//div[@id='a']"), ("(//a)[2]", "xpath=(//a)[2]"), ("#save", "css=#save"),
    ("input[name=q]", "css=input[name=q]"), ("css=.x > .y", "css=.x > .y"), ("id=go", 'css=[id="go"]'),
    ("name=age", 'css=[name="age"]'), ("testid=login", 'css=[data-testid="login"]'), ("text=Sign in", "text=Sign in"),
    ("role=button[name=\"Go\"]", 'role=button[name="Go"]'), ("xpath=//b", "xpath=//b"),
    ("placeholder=Search", 'css=[placeholder="Search"]'),
])
def test_parse_locator(text, selector):
    assert parse_locator(text).selector == selector


def test_locator_list_and_errors():
    assert [s.selector for s in parse_locator_list("id=a || css=.b ||  //c")] == ['css=[id="a"]', "css=.b", "xpath=//c"]
    with pytest.raises(ValueError):
        parse_locator("   ")


@pytest.mark.parametrize("findby,value,selector", [
    ("XPATH", "//a", "xpath=//a"), ("by_id", "x", 'css=[id="x"]'), ("Name", "n", 'css=[name="n"]'),
    ("CSS_SELECTOR", ".c", "css=.c"), ("TAGNAME", "h1", "css=h1"), ("CLASSNAME", "big", 'css=[class~="big"]'),
    ("LINKTEXT", "Get Quote", "xpath=//a[normalize-space(.)='Get Quote']"),
    ("PARTIALLINKTEXT", "Quote", "xpath=//a[contains(normalize-space(.), 'Quote')]"),
])
def test_legacy_findby_vocabulary(findby, value, selector):
    assert legacy_strategy(findby, value).selector == selector


def test_legacy_strategy_rejects_unknown_or_empty():
    assert legacy_strategy("BOGUS", "x") is None and legacy_strategy("XPATH", "") is None


def test_chain_order_and_fallback_switch():
    smap = SelectorMap({"//input[@name='a']": MapEntry(use=["css=input[name=a]"], index=2)})
    chain = build_chain("XPATH", "//input[@name='a']", "id=first", smap)
    assert [(s.origin, s.selector) for s in chain] == [
        ("sheet", 'css=[id="first"]'), ("map", "css=input[name=a]"), ("legacy", "xpath=//input[@name='a']")]
    assert chain[1].index == 2 and chain[0].index is None
    strict = build_chain("XPATH", "//input[@name='a']", "", smap, legacy_fallback=False)
    assert [s.origin for s in strict] == ["map"]
    assert [s.origin for s in build_chain("XPATH", "//zzz", "", smap, legacy_fallback=False)] == ["legacy"]   # never empty
    assert legacy_key("ID", "x") == "id:x" and legacy_key("XPATH", "//a") == "//a"


def test_selector_map_round_trip(tmp_path):
    path = tmp_path / "s.yaml"
    m = SelectorMap({"//a": MapEntry(["css=a"], None, "auto"), "(//b)[2]": MapEntry(["css=b"], 1, "harvest", "note")})
    m.save(path)
    loaded = SelectorMap.load(path)
    assert loaded.lookup("(//b)[2]").index == 1 and loaded.lookup("//a").source == "auto"
    path.write_text("locators:\n  '//x': 'css=x'\n  '//y': ['css=y', 'css=z']\n")
    loaded = SelectorMap.load(path)
    assert loaded.lookup("//x").use == ["css=x"] and loaded.lookup("//y").use == ["css=y", "css=z"]
    assert len(SelectorMap.load(tmp_path / "missing.yaml")) == 0


# ---- XPath -> CSS -------------------------------------------------------------------------------------------
CONVERTIBLE = {
    "//input[@name='tripDepartureDate']": 'input[name="tripDepartureDate"]',
    "//button[@id='add-container-button__1']": 'button[id="add-container-button__1"]',
    "//input[@id='cmp-Input' and @placeholder='Select a country']": 'input[id="cmp-Input"][placeholder="Select a country"]',
    "//span[@class='handlebar-recursive-replacement productName']": 'span[class="handlebar-recursive-replacement productName"]',
    "//span[contains(@class,'tripDepartureDate')]": 'span[class*="tripDepartureDate"]',
    "//div[@class='cmp-text']//span[contains(@class,'x')]": 'div[class="cmp-text"] span[class*="x"]',
    "//ul/li[@data-k]": "ul > li[data-k]",
    "//*[@id='q']": '[id="q"]',
    "//a[starts-with(@href,'/en/')]": 'a[href^="/en/"]',
    "//div[@data-cmp-claimantid='3']": 'div[data-cmp-claimantid="3"]',
}
NOT_CONVERTIBLE = [
    "//button[text()='Accept All Cookies']", "//p[contains(.,'$')]", "//a[contains(text(),'x')]", "//div[2]",
    "//button[@type='SUBMIT']",                                    # CSS would also match type="submit" (HTML case rules)
    "//a[@href='x' or @id='y']", "//div/following-sibling::span", "//input[not(@disabled)]", "div[@id='x']",
    "//span[contains(@class,'')]", "//x[@a='1'][2]",
]


@pytest.mark.parametrize("xpath,css", CONVERTIBLE.items())
def test_xpath_to_css_conversions(xpath, css):
    assert xpath_to_css(xpath).css == css


def test_positional_wrapper_becomes_nth():
    conv = xpath_to_css("(//input[@name='insuredAge'])[3]")
    assert (conv.css, conv.nth) == ('input[name="insuredAge"]', 2)
    assert xpath_to_css("(//x)[0]") is None


@pytest.mark.parametrize("xpath", NOT_CONVERTIBLE)
def test_unsafe_xpaths_are_left_alone(xpath):
    assert xpath_to_css(xpath) is None


def test_scoring_ranks_stable_anchors_above_brittle_ones():
    strong = score_xpath("//input[@name='tripDepartureDate']")[0]
    ok = score_xpath("//span[@class='productName']")[0]
    weak_text = score_xpath("//button[text()='Accept All Cookies']")[0]
    weak_pos = score_xpath("(//button[@type='button'])[2]")[0]
    assert strong > ok > weak_pos and ok > weak_text
    assert score_xpath("//div[@id='text-c91052af4d']")[0] < score_xpath("//div[@id='main-form']")[0]   # generated-looking id


DOM = """
<div id="q" class="cmp-text"><span class="x a">1</span><span class="tripDepartureDate">2</span></div>
<ul><li data-k>a</li><li>b</li><li data-k="1">c</li></ul>
<input name="tripDepartureDate"><input name="insuredAge"><input name="insuredAge"><input name="insuredAge">
<button id="add-container-button__1">+</button><input id="cmp-Input" placeholder="Select a country">
<span class="handlebar-recursive-replacement productName">P</span><span class="productName">Q</span>
<a href="/en/x">x</a><a href="/fr/x">y</a><div data-cmp-claimantid="3">z</div>
<button type="submit">lower</button><button type="SUBMIT">upper</button>
"""


@pytest.mark.browser
async def test_generated_css_matches_exactly_the_same_elements_as_the_xpath():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(f"<!doctype html><body>{DOM}</body>")
        html_of = "els => els.map(e => e.outerHTML)"
        for xpath in [*CONVERTIBLE, "(//input[@name='insuredAge'])[2]"]:
            conv = xpath_to_css(xpath)
            by_xpath = await page.locator(f"xpath={xpath}").evaluate_all(html_of)
            by_css = await page.locator(f"css={conv.css}").evaluate_all(html_of)
            if conv.nth is not None:
                by_css = by_css[conv.nth:conv.nth + 1]
            assert by_css == by_xpath, xpath
        # ...and this is why type='SUBMIT' is refused: CSS attribute values are case-insensitive for `type`.
        assert await page.locator("xpath=//button[@type='SUBMIT']").count() == 1
        assert await page.locator('css=button[type="SUBMIT"]').count() == 2
        await browser.close()


# ---- resolution against a live page --------------------------------------------------------------------------
@pytest.mark.browser
async def test_resolve_prefers_primary_falls_back_fast_and_reports_syntax_errors():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(f"<!doctype html><body>{DOM}</body>")
        primary = parse_locator_list("css=input[name=insuredAge]", "map")
        legacy = [legacy_strategy("XPATH", "(//input[@name='insuredAge'])[2]")]

        hit = await resolve(page, primary + legacy, 1, 2.0)
        assert hit.position == 0 and hit.count == 3 and not hit.used_fallback

        stale = parse_locator_list("css=input[name=renamed]", "map")
        started = time.monotonic()
        hit = await resolve(page, stale + legacy, 0, 5.0)
        assert hit.used_fallback and hit.strategy.origin == "legacy" and time.monotonic() - started < 1.0   # no 5 s wait

        assert await resolve(page, stale, 0, 0.3) is None                                                # genuinely absent
        assert await resolve(page, primary, 7, 0.3) is None                                              # index beyond matches
        with pytest.raises(SelectorSyntaxError):
            await resolve(page, parse_locator_list("css=div[[["), 0, 0.3)

        # late-appearing elements are found as soon as they exist (polling, not sleeping)
        await page.evaluate("setTimeout(() => { const b = document.createElement('b'); b.id = 'late'; document.body.append(b); }, 400)")
        started = time.monotonic()
        late = await resolve(page, parse_locator_list("id=late"), 0, 5.0)
        assert late is not None and 0.3 < time.monotonic() - started < 1.5
        await browser.close()


@pytest.mark.browser
async def test_every_legacy_findby_kind_finds_the_right_element():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""<!doctype html><body><a id="l1" class="big red" name="nm" href="#">Get Quote</a>
            <a href="#">Get Quote Now</a><h2>Head</h2></body>""")
        checks = [("ID", "l1", 1), ("NAME", "nm", 1), ("CLASSNAME", "big", 1), ("CLASSNAME", "bi", 0), ("TAGNAME", "h2", 1),
                  ("LINKTEXT", "Get Quote", 1), ("PARTIALLINKTEXT", "Quote", 2), ("CSS_SELECTOR", "a.red", 1), ("XPATH", "//h2", 1)]
        for findby, value, count in checks:
            assert await page.locator(legacy_strategy(findby, value).selector).count() == count, (findby, value)
        await browser.close()
