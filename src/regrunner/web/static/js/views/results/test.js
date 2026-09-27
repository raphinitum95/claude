// The test page: where it stopped on the block map, evidence around the failure, backup locators, this test's history.
import { html } from '../../util.js';
import { icon, pill } from '../../icons.js';
import { dur, timeOf } from '../../fmt.js';
import { banner } from '../shell.js';
import { failedStepCard } from '../results.js';
import { buildUrl } from '../build/actions.js';
import { resultsUrl } from './actions.js';
import { trendStrip } from './batch.js';

const BLOCK_COLOR = { pass: 'var(--pass)', fail: 'var(--fail)', warn: 'var(--warn)', pend: 'var(--pend)' };

function blockMap(blocks) {
  if (!blocks.length) return html`<p style="font-size: 12.5px; color: var(--tx3)">The workbook this ran from is not available, so no block map.</p>`;
  return html`<div style="display: flex; gap: 4px; flex-wrap: wrap">
${blocks.map((b) => html`<div title="${b.title} · ${b.count} step${b.count === 1 ? '' : 's'}"
style="flex: ${Math.max(b.count, 4)} 1 0; min-width: 44px; height: 46px; border-radius: 8px; padding: 6px 7px; display: flex; flex-direction: column; justify-content: space-between;
background: color-mix(in srgb, ${BLOCK_COLOR[b.status] || 'var(--tx3)'} 14%, var(--surface)); border: 1px solid color-mix(in srgb, ${BLOCK_COLOR[b.status] || 'var(--tx3)'} 45%, transparent);
${b.status === 'fail' ? 'box-shadow: 0 0 0 2px var(--fail)' : ''}">
<span class="trunc" style="font-size: 11px; font-weight: 600">${b.title}</span><span class="mono" style="font-size: 10px; color: var(--tx3)">${b.count}</span></div>`)}
</div>`;
}

function stepRow(runId, s) {
  if (s.status === 'FAILED') return failedStepCard({}, runId, s);
  return html`<div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 9px">
<span class="mono" style="width: 46px; font-size: 11.5px; color: var(--tx3)">${s.seq}</span>
<span class="pdot" style="background: ${s.status === 'PASSED' ? 'var(--pass)' : 'var(--tx3)'}"></span>
<span class="trunc" style="flex-grow: 1; font-size: 13px">${s.name || s.action}</span></div>`;
}

function backupsCard(backups, steps) {
  const rows = Object.entries(backups || {});
  if (!rows.length) return '';
  return html`<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 8px">
<span class="ttl" style="font-size: 15px">Backup locators</span>
${rows.map(([row, list]) => {
    const s = steps.find((x) => String(x.row) === row);
    return html`<div style="font-size: 12.5px"><b>${s ? s.name || s.action : `row ${row}`}</b>
<div style="display: flex; flex-direction: column; gap: 2px; margin-top: 4px">${list.map((l) => html`<span class="mono" style="font-size: 11.5px; color: var(--tx2)">${l}</span>`)}</div></div>`;
  })}
<span style="font-size: 11.5px; color: var(--tx3)">Probed on a primary miss once page gates and backup probing (P07) are built; for now this only lists what the step defines.</span>
</section>`;
}

export function testView(S) {
  const t = S.results.test;
  if (t.loading && !t.page) return html`<div class="page"><div class="skel" style="height: 46px; width: 340px"></div><div class="skel" style="height: 260px"></div></div>`;
  if (t.error) return html`<div class="page"><h1 class="disp" style="font-size: 28px">${t.error.status === 404 ? 'That test could not be found' : 'Could not open this test'}</h1>
${banner('fail', 'failc', t.error.message)}</div>`;
  const run = t.run.results;
  const meta = t.run.meta;
  const test = (run.tests || []).find((x) => x.id === t.testId);
  if (!test) return html`<div class="page">${banner('fail', 'failc', `${t.testId} is not in run ${t.runId}.`)}</div>`;
  const failedSteps = (test.steps || []).filter((s) => s.status === 'FAILED');
  const shown = t.showAllFails ? failedSteps : failedSteps.slice(0, 5);
  const wb = String(meta.workbook || '').split(/[\\/]/).pop().replace(/\.(xlsx|xlsm)$/i, '');
  return html`<div class="page">
<div style="display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--tx3)">
<a href="#/run/${t.runId}">${t.runId}</a>${icon('chevr', 12)}<span style="color: var(--tx)">${t.testId}</span></div>
<div style="display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap">
<div style="display: flex; flex-direction: column; gap: 4px">
<h1 class="disp" style="font-size: 28px; font-weight: 700; margin: 0">${test.status === 'PASSED' ? `${t.testId} passed` : `${t.testId} ${test.status.toLowerCase()}${failedSteps.length ? ` at step ${failedSteps[0].seq}` : ''}`}</h1>
<span class="mono" style="font-size: 12.5px; color: var(--tx3)">${wb} · ${meta.environment || ''} · ${dur(test.duration_s)}${test.ended_at ? ' · ' + timeOf(test.ended_at) : ''}</span>
</div><span style="flex-grow: 1"></span>${pill(test.status)}
<a class="btn btn-pri" href="${buildUrl(wb, 'test', test.sheet || t.testId)}" style="text-decoration: none">${icon('pencil', 14)} Fix in builder</a>
</div>
<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px">
<span class="lbl">Where it stopped</span>${blockMap(t.page.blocks)}
</section>
<div style="display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start">
<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 4px">
<span class="ttl" style="font-size: 16px; padding: 0 4px 8px">${failedSteps.length ? `Failed steps · ${failedSteps.length}` : 'No failed steps'}</span>
${shown.map((s) => stepRow(t.runId, s))}
${failedSteps.length > 5 ? html`<button class="lnk" data-act="results-toggle-fails">${t.showAllFails ? 'Show fewer' : `Show all ${failedSteps.length} failed steps`}</button>` : ''}
</section>
<div style="display: flex; flex-direction: column; gap: 14px">
${backupsCard(t.page.backups, test.steps || [])}
<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px">
<div style="display: flex; align-items: center; gap: 8px"><span class="ttl" style="font-size: 15px">This test, last ${t.page.history.length} run${t.page.history.length === 1 ? '' : 's'}</span></div>
${t.page.history.length ? trendStrip(t.page.history) : html`<span style="font-size: 12.5px; color: var(--tx3)">No earlier runs of this workbook yet.</span>`}
<a class="lnk" style="font-size: 12.5px" href="${resultsUrl('compare')}">Compare with other tests</a>
</section>
</div></div>
</div>`;
}
