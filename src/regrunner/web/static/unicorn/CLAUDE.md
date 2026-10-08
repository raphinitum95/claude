# CLAUDE.md: the unicorn scorekeeper (read this before touching anything in `unicorn/`)

An animated baby-unicorn mascot that lives inside the QA Regression web UI. When a run starts she animates in, sets up a PASS
board and a FAIL board and keeps score live. Between results she idles. Pure HTML / CSS / SVG / vanilla JS, no framework, no build step.

Where it lives: `src/regrunner/web/static/unicorn/` (served at `/static/unicorn/...`; the UI's CSP allows same-origin scripts and `data:` images).
Everything for this feature stays inside `src/` (the user's rule). It is a decoupled widget: it knows nothing about the runner except
the four calls in "Event interface" below.

```
unicorn/
  CLAUDE.md          this file: style rules, palette, proportions, working rules
  docs/rig-spec.md   part ids, pivots, mood states, event interface (the contract for Phase 2 code)
  docs/decisions.md  running log of every design decision and change (date + reason)
  reference/         the user's concept images (01 = MASTER); loose guides only, the master wins
  svg/               unicorn-front-sitting.svg (the rig); later poses
  tools/build_preview.py   regenerates preview.html (the SVG inlined + mood buttons) from svg/
  preview.html       GENERATED, open it in a browser (file:// works). Never edit by hand.
```

## Working rules (from the user's brief; they override your habits)

1. **One thing per round.** Never mix look changes, rigging and animation in one step. After the art is approved, the style is LOCKED:
   only specific requested fixes ("eyes 20% bigger").
2. Log every decision and change in `docs/decisions.md` (date, what, why). Keep `docs/rig-spec.md` true when an id or pivot changes.
3. After each step give the user a way to preview (open the SVG or `preview.html`) and commit (one commit per meaningful step).
4. Ambiguous? Ask ONE concise question instead of guessing.
5. Not built unless asked: 3D, extra poses (3/4, standing, walking), the 20-emotion set. Only 6 moods for now.
6. Phase 1 = layered SVG rig only (no scripts, no animation inside the SVG). Phase 2 (animation + logic) starts only after the user approves the art.
7. GSAP or any library: ask first. Default is none.

## Character (locked once approved)

Original character; do NOT imitate any existing franchise character. Cute chibi baby unicorn: white/lilac body, big round dark-violet eyes
with white sparkle highlights and lashes, small smile, pink blush, small pink heart on the chest, pink / lilac / teal flowing mane and tail,
golden spiral horn with soft glow and tiny sparkles, pink inner ears, lilac hooves.

Style: flat vector with soft gradient shading (radial / linear gradients, a horn highlight, a soft contact shadow). No heavy outlines
(2 px max, and only on lashes / mouth / brows). The mane is simplified to 6 big layered locks that sway independently.

Proportions (viewBox 600 x 600, axis of symmetry x = 270): head about 220 wide x 208 tall (the head is more than half the figure's height:
chibi), eyes 57 x 64 each at x = 270 +/- 64, y = 262; muzzle at y = 295, mouth at y = 320; horn tip y = 28; hooves bottom y = 573; tail reaches x = 505.

## Palette (sampled from the MASTER image with a median-cut over each region; "d" = derived by hand, not sampled)

| Token | Hex | Used for |
|---|---|---|
| body-white | `#FEF9F7` | body, head highlights |
| body-base | `#FCF5F5` | body, head mid |
| body-shade | `#F1E4EF` | body shading (lilac cast) |
| body-deep | `#C4AACD` | contact shade only, small areas |
| pink-hi / pink / pink-deep | `#FDB1D3` / `#F597C9` / `#DB8BBD` | mane + tail pink |
| lilac-hi (d) / lilac / lilac-deep | `#D9B4EE` / `#CB9AE5` / `#9F76BC` | mane + tail lilac |
| teal-hi / teal / teal-deep | `#B1EBE1` / `#86D4D5` / `#69C0CE` | mane + tail teal |
| horn-hi / horn / horn-mid / horn-deep | `#FCEFC3` / `#FCE09E` / `#F4C77B` / `#DB9E67` | horn |
| hoof-hi / hoof / hoof-deep | `#D7C3E1` / `#BCA0CF` / `#A185B8` | hooves |
| ear-inner / ear-inner-deep | `#F4BED0` / `#EE9FBF` | inner ears |
| blush | `#FEC9DB` | cheeks (use at 60-80 % opacity) |
| heart / heart-deep (d) | `#F8CDE4` / `#F2B0D0` | chest heart |
| eye-dark / eye-iris / eye-glow | `#1A141F` / `#4A365F` / `#8A79D1` | eyes (dark violet with a blue-lilac glow low in the iris) |
| line (d) | `#B07A9C` | mouth, nostrils, brows (brows `#B79AD0`) |
| reference background | `#CDCDCD` | NOT part of the art |

## Rules for the SVG rig

- Every movable part is its own `<g id="...">` (ids in `docs/rig-spec.md`). Never rename an id without updating the spec and Phase 2 code.
- CSS `transform` overrides an SVG `transform` attribute: animated groups carry NO transform attribute; mirrored art goes on an inner `<g>`.
- Pivots are set with CSS `transform-origin` in user units (viewBox space) inside the SVG's `<style>`; the table is in the spec.
- Hidden overlap art under every joint so rotating a part never shows a gap.
- Eye / brow / mouth / ear / effect states are `data-*` attributes on `#unicorn`; CSS in the SVG does the show/hide. No JS in the SVG.
- Keep it light: gradients and plain shapes only. No SVG filters or masks inside the rig (they are costly when animated). `clipPath` is allowed only to keep a static cast shadow on the surface it falls on.
- Shading: every shade overlay / cast shadow has class `shade` and sits inside its own part's group; light is from the upper left; `--shade-strength` scales it all (see rig-spec section 2b).
- Detail budget: add detail with gradients on shapes that already exist (strand streaks `gStrandV/H/D`, the horn twist `gHornTwist` = one repeating gradient), never with extra geometry or extra moving groups. Size guard: under 60 KB, at most 56 groups (`tests/test_unicorn_rig.py`).
- Eyes: the white of the eye stays visible; the iris is about 75 % of the eye (a full-eye iris looked alien).

## Performance rules for Phase 2 (the QA app runs several test workers on the same machine)

SVG / CSS transforms only; canvas only for particles; cap particles; about 30 fps where possible; pause idle loops when the tab is hidden;
stop every loop when the run ends and she is at rest; respect `prefers-reduced-motion`; no heavy libraries.

## Event interface (decoupled from the QA app)

```
unicorn.onRunStart({ totalTests? })
unicorn.onTestResult({ status: 'pass' | 'fail', name?: string })
unicorn.onRunComplete({ passed, failed, total })
unicorn.setMood(mood)   // manual override
```

Mood is a pure function of running totals; thresholds are configurable (defaults and details in `docs/rig-spec.md`).

## Preview

`python3 src/regrunner/web/static/unicorn/tools/build_preview.py` rewrites `preview.html`; open it in a browser. The app's own server also
serves it at `/static/unicorn/preview.html`. Python 3.9 compatible.
