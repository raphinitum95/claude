# Decisions log (newest at the bottom; one line of WHAT, one of WHY)

## 2026-10-08

- **Location: `src/regrunner/web/static/unicorn/`.** Why: the user wants everything inside `/src`; the QA app is FastAPI + a vanilla-JS
  single page app served from `web/static/` with no build step, so a plain folder of SVG/JS/CSS is served as-is at `/static/unicorn/`
  and passes the UI's CSP (`script-src 'self'`). No server code changes, no UI restart needed for this folder.
- **Dev docs live inside `unicorn/` (not in `dev/`).** Why: the user asked for everything inside `src/`, which overrides the repo's usual
  "notes go in dev/" habit. Cost: `dev/make_share_folder.py` copies all of `src/`, so the reference images (about 450 KB) and these docs
  ship in the shared folder too. Easy to exclude later if wanted.
- **`preview.html` is generated** by `tools/build_preview.py` (the SVG inlined next to mood buttons). Why: JS can only toggle the rig's
  `data-*` states if the SVG is inline, and `<object>` access is blocked on `file://`. The SVG stays the single source of truth.
- **Mirrored parts (ears, side locks, hind leg) are drawn as two explicit shapes, not a `transform` on the group.** Why: a CSS `transform`
  (what Phase 2 animates) replaces the SVG `transform` attribute, so a mirrored group would un-mirror itself when animated.
- **Reference images saved as `reference/01..04-*.webp`** (01 = MASTER, 02 turnaround, 03 emotion sheet, 04 views). Palette sampled from 01
  (see CLAUDE.md); values not present in the master as flat colours are marked "derived".
- **Rig built in one SVG, 600 x 600, axis x = 270.** Why: the master's figure plus tail is wider than tall; centring the axis at 270 keeps the whole
  bounding box (x 100 to 515) centred in the canvas. Draw order and ids: `rig-spec.md`.
- **States are `data-*` attributes on `#unicorn` plus CSS inside the SVG** (eyes, brows, mouth, ears, fx), pivots as CSS `transform-origin`. Why: the brief wants
  eye/brow states swappable by class or attribute and a documented pivot table; Phase 2 then only sets attributes and animates transforms. No JS in the SVG.
- **Eyelids are separate skin-coloured groups at `scaleY(0)`** (blink = scale to 1). Why: a blink and a sad/angry droop are then the same mechanism, and the lid
  shares the head's user-space gradient so it matches the face exactly. The lid is wider than the eye so it also hides the outer lashes when shut.
- **`head-rig` wrapper group** around locks, ears, head, face, horn and fringe. Why: one id to nod / turn the whole head; the brief's per-part ids all still exist inside it.
- **Hind legs and hind hooves live inside `body`; front hooves are nested in their legs.** Why: the brief lists only front hooves and `body`; nesting keeps legs and hooves moving together.
- **Chest heart is drawn after the legs.** Why: the legs' top edge overlapped the heart in the first render and cut it in half.
- **Chin shadow lives inside `neck`** (not `body`). Why: in `body` its ends stuck out past the neck as lilac tabs.
- **Hand-simplified mane: 6 locks (3 per side) + a 3-strand fringe + a small `mane-back`.** Why: the brief asks for 4 to 6 large locks that sway independently,
  not every curl. Left side is pink / lilac-teal / pink, right side teal / lilac-pink / lilac, matching where each hue sits in the master.
- **Rain cloud art is not drawn yet** (the `sad` mood lists it as a Phase 2 effect). `fx-sparkle`, `fx-sweat`, `fx-steam` are simple placeholders so every mood reads in the preview.
- **`tests/test_unicorn_rig.py`** (fast): every required id exists once, no scripts / animation / filters / transform attributes, every pivot is in the CSS, defaults are
  neutral mouth + open eyes, `preview.html` is not stale and rig-spec's mood rows match `MOODS`.
- **Known differences from the master, left for art direction:** flatter shading than the painted master; the mane is simplified (no fine curls); the tail ends in a hook, not the
  master's curl; the body column is a little straighter. Measured against the master: head width / figure height is 0.39 (master) vs 0.41 (rig), so the head is the same size;
  eye width / head width is 0.27 vs 0.25, so the eyes are about 7 % smaller.

## 2026-10-08 (feedback round 1: eyes)

- **Eyes: the white of the eye is always visible and the iris is smaller** (iris 45 x 51 inside an eye of 61 x 67, about 75 %; was 57 x 64, which filled the whole eye and read as alien).
  Highlights, glow and the sparkle star were scaled to the new iris. Why (user): "the pupil is too big, it makes it look more alien than cute; there should be some white of the eye".
  `.sclera` is no longer a `scared`-only part; `scared` now just shrinks the iris to 78 % again. The sclera has a soft lilac top shade (lid shadow).
- **Eye white gets a thin soft-lilac rim (1.6 px) and a deeper lid shadow at its top.** Why: pure white on the near-white face did not read at all in the first try.
