// Concurrency scenarios on the Run screens (P12): the lanes of each scenario side by side, the sync points they reached, and each lane's own
// result.  One renderer for a live run (views/live.js: runstate.js tests, which carry `lane` and the `scenario_sync` events as `syncs`) and a
// finished one (views/results.js: results.json tests, which carry the same two fields).  A scenario's lanes are ordinary tests of the run
// (ids "<scenario> · <lane>"), so everything else on these screens already shows them one by one; this only groups them.
import { html } from '../util.js';
import { icon, pill } from '../icons.js';
import { timeOf, dur } from '../fmt.js';

const at = (e) => (e.atMs != null ? timeOf(new Date(e.atMs).toISOString()) : timeOf(e.at));
const OVER = new Set(['released', 'ended', 'timeout']);

/** A test (live or finished) as a lane: {id, key, label, test, status, error, done, total, step, syncs}. */
function laneOf(t, live) {
  return { id: t.id, key: t.lane.key, label: t.lane.label || '', test: t.lane.test || t.lane.sheet || '', row: t.lane.data_row, status: t.status,
    error: t.error || '', done: live ? t.done : (t.passed || 0) + (t.failed || 0), total: live ? t.total : t.total_steps || 0,
    step: live ? t.step : null, syncs: t.syncs || [] };
}

/** [{name, notes, lanes, syncs: [{name, lanes}], orders: [{name, first, then}]}] for every scenario that has a lane among ``tests``. */
export function scenarioGroups(tests, described, live) {
  const byName = new Map();
  for (const t of tests) {
    if (!t.lane || !t.lane.scenario) continue;
    if (!byName.has(t.lane.scenario)) {
      const d = (described || []).find((x) => x.name === t.lane.scenario);
      byName.set(t.lane.scenario, { name: t.lane.scenario, notes: d ? d.notes : '', syncs: d ? d.syncs : null, orders: d ? d.orders : null, lanes: [] });
    }
    byName.get(t.lane.scenario).lanes.push(laneOf(t, live));
  }
  for (const g of byName.values()) {
    g.lanes.sort((a, b) => a.key.localeCompare(b.key));
    if (!g.syncs) {                                            // (a finished run: worked out from what the lanes met)
      const seen = new Map();
      for (const l of g.lanes) for (const e of l.syncs) if (e.kind === 'sync') seen.set(e.item, [...new Set([...(seen.get(e.item) || []), l.key])]);
      g.syncs = [...seen].map(([name, lanes]) => ({ name, lanes }));
    }
    if (!g.orders) {
      const seen = new Map();
      for (const l of g.lanes) for (const e of l.syncs) if (e.kind === 'order') { const o = seen.get(e.item) || { name: e.item, first: '', then: '' }; o[e.role === 'first' ? 'first' : 'then'] = l.key; seen.set(e.item, o); }
      g.orders = [...seen.values()];
    }
  }
  return [...byName.values()];
}

const lastAt = (lane, item) => { const own = lane.syncs.filter((e) => e.item === item); return own[own.length - 1] || null; };

function syncChip(g, s) {
  const lanes = g.lanes.filter((l) => s.lanes.includes(l.key));
  const last = lanes.map((l) => [l, lastAt(l, s.name)]);
  const gaveUp = last.filter(([, e]) => e && e.state === 'timeout').map(([l]) => l.key);
  if (gaveUp.length) return html`<span class="tag tag-fail" title="${last.map(([, e]) => (e ? e.message : '')).join(' ')}">${icon('x', 11)} ${s.name} · ${gaveUp.join(', ')} gave up waiting</span>`;
  if (last.length && last.every(([, e]) => e && OVER.has(e.state))) {
    const released = last.filter(([, e]) => e.state === 'released');
    const when = released.length ? at(released.reduce((a, [, e]) => ((e.atMs || Date.parse(e.at)) > (a.atMs || Date.parse(a.at)) ? e : a), released[0][1])) : '';
    const ended = last.filter(([, e]) => e.state === 'ended').map(([l]) => l.key);
    return html`<span class="tag tag-pass">${icon('check', 11)} ${s.name} · ${ended.length ? `${ended.join(', ')} ended first` : 'all arrived'}${when ? ` · released ${when}` : ''}</span>`;
  }
  const waiting = last.filter(([, e]) => e && (e.state === 'arrived' || e.state === 'waiting')).map(([l]) => l.key);
  const notThere = last.filter(([, e]) => !e).map(([l]) => l.key);
  if (waiting.length) return html`<span class="tag tag-warn">${s.name} · ${waiting.join(', ')} waiting${notThere.length ? ` · ${notThere.join(', ')} not there yet` : ''}</span>`;
  return html`<span class="tag">${s.name} · not reached</span>`;
}

function orderChip(g, o) {
  const then = g.lanes.find((l) => l.key === o.then);
  const e = then ? lastAt(then, o.name) : null;
  if (e && e.state === 'released') return html`<span class="tag tag-pass" title="${e.message}">${icon('check', 11)} ${o.name}</span>`;
  if (e && e.state === 'timeout') return html`<span class="tag tag-fail" title="${e.message}">${icon('x', 11)} ${o.name} · gave up</span>`;
  if (e && e.state === 'waiting') return html`<span class="tag tag-warn">${o.name} · ${o.then} waits for ${o.first}</span>`;
  return html`<span class="tag">${o.name}</span>`;
}

const TONE = { released: 'var(--pass)', done: 'var(--pass)', arrived: 'var(--warn)', waiting: 'var(--warn)', ended: 'var(--tx3)', timeout: 'var(--fail)' };

function laneState(l, live) {
  const open = l.syncs.length ? l.syncs[l.syncs.length - 1] : null;
  if (live && l.status === 'RUNNING' && open && (open.state === 'arrived' || open.state === 'waiting')) return [`At ${open.item} · waiting for ${(open.waiting || []).join(' and ') || 'the others'}`, 'var(--warn)'];
  if (live && l.status === 'RUNNING') return [l.step ? `Running step ${l.step.n}` : 'Starting', 'var(--acc)'];
  if (l.status === 'QUEUED') return ['Starts with the others', 'var(--pend)'];
  return [null, null];
}

function laneColumn(l, live, runId) {
  const [state, color] = laneState(l, live);
  const pct = l.total ? Math.min(100, Math.round((100 * l.done) / l.total)) : 0;
  const name = html`${l.test}${l.row ? ` · row ${l.row}` : ''}${l.label ? ` · ${l.label}` : ''}`;
  return html`<section class="card" data-key="lane-${l.id}" style="flex: 1; min-width: 240px; padding: 16px; display: flex; flex-direction: column; gap: 12px">
<div style="display: flex; align-items: center; gap: 10px"><span class="mono" style="width: 28px; height: 28px; flex: none; border-radius: 8px; display: grid; place-items: center; background: var(--acc-soft); color: var(--acc); font-weight: 700">${l.key}</span>
<div style="display: flex; flex-direction: column; min-width: 0">${runId ? html`<a class="trunc" style="font-weight: 700; color: var(--tx)" href="#/results/test/${runId}/${encodeURIComponent(l.id)}">${name}</a>` : html`<b class="trunc">${name}</b>`}
${state ? html`<span style="font-size: 12px; color: ${color}">${state}</span>` : html`<span>${pill(l.status)}</span>`}</div></div>
<div style="height: 6px; border-radius: 99px; background: var(--track); overflow: hidden"><div style="width: ${pct}%; height: 100%; background: ${color || (l.status === 'PASSED' ? 'var(--pass)' : 'var(--fail)')}"></div></div>
${l.syncs.filter((e) => e.state !== 'arrived' || l.syncs[l.syncs.length - 1] === e).map((e) => html`<div style="display: flex; align-items: flex-start; gap: 9px; padding: 7px 10px; border-radius: 9px; font-size: 12.5px; ${e.kind === 'sync' ? 'background: var(--acc-soft); border: 1px solid var(--acc-line)' : 'border: 1px solid var(--line2)'}">
<span style="color: ${TONE[e.state] || 'var(--tx2)'}; display: inline-flex; margin-top: 1px">${icon(e.kind === 'sync' ? 'sync' : 'arrowr', 13)}</span>
<span style="flex: 1; min-width: 0">${e.message}</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${at(e)}${e.waited_s ? ` · ${dur(e.waited_s)}` : ''}</span></div>`)}
${!live && l.error ? html`<div style="font-size: 12px; color: var(--tx2); overflow-wrap: anywhere">${l.error.split('\n')[0]}</div>` : ''}
</section>`;
}

function section(g, live, runId) {
  return html`<section data-key="scenario-${g.name}" style="display: flex; flex-direction: column; gap: 14px">
<div style="display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap"><span class="eyebrow">Scenario${live ? ' · live' : ''}</span><h2 class="ttl" style="font-size: 20px">${g.name}</h2>
${g.notes ? html`<span style="font-size: 12.5px; color: var(--tx2)">${g.notes}</span>` : ''}</div>
${g.syncs.length || g.orders.length ? html`<div style="display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line2); flex-wrap: wrap">
<span class="lbl">Sync points</span>${g.syncs.map((s) => syncChip(g, s))}${g.orders.map((o) => orderChip(g, o))}</div>` : ''}
<div style="display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap">${g.lanes.map((l) => laneColumn(l, live, runId))}</div>
<div class="bn">${icon('info', 15, 'color: var(--tx3)')}<span>Results report each lane on its own. A lane that fails still releases the others at the next sync point, so one failure never hangs the scenario.</span></div></section>`;
}

/** The live run's scenarios (views/live.js). */
export function scenarioLive(run) {
  const groups = scenarioGroups(run.order.map((id) => run.tests[id]), run.scenarios, true);
  return groups.map((g) => section(g, run.status === 'RUNNING', null));
}

/** A finished run's scenarios (views/results.js): each lane links to its own test page in the Results tab. */
export function scenarioFinished(results, runId) {
  return scenarioGroups(results.tests || [], null, false).map((g) => section(g, false, runId));
}
