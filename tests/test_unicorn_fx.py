"""The unicorn's glitter and rain (src/regrunner/web/static/unicorn/js/fx.js) and the hooks the mood controller has into it (js/mood.js).

The particle motion is a pure engine with injected randomness, so the caps and the timing are checked exactly. The canvas part runs in a real Chromium on the
generated preview page (file://): one canvas, a loop that exists only while there are particles, a 30 fps cap, nothing at all under reduced motion or in a hidden tab."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

pytestmark = pytest.mark.browser

PREVIEW = (Path(__file__).resolve().parent.parent / "src" / "regrunner" / "web" / "static" / "unicorn" / "preview.html").as_uri()

SEEDED = """(seed) => { let a = seed; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }"""


@pytest.fixture
async def browser():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        yield browser
        await browser.close()


async def open_preview(browser, **context_options):
    context = await browser.new_context(viewport={"width": 1000, "height": 1000}, **context_options)
    page = await context.new_page()
    await page.goto(PREVIEW)
    await page.evaluate("() => { unicorn.destroy(); idle.stop(); fx.clear(); }")      # the preview's own wiring stays out of the way
    return page


async def lit_pixels(page) -> int:
    return await page.evaluate("""() => { const c = fx.canvas, d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
      for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n += 1; return n; }""")


async def test_no_more_particles_than_the_cap_are_ever_alive_whatever_is_asked_for(browser):
    page = await open_preview(browser)
    result = await page.evaluate("""(seeded) => {
      const e = UnicornFx.createEngine({ random: eval(seeded)(3), max: 90 });
      let peak = 0;
      for (let i = 0; i < 40; i += 1) e.glitter({ x: 266, y: 30, count: 50 });     // 2000 asked for in one go
      peak = Math.max(peak, e.live());
      e.rain(true); e.celebrate();
      for (let t = 0; t < 4000; t += 33) { e.step(33); peak = Math.max(peak, e.live()); e.glitter({ x: 100, y: 100, count: 30 }); peak = Math.max(peak, e.live()); }
      return peak;
    }""", SEEDED)
    assert result <= 90, f"a burst, a celebration and rain together never go past the cap: {result}"


async def test_glitter_bursts_out_falls_with_gravity_and_is_gone_within_about_two_seconds(browser):
    page = await open_preview(browser)
    r = await page.evaluate("""(seeded) => {
      const e = UnicornFx.createEngine({ random: eval(seeded)(5), max: 90 });
      e.glitter({ x: 266, y: 34, count: 30, from: -150, to: -30, speed: 190 });
      const first = e.particles().map((p) => ({ x: p.x, y: p.y, vy: p.vy }));
      const colors = new Set(e.particles().map((p) => p.color));
      let t = 0, goneAt = null, meanVyEarly = 0, meanVyLate = 0;
      meanVyEarly = e.particles().reduce((s, p) => s + p.vy, 0) / e.particles().length;
      for (; t < 4000; t += 33) {
        e.step(33);
        if (t === 600) meanVyLate = e.particles().reduce((s, p) => s + p.vy, 0) / Math.max(1, e.particles().length);
        if (goneAt === null && e.live() === 0) goneAt = t;
      }
      return { n: first.length, near: first.every((p) => Math.abs(p.x - 266) <= 4.1 && Math.abs(p.y - 34) <= 3.1), colors: [...colors], meanVyEarly, meanVyLate, goneAt, busy: e.busy() };
    }""", SEEDED)
    assert r["n"] == 30 and r["near"], "the burst starts at the horn tip"
    assert set(r["colors"]) <= {"#FFF3B8", "#FCE09E", "#FDB1D3", "#CB9AE5", "#86D4D5", "#FFFFFF"}, "only the rig's palette"
    assert r["meanVyLate"] > r["meanVyEarly"] + 40, "gravity pulls the glitter down"
    assert r["goneAt"] is not None and r["goneAt"] <= 2300 and r["busy"] is False, f"it is all gone by itself (at {r['goneAt']} ms)"


async def test_a_celebration_is_four_staggered_bursts_from_the_horn_and_both_sides(browser):
    page = await open_preview(browser)
    r = await page.evaluate("""(seeded) => {
      const e = UnicornFx.createEngine({ random: eval(seeded)(9), max: 90 });
      e.celebrate();
      const at = {}; let peak = 0;
      for (let t = 0; t <= 800; t += 20) { e.step(20); at[t] = e.live(); peak = Math.max(peak, e.live()); }
      return { start: at[0], early: at[100], mid: at[200], late: at[700], peak, busy: e.busy() };
    }""", SEEDED)
    assert r["busy"], "pending bursts count as work to do"
    assert r["start"] == 22 and r["early"] <= 22, "the first fountain is the horn's"
    assert r["mid"] >= 34, "the two side fountains follow a moment later"
    assert 50 <= r["peak"] <= 66 and r["late"] > 0, "a second horn burst comes later still; 66 particles in all, under the cap"


async def test_rain_falls_only_in_its_three_lanes_stops_at_each_lane_end_and_runs_out_when_switched_off(browser):
    page = await open_preview(browser)
    r = await page.evaluate("""(seeded) => {
      const e = UnicornFx.createEngine({ random: eval(seeded)(11), max: 90 });
      e.rain(true);
      const lanes = [[96, 166, 330], [374, 444, 330], [214, 326, 128]];
      let spawned = 0, seen = new Set(), peak = 0, bad = 0, lowest = { top: 0, side: 0 };
      for (let t = 0; t < 3000; t += 33) {
        e.step(33);
        e.particles().forEach((p) => {
          if (!seen.has(p)) { seen.add(p); spawned += 1; }
          const lane = lanes.find((l) => p.x >= l[0] - 20 && p.x <= l[1] + 20);
          if (!lane || p.y > lane[2] + 1) bad += 1;
          if (lane && lane[2] === 128) lowest.top = Math.max(lowest.top, p.y); else lowest.side = Math.max(lowest.side, p.y);
        });
        peak = Math.max(peak, e.live());
      }
      e.rain(false);
      for (let t = 0; t < 2000; t += 33) e.step(33);
      return { spawned, peak, bad, lowest, rainingAfter: e.isRaining(), left: e.live(), busy: e.busy() };
    }""", SEEDED)
    assert 100 <= r["spawned"] <= 140, f"about 40 drops a second for 3 s: {r['spawned']}"
    assert r["peak"] <= 34 and r["bad"] == 0, "no more than 34 drops in the air, always inside a lane and above its end"
    assert r["lowest"]["top"] <= 128 and 250 <= r["lowest"]["side"] <= 330, "drops over her head stop on it; drops beside her fall past the mane"
    assert r["rainingAfter"] is False and r["left"] == 0 and r["busy"] is False, "switched off, the rain in the air finishes and nothing is left to run"


async def test_the_canvas_is_one_click_through_layer_laid_over_the_rig_with_room_for_glitter_to_leave_her_outline(browser):
    page = await open_preview(browser)
    info = await page.evaluate("""() => { const s = document.querySelector('#stage svg').getBoundingClientRect(), c = fx.canvas, r = c.getBoundingClientRect();
      return { canvases: document.querySelectorAll('#stage canvas').length, events: getComputedStyle(c).pointerEvents, aria: c.getAttribute('aria-hidden'),
               margin: s.left - r.left, svgW: s.width, canvasW: r.width, stagePosition: getComputedStyle(document.getElementById('stage')).position }; }""")
    assert info["canvases"] == 1 and info["events"] == "none" and info["aria"] == "true"
    assert info["stagePosition"] == "relative" and info["margin"] > 0.15 * info["svgW"] and info["canvasW"] > info["svgW"] * 1.3


async def test_nothing_runs_at_rest_a_burst_draws_and_then_the_loop_ends_by_itself_and_the_canvas_is_empty(browser):
    page = await open_preview(browser)
    await asyncio.sleep(0.5)
    assert (await page.evaluate("fx.stats()"))["frames"] == 0 and not (await page.evaluate("fx.stats()"))["running"], "no particles, no loop"
    await page.evaluate("fx.celebrate()")
    await asyncio.sleep(0.5)
    mid = await page.evaluate("fx.stats()")
    assert mid["running"] and mid["frames"] > 5 and await lit_pixels(page) > 50, "glitter is drawn while it lasts"
    for _ in range(60):
        await asyncio.sleep(0.1)
        if not (await page.evaluate("fx.stats()"))["running"]:
            break
    done = await page.evaluate("fx.stats()")
    assert not done["running"] and done["live"] == 0, "the loop ended by itself"
    assert await lit_pixels(page) == 0, "and the canvas was left empty"
    frames = done["frames"]
    await asyncio.sleep(0.4)
    assert (await page.evaluate("fx.stats()"))["frames"] == frames


async def test_the_loop_is_capped_at_thirty_frames_a_second(browser):
    page = await open_preview(browser)
    await page.evaluate("fx.rain(true)")
    await asyncio.sleep(2.2)
    stats = await page.evaluate("fx.stats()")
    await page.evaluate("fx.rain(false)")
    assert 25 <= stats["frames"] <= 70, f"about 30 fps, not 60: {stats['frames']} frames in 2.2 s"
    assert stats["live"] <= 34


async def test_a_hidden_tab_pauses_it_and_reduced_motion_means_no_glitter_and_no_rain_at_all(browser):
    page = await open_preview(browser)
    await page.evaluate("fx.rain(true)")
    await asyncio.sleep(0.3)
    await page.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); }""")
    frames = (await page.evaluate("fx.stats()"))["frames"]
    await asyncio.sleep(0.4)
    assert (await page.evaluate("fx.stats()"))["frames"] == frames, "no frames while the tab is hidden"
    await page.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')); }""")
    await asyncio.sleep(0.4)
    assert (await page.evaluate("fx.stats()"))["frames"] > frames, "and it carries on when she is visible again"
    await page.evaluate("fx.rain(false)")

    calm = await open_preview(browser, reduced_motion="reduce")
    await calm.evaluate("fx.celebrate(); fx.sparkle(); fx.burst({}); fx.rain(true)")
    await asyncio.sleep(0.5)
    stats = await calm.evaluate("fx.stats()")
    assert stats["reducedMotion"] and stats["frames"] == 0 and stats["live"] == 0 and not stats["raining"] and await lit_pixels(calm) == 0


async def test_rain_stops_by_itself_after_its_time_limit_and_a_new_failure_renews_it_and_destroy_removes_the_canvas(browser):
    page = await open_preview(browser)
    await page.evaluate("""() => { window.fx2 = UnicornFx.attach(document.getElementById('stage'), { svg: document.querySelector('#stage svg'), rainMaxMs: 400 }); fx2.rain(true); }""")
    await asyncio.sleep(0.2)
    assert (await page.evaluate("fx2.stats()"))["raining"]
    await page.evaluate("fx2.rain(true)")                                          # renewed: the 400 ms start again
    await asyncio.sleep(0.3)
    assert (await page.evaluate("fx2.stats()"))["raining"], "a renewal restarts the time limit"
    for _ in range(40):
        await asyncio.sleep(0.1)
        if not (await page.evaluate("fx2.stats()"))["running"]:
            break
    stats = await page.evaluate("fx2.stats()")
    assert not stats["raining"] and not stats["running"] and stats["live"] == 0, "it ran out by itself, and so did the loop"
    await page.evaluate("fx2.destroy()")
    assert await page.evaluate("document.querySelectorAll('#stage canvas').length") == 1, "only the other canvas is left"


async def test_one_engine_step_with_a_full_set_of_particles_costs_a_small_fraction_of_a_frame(browser):
    page = await open_preview(browser)
    per_step = await page.evaluate("""() => { const e = UnicornFx.createEngine({ max: 90 }); e.rain(true);
      let t0 = performance.now(), n = 0;
      for (let i = 0; i < 6000; i += 1) { if (i % 20 === 0) e.glitter({ x: 266, y: 34, count: 30 }); e.step(33); n += 1; }
      return (performance.now() - t0) / n; }""")
    assert per_step < 0.1, f"{per_step:.4f} ms per step"


FAKE_FX = """window.fakeFx = { calls: [], sparkle() { this.calls.push('sparkle'); }, celebrate() { this.calls.push('celebrate'); }, rain(on) { this.calls.push('rain:' + on); } };"""
FAST = "{ startExcitedMs: 40, passSparkleMs: 40, flinchMs: 40, celebrateMs: 100, endSparkleMs: 40, restAfterMs: 60, sadRainMs: 150 }"


async def mood_page(browser):
    page = await open_preview(browser)
    await page.evaluate(FAKE_FX)
    await page.evaluate(f"() => {{ window.u = UnicornMood.create(document.querySelector('#stage svg'), {{ fx: window.fakeFx, config: {FAST} }}); }}")
    return page


async def test_a_pass_sparkles_a_great_ending_celebrates_and_a_happy_one_sparkles(browser):
    page = await mood_page(browser)
    await page.evaluate("u.onRunStart({}); u.onTestResult({ status: 'pass' }); u.onTestResult({ status: 'pass' })")
    assert (await page.evaluate("fakeFx.calls")) == ["sparkle", "sparkle"]
    await page.evaluate("fakeFx.calls.length = 0; u.onRunComplete({ passed: 20, failed: 0, total: 20 })")
    assert (await page.evaluate("fakeFx.calls")) == ["celebrate"]
    await page.evaluate("fakeFx.calls.length = 0; u.onRunStart({}); fakeFx.calls.length = 0; u.onRunComplete({ passed: 8, failed: 2, total: 10 })")
    assert (await page.evaluate("fakeFx.calls")) == ["sparkle"]


async def test_rain_falls_while_she_is_sad_each_failure_renews_it_and_it_stops_after_a_sad_ending_while_the_cloud_stays(browser):
    page = await mood_page(browser)
    await page.evaluate("u.onRunStart({})")
    await asyncio.sleep(0.1)                                                                          # the start excitement is over
    await page.evaluate("u.onTestResult({ status: 'pass' }); fakeFx.calls.length = 0; for (let i = 0; i < 3; i += 1) u.onTestResult({ status: 'fail' })")
    assert (await page.evaluate("u.getMood()")) == "scared", "three in a row: nervous, not sad: no rain yet"
    await page.evaluate("fakeFx.calls.length = 0; u.onTestResult({ status: 'pass' })")                 # 2 pass / 3 fail = 40 %: sad
    assert (await page.evaluate("u.getMood()")) == "sad"
    assert "rain:true" in await page.evaluate("fakeFx.calls"), "sad: rain"
    await page.evaluate("fakeFx.calls.length = 0; u.onTestResult({ status: 'fail' })")
    assert "rain:true" in await page.evaluate("fakeFx.calls"), "a failure while sad renews the rain"
    assert (await page.evaluate("document.getElementById('unicorn').dataset.fx")) == "rain", "the cloud is the SVG's `rain` state"
    await page.evaluate("fakeFx.calls.length = 0; u.onRunComplete({ passed: 2, failed: 4, total: 6 })")
    await asyncio.sleep(0.4)
    assert "rain:false" in await page.evaluate("fakeFx.calls"), "after a sad ending the rain stops by itself"
    assert (await page.evaluate("document.getElementById('unicorn').dataset.mood")) == "sad" and (await page.evaluate("document.getElementById('unicorn').dataset.fx")) == "rain", "the sad pose and the cloud stay"


async def test_rain_stops_when_the_mood_changes_and_a_new_run_starts_clean(browser):
    page = await mood_page(browser)
    await page.evaluate("u.setMood('sad')")
    assert "rain:true" in await page.evaluate("fakeFx.calls"), "a manual sad rains too"
    await page.evaluate("fakeFx.calls.length = 0; u.setMood('happy')")
    assert await page.evaluate("fakeFx.calls") == ["rain:false"]
    await page.evaluate("fakeFx.calls.length = 0; u.onRunStart({}); u.onTestResult({ status: 'fail' }); u.onTestResult({ status: 'fail' }); u.onTestResult({ status: 'pass' }); u.onTestResult({ status: 'fail' });"
                        " u.onRunComplete({ passed: 1, failed: 3, total: 4 })")
    await asyncio.sleep(0.4)
    await page.evaluate("fakeFx.calls.length = 0; u.onRunStart({})")
    await asyncio.sleep(0.1)
    await page.evaluate("u.onTestResult({ status: 'fail' }); u.onTestResult({ status: 'fail' }); u.onTestResult({ status: 'fail' }); u.onTestResult({ status: 'pass' }); u.onTestResult({ status: 'fail' })")
    assert "rain:true" in await page.evaluate("fakeFx.calls"), "the rain of a new sad run is not held back by the last run's ending"


async def test_the_preview_buttons_make_glitter_and_rain(browser):
    page = await open_preview(browser)
    await page.click("#fx-burst")
    await asyncio.sleep(0.3)
    assert (await page.evaluate("fx.stats()"))["running"]
    await page.evaluate("fx.clear()")
    await page.click("#fx-rain-toggle")
    assert await page.evaluate("fx.isRaining()")
    await page.click("#fx-rain-toggle")
    assert not await page.evaluate("fx.isRaining()")
