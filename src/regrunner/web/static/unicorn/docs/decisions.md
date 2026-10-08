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
