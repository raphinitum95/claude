"""The unicorn's idle animation (src/regrunner/web/static/unicorn/js/idle.js): breathing, blinking, tail swish, ear flick, mane sway.

The motion engine is a pure function of a virtual clock with injected randomness, so the timing is checked exactly; the DOM part is checked in a real
Chromium on the generated preview page (file://): it must stay under 30 frames a second, write only the parts it owns, stop when the tab is hidden or
the user asks for reduced motion, leave the moods' own ear / eyelid poses alone, and put everything back when it stops."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

pytestmark = pytest.mark.browser

PREVIEW = (Path(__file__).resolve().parent.parent / "src" / "regrunner" / "web" / "static" / "unicorn" / "preview.html").as_uri()

# a small seeded random generator (mulberry32) so the engine tests are exact
SEEDED = """(seed) => { let a = seed; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }"""

OWNED = ["head-rig", "neck", "body", "chest-heart", "tail", "front-leg-left", "front-leg-right", "mane-back", "ear-left", "ear-right", "eyelid-left", "eyelid-right",
         "mane-lock-1", "mane-lock-2", "mane-lock-3", "mane-lock-4", "mane-lock-5", "mane-lock-6"]
UNTOUCHED = ["horn", "head", "mane-front", "eye-left", "eye-right", "mouth-open", "mouth-neutral", "cheek-left", "shadow", "hoof-left"]


@pytest.fixture
async def browser():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        yield browser
        await browser.close()


async def open_preview(browser, **context_options):
    context = await browser.new_context(viewport={"width": 900, "height": 1000}, **context_options)
    page = await context.new_page()
    await page.goto(PREVIEW)
    return page


async def inline(page, ids):
    return await page.evaluate("(ids) => Object.fromEntries(ids.map((id) => [id, document.getElementById(id).style.transform]))", ids)


async def test_a_blink_comes_every_three_to_five_seconds_and_one_in_six_is_a_double(browser):
    page = await open_preview(browser)
    result = await page.evaluate("""(seeded) => {
      const make = eval(seeded);
      const engine = UnicornIdle.createEngine({ random: make(7) });
      const starts = []; let shut = 0, prev = 0, peak = 0;
      for (let t = 0; t < 600000; t += 33) {
        const lid = engine.step(33).lid;
        if (lid > 0 && prev === 0) starts.push(t);
        peak = Math.max(peak, lid); prev = lid;
      }
      // gaps between the starts of separate blinks; a double blink is two starts 330 ms apart
      const gaps = starts.slice(1).map((s, i) => s - starts[i]);
      return { first: starts[0], peak, doubles: gaps.filter((g) => g < 500).length, singles: gaps.filter((g) => g >= 500).length,
               longGaps: gaps.filter((g) => g >= 500), blinks: starts.length };
    }""", SEEDED)
    assert 2000 <= result["first"] <= 4300, "the first blink comes soon after she appears"
    assert result["peak"] >= 0.99, "a blink shuts the lids completely"
    assert min(result["longGaps"]) >= 3000 and max(result["longGaps"]) <= 5900, "between blinks: 3 to 5 s (plus the blink itself)"
    share = result["doubles"] / (result["doubles"] + result["singles"])
    assert 0.06 <= share <= 0.30, f"about one blink in six is a double blink, got {share:.2f}"


async def test_an_ear_flicks_now_and_then_on_either_side_and_comes_back(browser):
    page = await open_preview(browser)
    result = await page.evaluate("""(seeded) => {
      const make = eval(seeded);
      const engine = UnicornIdle.createEngine({ random: make(11) });
      let flicks = 0, prev = 0, sides = new Set(), peak = 0, last = null;
      for (let t = 0; t < 180000; t += 33) {
        const ear = engine.step(33).ear;
        if (ear.side !== 0 && prev === 0) { flicks += 1; sides.add(ear.side); }
        if (ear.side !== 0) peak = Math.max(peak, Math.abs(ear.rot));
        prev = ear.side; last = ear;
      }
      return { flicks, sides: [...sides].sort(), peak };
    }""", SEEDED)
    assert 12 <= result["flicks"] <= 28, f"an ear flick every 6 to 12 s: {result['flicks']} in 3 minutes"
    assert result["sides"] == [-1, 1], "both ears flick"
    assert 8 <= result["peak"] <= 12, "a flick is a small, quick twitch"


async def test_the_motion_stays_small_and_settling_eases_everything_to_rest_without_starting_new_blinks(browser):
    page = await open_preview(browser)
    result = await page.evaluate("""(seeded) => {
      const make = eval(seeded);
      const engine = UnicornIdle.createEngine({ random: make(3) });
      let maxTail = 0, maxLock = 0, minHead = 0, maxBodyY = 0;
      for (let t = 0; t < 60000; t += 33) {
        const p = engine.step(33);
        maxTail = Math.max(maxTail, Math.abs(p.tail.rot)); maxLock = Math.max(maxLock, ...p.locks.map(Math.abs));
        minHead = Math.min(minHead, p.head.ty); maxBodyY = Math.max(maxBodyY, p.body.sy);
      }
      const blinksBefore = engine.blinkCount();
      engine.settle(700);
      let rest = null, steps = 0;
      while (steps < 200 && !engine.atRest()) { rest = engine.step(33); steps += 1; }
      const after = engine.step(33);
      for (let i = 0; i < 400; i += 1) engine.step(33);       // 13 more seconds: a settled engine starts no blink
      return { maxTail, maxLock, minHead, maxBodyY, atRest: engine.atRest(), steps, restTail: after.tail.rot, restHead: after.head.ty, restBody: after.body.sy,
               newBlinks: engine.blinkCount() - blinksBefore };
    }""", SEEDED)
    assert result["maxTail"] <= 4.5 and result["maxLock"] <= 2.5, "tail and mane sway by a few degrees at most"
    assert -1.5 <= result["minHead"] <= -1.0 and result["maxBodyY"] <= 1.0105, "breathing is a pixel or so"
    assert result["atRest"] and result["steps"] <= 60, "she is at rest well inside a second"
    assert result["restTail"] == 0 and result["restHead"] == 0 and result["restBody"] == 1
    assert result["newBlinks"] <= 1, "at most the blink that was already under way finishes; none start while settling"


async def test_the_loop_runs_at_most_thirty_frames_a_second_and_only_writes_the_parts_it_owns(browser):
    page = await open_preview(browser)
    await asyncio.sleep(2.2)
    stats = await page.evaluate("idle.stats()")
    assert 30 <= stats["frames"] <= 70, f"about 30 fps (a 60 Hz screen must not mean 60 frames): {stats['frames']} frames in 2.2 s"
    assert stats["writes"] > 100 and stats["writes"] / stats["frames"] <= 19, "only changed transforms are written, at most the 18 owned parts a frame"
    owned = await inline(page, OWNED)
    assert "rotate(" in owned["tail"] and owned["head-rig"].startswith("translateY("), "she is moving"
    assert all(v == "" for v in (await inline(page, UNTOUCHED)).values()), "no other part of the locked art gets an inline transform"


async def test_stopping_puts_every_part_back_to_its_css_pose(browser):
    page = await open_preview(browser)
    await asyncio.sleep(0.5)
    await page.evaluate("idle.stop()")
    frames = (await page.evaluate("idle.stats()"))["frames"]
    await asyncio.sleep(0.3)
    stats = await page.evaluate("idle.stats()")
    assert stats["frames"] == frames and not stats["running"], "the loop is really stopped"
    assert all(v == "" for v in (await inline(page, OWNED)).values())


async def test_a_hidden_tab_pauses_the_loop_and_a_visible_one_resumes_it(browser):
    page = await open_preview(browser)
    await asyncio.sleep(0.4)
    await page.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
                                    document.dispatchEvent(new Event('visibilitychange')); }""")
    frames = (await page.evaluate("idle.stats()"))["frames"]
    await asyncio.sleep(0.5)
    paused = await page.evaluate("idle.stats()")
    assert paused["frames"] == frames and not paused["running"] and paused["hidden"], "no frames at all while the tab is hidden"
    await page.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
                                    document.dispatchEvent(new Event('visibilitychange')); }""")
    await asyncio.sleep(0.5)
    assert (await page.evaluate("idle.stats()"))["frames"] > frames + 5, "she moves again when the tab is visible"


async def test_reduced_motion_means_no_loop_at_all(browser):
    page = await open_preview(browser, reduced_motion="reduce")
    await asyncio.sleep(0.6)
    stats = await page.evaluate("idle.stats()")
    assert stats["reducedMotion"] and stats["frames"] == 0 and not stats["running"]
    assert all(v == "" for v in (await inline(page, OWNED)).values()), "she stays in her resting pose"


async def test_the_moods_own_ear_and_eyelid_poses_are_left_alone_and_a_blink_works_when_the_eyes_are_open(browser):
    page = await open_preview(browser)
    await page.click("button[data-mood=sad]")                          # sad: droopy ears, lids parked by CSS
    await page.evaluate("idle.blinkNow()")
    for _ in range(25):
        await asyncio.sleep(0.04)
        lids = await inline(page, ["eyelid-left", "eyelid-right", "ear-left", "ear-right"])
        assert lids == {"eyelid-left": "", "eyelid-right": "", "ear-left": "", "ear-right": ""}, "sad: the idle loop must not override the CSS pose"
    await page.click("button[data-mood=neutral]")
    await page.evaluate("idle.blinkNow()")
    seen = set()
    for _ in range(30):
        await asyncio.sleep(0.03)
        seen.add((await inline(page, ["eyelid-left"]))["eyelid-left"][:8])
    assert any(v.startswith("scaleY(") for v in seen), f"the lids closed during the blink: {seen}"


async def test_settling_eases_her_to_rest_then_stops_by_itself_and_clears_the_transforms(browser):
    page = await open_preview(browser)
    await asyncio.sleep(0.4)
    await page.evaluate("idle.settle(300)")
    for _ in range(60):
        await asyncio.sleep(0.05)
        if await page.evaluate("idle.settled()"):
            break
    stats = await page.evaluate("idle.stats()")
    assert await page.evaluate("idle.settled()") and not stats["running"], "she came to rest and the loop ended"
    assert all(v == "" for v in (await inline(page, OWNED)).values())
    await page.evaluate("idle.start()")
    await asyncio.sleep(0.3)
    assert (await page.evaluate("idle.stats()"))["running"], "start() wakes her again"


async def test_one_engine_step_costs_far_less_than_a_millisecond(browser):
    page = await open_preview(browser)
    per_step = await page.evaluate("""() => { const e = UnicornIdle.createEngine(); const t0 = performance.now();
      for (let i = 0; i < 20000; i += 1) e.step(33); return (performance.now() - t0) / 20000; }""")
    assert per_step < 0.05, f"{per_step:.4f} ms per step"
