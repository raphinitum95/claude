// The concurrency scenario board (Q35/Q36): lanes side by side, each a row of its test's blocks; sync lines ("all wait here") as columns
// every lane in them lines up on; order markers ("A before B") as chips on the blocks at each end.  A scenario is one row group of the
// hidden _rr_scenarios table (workbook/scenarios.py); every edit here sends the whole scenario back as one set_scenario op through /edit,
// so it shares the workbook's undo and autosaved draft.  Runs: the scenario's own last runs, per lane (GET .../scenarios/<name>/runs).
import { S, rerender } from '../../state.js';
import { html, raw, cx, toast, debounce } from '../../util.js';
import { icon, pill } from '../../icons.js';
import { api } from '../../api.js';
import { loadRuns } from '../../actions.js';
import { buildRail } from './rail.js';
import { applyOps, bm, buildUrl } from './actions.js';

const enc = encodeURIComponent;
const KIND_ICON = { web: 'grid', api: 'xml', xml: 'xml' };            // (an API test gets the <> icon, JSON or XML alike)
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

// UI-only state: what is selected on the board and the scenario's last runs (reset when another scenario opens)
const ui = { name: null, sel: { kind: 'scenario', key: '' }, runs: null, runsFor: null };

export const currentScenario = () => { const m = bm(); return m && S.build.scenario ? (m.scenarios || []).find((s) => s.name === S.build.scenario) : null; };

/** The plain definition (what set_scenario takes) of a board scenario: its own fields, none of the derived ones. */
function definitionOf(sc) {
  return {
    name: sc.name, enabled: sc.enabled, timeout: sc.timeout, notes: sc.notes || '',
    lanes: sc.lanes.map((l) => ({ key: l.key, test: l.test, dataRow: l.dataRow, label: l.label || '' })),
    syncs: sc.syncs.map((s) => ({ name: s.name, timeout: s.timeout, points: s.points.map((p) => ({ ...p })) })),
    orders: sc.orders.map((o) => ({ name: o.name, timeout: o.timeout, first: { ...o.first }, then: { ...o.then } })),
  };
}

async function save(def, rename) {
  const op = { op: 'set_scenario', scenario: def };
  if (rename && rename !== def.name) op.rename = rename;
  const applied = await applyOps([op]);
  if (applied && rename && rename !== def.name) location.hash = buildUrl(S.build.name, 'scenario', def.name);
  return applied;
}

/** Change the open scenario with ``fn(def)`` and send it. */
function edit(fn) {
  const sc = currentScenario();
  if (!sc) return;
  const def = definitionOf(sc);
  if (fn(def) === false) return;
  save(def);
}
const editDebounced = debounce((fn) => edit(fn), 500);

// ---- layout: which blocks of each lane sit between which sync lines --------------------------------------------------------------
function refIndex(lane, ref) {
  if (!ref) return -1;
  const i = lane.blocks.findIndex((b) => b.ref.toLowerCase() === String(ref).toLowerCase());
  return i;
}

/** Per lane: [{fromSync, toSync, blocks}] segments (sync numbers are 1-based positions in sc.syncs; 0 = the start, n+1 = the end). */
function laneSegments(sc, lane) {
  const n = sc.syncs.length;
  const cuts = [];                                         // [{k, at}] at = index of the first block after the sync line
  sc.syncs.forEach((s, i) => {
    const p = s.points.find((x) => x.lane === lane.key);
    if (!p) return;
    const idx = p.block ? refIndex(lane, p.block) : -1;
    const at = p.block ? (idx < 0 ? lane.blocks.length : idx + 1) : 0;
    const prev = cuts.length ? cuts[cuts.length - 1].at : 0;
    cuts.push({ k: i + 1, at: Math.max(prev, at) });       // (a line out of order is drawn where it can be: the problems list says why)
  });
  const out = [];
  let from = 0; let start = 0;
  for (const c of cuts) {
    out.push({ fromSync: from, toSync: c.k, blocks: lane.blocks.slice(start, c.at) });
    from = c.k; start = c.at;
  }
  out.push({ fromSync: from, toSync: n + 1, blocks: lane.blocks.slice(start) });
  return out;
}

function orderChips(sc, lane, block) {
  const chips = [];
  for (const o of sc.orders) {
    if (o.first.lane === lane.key && (o.first.block || '').toLowerCase() === block.ref.toLowerCase()) {
      chips.push(html`<button class="tag" style="color: var(--k-flow); border-color: currentColor" data-act="sc-select" data-kind="order" data-key="${o.name}" title="${o.name}: ${lane.key} finishes this before ${o.then.lane} starts ${o.then.block || 'its first step'}">${icon('arrowr', 10)} then ${o.then.lane}</button>`);
    }
    if (o.then.lane === lane.key && (o.then.block || '').toLowerCase() === block.ref.toLowerCase()) {
      chips.push(html`<button class="tag" style="color: var(--k-flow); border-color: currentColor" data-act="sc-select" data-kind="order" data-key="${o.name}" title="${o.name}: waits here until ${o.first.lane} has finished ${o.first.block || 'all its steps'}">${icon('arrowl', 10)} after ${o.first.lane}</button>`);
    }
  }
  return chips;
}

function blockCard(S, sc, lane, b) {
  return html`<div class="card" data-key="scb-${lane.key}-${b.ref}" style="flex: none; width: 168px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; border-radius: 10px">
<a href="${buildUrl(S.build.name, 'test', lane.test)}" class="trunc" style="font-size: 12.5px; font-weight: 650; color: var(--tx); line-height: 1.25" title="Open ${lane.test} in the editor">${b.title}</a>
<span style="display: flex; gap: 4px; flex-wrap: wrap; align-items: center"><span class="mono" style="font-size: 10.5px; color: var(--tx3)">${b.count} step${b.count === 1 ? '' : 's'}</span>
${b.sideEffects ? html`<span class="tag tag-warn" style="height: 18px">${icon('bolt', 10)} side effects</span>` : ''}${orderChips(sc, lane, b)}</span></div>`;
}

function laneHead(S, sc, lane) {
  const on = ui.sel.kind === 'lane' && ui.sel.key === lane.key;
  const heads = sc.orders.filter((o) => (o.then.lane === lane.key && !o.then.block) || (o.first.lane === lane.key && !o.first.block));
  return html`<button class="${cx('sc-head', on && 'on')}" data-act="sc-select" data-kind="lane" data-key="${lane.key}" style="width: 100%; height: 100%; box-sizing: border-box; display: flex; align-items: center; gap: 10px; padding: 8px 12px; text-align: left; border: 0; border-bottom: 1px solid var(--line); background: ${on ? 'var(--acc-soft)' : 'var(--rail)'}; color: inherit; cursor: pointer; min-height: 76px">
<span class="mono" style="width: 26px; height: 26px; flex: none; border-radius: 8px; display: grid; place-items: center; background: var(--acc-soft); color: var(--acc); font-weight: 700">${lane.key}</span>
<span style="display: flex; flex-direction: column; min-width: 0; gap: 2px"><span style="display: flex; align-items: center; gap: 6px; font-weight: 700">${icon(KIND_ICON[lane.kind] || 'grid', 13)}<span class="trunc">${lane.test || '(no test)'}</span></span>
<span class="trunc" style="font-size: 11.5px; color: var(--tx3)">${lane.found ? `row ${lane.usesRow || '–'}${lane.label ? ' · ' + lane.label : lane.dataLabel ? ' · ' + lane.dataLabel : ''}` : 'test not found'}</span>
${heads.map((o) => html`<span class="tag" style="color: var(--k-flow); align-self: flex-start">${o.then.lane === lane.key ? `starts after ${o.first.lane}` : `finishes before ${o.then.lane}`}</span>`)}</span></button>`;
}

function board(S, sc) {
  const n = sc.syncs.length;
  const cols = ['230px'];
  for (let k = 0; k <= n; k++) { cols.push('minmax(180px, max-content)'); if (k < n) cols.push('40px'); }
  const segCol = (j) => 2 + 2 * j;
  const syncCol = (k) => 1 + 2 * k;
  const cells = [];
  cells.push(html`<div style="grid-column: 1; grid-row: 1; padding: 0 12px; display: flex; align-items: flex-end"><span class="lbl">Lanes</span></div>`);
  sc.syncs.forEach((s, i) => {
    const on = ui.sel.kind === 'sync' && ui.sel.key === s.name;
    cells.push(html`<button data-act="sc-select" data-kind="sync" data-key="${s.name}" title="${s.name}: every lane in it waits here until all have arrived" style="grid-column: ${syncCol(i + 1) - 1} / span 3; grid-row: 1; justify-self: center; align-self: end; padding: 2px 8px; border-radius: 6px; border: 0; background: ${on ? 'var(--acc)' : 'var(--acc-soft)'}; color: ${on ? 'var(--acc-tx)' : 'var(--acc)'}; font-size: 11px; font-weight: 700; white-space: nowrap; cursor: pointer">${icon('sync', 11)} ${s.name}</button>`);
  });
  sc.lanes.forEach((lane, li) => {
    const row = li + 2;
    cells.push(html`<div style="grid-column: 1; grid-row: ${row}; display: flex">${laneHead(S, sc, lane)}</div>`);
    for (const seg of laneSegments(sc, lane)) {
      cells.push(html`<div style="grid-column: ${segCol(seg.fromSync)} / ${segCol(seg.toSync - 1) + 1}; grid-row: ${row}; display: flex; gap: 8px; align-items: center; padding: 10px 8px; border-bottom: 1px solid var(--line); min-height: 76px">
${seg.blocks.length ? seg.blocks.map((b) => blockCard(S, sc, lane, b)) : html`<span style="font-size: 11.5px; color: var(--tx3)">${lane.found ? '' : 'no test'}</span>`}</div>`);
    }
    sc.syncs.forEach((s, i) => {
      if (!s.points.some((p) => p.lane === lane.key)) return;
      const on = ui.sel.kind === 'sync' && ui.sel.key === s.name;
      cells.push(html`<div style="grid-column: ${syncCol(i + 1)}; grid-row: ${row}; display: flex; justify-content: center; border-bottom: 1px solid var(--line)" title="Lane ${lane.key} waits here for the others in ${s.name}">
<div style="width: ${on ? 4 : 2}px; background: var(--acc); border-radius: 2px"></div></div>`);
    });
  });
  return html`<div class="card" style="padding: 12px 0 0; overflow: auto"><div style="display: grid; grid-template-columns: ${cols.join(' ')}; grid-template-rows: 26px; min-width: max-content">${cells}</div></div>`;
}

// ---- inspector -------------------------------------------------------------------------------------------------------------------------
const field = (label, inner) => html`<label style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">${label}</span>${inner}</label>`;

function blockOptions(lane, value, first, firstLabel) {
  return html`<option value="" ${!value ? raw('selected') : ''}>${firstLabel}</option>
${(lane ? lane.blocks : []).map((b) => html`<option value="${b.ref}" ${value && value.toLowerCase() === b.ref.toLowerCase() ? raw('selected') : ''}>${first}${b.title}${b.ref !== b.title ? ` (${b.ref})` : ''}</option>`)}`;
}

function laneOptions(sc, value) {
  return sc.lanes.map((l) => html`<option value="${l.key}" ${l.key === value ? raw('selected') : ''}>${l.key} · ${l.test}${l.label ? ` (${l.label})` : ''}</option>`);
}

function scenarioInspector(S, sc, m) {
  return html`<span class="lbl">Scenario</span>
${field('Name', html`<input class="fld" value="${sc.name}" data-change="sc-rename">`)}
${field('What it is for', html`<textarea class="fld" rows="3" style="height: auto; padding: 8px" data-input="sc-notes" placeholder="Two agents edit one policy at the same time">${sc.notes || ''}</textarea>`)}
<label style="display: flex; align-items: center; gap: 10px; font-size: 13px"><input type="checkbox" class="sw" ${sc.enabled ? raw('checked') : ''} data-change="sc-enabled"> Runs with the workbook's defaults</label>
${field('Give up waiting after (seconds with no step started or finished by the lanes waited for)', html`<input class="fld mono" type="number" min="5" value="${sc.timeout != null ? sc.timeout : ''}" placeholder="${sc.timeoutUsed || 120}" data-input="sc-timeout">`)}
<div class="hr"></div>
<button class="btn btn-sm" data-act="sc-delete" style="color: var(--fail)">${icon('trash', 13)} Delete scenario</button>`;
}

function laneInspector(S, sc, lane, m) {
  const tests = m.tests.filter((t) => t.kind === 'web' || t.kind === 'api' || t.kind === 'xml');
  const t = m.tests.find((x) => x.id === lane.test);
  return html`<span class="lbl">Lane ${lane.key}</span>
${field('Test', html`<select class="fld" data-change="sc-lane-test" data-key="${lane.key}">${!t ? html`<option selected>${lane.test || '(pick a test)'}</option>` : ''}${tests.map((x) => html`<option value="${x.id}" ${x.id === lane.test ? raw('selected') : ''}>${x.id}</option>`)}</select>`)}
${field('Data row (its own user, its own data)', html`<select class="fld" data-change="sc-lane-row" data-key="${lane.key}">
<option value="" ${lane.dataRow == null ? raw('selected') : ''}>First enabled row${t && t.buildingWith ? ` (row ${t.buildingWith})` : ''}</option>
${(t ? t.dataRows : []).map((r) => html`<option value="${r.row}" ${r.row === lane.dataRow ? raw('selected') : ''}>Row ${r.row}${r.label ? ' · ' + r.label : ''}${r.enabled === false ? ' · off (runs here anyway)' : ''}</option>`)}</select>`)}
${field('Label', html`<input class="fld" value="${lane.label || ''}" placeholder="agent Ana" data-input="sc-lane-label" data-key="${lane.key}">`)}
<div class="hr"></div>
<button class="btn btn-sm" data-act="sc-remove-lane" data-key="${lane.key}" style="color: var(--fail)">${icon('trash', 13)} Remove lane ${lane.key}</button>`;
}

function syncInspector(S, sc, s) {
  return html`<span class="lbl">Sync line</span><span class="ttl">${s.name} · all wait here</span>
<span style="font-size: 12.5px; color: var(--tx2)">Every lane in it stops here until all have arrived, then they carry on together. A lane that ends first (passed or failed) is not waited for.</span>
${field('Name', html`<input class="fld" value="${s.name}" data-change="sc-sync-name" data-key="${s.name}">`)}
${sc.lanes.map((lane) => {
    const p = s.points.find((x) => x.lane === lane.key);
    return html`<div class="field" style="min-height: 34px; gap: 8px"><span class="mono" style="color: var(--acc); font-weight: 700">${lane.key}</span>
<select class="fld" style="border: 0; background: transparent; height: 30px" data-change="sc-sync-point" data-key="${s.name}" data-lane="${lane.key}">
<option value="-" ${!p ? raw('selected') : ''}>not in this sync</option>
<option value="" ${p && !p.block ? raw('selected') : ''}>at the start (before its first step)</option>
${lane.blocks.map((b) => html`<option value="${b.ref}" ${p && p.block && p.block.toLowerCase() === b.ref.toLowerCase() ? raw('selected') : ''}>after “${b.title}”${b.ref !== b.title ? ` (${b.ref})` : ''}</option>`)}</select></div>`;
  })}
${field('Give up waiting after (s)', html`<input class="fld mono" type="number" min="5" value="${s.timeout != null ? s.timeout : ''}" placeholder="${sc.timeoutUsed || 120} (the scenario's)" data-input="sc-sync-timeout" data-key="${s.name}">`)}
<div class="hr"></div>
<button class="btn btn-sm" data-act="sc-delete-sync" data-key="${s.name}" style="color: var(--fail)">${icon('trash', 13)} Delete ${s.name}</button>`;
}

function orderInspector(S, sc, o) {
  const a = sc.lanes.find((l) => l.key === o.first.lane);
  const b = sc.lanes.find((l) => l.key === o.then.lane);
  return html`<span class="lbl">Order marker</span><span class="ttl">${o.name}</span>
<span style="font-size: 12.5px; color: var(--tx2)">${o.first.lane}’s ${o.first.block ? `“${o.first.block}”` : 'last step'} finishes before ${o.then.lane}’s ${o.then.block ? `“${o.then.block}”` : 'first step'} starts. If ${o.first.lane} ends early (a failure), ${o.then.lane} is not held back.</span>
${field('Name', html`<input class="fld" value="${o.name}" data-change="sc-order-name" data-key="${o.name}">`)}
${field('First', html`<div style="display: flex; gap: 6px"><select class="fld" style="width: 90px" data-change="sc-order-lane" data-key="${o.name}" data-end="first">${laneOptions(sc, o.first.lane)}</select>
<select class="fld" data-change="sc-order-block" data-key="${o.name}" data-end="first">${blockOptions(a, o.first.block, 'finishing “', 'finishing all its steps')}</select></div>`)}
${field('Then', html`<div style="display: flex; gap: 6px"><select class="fld" style="width: 90px" data-change="sc-order-lane" data-key="${o.name}" data-end="then">${laneOptions(sc, o.then.lane)}</select>
<select class="fld" data-change="sc-order-block" data-key="${o.name}" data-end="then">${blockOptions(b, o.then.block, 'before “', 'before its first step')}</select></div>`)}
${field('Give up waiting after (s)', html`<input class="fld mono" type="number" min="5" value="${o.timeout != null ? o.timeout : ''}" placeholder="${sc.timeoutUsed || 120} (the scenario's)" data-input="sc-order-timeout" data-key="${o.name}">`)}
<div class="hr"></div>
<button class="btn btn-sm" data-act="sc-delete-order" data-key="${o.name}" style="color: var(--fail)">${icon('trash', 13)} Delete marker</button>`;
}

function inspector(S, sc, m) {
  const sel = ui.sel;
  let body;
  if (sel.kind === 'lane' && sc.lanes.some((l) => l.key === sel.key)) body = laneInspector(S, sc, sc.lanes.find((l) => l.key === sel.key), m);
  else if (sel.kind === 'sync' && sc.syncs.some((s) => s.name === sel.key)) body = syncInspector(S, sc, sc.syncs.find((s) => s.name === sel.key));
  else if (sel.kind === 'order' && sc.orders.some((o) => o.name === sel.key)) body = orderInspector(S, sc, sc.orders.find((o) => o.name === sel.key));
  else body = scenarioInspector(S, sc, m);
  return html`<aside class="scroll" aria-label="Selected" style="width: 330px; flex: none; border-left: 1px solid var(--line); background: var(--rail); padding: 18px 16px; display: flex; flex-direction: column; gap: 14px; overflow: auto">
${sel.kind !== 'scenario' ? html`<button class="lnk" style="align-self: flex-start" data-act="sc-select" data-kind="scenario" data-key="">${icon('chevl', 11)} Scenario settings</button>` : ''}${body}</aside>`;
}

// ---- last runs ---------------------------------------------------------------------------------------------------------------------------
const STATE_TONE = { released: 'var(--pass)', done: 'var(--pass)', arrived: 'var(--warn)', waiting: 'var(--warn)', ended: 'var(--tx3)', timeout: 'var(--fail)' };

function runsCard(S, sc) {
  const runs = ui.runsFor === sc.name ? ui.runs : null;
  return html`<section class="card" style="padding: 16px 18px; display: flex; flex-direction: column; gap: 10px"><div style="display: flex; align-items: center; gap: 10px"><h2 class="ttl">Last runs</h2>
<span style="font-size: 12px; color: var(--tx3)">each lane reported on its own</span></div>
${runs == null ? html`<span style="font-size: 12.5px; color: var(--tx3)">Loading…</span>` : !runs.length ? html`<span style="font-size: 12.5px; color: var(--tx3)">Not run yet.</span>`
    : runs.map((r) => html`<div data-key="scr-${r.runId}" style="display: flex; flex-direction: column; gap: 6px; padding-top: 8px; border-top: 1px solid var(--line)">
<div style="display: flex; align-items: center; gap: 8px"><a class="mono" href="#/run/${r.runId}" style="font-size: 12.5px">${r.runId}</a><span class="tag">${r.environment}</span></div>
${r.lanes.map((l) => html`<div style="display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px"><span class="mono" style="width: 18px; color: var(--acc); font-weight: 700">${l.key}</span>${pill(l.status)}
<span style="display: flex; flex-direction: column; gap: 3px; min-width: 0"><span class="trunc" style="color: var(--tx2)">${l.test}${l.label ? ' · ' + l.label : ''}${l.error ? ' · ' + l.error.split('\n')[0] : ''}</span>
<span style="display: flex; gap: 4px; flex-wrap: wrap">${(l.syncs || []).filter((x) => ['released', 'timeout', 'ended', 'done'].includes(x.state)).map((x) => html`<span class="tag" style="color: ${STATE_TONE[x.state] || 'var(--tx2)'}" title="${x.message}">${x.item} · ${x.state}${x.waited_s ? ` · ${Math.round(x.waited_s)} s` : ''}</span>`)}</span></span></div>`)}</div>`)}</section>`;
}

async function loadScenarioRuns(name) {
  ui.runsFor = name; ui.runs = null;
  try {
    const res = await api(`/api/build/workbooks/${enc(S.build.name)}/scenarios/${enc(name)}/runs`);
    if (ui.runsFor === name) { ui.runs = res.runs; rerender(); }
  } catch (e) { if (ui.runsFor === name) { ui.runs = []; rerender(); } }
}

// ---- the screen ------------------------------------------------------------------------------------------------------------------------
export function scenarioBoard(S) {
  const m = bm();
  const sc = currentScenario();
  if (!sc) {
    return html`<div class="app-body">${buildRail(S)}<main class="main"><div class="page"><b>No scenario called “${S.build.scenario}”.</b>
<p style="color: var(--tx2)">It may have been renamed or deleted. <a href="${buildUrl(S.build.name, 'map')}">Back to the workbook map</a></p></div></main></div>`;
  }
  if (ui.name !== sc.name) { ui.name = sc.name; ui.sel = { kind: 'scenario', key: '' }; loadScenarioRuns(sc.name); }
  const errors = sc.problems.filter((p) => p.severity === 'error');
  const twins = sc.lanes.length > 1 && new Set(sc.lanes.map((l) => l.test)).size < sc.lanes.length;
  return html`<div class="app-body">${buildRail(S)}<main class="main" style="display: flex; flex-direction: column; min-width: 0; overflow: hidden">
<div style="height: 52px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 16px; border-bottom: 1px solid var(--line); background: var(--rail)">
<span class="chip" style="height: 28px">${icon('sync', 14)} Scenario</span><span class="trunc" style="font-size: 12.5px; color: var(--tx3)">Runs as one unit and reports per lane. For concurrency cases, not load.</span>
<span style="flex-grow: 1"></span>
<button class="btn btn-sm" data-act="sc-add-lane">${icon('plus', 13)} Lane</button>
<button class="btn btn-sm" data-act="sc-add-sync" ${sc.lanes.length < 2 ? raw('disabled') : ''}>${icon('sync', 13)} Sync line</button>
<button class="btn btn-sm" data-act="sc-add-order" ${sc.lanes.length < 2 ? raw('disabled') : ''}>${icon('arrowr', 13)} Order marker</button>
<button class="btn btn-sm btn-pri" data-act="sc-run" ${errors.length ? raw('disabled title="Fix the problems below first"') : ''}>${icon('play', 12)} Run it on ${m.environment || 'the default environment'}</button></div>
<div style="flex-grow: 1; display: flex; min-height: 0">
<div class="scroll" style="flex: 1; min-width: 0; overflow: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px">
<div style="display: flex; align-items: baseline; gap: 12px"><h1 class="disp" style="font-size: 24px; margin: 0">${sc.name}</h1>${sc.enabled ? '' : html`<span class="tag">not in default runs</span>`}
<span style="font-size: 12.5px; color: var(--tx2)">${sc.notes || ''}</span></div>
${sc.lanes.length ? board(S, sc) : html`<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 26px; text-align: center; color: var(--tx2)">Add a lane: an existing test, or the same test again with its own data row.</div>`}
<div style="display: flex; gap: 12px; flex-wrap: wrap">
${sc.sharedSignIn.length ? html`<div class="bn" style="flex: 1; min-width: 260px">${icon('key', 15, 'color: var(--tx3)')}<span><b>Sign-in codes.</b> Lanes ${sc.sharedSignIn.map((g) => g.join(' and ')).join('; ')} use the same one-time-code key: each gets its own 30 s code window (a code works once), so the scenario takes up to 30 s longer at that point.</span></div>`
    : sc.lanes.length > 1 ? html`<div class="bn" style="flex: 1; min-width: 260px">${icon('key', 15, 'color: var(--tx3)')}<span><b>Sign-in codes.</b> No two lanes share a one-time-code key. If they did, each would get its own 30 s code window.</span></div>` : ''}
<div class="bn" style="flex: 1; min-width: 260px">${icon('info', 15, 'color: var(--tx3)')}<span>${twins ? 'Lanes of the same test run with their own data row. ' : ''}Steps between sync lines run at the same time, each lane in its own browser session. A lane that fails still releases the others, so one failure never hangs the scenario.</span></div></div>
${sc.problems.length ? html`<section class="card" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 8px"><h2 class="ttl">Problems (${sc.problems.length})</h2>
${sc.problems.map((p) => html`<div style="display: flex; gap: 8px; font-size: 12.5px"><span class="pdot" style="margin-top: 5px; background: ${p.severity === 'error' ? 'var(--fail)' : p.severity === 'warning' ? 'var(--warn)' : 'var(--acc)'}"></span><span>${p.message}</span></div>`)}</section>` : ''}
${runsCard(S, sc)}</div>
${inspector(S, sc, m)}</div></main></div>`;
}

// ---- workbook map / rail pieces ------------------------------------------------------------------------------------------------------------
export function scenarioCards(S) {
  const m = bm();
  const list = m.scenarios || [];
  return html`<div style="display: flex; align-items: center; gap: 10px; margin-top: 8px"><h2 class="ttl" style="font-size: 17px">Scenarios</h2>
<span class="chip mono">${list.length}</span><span style="font-size: 12.5px; color: var(--tx3)">several tests at the same time, with sync points</span>
<span style="flex: 1"></span><button class="btn btn-sm" data-act="sc-new">${icon('plus', 13)} New scenario</button></div>
${list.length ? html`<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px">${list.map((sc) => {
    const worst = sc.problems.some((p) => p.severity === 'error') ? 'var(--fail)' : sc.problems.some((p) => p.severity === 'warning') ? 'var(--warn)' : '';
    return html`<div class="card" data-key="scc-${sc.name}" style="padding: 14px; display: flex; flex-direction: column; gap: 8px; ${sc.enabled ? '' : 'opacity: .7'}">
<div style="display: flex; align-items: center; gap: 8px"><span style="color: var(--k-flow); display: inline-flex">${icon('sync', 16)}</span>
<a href="${buildUrl(S.build.name, 'scenario', sc.name)}" class="disp trunc" style="font-size: 16px; font-weight: 700; color: var(--tx)">${sc.name}</a><span style="flex: 1"></span>
${worst ? html`<span class="pdot" style="background: ${worst}" title="${sc.problems.length} problem(s)"></span>` : ''}</div>
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">${sc.lanes.length} lane${sc.lanes.length === 1 ? '' : 's'} · ${sc.syncs.length} sync line${sc.syncs.length === 1 ? '' : 's'} · ${sc.orders.length} order marker${sc.orders.length === 1 ? '' : 's'}</span>
<span style="display: flex; gap: 5px; flex-wrap: wrap">${sc.lanes.map((l) => html`<span class="tag"><b style="color: var(--acc)">${l.key}</b>&nbsp;${l.test}${l.usesRow ? ` · row ${l.usesRow}` : ''}</span>`)}</span>
${sc.notes ? html`<span class="trunc" style="font-size: 12px; color: var(--tx2)">${sc.notes}</span>` : ''}</div>`;
  })}</div>` : ''}`;
}

export function scenarioRailItems(S) {
  const m = bm();
  const list = m.scenarios || [];
  return html`<div style="display: flex; flex-direction: column; gap: 2px"><div style="display: flex; align-items: center; justify-content: space-between; padding: 0 6px 2px"><span class="lbl">Scenarios</span>
<button class="btn btn-ghost btn-sm" style="height: 22px; padding: 0 5px" data-act="sc-new" aria-label="New scenario">${icon('plus', 12)}</button></div>
${list.map((sc) => { const on = S.build.screen === 'scenario' && S.build.scenario === sc.name; return html`<a class="rail-item ${on ? 'on' : ''}" data-key="sr-${sc.name}" href="${buildUrl(S.build.name, 'scenario', sc.name)}" aria-current="${on ? 'page' : 'false'}">
<span style="color: var(--tx3); display: inline-flex">${icon('sync', 14)}</span><span class="trunc" style="flex: 1">${sc.name}</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${sc.lanes.length}</span></a>`; })}</div>`;
}

// ---- actions -----------------------------------------------------------------------------------------------------------------------------
function nextKey(def) { return [...LETTERS].find((k) => !def.lanes.some((l) => l.key === k)) || 'Z'; }

async function newScenario() {
  const m = bm();
  const name = (window.prompt('Name of the new scenario (what it tests, e.g. "Two agents edit one policy")', '') || '').trim();
  if (!name) return;
  const web = m.tests.filter((t) => t.kind === 'web');
  const twice = web.find((t) => t.dataRows.filter((r) => r.enabled !== false).length >= 2);
  let lanes = [];
  if (twice) {
    const rows = twice.dataRows.filter((r) => r.enabled !== false);
    lanes = [{ key: 'A', test: twice.id, dataRow: rows[0].row, label: rows[0].label || '' }, { key: 'B', test: twice.id, dataRow: rows[1].row, label: rows[1].label || '' }];
  } else if (web.length) {
    lanes = web.slice(0, 2).map((t, i) => ({ key: LETTERS[i], test: t.id, dataRow: null, label: '' }));
  }
  const applied = await save({ name, enabled: true, timeout: null, notes: '', lanes, syncs: [], orders: [] });
  if (applied) location.hash = buildUrl(S.build.name, 'scenario', name);
}

async function runScenario() {
  const m = bm();
  const sc = currentScenario();
  if (!sc) return;
  if (m.status.modified) { toast('Save to Excel first: a run reads the saved workbook, not the draft.', 6000); return; }
  if ((m.environments.production || []).includes(m.environment)) { toast(`${m.environment} is production: start this from New run, which asks you to confirm.`, 7000); return; }
  try {
    const res = await api('/api/runs', { method: 'POST', body: { workbook: S.build.name, tests: [sc.name], env: m.environment || null } });
    await loadRuns();
    location.hash = `#/run/${res.run_id}`;
  } catch (e) { toast(e.message, 7000); }
}

const num = (v) => (v === '' || v == null ? null : Number(v));
const findSync = (def, name) => def.syncs.find((s) => s.name === name);
const findOrder = (def, name) => def.orders.find((o) => o.name === name);

export const acts = {
  'sc-new': newScenario,
  'sc-run': runScenario,
  'sc-select'(el) { ui.sel = { kind: el.dataset.kind, key: el.dataset.key || '' }; rerender(); },
  'sc-add-lane'() {
    edit((def) => {
      const last = def.lanes[def.lanes.length - 1];
      const m = bm();
      const t = m.tests.find((x) => last && x.id === last.test) || m.tests.find((x) => x.kind === 'web');
      if (!t) { toast('Add a test first: a lane runs an existing test.'); return false; }
      const used = def.lanes.filter((l) => l.test === t.id).map((l) => l.dataRow);
      const row = (t.dataRows.find((r) => !used.includes(r.row)) || {}).row || null;
      const key = nextKey(def);
      def.lanes.push({ key, test: t.id, dataRow: row, label: '' });
      ui.sel = { kind: 'lane', key };
    });
  },
  'sc-remove-lane'(el) {
    const key = el.dataset.key;
    edit((def) => {
      def.lanes = def.lanes.filter((l) => l.key !== key);
      def.syncs.forEach((s) => { s.points = s.points.filter((p) => p.lane !== key); });
      def.orders = def.orders.filter((o) => o.first.lane !== key && o.then.lane !== key);
      ui.sel = { kind: 'scenario', key: '' };
    });
  },
  'sc-add-sync'() {
    const sc = currentScenario();
    edit((def) => {
      let n = def.syncs.length + 1;
      while (findSync(def, `Sync ${n}`)) n += 1;
      const name = `Sync ${n}`;
      def.syncs.push({ name, timeout: null, points: sc.lanes.map((l) => ({ lane: l.key, block: (l.blocks[Math.min(n - 1, Math.max(0, l.blocks.length - 2))] || {}).ref || '' })) });
      ui.sel = { kind: 'sync', key: name };
    });
  },
  'sc-add-order'() {
    const sc = currentScenario();
    edit((def) => {
      const [a, b] = sc.lanes;
      const name = `${a.key} before ${b.key}${findOrder(def, `${a.key} before ${b.key}`) ? ` (${def.orders.length + 1})` : ''}`;
      const last = (lane) => (lane.blocks.length > 1 ? lane.blocks[lane.blocks.length - 2].ref : '');
      def.orders.push({ name, timeout: null, first: { lane: a.key, block: last(a) }, then: { lane: b.key, block: last(b) } });
      ui.sel = { kind: 'order', key: name };
    });
  },
  'sc-delete-sync'(el) { edit((def) => { def.syncs = def.syncs.filter((s) => s.name !== el.dataset.key); ui.sel = { kind: 'scenario', key: '' }; }); },
  'sc-delete-order'(el) { edit((def) => { def.orders = def.orders.filter((o) => o.name !== el.dataset.key); ui.sel = { kind: 'scenario', key: '' }; }); },
  async 'sc-delete'() {
    const sc = currentScenario();
    if (!sc || !window.confirm(`Delete the scenario “${sc.name}”? Its tests stay as they are. (Undo brings it back.)`)) return;
    const applied = await applyOps([{ op: 'delete_scenario', name: sc.name }]);
    if (applied) location.hash = buildUrl(S.build.name, 'map');
  },
};

export const changes = {
  'sc-rename'(el) {
    const sc = currentScenario();
    const name = el.value.trim();
    if (!sc || !name || name === sc.name) return;
    const def = definitionOf(sc);
    def.name = name;
    save(def, sc.name);
  },
  'sc-enabled'(el) { edit((def) => { def.enabled = el.checked; }); },
  'sc-lane-test'(el) { edit((def) => { const l = def.lanes.find((x) => x.key === el.dataset.key); l.test = el.value; l.dataRow = null; }); },
  'sc-lane-row'(el) { edit((def) => { def.lanes.find((x) => x.key === el.dataset.key).dataRow = el.value ? Number(el.value) : null; }); },
  'sc-sync-name'(el) {
    const to = el.value.trim();
    if (!to) return;
    edit((def) => { const s = findSync(def, el.dataset.key); if (findSync(def, to)) return false; s.name = to; ui.sel = { kind: 'sync', key: to }; });
  },
  'sc-sync-point'(el) {
    edit((def) => {
      const s = findSync(def, el.dataset.key);
      s.points = s.points.filter((p) => p.lane !== el.dataset.lane);
      if (el.value !== '-') s.points.push({ lane: el.dataset.lane, block: el.value });
      const order = def.lanes.map((l) => l.key);
      s.points.sort((x, y) => order.indexOf(x.lane) - order.indexOf(y.lane));
    });
  },
  'sc-order-name'(el) {
    const to = el.value.trim();
    if (!to) return;
    edit((def) => { const o = findOrder(def, el.dataset.key); if (findOrder(def, to)) return false; o.name = to; ui.sel = { kind: 'order', key: to }; });
  },
  'sc-order-lane'(el) { edit((def) => { const end = findOrder(def, el.dataset.key)[el.dataset.end]; end.lane = el.value; end.block = ''; }); },
  'sc-order-block'(el) { edit((def) => { findOrder(def, el.dataset.key)[el.dataset.end].block = el.value; }); },
};

export const inputs = {
  'sc-notes'(el) { const v = el.value; editDebounced((def) => { def.notes = v; }); },
  'sc-timeout'(el) { const v = num(el.value); if (v != null && v < 5) return; editDebounced((def) => { def.timeout = v; }); },
  'sc-lane-label'(el) { const v = el.value, key = el.dataset.key; editDebounced((def) => { def.lanes.find((x) => x.key === key).label = v; }); },
  'sc-sync-timeout'(el) { const v = num(el.value), key = el.dataset.key; if (v != null && v < 5) return; editDebounced((def) => { findSync(def, key).timeout = v; }); },
  'sc-order-timeout'(el) { const v = num(el.value), key = el.dataset.key; if (v != null && v < 5) return; editDebounced((def) => { findOrder(def, key).timeout = v; }); },
};
