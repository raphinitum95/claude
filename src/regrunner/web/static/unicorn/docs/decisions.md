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

## 2026-10-08 (feedback round 1: shading and depth)

- **Shading is added inside each part's own group, as `.shade` elements** (overlay = the part's outline with a clear-to-tint gradient on the far side). Why (user): "there is absolutely no
  shading, can there not be sections to shade, so the left leg is still the left leg but within that you shade the right-hand side". It was not too difficult: the overlay reuses the
  part's own path, so silhouettes did not change and the shading moves with the part.
- **Legs cast a shadow on the torso and haunches** (the user's "box shadow" idea), built as stacked widening strokes under the leg, not an SVG filter (filters are costly when animated).
  Casts are clipped (`clip-path`) to the surface they fall on: the first unclipped try left grey halos on the background around the mane and tail.
- **Front legs got rounded shoulder tops** (they started as a flat edge, which read as a pale rectangle under the chest) and a crease line between them. The torso is a little wider at the shoulders.
- **The neck is drawn before the body; the chin shadow moved to the body.** Why: with rim shading on both, the neck's flat lower edge showed as a hard "bib".
- **Hair shading is lighter than skin shading** (about 0.3 vs 0.55 at the darkest). Why: at skin strength the pastel mane went grey.
- **Light comes from the upper left; `--shade-strength` (CSS variable on `#unicorn`) scales all shading**, so "more / less shading" is one number. Hooves got a tight dark contact shadow.
- Not done: no shading on the horn beyond its own gradient, none inside the mane locks beyond rim + side tint, and no separate "highlight" layer system; say so if you want more.

## 2026-10-08 (feedback round 2: shading too rough; soft but cheap)

- **Front legs use the torso's own fill and have no visible start.** Why (user): the leg shading was "too rough, particularly where the leg meets the chest, it makes the leg seem like a separate entity".
  Cause: a lighter leg fill, rim overlays, rounded tops and stacked cast shadows drew an outline round each leg. Now the legs are only shaded by a soft oval on the far edge and a faint ankle shade.
- **Soft ovals instead of slivers.** A first try with tapered slivers left hard diagonal edges (spikes). A radial oval that fades to nothing on all sides has no edge, and sits inside its own leg so the other leg's fill never cuts it.
- **Jaw band under the mouth removed, muzzle highlight now fades out, head rim lighter.** Why (user): "the snout is too rough, it feels like she's got a beard". The band under the mouth was the beard.
- **Stacked-stroke cast shadows removed** from legs, hooves and tail (they banded); one very faint one stays under the fringe. Torso rim overlay and the haunch crease lines removed.
- **All shade strengths roughly halved** (skin rim 0.55 to 0.30, hair rim 0.30 to 0.18, side 0.62 to 0.34, hair side 0.26 to 0.16, bottom 0.40 to 0.22). Chosen approach: "soft but cheap" (no blur filter).

## 2026-10-08 (feedback round 3: eyes like the reference, less round face, hair vs horn)

- **Eye rebuilt from the reference**: a violet RING (23 x 29, light blue glow at the bottom) with a darker PUPIL (17.5 x 22) inside it. Both sit toward the nose (ring 4.5 px, pupil 7 px), so the white of the
  eye is only a crescent on the outer side. Highlights follow the reference: big dot top, small dot below, a star lower left, a small light-blue dot on the lower outer ring. The eye white has a thin dark outline,
  the top lash line is thicker and the flicks are shorter and curved. Why (user): "the pupils on the reference are an outer and an inner circle, closer to the nose, so the white of the eye is on the outside".
- **Head is a rounded square with straighter sides** (widest at the cheeks, flatter forehead, a slightly lower chin) instead of a near circle. Why (user): "the face is less round on the reference".
- **Hair vs horn: the horn is now drawn OVER the fringe** (order is face, fringe, horn) and the strands' roots are behind it or away from it (the teal strand starts at the upper right). A soft shade sits round the
  horn base. Why (user): "the hair by the horn seems to be coming out of the horn". The horn's id order changed: `mane-front` is now drawn BEFORE `horn`.
- Pink curl moved 8 px outward so it no longer sits on the left lashes; the eyelid is a little bigger so it hides the lashes in a blink, and in the sad mood the lash flicks are hidden (the drooping lid left their tips floating).

## 2026-10-08 (detail without cost)

- **Hair strands are gradient streaks painted over the existing shapes**, not extra paths: one multi-stop gradient (`STRANDS`, 13 stops of faint white / violet) used three ways (vertical, horizontal, diagonal via `gradientTransform`).
  First try was far too strong (brushed-metal look); alphas were then cut to about a third. Why (user): "more detail only if we can find creative ways that don't cost size or performance".
- **The horn's four spiral arcs became one repeating gradient** (`spreadMethod="repeat"`, diagonal bands of darker gold then a pale sheen), which reads as a twisted rope and is one element instead of a path of four curves.
- **Measured cost of this round:** SVG 38.6 to 43.8 KB (8.0 KB gzipped), paths 107 to 119 (12 overlays), moving groups 52 to 52 (unchanged), gradients 35 to 39. A size / group guard was added to the test (under 60 KB, at most 56 groups).
- Not done (would cost geometry): iris rays, individual hair strands, fur, ear fluff.
