// Test editor: block map, step cards / Excel grid, inspector, data drawer, problems panel, add-step menu.
import { html, raw, cx } from '../../util.js';
import { icon } from '../../icons.js';
import { runFileUrl } from '../../api.js';
import { buildRail } from './rail.js';
import {
  bm, currentTest, selectedStep, buildUrl, effectiveBuildingWith, loadGrid, rememberedBulkPos,
} from './actions.js';
import { sessionBar, sessionMark, pickPanel, sessionOpen } from './session.js';
import { apiEditor } from './api_editor.js';

const enc = encodeURIComponent;

const KIND_BADGE = { nav: 'Go', act: 'Click', input: 'Type', check: 'Check', save: 'Save', wait: 'Wait', call: 'Call', flow: 'Flow', legacy: 'Legacy', other: 'Step', empty: '' };
const BLOCK_KIND_LABEL = { page: 'Page', window: 'Window', call: 'Call', loop: 'Repeat' };

function tokenParts(text) {
  if (!text) return [];
  const out = [];
  let last = 0;
  const re = /\{(SECRET:)?([A-Za-z_][A-Za-z0-9_]*)\}/g;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ t: text.slice(last, m.index), v: false });
    out.push({ t: m[2], v: true, secret: !!m[1] });
    last = re.lastIndex;
  }
  if (last < text.length) out.push({ t: text.slice(last), v: false });
  return out;
}
const tokenHtml = (text) => tokenParts(text).map((p) => (p.v ? html`<span class="var${p.secret ? ' secret' : ''}">${p.secret ? '•••• ' : ''}${p.t}</span>` : html`${p.t}`));

// ---- a step's last-run outcome: a passive card badge, plus evidence in the inspector -----------------------------
function lastRunMark(r) {
  if (!r) return '';
  if (r.status !== 'FAILED') return html`<span class="pdot" style="background: var(--pass)" title="PASSED on the last run"></span>`;
  return html`<span class="tag" style="color: var(--fail); border-color: var(--fail)" title="${r.error || 'Failed'} (run ${r.runId})">${icon('warn', 10)} failed last run</span>`;
}

function lastRunCard(t, s) {
  const r = s.lastResult;
  if (!r || r.status !== 'FAILED') return '';
  return html`<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; box-shadow: none; border-color: var(--fail-line)">
<div style="display: flex; align-items: center; gap: 8px">${lastRunMark(r)}<span class="mono" style="font-size: 11px; color: var(--tx3)">${r.when || r.runId}</span><span style="flex: 1"></span>
<a class="lnk" style="font-size: 12px" href="#/results/test/${enc(r.runId)}/${enc(t.id)}">Open that run</a></div>
${r.error ? html`<span style="font-size: 12.5px; color: var(--tx2); overflow-wrap: anywhere">${r.error}</span>` : ''}
${r.screenshot ? html`<div class="shot zoom" style="max-width: 260px" data-act="zoom" data-src="${runFileUrl(r.runId, r.screenshot)}" role="button" tabindex="0" aria-label="Enlarge the screenshot from the failed run">
<img src="${runFileUrl(r.runId, r.screenshot)}" alt="Screenshot from the failed run" loading="lazy" decoding="async"></div>` : ''}
${r.locatorMiss ? html`<span style="font-size: 11.5px; color: var(--tx3)">Looks like the element could not be found. Pick it again below, or open the site and Run up to here to see it live.</span>` : ''}
</div>`;
}

// ---- sub-header: kind, needs/provides, cards/grid toggle -----------------------------------------------------
function subHeader(S, t) {
  const needs = t.needs || [];
  const provides = t.provides || [];
  const ed = S.build.ed;
  return html`<div style="flex: none; display: flex; align-items: center; gap: 10px; padding: 6px 16px; min-height: 48px; flex-wrap: wrap; border-bottom: 1px solid var(--line); background: var(--rail)">
<span class="chip" style="height: 26px">${icon(t.kind === 'web' ? 'grid' : t.kind, 13)} ${t.kind === 'web' ? 'Website' : t.kind.toUpperCase()} test</span>
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">${t.steps.length} steps · ${t.blocks.length} blocks</span>
<span style="width: 1px; height: 20px; background: var(--line)"></span>
<span class="chip" title="${needs.length ? needs.join(', ') : 'Nothing'}">${icon('arrowr', 12)} Needs ${needs.length}</span>
<span class="chip" title="${provides.length ? provides.join(', ') : 'Nothing'}">${icon('arrowl', 12)} Provides ${provides.length}</span>
<span style="flex: 1"></span>
<span style="font-size: 12px; color: var(--tx3)">Building with</span>
<span class="chip chip-acc">${icon('table', 12)} Row ${effectiveBuildingWith(t) || '–'}</span>
<div class="seg" role="group" aria-label="View" style="width: 190px">
<button class="${cx(ed.mode === 'cards' && 'on')}" data-act="build-mode-cards" aria-pressed="${String(ed.mode === 'cards')}">${icon('list', 13)} Cards</button>
<button class="${cx(ed.mode === 'grid' && 'on')}" data-act="build-mode-grid" aria-pressed="${String(ed.mode === 'grid')}">${icon('grid', 13)} Grid</button></div>
</div>`;
}

// ---- block strip -----------------------------------------------------------------------------------------------
function blockStrip(S, t) {
  const ed = S.build.ed;
  return html`<div style="flex: none; padding: 10px 16px 0">
<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px"><span class="lbl">Test map</span>
<span style="font-size: 11.5px; color: var(--tx3)">${t.blocks.length} blocks</span></div>
<div class="scroll" style="display: flex; gap: 6px; overflow-x: auto; padding-bottom: 10px">
${t.blocks.map((b, i) => html`<button data-key="blk-${b.id}" data-act="build-pick-block" data-i="${i}" data-block-title="${b.title}" style="flex: none; min-width: 128px; padding: 7px 10px; border-radius: 10px; border: 1px solid ${i === ed.block ? 'var(--acc)' : 'var(--line2)'}; background: ${i === ed.block ? 'var(--sel-bg, var(--acc-soft))' : 'var(--surface)'}; display: flex; flex-direction: column; gap: 4px; text-align: left">
<span style="display: flex; align-items: center; gap: 5px"><span class="badge k-${b.kind === 'page' ? 'nav' : b.kind === 'call' ? 'api' : b.kind === 'loop' ? 'flow' : 'wait'}" style="height: 16px; font-size: 9px; padding: 0 5px">${BLOCK_KIND_LABEL[b.kind] || b.kind}</span>
${b.gate ? html`<span style="color: var(--pass); display: inline-flex" title="Page gate: ${b.gate}">${icon('gate', 11)}</span>` : ''}
<span class="mono" style="font-size: 10px; color: var(--tx3); margin-left: auto">${b.count}</span>
${b.dot ? html`<span class="pdot" style="background: var(--${b.dot})"></span>` : ''}</span>
<span class="trunc" style="font-size: 12.5px; font-weight: 600">${b.title}</span></button>`)}
<button class="btn btn-ghost" style="flex: none; align-self: stretch; border: 1px dashed var(--line2); padding: 0 12px" data-act="build-new-page" title="A new page at the end of the test: the next step you add starts it">${icon('plus', 13)} New page</button>
</div></div>`;
}

// ---- block header + gate chip ------------------------------------------------------------------------------------
function blockHeader(S, t, b, idx) {
  return html`<div style="flex: none; display: flex; align-items: center; gap: 10px; padding: 4px 16px 8px">
<button class="icon-btn" data-act="build-prev-block" aria-label="Previous block" ${idx === 0 ? raw('disabled') : ''}>${icon('chevl', 14)}</button>
<div style="display: flex; flex-direction: column; gap: 2px; min-width: 0">
<div style="display: flex; align-items: center; gap: 8px"><span class="badge k-nav">${BLOCK_KIND_LABEL[b.kind] || b.kind}</span>
<span class="disp trunc" style="font-size: 18px; font-weight: 700">${b.title}</span>
<button class="btn btn-ghost btn-sm" style="padding: 0 5px" data-act="build-rename-block" aria-label="Rename block">${icon('pencil', 12)}</button></div>
<span style="font-size: 12px; color: var(--tx3)">Block ${idx + 1} of ${t.blocks.length} · steps ${b.start}–${b.end}</span></div>
<button class="icon-btn" data-act="build-next-block" aria-label="Next block" ${idx === t.blocks.length - 1 ? raw('disabled') : ''}>${icon('chevr', 14)}</button>
<span style="flex: 1"></span>
<button class="btn" data-act="build-toggle-menu">${icon('plus', 13)} Add step ${icon('chevron', 12)}</button></div>
${b.gate ? html`<div style="padding: 0 16px 8px"><div style="display: flex; align-items: center; gap: 10px; padding: 7px 12px; border-radius: 10px; border: 1px solid var(--pass-line); background: var(--pass-soft); font-size: 12.5px">
<span style="color: var(--pass); display: inline-flex">${icon('gate', 15)}</span><b>Arrived at: ${b.gate}</b><span class="tag tag-fail" title="A failed gate always stops the test">hard stop</span></div></div>` : ''}`;
}

// ---- step cards ----------------------------------------------------------------------------------------------
function stepCard(S, t, s) {
  const ed = S.build.ed;
  const sel = ed.sel === s.row;
  const mm = ed.multi.includes(s.row);
  const border = sel ? 'border-color: var(--acc); box-shadow: 0 0 0 1px var(--acc-line)' : mm ? 'border-color: var(--acc-line)' : '';
  return html`<div class="scard" data-key="s-${s.row}" data-row="${s.row}" draggable="true" style="${border}${s.enabled === false ? '; opacity: .6' : ''}${s.legacy ? '; border-style: dashed' : ''}">
<span class="sgrip" aria-hidden="true" title="Drag to move (onto a page above to move it there)">⠿</span>
<input type="checkbox" class="cb" ${mm ? raw('checked') : ''} data-act="build-toggle-multi" data-row="${s.row}" aria-label="Select step ${s.n}">
<button data-act="build-pick-step" data-row="${s.row}" style="flex: 1; min-width: 0; display: flex; align-items: center; gap: 9px; min-height: 30px">
<span class="mono" style="width: 26px; flex: none; font-size: 11px; color: var(--tx3); text-align: right">${s.n}</span>
<span class="badge k-${s.kind}" style="width: 52px; flex: none">${KIND_BADGE[s.kind] || s.method}</span>
<span class="trunc" style="font-weight: 600; text-align: left; ${s.enabled === false ? 'text-decoration: line-through' : ''}">${tokenHtml(s.nameAuto ? s.autoName : s.name)}</span>
${s.context ? html`<span class="tag">${icon('frame', 10)} ${s.context}</span>` : ''}
<span style="flex: 1"></span>
${sessionMark(s.row)}
${s.sideEffects ? html`<span class="tag tag-warn">${icon('bolt', 10)} side effects</span>` : ''}
${s.legacy ? html`<span class="tag">${icon('lock', 10)} legacy</span>` : ''}
${(s.problems || []).length ? html`<span class="pdot" style="background: var(--${s.problems.includes('error') ? 'fail' : 'warn'})" title="Problem on this step"></span>` : ''}
${lastRunMark(s.lastResult)}
</button></div>`;
}

function cardsView(S, t, b) {
  const steps = t.steps.filter((s) => s.n >= b.start && s.n <= b.end);
  const anchor = bulkAnchorRow(S, steps);
  return html`<div class="scroll" style="flex: 1; overflow: auto; padding: 0 16px 16px">
<div class="scards" style="display: flex; flex-direction: column; gap: 5px">
${steps.map((s) => html`${stepCard(S, t, s)}${s.row === anchor ? bulkAnchor(S) : ''}`)}
<button class="btn btn-ghost" style="justify-content: center; border: 1px dashed var(--line2); height: 34px; margin-top: 2px" data-act="build-add-here" data-row="${steps.length ? steps[steps.length - 1].row : ''}">${icon('plus', 13)} Add step here</button>
</div>
${b.returnsTo ? html`<div style="margin-top: 12px; display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 10px; border: 1px dashed var(--line2); font-size: 12.5px; color: var(--tx2)">${icon('arrowl', 13)} Then carries on at <b style="color: var(--tx)">${b.returnsTo}</b></div>` : ''}
</div>`;
}

// ---- Excel grid view -----------------------------------------------------------------------------------------
// The test's sheet as it is in Excel: a real table (row numbers = Excel rows, header row stuck to the top), the selected step's row marked,
// long cells cut short with the whole text on hover. Read-only: edits go through the cards and the inspector. Reloads after an edit.
function gridView(S, t) {
  const ed = S.build.ed;
  if (ed.grid === 'loading' || !ed.grid) return html`<div style="flex: 1; display: flex; align-items: center; justify-content: center; color: var(--tx3)">Loading the sheet…</div>`;
  const g = ed.grid;
  const m = bm();
  if (m && g.version !== m.version) setTimeout(loadGrid, 0);                    // (an edit since it was read: read it again, show this meanwhile)
  const text = (c) => (c == null ? '' : String(c));
  return html`<div class="scroll gwrap">
<table class="mono gtable">
<thead><tr><th class="gnum">1</th>${g.headers.map((h) => html`<th title="${text(h)}">${text(h)}</th>`)}</tr></thead>
<tbody>${g.rows.map((row, i) => html`<tr data-key="grow-${i}" class="${cx(ed.sel === i + 2 && 'on')}"><td class="gnum">${i + 2}</td>
${g.headers.map((_h, j) => html`<td title="${text(row[j])}">${text(row[j])}</td>`)}</tr>`)}</tbody>
</table></div>`;
}

// ---- bulk bar + add-step menu ---------------------------------------------------------------------------------
// The "selected" bar: right under the lowest ticked step card of this page, in the list itself (it pushes the cards below it down, so it never
// covers one you may want to tick next), or where the person dragged it (kept for the browser session; "put it back" returns it here).
// Only the paste bar stays at the bottom of the column.
function bulkAnchorRow(S, steps) {
  const ed = S.build.ed;
  if (!ed.multi.length || rememberedBulkPos()) return null;
  const ticked = steps.filter((s) => ed.multi.includes(s.row));
  return ticked.length ? ticked[ticked.length - 1].row : null;
}

function bulkAnchor(S) {
  return html`<div class="bulk-anchor" data-key="bulk-anchor">${bulkBarBody(S, '')}</div>`;
}

function bulkBarBody(S, style) {
  const ed = S.build.ed;
  const moved = !!rememberedBulkPos();
  return html`<div class="bulk-bar ${moved ? 'moved' : ''}" style="${style}" role="toolbar" aria-label="Selected steps">
<span class="bulk-grip" data-bulk-grip="1" title="Drag to move this bar${moved ? ' (double-click: back next to the selection)' : ''}" aria-hidden="true">⠿</span>
<b class="bulk-count">${ed.multi.length} selected</b><span class="bulk-sep"></span>
<button class="btn btn-sm btn-ghost" data-act="build-bulk-enable">On</button><button class="btn btn-sm btn-ghost" data-act="build-bulk-disable">Off</button>
<button class="btn btn-sm btn-ghost" data-act="build-bulk-stop">Stop on fail</button><button class="btn btn-sm btn-ghost" data-act="build-bulk-continue">Keep going</button>
<button class="btn btn-sm btn-ghost" data-act="build-move-block">Move to block…</button>
<button class="btn btn-sm btn-ghost" data-act="build-copy-steps">${icon('copy', 13)} Copy</button>
<button class="btn btn-sm btn-ghost" data-act="build-save-template">${icon('layers', 13)} Save as template</button>
<button class="btn btn-sm btn-ghost" style="color: var(--fail)" data-act="build-delete-selected">${icon('trash', 13)} Delete</button>
${moved ? html`<button class="icon-btn" style="width: 26px; height: 26px" data-act="build-bulk-home" aria-label="Put the bar back next to the selection" title="Put it back next to the selection">${icon('undo', 12)}</button>` : ''}
<button class="icon-btn" style="width: 26px; height: 26px" data-act="build-clear-multi" aria-label="Clear selection">${icon('x', 12)}</button></div>`;
}

/** The bar when it is not beside a card: where it was dragged to (fixed on the screen), or at the bottom when the selection is on another page
 * of the test (and the paste bar). */
function bulkBar(S) {
  const ed = S.build.ed;
  const clip = S.build.clip;
  if (!ed.multi.length) {
    if (!clip) return '';
    return html`<div class="bulk-bar" style="bottom: ${ed.drawer ? 260 : 16}px">
<button class="btn btn-sm btn-ghost" data-act="build-paste-steps">${icon('copy', 13)} Paste ${clip.steps.length} step${clip.steps.length === 1 ? '' : 's'}</button></div>`;
  }
  const pos = rememberedBulkPos();
  if (pos) return bulkBarBody(S, `position: fixed; left: ${pos.x}px; top: ${pos.y}px; transform: none; bottom: auto`);
  const t = currentTest();
  const b = t && t.blocks[Math.min(ed.block, t.blocks.length - 1)];
  const onThisPage = t && ed.mode === 'cards' && (!b || t.steps.some((s) => ed.multi.includes(s.row) && s.n >= b.start && s.n <= b.end));
  return onThisPage ? '' : bulkBarBody(S, `bottom: ${ed.drawer ? 260 : 16}px`);
}

function addStepMenu(S) {
  const ed = S.build.ed;
  if (!ed.menu) return '';
  const q = (ed.menuQuery || '').toLowerCase();
  const groups = (S.build.keywords && S.build.keywords.groups) || [];
  return html`<div class="menu add-menu" style="padding: 6px" role="menu">
<div class="field" style="margin-bottom: 6px">${icon('search', 14)}<input class="fld" style="border: 0; height: auto; padding: 0; background: transparent" placeholder="Search actions…" value="${ed.menuQuery || ''}" data-input="build-menu-query" autocomplete="off"></div>
${ed.pendingBlock ? html`<div class="bn bn-acc" style="padding: 8px 10px; margin-bottom: 6px">${icon('layers', 13, 'color: var(--acc)')}<span style="flex: 1">The step you pick starts the new page <b>${ed.pendingBlock}</b>, at the end of the test.</span>
<button class="icon-btn" style="width: 22px; height: 22px" data-act="build-new-page-cancel" aria-label="Not a new page">${icon('x', 11)}</button></div>` : ''}
<button class="mitem" data-act="build-open-insert-template">${icon('layers', 14)}<span style="flex: 1">Insert a template</span></button>
${ed.sel != null && !ed.pendingBlock ? html`<button class="mitem" data-act="build-start-page" data-row="${ed.sel}">${icon('grid', 14)}<span style="flex: 1">Start a new page at the selected step…</span></button>` : ''}
${!ed.pendingBlock ? html`<button class="mitem" data-act="build-new-page">${icon('plus', 14)}<span style="flex: 1">Add a new page at the end…</span></button>` : ''}
${sessionOpen() ? html`<button class="mitem" data-act="build-rec-here">${icon('rec', 14)}<span style="flex: 1">Record from here in the browser</span></button>`
  : html`<button class="mitem" disabled style="opacity: .5; cursor: default" title="Open the site first (the button under the test's header)">${icon('rec', 14)}<span style="flex: 1">Record from here in the browser</span></button>`}
${sessionOpen() ? html`<button class="mitem" data-act="build-sess-pick">${icon('target', 14)}<span style="flex: 1">Pick an element on the page</span></button>`
  : html`<button class="mitem" disabled style="opacity: .5; cursor: default" title="Open the site first (the button under the test's header)">${icon('target', 14)}<span style="flex: 1">Pick an element on the page</span></button>`}
<div class="hr" style="margin: 5px 0"></div>
${groups.map((g) => { const methods = g.methods.filter((m) => !q || m.method.toLowerCase().includes(q) || (m.label || '').toLowerCase().includes(q)); return methods.length ? html`<span class="lbl" style="padding: 4px 10px; display: block">${g.group}</span>
${methods.map((m) => html`<button class="mitem" data-act="build-insert" data-method="${m.method}">${icon(m.element ? 'target' : 'bolt', 13)}<span style="flex: 1">${m.label || m.method}</span></button>`)}` : ''; })}
</div>`;
}

// ---- data drawer -----------------------------------------------------------------------------------------------
function drawer(S, t) {
  const ed = S.build.ed;
  return html`<div style="flex: none; border-top: 1px solid var(--line); background: var(--rail)">
<button data-act="build-toggle-drawer" style="width: 100%; height: 34px; display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: 12.5px">
${icon('table', 13)}<b>Data</b><span style="color: var(--tx3)">${t.paramSheet || 'no parameter sheet'}</span><span style="flex: 1"></span>
<span style="color: var(--tx3); display: inline-flex">${icon(ed.drawer ? 'chevr' : 'chevl', 12, 'transform: rotate(90deg)')}</span></button>
${ed.drawer ? drawerBody(S, t) : ''}</div>`;
}

function drawerBody(S, t) {
  const ed = S.build.ed;
  if (!t.paramSheet) return html`<div style="padding: 0 16px 14px; font-size: 12.5px; color: var(--tx3)">This test has no parameter sheet.</div>`;
  if (ed.drawerGrid === undefined || ed.drawerSheetName !== t.paramSheet) return html`<div style="padding: 0 16px 14px; color: var(--tx3); font-size: 12.5px">Loading…</div>`;
  const g = ed.drawerGrid;
  if (!g) return html`<div style="padding: 0 16px 14px; color: var(--tx3); font-size: 12.5px">Could not read ${t.paramSheet}.</div>`;
  const using = effectiveBuildingWith(t);
  return html`<div style="padding: 0 16px 14px; display: flex; flex-direction: column; gap: 8px">
<div class="scroll" style="max-height: 190px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; background: var(--surface)">
<table class="tbl"><thead><tr><th></th>${g.headers.map((h) => html`<th>${h}</th>`)}</tr></thead>
<tbody>${g.rows.map((row, i) => { const sheetRow = i + 2; const on = using === sheetRow; return html`<tr style="${on ? 'background: var(--acc-soft)' : ''}" data-key="drow-${sheetRow}">
<td><button class="tag ${on ? 'tag-acc' : ''}" data-act="build-drow-use" data-row="${sheetRow}">${on ? '● using' : 'use'}</button></td>
${row.map((c, ci) => html`<td><input class="fld mono" style="height: 26px; font-size: 11.5px; border: 0; background: transparent; padding: 0" value="${c == null ? '' : String(c)}" data-input="build-drow-cell" data-row="${sheetRow}" data-col="${g.headers[ci]}"></td>`)}
</tr>`; })}</tbody></table></div></div>`;
}

// ---- inspector -----------------------------------------------------------------------------------------------
function problemsPanel(S, t) {
  const m = bm();
  const rows = (m.problems || []).filter((p) => !p.test || p.test === t.id).sort((a, b) => ({ error: 0, warning: 1, info: 2 }[a.severity] - { error: 0, warning: 1, info: 2 }[b.severity]));
  return html`<div style="padding: 14px 16px 10px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 8px"><span class="ttl" style="font-size: 15px">Problems</span>
<span class="tag">${rows.length}</span><span style="flex: 1"></span><button class="icon-btn" data-act="build-toggle-problems" aria-label="Close problems">${icon('x', 13)}</button></div>
<div class="scroll" style="flex: 1; overflow: auto; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px">
${rows.length ? rows.map((p) => html`<div class="card" style="padding: 10px 12px; display: flex; gap: 9px; box-shadow: none" data-key="pb-${p.id}">
<span class="pdot" style="margin-top: 5px; background: var(--${p.severity === 'error' ? 'fail' : p.severity === 'warning' ? 'warn' : 'tx3'})"></span>
<div style="display: flex; flex-direction: column; gap: 4px; min-width: 0"><span style="font-size: 12.5px">${p.row ? html`<b>Step ${p.n || ''}</b> ` : ''}<span style="color: var(--tx2)">${p.message}</span></span>
${p.row ? html`<button class="btn btn-sm" data-act="build-pick-step" data-row="${p.row}">Show step</button>` : ''}</div></div>`)
  : html`<span style="font-size: 12.5px; color: var(--tx3); padding: 4px">No problems on this test.</span>`}
</div>`;
}

// The legacy FindBy vocabulary (selectors/spec.py FINDBY_ALIASES), in the words the inspector shows.
const FIND_BY = [['BY_XPATH', 'XPath'], ['BY_ID', 'id'], ['BY_CSSSELECTOR', 'CSS'], ['BY_NAME', 'name'], ['BY_LINKTEXT', 'Link text'],
  ['BY_PARTIALLINKTEXT', 'Part of link text'], ['BY_CLASSNAME', 'Class'], ['BY_TAGNAME', 'Tag']];

/** "On which element": the element's words, how it is found (FindBy) and the locator itself, both editable, and "Pick on the page" (which
 * opens the site first when needed). Shown for every step whose action works on an element, even before it has one. */
function elementSection(s) {
  const loc = s.locator || {};
  const findBy = (loc.findBy || '').toUpperCase();
  const known = FIND_BY.some(([k]) => k === findBy);
  const words = loc.plainWords || [];
  return html`<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">On which element</span>
${words.length ? html`<div style="display: flex; flex-wrap: wrap; gap: 5px; align-items: center">${words.map((w) => (w.role === 'name' || w.role === 'context')
    ? (w.variable ? html`<span class="var">${icon('braces', 11)} ${w.variable}</span>` : html`<b style="font-size: 12.5px">“${w.text}”</b>`) : html`<span class="tag">${w.text}</span>`)}</div>` : ''}
<div style="display: flex; gap: 6px; min-width: 0">
<select class="fld" style="width: 118px; flex: none; font-size: 12px" data-change="build-step-findby" data-row="${s.row}" aria-label="How the element is found">
${!findBy ? html`<option value="" selected>Find by…</option>` : ''}${findBy && !known ? html`<option value="${loc.findBy}" selected>${loc.findBy}</option>` : ''}
${FIND_BY.map(([k, label]) => html`<option value="${k}" ${k === findBy ? raw('selected') : ''}>${label}</option>`)}</select>
<input class="fld mono" style="flex: 1; min-width: 0; font-size: 12px" value="${loc.value || ''}" placeholder="//button[text()='Next'], #id, …" data-input="build-step-locator" data-row="${s.row}" data-findby="${loc.findBy || ''}" aria-label="Locator (FindBy_Value)"></div>
<button class="btn btn-sm" style="align-self: flex-start" data-act="build-sess-pick-for" data-row="${s.row}" title="Click the element in the build window: its locator is checked on the live page">${icon('target', 13)} ${sessionOpen() ? 'Pick on the page' : 'Open the site and pick'}</button>
${(loc.backups || []).length ? html`<span style="font-size: 12px; color: var(--tx3)">${loc.backups.length} backup locator${loc.backups.length === 1 ? '' : 's'} stored.</span>` : ''}</div>`;
}

function inspector(S, t, s) {
  if (!s) return html`<div style="padding: 20px; color: var(--tx3); font-size: 13px">No step selected.</div>`;
  return html`<div style="padding: 14px 16px 12px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 7px">
<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="font-size: 12px; color: var(--tx3)">Step ${s.n}</span><span class="badge k-${s.kind}">${KIND_BADGE[s.kind] || s.method}</span>
${s.sideEffects ? html`<span class="tag tag-warn">${icon('bolt', 10)} side effects</span>` : ''}<span style="flex: 1"></span>
<span class="mono" style="font-size: 11px; color: var(--tx3)">row ${s.row}</span></div>
<div class="disp" style="font-size: 16px; font-weight: 700">${tokenHtml(s.nameAuto ? s.autoName : s.name)}</div>
</div>
<div class="scroll" style="flex: 1; overflow: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 16px">
${lastRunCard(t, s)}
${pickPanel(S, t, s)}
${s.legacy ? html`<div class="bn">${icon('lock', 14, 'color: var(--tx3)')}<span><b>Legacy row, kept exactly as it is.</b> ${s.legacy} Move it with bulk edit; edit its cells in the Excel grid.</span></div>`
  : html`
<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Name</span>
<input class="fld" value="${s.nameAuto ? '' : s.name}" placeholder="${s.autoName}" data-input="build-step-name" data-row="${s.row}">
<div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx3)">${s.nameAuto ? 'Auto name' : html`<button class="lnk" data-act="build-name-auto" data-row="${s.row}">Use automatic name</button>`}
<span style="flex: 1"></span><button class="lnk" data-act="build-start-page" data-row="${s.row}" title="This step and the ones after it on this page become a new page">Start a new page here</button></div></div>
${s.call ? html`<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Runs this test, then carries on</span>
<div class="field" style="min-height: 40px">${icon('api', 15, 'color: var(--k-api)')}<b>${s.call}</b><span style="flex: 1"></span><a href="${buildUrl(S.build.name, 'test', s.call)}">Open</a></div></div>` : ''}
${s.element || (s.locator && (s.locator.value || s.locator.findBy)) ? elementSection(s) : ''}
${!s.call ? html`<div style="display: flex; flex-direction: column; gap: 8px"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">Value</span><span style="flex: 1"></span>
<button class="btn btn-ghost btn-sm" style="height: 22px; font-size: 11px; padding: 0 6px" data-act="build-open-value-builder" data-row="${s.row}" title="Value builder: writes a formula">ƒ Value builder</button></div>
<div class="field">${s.value ? html`<span style="flex-wrap: wrap; display: flex; gap: 3px">${tokenHtml(s.value)}</span>` : html`<span class="mono" style="font-size: 12px; color: var(--tx3)">(empty)</span>`}</div>
<input class="fld mono" style="font-size: 12px" value="${s.value}" data-input="build-step-value" data-row="${s.row}"></div>
<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Expected</span>
<input class="fld mono" style="font-size: 12px" value="${s.expected}" placeholder="(no comparison)" data-input="build-step-expected" data-row="${s.row}">
<select class="fld" data-change="build-step-match" data-row="${s.row}">
<option value="" ${s.match ? '' : raw('selected')}>No comparison</option><option value="exact" ${s.match === 'exact' ? raw('selected') : ''}>Exact match</option><option value="contains" ${s.match === 'contains' ? raw('selected') : ''}>Contains</option></select></div>
<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Save the result as</span>
<input class="fld mono" style="font-size: 12px" value="${s.saveAs || s.output}" placeholder="not saved" data-input="build-step-saveas" data-row="${s.row}"></div>` : ''}
<div style="display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid var(--line)">
<div style="display: flex; justify-content: space-between; align-items: center"><span style="font-size: 13px; color: var(--tx2)">If this step fails</span>
<div class="seg" style="width: 190px"><button class="${cx(s.onFail !== 'continue' && 'on')}" data-act="build-set-onfail" data-val="stop" data-row="${s.row}">Stop</button><button class="${cx(s.onFail === 'continue' && 'on')}" data-act="build-set-onfail" data-val="continue" data-row="${s.row}">Keep going</button></div></div>
<div style="display: flex; justify-content: space-between; align-items: center"><span style="font-size: 13px; color: var(--tx2)">Give up after</span>
<input class="fld mono" style="width: 90px; height: 30px; font-size: 12px" type="number" min="0" value="${s.timeout != null ? s.timeout : ''}" placeholder="default" data-input="build-step-timeout" data-row="${s.row}"></div>
<div style="display: flex; justify-content: space-between; align-items: center"><span style="font-size: 13px; color: var(--tx2)">Run this step</span>
<input type="checkbox" class="sw" ${s.enabled !== false ? raw('checked') : ''} data-act="build-toggle-enabled-step" data-row="${s.row}" aria-label="Run this step"></div>
<div style="display: flex; justify-content: space-between; align-items: center; gap: 12px"><span style="font-size: 13px; color: var(--tx2)">Has side effects<span style="display: block; font-size: 11px; color: var(--tx3)">Blocked on production</span></span>
<input type="checkbox" class="sw" ${s.sideEffects ? raw('checked') : ''} data-act="build-toggle-side" data-row="${s.row}" aria-label="Has side effects"></div></div>
<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Notes</span>
<textarea class="fld" style="height: 60px; padding: 8px 10px; resize: vertical" data-input="build-step-notes" data-row="${s.row}">${s.notes || ''}</textarea></div>`}
</div>`;
}

// ---- phone layout: one pane at a time (Steps / Details / Test) ------------------------------------------------
// Above 820px every pane shows at once and none of this is visible; the panes are `display: contents` wrappers, so the desktop
// layout is exactly what it was.  Under 820px only the chosen pane shows (app.css, "small screens").

function paneSwitch(t, pane) {
  const tab = (id, label, extra = '') => html`<button role="tab" aria-selected="${String(pane === id)}" class="${cx('pane-tab', pane === id && 'on')}" data-act="build-pane" data-val="${id}">${label}${extra}</button>`;
  return html`<div class="pane-switch" role="tablist" aria-label="What to show">${tab('steps', 'Steps ', html`<span class="mono" style="font-size: 11px; color: var(--tx3)">${t.steps.length}</span>`)}${tab('details', 'Details')}${tab('test', 'Test')}</div>`;
}

/** The fixed bar at the bottom of a phone screen: what is selected and the way to the next pane. */
function phoneBars(t, s, at, pane) {
  if (pane === 'steps') {
    return html`<div class="phone-bar" role="region" aria-label="Selected step">
<div style="min-width: 0; flex: 1"><div class="mono" style="font-size: 11px; color: var(--tx3)">${s ? `Step ${s.n} selected` : 'No step selected'}</div>
<div class="trunc" style="font-weight: 600">${s ? (s.nameAuto ? s.autoName : s.name) || 'Step' : 'Tap a step to edit it'}</div></div>
<button class="btn btn-pri" style="height: 46px" data-act="build-pane" data-val="details" ${s ? '' : raw('disabled')}>Edit details ${icon('chevr', 13)}</button></div>`;
  }
  if (pane === 'details') {
    return html`<div class="phone-bar" role="region" aria-label="Step navigation">
<button class="btn" style="height: 46px" data-act="build-pane" data-val="steps">${icon('chevl', 13)} Steps</button>
<button class="btn" style="height: 46px; flex: 1" data-act="build-step-nav" data-dir="-1" ${at > 0 ? '' : raw('disabled')}>${icon('chevl', 13)} Previous</button>
<button class="btn" style="height: 46px; flex: 1" data-act="build-step-nav" data-dir="1" ${at >= 0 && at < t.steps.length - 1 ? '' : raw('disabled')}>Next ${icon('chevr', 13)}</button></div>`;
  }
  return '';
}

// ---- top-level -----------------------------------------------------------------------------------------------
export function testEditor(S) {
  const t = currentTest();
  const m = bm();
  if (!t) return html`<div class="app-body">${buildRail(S)}<main class="main"><div class="page"><b>That test does not exist in ${m ? m.name : 'this workbook'}.</b></div></main></div>`;
  if (t.kind === 'api' || t.kind === 'xml') return apiEditor(S);         // API / XML tests: their own editor (P10)
  const ed = S.build.ed;
  const b = t.blocks.length ? t.blocks[Math.min(ed.block, t.blocks.length - 1)] : { start: 0, end: t.steps.length, title: 'All steps', kind: 'page' };
  const idx = t.blocks.indexOf(b);
  const s = selectedStep();
  const pane = ed.pane || 'steps';
  const at = t.steps.findIndex((x) => s && x.row === s.row);
  return html`<div class="app-body" data-pane="${pane}">${buildRail(S)}
<main class="main b-main" style="display: flex; flex-direction: column; position: relative; min-width: 0">
${paneSwitch(t, pane)}
<div class="pane pane-test">${subHeader(S, t)}</div>
<div class="pane pane-steps">
${sessionBar(S)}
${blockStrip(S, t)}
${t.blocks.length ? blockHeader(S, t, b, Math.max(0, idx)) : ''}
${ed.mode === 'grid' ? gridView(S, t) : cardsView(S, t, b)}
${bulkBar(S)}
${addStepMenu(S)}
</div>
<div class="pane pane-test">${drawer(S, t)}</div>
</main>
<aside class="b-aside pane-details" style="--w: 372px">
${ed.problems ? problemsPanel(S, t) : inspector(S, t, s)}
${!ed.problems ? html`<div style="padding: 8px 16px; border-top: 1px solid var(--line)"><button class="lnk" data-act="build-toggle-problems">${m.problemCounts.error + m.problemCounts.warning} problems in this workbook</button></div>` : ''}
</aside>
${phoneBars(t, s, at, pane)}</div>`;
}
