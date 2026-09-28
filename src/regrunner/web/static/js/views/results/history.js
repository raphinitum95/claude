// The Results tab's left rail (every batch and solo run, searchable and filterable) and the landing screen it opens to.
import { html } from '../../util.js';
import { icon } from '../../icons.js';
import { dur, isToday, plural } from '../../fmt.js';
import { S } from '../../state.js';
import { resultsUrl } from './actions.js';

function testsLabelOf(r) {
  const ids = r.test_ids || [];
  if (ids.length === 1) return ids[0];
  return plural(ids.length || r.tests || (r.summary && r.summary.tests) || 0, 'test');
}

function baseNameOf(path) { return String(path || '').split(/[\\/]/).pop(); }

function mergedItems() {
  const h = S.results.history;
  const batches = (h.batches || []).map((b) => ({
    kind: 'batch', id: b.id, started_at: b.started_at, workbooks: b.workbooks, environment: b.environment, active: b.active,
    title: b.label, sub: `${plural(b.workbooks.length, 'workbook')} · ${plural(b.tests, 'test')}`,
    verdict: b.active ? 'run' : b.failed ? 'fail' : 'pass',
    tag: b.active ? `${b.percent}% running` : `${b.passed} passed${b.failed ? `, ${b.failed} failed` : ''}`,
  }));
  const solo = S.runs.filter((r) => !r.batch_id).map((r) => ({
    kind: 'run', id: r.run_id, started_at: r.started_at, workbooks: [baseNameOf(r.workbook)], environment: r.environment, active: r.active,
    title: r.run_id, sub: `${baseNameOf(r.workbook)} · ${testsLabelOf(r)}`,
    verdict: r.active ? 'run' : r.status === 'PASSED' ? 'pass' : 'fail',
    tag: r.active ? 'running' : r.status.toLowerCase() + (r.duration_s != null ? ` · ${dur(r.duration_s)}` : ''),
  }));
  return [...batches, ...solo].sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
}

function filteredItems() {
  const h = S.results.history;
  const q = h.q.trim().toLowerCase();
  return mergedItems().filter((it) =>
    (!q || it.title.toLowerCase().includes(q) || it.workbooks.some((w) => w.toLowerCase().includes(q))) &&
    (!h.workbook || it.workbooks.includes(h.workbook)) &&
    (!h.environment || it.environment === h.environment) &&
    (!h.status || it.verdict === h.status));
}

function itemUrl(it) { return it.kind === 'batch' ? resultsUrl('batch', it.id) : resultsUrl('run', it.id); }

function itemRow(S, it) {
  const on = (S.results.screen === 'batch' && S.results.batch.id === it.id) || (S.route.name === 'run' && S.route.id === it.id);
  const color = { run: 'var(--acc)', pass: 'var(--pass)', fail: 'var(--fail)' }[it.verdict];
  return html`<a href="${itemUrl(it)}" class="side-run ${on ? 'on' : ''}" style="text-decoration: none" data-key="${it.kind}-${it.id}">
<span class="pdot" style="margin-top: 7px; background: ${color}"></span>
<span style="min-width: 0; flex: 1"><span class="mono" style="display: block; font-size: 12px; font-weight: 600">${it.title}</span>
<span class="trunc" style="display: block; font-size: 12px; color: var(--tx2)">${it.sub}</span>
<span style="font-size: 11.5px; color: ${color}">${it.tag}</span></span></a>`;
}

export function resultsRail(S) {
  const h = S.results.history;
  const all = mergedItems();
  const envs = [...new Set(all.map((i) => i.environment).filter(Boolean))];
  const wbs = [...new Set(all.flatMap((i) => i.workbooks))].sort();
  const items = filteredItems();
  const today = items.filter((i) => isToday(i.started_at));
  const earlier = items.filter((i) => !isToday(i.started_at));
  const group = (label, list) => (list.length ? html`<div><div class="lbl" style="padding: 0 10px 8px">${label}</div>
<div style="display: flex; flex-direction: column; gap: 4px">${list.map((it) => itemRow(S, it))}</div></div>` : '');
  return html`<aside class="side" aria-label="Results">
<div class="field" style="min-height: 34px">${icon('search', 14)}
<input data-input="results-filter" data-field="q" value="${h.q}" placeholder="Find a batch, run or workbook"
style="border: none; background: transparent; flex: 1; font-size: 12.5px; color: var(--tx)"></div>
<div style="display: flex; gap: 6px; flex-wrap: wrap">
${wbs.map((w) => html`<button class="tag ${h.workbook === w ? 'tag-acc' : ''}" data-act="results-toggle-filter" data-field="workbook" data-val="${w}">${w}</button>`)}
</div>
<div style="display: flex; gap: 6px; flex-wrap: wrap">
${envs.map((e) => html`<button class="tag ${h.environment === e ? 'tag-acc' : ''}" data-act="results-toggle-filter" data-field="environment" data-val="${e}">${e}</button>`)}
<button class="tag ${h.status === 'fail' ? 'tag-fail' : ''}" data-act="results-toggle-filter" data-field="status" data-val="fail">${icon('warn', 11)} Failed only</button>
</div>
<a class="btn btn-sm" href="${resultsUrl('compare')}" style="text-decoration: none">${icon('grid', 13)} Compare runs</a>
${items.length ? html`${group('Today', today)}${group('Earlier', earlier)}` : html`<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 20px 14px; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('clock', 24)}</div><div style="font-weight: 650; margin-top: 8px">Nothing here yet</div>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 2px">${all.length ? 'No batch or run matches this filter.' : 'Finished runs and batches show up here.'}</div></div>`}
</aside>`;
}

export function historyView(S) {
  const h = S.results.history;
  if (h.loading && !h.batches) return html`<div class="page"><div class="skel" style="height: 46px; width: 300px"></div><div class="skel" style="height: 220px"></div></div>`;
  if (h.error) return html`<div class="page"><b>Could not load the Results tab.</b><p style="color: var(--tx2)">${h.error.message}</p></div>`;
  const items = filteredItems();
  const picked = items[0];
  return html`<div class="page" style="max-width: 720px; margin: 8vh auto; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('history', 30)}</div>
<h1 class="disp" style="font-size: 26px; margin-top: 10px">Pick a batch or run</h1>
<p style="color: var(--tx2)">Search or filter on the left, or jump into the most recent one below.</p>
${picked ? html`<a class="btn btn-pri" style="margin: 10px auto; text-decoration: none" href="${itemUrl(picked)}">${icon('external', 15)} Open ${picked.title}</a>` : ''}
<a class="btn" style="margin: 6px auto; text-decoration: none" href="${resultsUrl('compare')}">${icon('grid', 15)} Compare runs across workbooks</a>
</div>`;
}
