// Compare: tests x last N runs, per workbook, with a verdict per row and "what changed" markers.
import { html } from '../../util.js';
import { dayKey } from '../../fmt.js';
import { resultsUrl } from './actions.js';

const CELL_COLOR = { PASSED: 'var(--pass)', FAILED: 'var(--fail)', ERROR: 'var(--fail)' };
const VERDICT_TAG = { new: 'tag-fail', failing: 'tag-fail', flaky: 'tag-warn', fixed: 'tag-pass', stable: '', no_history: '' };

function workbookGrid(wb, columns, rows) {
  const cols = columns[wb] || [];
  const markers = columns[`${wb}__markers`] || [];
  const own = rows.filter((r) => r.workbook === wb);
  if (!cols.length) return html`<div class="card" style="padding: 14px"><b>${wb}</b><p style="color: var(--tx3); font-size: 12.5px">No finished runs yet.</p></div>`;
  return html`<section class="card cmp-card" style="padding: 14px 0 8px; overflow: hidden">
<div style="padding: 0 16px 10px"><b style="font-size: 14px">${wb}</b></div>
<div class="cmp-row" style="display: grid; grid-template-columns: 200px repeat(${cols.length}, minmax(0, 1fr)) 130px; gap: 6px; align-items: end; padding: 0 16px 8px">
<span class="lbl">Test</span>
${cols.map((c) => html`<span style="display: flex; flex-direction: column; align-items: center; font-size: 10.5px; color: var(--tx3)"><b class="mono">${dayKey(c.started_at).slice(5)}</b><span>${c.environment}</span></span>`)}
<span class="lbl">Verdict</span></div>
${own.map((r) => {
    const lastIdx = [...r.cells.keys()].reverse().find((i) => r.cells[i]);
    const link = lastIdx != null ? resultsUrl('test', cols[lastIdx].run_id, r.test) : null;
    return html`<div class="cmp-row" style="display: grid; grid-template-columns: 200px repeat(${cols.length}, minmax(0, 1fr)) 130px; gap: 6px; align-items: center; padding: 5px 16px; border-top: 1px solid var(--line)">
${link ? html`<a href="${link}" class="trunc" style="font-size: 13px; font-weight: 600; text-decoration: none">${r.test}</a>` : html`<b class="trunc" style="font-size: 13px">${r.test}</b>`}
${r.cells.map((c) => html`<span title="${c || 'not in this run'}" style="height: 20px; border-radius: 5px; background: ${CELL_COLOR[c] || 'transparent'}; ${!c ? 'border: 1px dashed var(--line2)' : ''}"></span>`)}
<span>${VERDICT_TAG[r.verdict] ? html`<span class="tag ${VERDICT_TAG[r.verdict]}">${r.verdict}</span>` : ''}</span></div>`;
  })}
${markers.length ? html`<div style="padding: 10px 16px 4px; border-top: 1px solid var(--line); font-size: 12px; color: var(--tx3)">${markers.join(' · ')}</div>` : ''}
</section>`;
}

export function compareView(S) {
  const c = S.results.compare;
  const names = S.workbooks.map((w) => w.name);
  if (c.loading && !c.data) return html`<div class="page"><div class="skel" style="height: 46px; width: 300px"></div><div class="skel" style="height: 220px"></div></div>`;
  return html`<div class="page">
<div style="display: flex; align-items: flex-end; gap: 12px"><div style="display: flex; flex-direction: column; gap: 4px">
<span class="eyebrow">Compare</span><h1 class="disp" style="font-size: 28px; font-weight: 700; margin: 0">Last ${c.n} runs</h1></div></div>
<div style="display: flex; gap: 8px; flex-wrap: wrap">
${names.map((n) => html`<button class="chip ${c.workbooks.includes(n) ? 'chip-acc' : ''}" data-act="results-compare-toggle" data-wb="${n}">${n}</button>`)}
${!names.length ? html`<span style="font-size: 12.5px; color: var(--tx3)">No workbooks yet.</span>` : ''}
</div>
${c.error ? html`<p style="color: var(--fail)">${c.error.message}</p>` : ''}
${c.data ? html`<div style="display: flex; flex-direction: column; gap: 14px">
${(c.workbooks.length ? c.workbooks : Object.keys(c.data.columns).filter((k) => !k.endsWith('__markers'))).map((wb) => workbookGrid(wb, c.data.columns, c.data.rows))}
</div>` : ''}
</div>`;
}
