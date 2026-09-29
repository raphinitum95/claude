// The batch page: verdict, what changed since last time, failures grouped by cause, every test with a trend strip.
import { html } from '../../util.js';
import { icon, pill } from '../../icons.js';
import { dur, timeOf, plural } from '../../fmt.js';
import { banner } from '../shell.js';
import { runFileUrl } from '../../api.js';
import { resultsUrl } from './actions.js';

const VERDICT_TAG = { new: ['tag-fail', 'new failure'], failing: ['tag-fail', 'failing'], flaky: ['tag-warn', 'flaky'],
                     fixed: ['tag-pass', 'fixed'], stable: ['', ''], no_history: ['', ''] };

export function trendStrip(seq) {
  const color = { PASSED: 'var(--pass)', FAILED: 'var(--fail)', ERROR: 'var(--fail)' };
  return html`<span style="display: flex; gap: 2px" title="Last ${seq.length} run${seq.length === 1 ? '' : 's'}, oldest first">
${seq.map((h) => html`<span style="width: 7px; height: 16px; border-radius: 2px; background: ${color[h.status] || 'var(--pend)'}" title="${h.run_id}: ${h.status}"></span>`)}
</span>`;
}

function causeGroup(g) {
  return html`<div class="card" style="overflow: hidden">
<div style="padding: 11px 14px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--line)">
<b>${g.title}</b><span class="tag ${g.kind === 'other' ? '' : 'tag-fail'}">${g.items.length}</span>
<span style="font-size: 12px; color: var(--tx3)">${g.why}</span></div>
${g.items.map((it) => html`<div style="display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; padding: 10px 14px; border-top: 1px solid var(--line)">
<b style="font-size: 13px; width: 180px; max-width: 100%" class="trunc">${it.test}</b>
<span class="trunc" style="font-size: 12.5px; color: var(--tx2); flex-grow: 1">${it.message}</span>
${VERDICT_TAG[it.verdict] && VERDICT_TAG[it.verdict][1] ? html`<span class="tag ${VERDICT_TAG[it.verdict][0]}">${VERDICT_TAG[it.verdict][1]}</span>` : ''}
<a class="btn btn-sm" href="${resultsUrl('test', it.run_id, it.test)}" style="text-decoration: none">Open</a></div>`)}
</div>`;
}

/** One row per run of the batch: its verdict, the full run page (the same one the Run tab shows) and its HTML report, each opening from here. */
function runsCard(bt) {
  const runs = bt.runs || [];
  return html`<section class="card" style="overflow: hidden">
<div style="padding: 12px 16px; display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 17px">Runs in this batch</span>
<span style="font-size: 12.5px; color: var(--tx3)">One run per workbook. Open its full results or its HTML report.</span></div>
${runs.map((r) => {
    const wb = String(r.workbook || '').split(/[\\/]/).pop() || r.run_id;
    return html`<div data-key="run-${r.run_id}" style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; padding: 10px 16px; border-top: 1px solid var(--line)">
<b class="trunc mono" style="font-size: 13px; min-width: 140px; max-width: 100%">${wb}</b>${pill(r.active ? 'RUNNING' : r.status)}
<span class="mono" style="font-size: 11.5px; color: var(--tx3); flex-grow: 1">${r.run_id}${r.duration_s != null ? ' · ' + dur(r.duration_s) : ''}</span>
<a class="btn btn-sm" href="${resultsUrl('run', r.run_id)}" style="text-decoration: none">${icon('list', 13)} Results</a>
${r.report_html ? html`<a class="btn btn-sm" href="${runFileUrl(r.run_id, 'report.html')}" target="_blank" rel="noopener" style="text-decoration: none">${icon('external', 13)} HTML report</a>` : ''}
${r.report_pdf ? html`<a class="btn btn-sm" href="${runFileUrl(r.run_id, 'report.pdf', true)}" style="text-decoration: none">${icon('file', 13)} PDF</a>` : ''}
<button class="icon-btn" style="width: 28px; height: 28px" data-act="ask-delete-run" data-id="${r.run_id}" data-batch="${bt.id}" aria-label="Delete the run of ${wb}" title="Delete this run from the batch">${icon('trash', 13)}</button></div>`;
  })}
</section>`;
}

function allTestsTable(tests) {
  const byWb = new Map();
  for (const t of tests) { if (!byWb.has(t.workbook)) byWb.set(t.workbook, []); byWb.get(t.workbook).push(t); }
  return html`<section class="card" style="overflow: hidden">
<div style="padding: 12px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--line)"><span class="ttl" style="font-size: 17px">All tests</span></div>
${[...byWb.entries()].map(([wb, rows]) => html`<div>
<div style="padding: 9px 16px; background: var(--surface2); border-top: 1px solid var(--line)"><b style="font-size: 13px">${wb}</b></div>
${rows.map((t) => html`<div class="rrow-b" style="display: grid; grid-template-columns: minmax(0, 1fr) 130px 90px 90px 80px; gap: 14px; align-items: center; padding: 8px 16px 8px 26px; border-top: 1px solid var(--line)">
<span style="display: flex; align-items: center; gap: 8px; min-width: 0"><b class="trunc" style="font-size: 13px">${t.id}</b>
${VERDICT_TAG[t.verdict] && VERDICT_TAG[t.verdict][1] ? html`<span class="tag ${VERDICT_TAG[t.verdict][0]}">${VERDICT_TAG[t.verdict][1]}</span>` : ''}</span>
${trendStrip(t.trend)}${pill(t.status)}
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">${t.duration_s != null ? dur(t.duration_s) : '—'}</span>
<a class="lnk" style="font-size: 12.5px" href="${resultsUrl('test', t.run_id, t.id)}">Open</a></div>`)}
</div>`)}
</section>`;
}

export function batchView(S) {
  const b = S.results.batch;
  if (b.loading && !b.data) return html`<div class="page"><div class="skel" style="height: 46px; width: 340px"></div><div class="skel" style="height: 260px"></div></div>`;
  if (b.error) return html`<div class="page"><h1 class="disp" style="font-size: 28px">${b.error.status === 404 ? 'That batch does not exist' : 'Could not open this batch'}</h1>
${banner('fail', 'failc', b.error.message)}</div>`;
  const d = b.data;
  const bt = d.batch;
  const failing = bt.failed > 0;
  return html`<div class="page">
<div style="display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap">
<div style="display: flex; flex-direction: column; gap: 4px">
<span class="eyebrow">Batch ${bt.id}${bt.environment ? ' · ' + bt.environment : ''}</span>
<h1 class="disp" style="font-size: 30px; font-weight: 700; margin: 0">${failing ? `${bt.failed} of ${bt.finished} run${bt.finished === 1 ? '' : 's'} failed` : bt.active ? `${bt.percent}% done` : 'Everything passed'}</h1>
<span class="mono" style="font-size: 12.5px; color: var(--tx3)">${plural(bt.workbooks.length, 'workbook')} · ${plural(bt.tests, 'test')}${bt.started_at ? ' · ' + timeOf(bt.started_at) : ''}</span>
${d.rerun_of ? html`<span style="font-size: 12px; color: var(--tx3)">Re-run of <a href="${resultsUrl('batch', d.rerun_of)}">batch ${d.rerun_of}</a></span>` : ''}
</div><span style="flex-grow: 1"></span>
${!bt.active ? html`<button class="btn" data-act="results-rerun-failed" data-id="${bt.id}" ${failing ? '' : 'disabled'}>${icon('undo', 14)} Re-run failed</button>
<button class="btn" style="color: var(--fail)" data-act="ask-delete-batch" data-id="${bt.id}">${icon('trash', 14)} Delete batch</button>` : ''}
</div>
${d.what_changed.length ? html`<div class="bn">${icon('info', 15, 'color: var(--tx3)')}
<span><b>What changed since last time:</b> ${d.what_changed.join(' · ')}</span></div>` : ''}
${runsCard(bt)}
${d.groups.length ? html`<div style="display: flex; flex-direction: column; gap: 12px">
<div style="display: flex; align-items: center; gap: 10px"><span class="ttl">Failures, grouped by cause</span>
<span style="font-size: 12.5px; color: var(--tx3)">Start at the top; the ones below often go away once it's fixed.</span></div>
${d.groups.map(causeGroup)}</div>` : ''}
${allTestsTable(d.tests)}
</div>`;
}
