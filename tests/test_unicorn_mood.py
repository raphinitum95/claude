"""The unicorn's mood state machine (src/regrunner/web/static/unicorn/js/mood.js) and the one-shot reactions it asks of the idle loop (js/idle.js).

The mood is a pure function of the running totals, so the thresholds are checked as a table; the controller is checked with a fake idle object (what it
asks for, and when), and the reactions' shape with the pure engine; a few checks run in a real Chromium on the generated preview page (file://)."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

pytestmark = pytest.mark.browser

UNICORN = Path(__file__).resolve().parent.parent / "src" / "regrunner" / "web" / "static" / "unicorn"
PREVIEW = (UNICORN / "preview.html").as_uri()

FAKE_IDLE = """window.fakeIdle = { calls: [], start() { this.calls.push('start'); }, settle() { this.calls.push('settle'); },
  react(name) { this.calls.push('react:' + name); return true; } };"""
FAST = "{ startExcitedMs: 80, passSparkleMs: 80, flinchMs: 80, celebrateMs: 150, endSparkleMs: 100, restAfterMs: 100 }"


@pytest.fixture
async def page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 900, "height": 1000})
        await page.goto(PREVIEW)
        await page.evaluate("() => { unicorn.destroy(); idle.stop(); }")        # the preview's own controller stays out of the way
        await page.evaluate(FAKE_IDLE)
        yield page
        await browser.close()


async def attrs(page):
    return await page.evaluate("""() => { const r = document.getElementById('unicorn');
      return { mood: r.dataset.mood, eyes: r.dataset.eyes, brows: r.dataset.brows, mouth: r.dataset.mouth, ears: r.dataset.ears, fx: r.dataset.fx }; }""")


async def make(page, config=FAST):
    await page.evaluate(f"() => {{ window.fakeIdle.calls.length = 0; window.u = UnicornMood.create(document.querySelector('#stage svg'), {{ idle: window.fakeIdle, config: {config} }}); }}")


async def test_the_mood_follows_the_pass_rate_with_the_briefs_thresholds_and_a_minimum_before_any_verdict(page):
    cases = [  # (passed, failed, failStreak, done, expected)
        (0, 0, 0, False, "neutral"), (2, 0, 0, False, "neutral"), (0, 2, 2, False, "neutral"),          # fewer than 3 results: no verdict
        (10, 0, 0, False, "happy"), (7, 3, 0, False, "happy"), (6, 4, 0, False, "happy"), (5, 5, 0, False, "sad"),
        (7, 3, 3, False, "scared"), (0, 3, 3, False, "scared"),                                            # three failures in a row mid-run: nervous
        (19, 1, 0, True, "joyful"), (18, 2, 0, True, "happy"), (12, 8, 0, True, "happy"), (11, 9, 0, True, "sad"), (0, 0, 0, True, "neutral"),
        (95, 5, 0, True, "joyful"), (1, 0, 0, True, "joyful"),                                             # a finished run of one test is judged at once
    ]
    got = await page.evaluate("""(cases) => cases.map(([passed, failed, failStreak, done]) => UnicornMood.moodFor({ passed, failed, failStreak, done }))""", cases)
    assert got == [c[4] for c in cases], list(zip(cases, got))
    custom = await page.evaluate("""() => [UnicornMood.moodFor({ passed: 8, failed: 2, done: true }, { celebrate: 0.8 }),
                                          UnicornMood.moodFor({ passed: 8, failed: 2, done: true }), UnicornMood.moodFor({ passed: 4, failed: 6, done: true }, { happy: 0.4 })]""")
    assert custom == ["joyful", "happy", "happy"], "the thresholds are configurable"


async def test_the_pose_table_in_the_code_equals_the_spec_and_uses_only_values_the_svg_knows(page):
    poses = await page.evaluate("UnicornMood.POSES")
    spec = (UNICORN / "docs" / "rig-spec.md").read_text(encoding="utf-8").splitlines()
    rows = {}
    for line in spec:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and (cells[0].startswith("`") or cells[0].startswith("(neutral")) and re.fullmatch(r"`[a-z]+`", cells[1] or ""):
            name = "neutral" if cells[0].startswith("(neutral") else cells[0].strip("`")
            rows[name] = dict(zip(["eyes", "brows", "mouth", "ears", "fx"], [re.match(r"`([a-z]+)`", c).group(1) for c in cells[1:6]]))
    assert rows == poses, "docs/rig-spec.md section 4 and UnicornMood.POSES must be the same table"
    svg = (UNICORN / "svg" / "unicorn-front-sitting.svg").read_text(encoding="utf-8")
    known = {(k, v) for k, v in re.findall(r'data-(\w+)="([\w-]+)"', svg)}
    for mood, pose in poses.items():
        for key, value in pose.items():
            assert (key, value) in known, f"{mood}: the SVG has no data-{key}={value}"


async def test_a_run_walks_the_unicorn_through_excited_neutral_happy_scared_and_sad_and_then_she_settles(page):
    await make(page)
    assert (await attrs(page))["mood"] == "neutral"
    await page.evaluate("u.onRunStart({ totalTests: 20 })")
    assert (await attrs(page))["mood"] == "excited" and (await attrs(page))["eyes"] == "wide"
    await asyncio.sleep(0.15)
    assert (await attrs(page))["mood"] == "neutral", "the start excitement is brief"
    await page.evaluate("u.onTestResult({ status: 'pass' })")
    assert (await attrs(page))["fx"] == "sparkle", "a pass gives a small sparkle ..."
    await asyncio.sleep(0.15)
    assert (await attrs(page))["fx"] == "none", "... that goes away by itself"
    await page.evaluate("u.onTestResult({ status: 'pass' }); u.onTestResult({ status: 'pass' })")
    assert (await attrs(page))["mood"] == "happy"
    await page.evaluate("u.onTestResult({ status: 'fail' })")
    assert (await attrs(page))["ears"] == "back", "a fail flinches: ears go back for a moment"
    await asyncio.sleep(0.15)
    assert (await attrs(page))["ears"] == "neutral"
    await page.evaluate("u.onTestResult({ status: 'fail' }); u.onTestResult({ status: 'fail' })")
    assert (await attrs(page))["mood"] == "scared" and (await attrs(page))["fx"] == "sweat", "three failures in a row: nervous"
    await page.evaluate("u.onTestResult({ status: 'pass' })")                      # 4 pass / 3 fail = 57 %: the streak is broken but the rate is low
    assert (await attrs(page))["mood"] == "sad"
    calls = await page.evaluate("window.fakeIdle.calls")
    assert calls.count("react:flinch") == 3 and calls.count("react:maneFlick") == 4 and calls[0] == "start"
    assert "settle" not in calls, "she keeps idling while the run goes on"
    assert await page.evaluate("u.onRunComplete({ passed: 4, failed: 3, total: 7 })") == "sad"
    await asyncio.sleep(0.25)
    assert (await page.evaluate("window.fakeIdle.calls"))[-1] == "settle", "after a sad ending she settles to rest and the loop stops"
    assert (await attrs(page))["mood"] == "sad", "the sad pose stays"


async def test_a_great_run_ends_in_a_celebration_and_a_decent_one_in_a_small_sparkle_and_both_settle(page):
    await make(page)
    await page.evaluate("u.onRunStart({}); for (let i = 0; i < 19; i += 1) u.onTestResult({ status: 'pass' }); u.onTestResult({ status: 'fail' })")
    await asyncio.sleep(0.2)                                                       # let the start excitement and flashes end
    await page.evaluate("window.fakeIdle.calls.length = 0")
    assert await page.evaluate("u.onRunComplete({ passed: 19, failed: 1, total: 20 })") == "joyful"
    now = await attrs(page)
    assert now["eyes"] == "closed" and now["fx"] == "sparkle"
    assert (await page.evaluate("window.fakeIdle.calls")) == ["start", "react:hop"], "the celebration wakes her and hops"
    await asyncio.sleep(0.3)
    assert (await page.evaluate("window.fakeIdle.calls"))[-1] == "settle"

    await page.evaluate("window.fakeIdle.calls.length = 0")
    assert await page.evaluate("u.onRunComplete({ passed: 9, failed: 1, total: 10 })") == "happy"
    assert (await attrs(page))["fx"] == "sparkle"
    await asyncio.sleep(0.3)
    assert (await page.evaluate("window.fakeIdle.calls")) == ["react:maneFlick", "settle"]
    assert (await attrs(page))["fx"] == "none"


async def test_a_manual_mood_overrides_the_results_until_it_is_cleared_and_a_new_run_clears_it(page):
    await make(page)
    await page.evaluate("u.onRunStart({}); u.setMood('angry')")
    await asyncio.sleep(0.15)
    assert (await attrs(page))["mood"] == "angry" and (await attrs(page))["fx"] == "steam"
    await page.evaluate("for (let i = 0; i < 5; i += 1) u.onTestResult({ status: 'pass' })")
    assert (await attrs(page))["mood"] == "angry", "results do not change a manual mood"
    await page.evaluate("u.setMood(null)")
    await asyncio.sleep(0.1)
    assert (await attrs(page))["mood"] == "happy", "back to automatic"
    await page.evaluate("u.setMood('sad'); u.onRunStart({})")
    assert (await attrs(page))["mood"] == "excited", "a new run clears the override"
    assert await page.evaluate("[(() => { try { u.setMood('hungry'); } catch (e) { return e.message; } })(), (() => { try { u.onTestResult({ status: 'maybe' }); } catch (e) { return e.name; } })()]") \
        == ["unknown mood: hungry", "TypeError"]


async def test_a_new_run_starts_from_zero_and_a_result_after_the_end_opens_a_new_run(page):
    await make(page)
    await page.evaluate("u.onRunStart({}); u.onTestResult({ status: 'fail' }); u.onRunComplete({ passed: 0, failed: 1, total: 1 })")
    assert (await page.evaluate("u.getTotals()"))["done"]
    await page.evaluate("u.onTestResult({ status: 'pass' })")
    totals = await page.evaluate("u.getTotals()")
    assert totals["passed"] == 1 and totals["failed"] == 0 and totals["running"] and not totals["done"], "a stray result after the end starts a fresh run"
    await page.evaluate("u.onRunStart({ totalTests: 5 })")
    assert (await page.evaluate("u.getTotals()")) == {"passed": 0, "failed": 0, "failStreak": 0, "total": 5, "running": True, "done": False}


async def test_each_reaction_is_a_short_one_shot_that_returns_to_nothing_and_none_start_while_settling(page):
    result = await page.evaluate("""() => {
      const seeded = (seed) => () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
      const react = (name) => {                    // the same seed twice: the difference between the two engines is exactly the reaction
        const withIt = UnicornIdle.createEngine({ random: seeded(5) }), without = UnicornIdle.createEngine({ random: seeded(5) });
        withIt.step(33); without.step(33);
        const started = withIt.trigger(name);
        let headTy = 0, hop = 0, lock = 0, end = 0;
        for (let t = 0; t < 2000; t += 33) {
          const a = withIt.step(33), b = without.step(33);
          const dHead = Math.abs(a.head.ty - b.head.ty), dLock = Math.max(...a.locks.map((x, i) => Math.abs(x - b.locks[i])));
          headTy = Math.max(headTy, dHead); hop = Math.max(hop, a.hop); lock = Math.max(lock, dLock);
          if (Math.max(dHead, Math.abs(a.head.rot - b.head.rot), a.hop, dLock) > 0.01) end = t;
        }
        return { started, headTy, hop, lock, end, atRest: withIt.atRest() };
      };
      const settling = UnicornIdle.createEngine(); settling.settle(100);
      return { hop: react('hop'), flinch: react('flinch'), flick: react('maneFlick'), whileSettling: settling.trigger('hop'), unknown: UnicornIdle.createEngine().trigger('moonwalk') };
    }""")
    assert result["hop"]["started"] and 12 <= result["hop"]["hop"] <= 14.1, "a celebration hop is a small bounce, about 14 px at most"
    assert 2.5 <= result["flinch"]["headTy"] <= 3.3, "a flinch drops the head about 3 px"
    assert 3 <= result["flick"]["lock"] <= 8, "a mane flick adds a few degrees to the locks"
    assert result["hop"]["end"] <= 900 and result["flinch"]["end"] <= 420 and result["flick"]["end"] <= 850, "every reaction is over quickly"
    assert result["whileSettling"] is False and result["unknown"] is False, "no reaction while settling; an unknown name is ignored"


async def test_a_hop_lifts_the_whole_figure_except_her_shadow_and_then_she_stands_again(page):
    await page.evaluate("() => idle.start()")
    await asyncio.sleep(0.2)
    assert await page.evaluate("idle.react('hop')")
    lifted = []
    for _ in range(30):
        await asyncio.sleep(0.03)
        lifted.append(await page.evaluate("""() => { const ty = (id) => { const m = /translateY\\((-?[\\d.]+)px\\)/.exec(document.getElementById(id).style.transform); return m ? parseFloat(m[1]) : 0; };
          return { body: ty('body'), tail: ty('tail'), legs: ty('front-leg-left'), head: ty('head-rig'), shadow: document.getElementById('shadow').style.transform }; }"""))
    assert min(x["body"] for x in lifted) < -5, "the body leaves the ground"
    assert all(x["shadow"] == "" for x in lifted), "her shadow stays on the ground"
    top = min(lifted, key=lambda x: x["body"])
    assert top["tail"] < -5 and top["legs"] < -5 and top["head"] < -5, "everything but the shadow goes up together"
    await asyncio.sleep(1.0)
    assert abs(await page.evaluate("(() => { const m = /translateY\\((-?[\\d.]+)px\\)/.exec(document.getElementById('body').style.transform); return m ? parseFloat(m[1]) : 0; })()")) < 0.1


async def test_the_preview_buttons_drive_a_run_and_a_manual_mood(page):
    await page.reload()
    await page.click("#run-start")
    assert (await attrs(page))["mood"] == "excited"
    await asyncio.sleep(1.7)
    for _ in range(3):
        await page.click("#run-pass")
    assert (await attrs(page))["mood"] == "happy"
    assert "3 pass / 0 fail" in await page.inner_text("#totals-now")
    await page.click("#moods button[data-mood=angry]")
    assert (await attrs(page))["mood"] == "angry" and "(manual)" in await page.inner_text("#mood-now")
    await page.click("#moods button[data-mood=auto]")
    assert (await attrs(page))["mood"] == "happy"
