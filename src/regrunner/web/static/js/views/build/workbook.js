// Workbook map (tests as cards) and variable map (set by / used by, jump to step).
import { html, raw } from '../../util.js';
import { icon } from '../../icons.js';
import { buildUrl, bm } from './actions.js';

const KIND_ICON = { web: 'grid', api: 'api', xml: 'xml' };
const KIND_LABEL = { web: 'Website', api: 'API', xml: 'XML' };
const LAST = { PASSED: ['p-pass', 'check', 'Passed'], FAILED: ['p-fail', 'x', 'Failed'] };

function testCard(S, t) {
  const last = t.lastRun && LAST[t.lastRun.status];
  return html`<div class="card" data-key="tc-${t.id}" style="padding: 14px; display: flex; flex-direction: column; gap: 9px; ${t.enabled ? '' : 'opacity: .6'}">
<div style="display: flex; align-items: center; gap: 8px">
<span style="color: var(--k-${t.kind === 'web' ? 'nav' : t.kind}); display: inline-flex">${icon(KIND_ICON[t.kind] || 'grid', 16)}</span>
<a href="${buildUrl(S.build.name, 'test', t.id)}" class="disp trunc" style="font-size: 16px; font-weight: 700; color: var(--tx)">${t.id}</a>
<span style="flex: 1"></span>
<input type="checkbox" class="sw" ${t.enabled ? raw('checked') : ''} data-change="build-toggle-test" data-test="${t.id}" aria-label="Run ${t.id} in this workbook">
</div>
<div style="display: flex; align-items: center; gap: 6px">
${last ? html`<span class="pill ${last[0]}">${icon(last[1], 11)} ${last[2]}</span>` : html`<span class="pill p-pend">${icon('dashed', 11)} Not run</span>`}
<span class="mono" style="font-size: 11.5px; color: var(--tx3)">${KIND_LABEL[t.kind] || t.kind} · ${t.steps.length} steps</span>
<span style="flex: 1"></span>
${t.paramSheet ? html`<button class="chip" style="height: 22px; font-size: 11px" data-act="build-open-grid" data-sheet="${t.paramSheet}">${icon('table', 11)} ${t.paramSheet}</button>` : ''}
</div>
<div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap">${(t.tags || []).map((g) => html`<span class="tag">${g}</span>`)}
<span style="flex: 1"></span><span style="font-size: 11px; color: var(--tx3)">needs ${(t.needs || []).length} · gives ${(t.provides || []).length}</span></div>
${t.comment ? html`<span class="trunc" style="font-size: 12px; color: var(--tx2)">${t.comment}</span>` : ''}
${!t.listed ? html`<span class="tag tag-warn" title="No DataSheets row: nothing runs this sheet on its own">not listed</span>` : ''}
</div>`;
}

export function workbookMap(S) {
  const m = bm();
  const web = m.tests.filter((t) => t.kind === 'web');
  const other = m.tests.filter((t) => t.kind !== 'web');
  return html`<div class="page" style="max-width: none">
<div style="display: flex; align-items: center; gap: 10px"><h1 class="ttl" style="font-size: 20px">Tests</h1>
<span class="chip mono">${m.tests.length} tests</span>
${m.problemCounts.error ? html`<span class="chip chip-warn">${icon('warn', 13)} ${m.problemCounts.error} problem${m.problemCounts.error === 1 ? '' : 's'}</span>` : ''}
<span style="flex: 1"></span><button class="btn btn-sm" data-act="build-new-test">${icon('plus', 13)} New test</button></div>
${m.tests.length === 0 ? html`<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 30px; text-align: center">
<div style="color: var(--tx3); display: inline-flex">${icon('grid', 26)}</div><div style="font-weight: 650; margin-top: 8px">No tests yet</div>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 2px">Add one to start building.</div></div>` : ''}
<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px">${web.map((t) => testCard(S, t))}${other.map((t) => testCard(S, t))}</div>
</div>`;
}

// ---- variable map -----------------------------------------------------------------------------------------------
const VKIND = { env: ['globe', 'k-nav', 'Environment'], set: ['braces', 'k-save', 'Set by steps'], data: ['table', 'k-input', 'Data'], flag: ['flag', 'k-flow', 'Flag'] };

function varRow(S, v, on) {
  const [i, cls] = v.secret ? ['lock', ''] : (VKIND[v.kind] || VKIND.data);
  return html`<button class="rail-item ${on ? 'on' : ''}" style="height: auto; padding: 7px 10px; align-items: flex-start" data-key="v-${v.key}" data-act="build-select-variable" data-field="${v.key}">
<span style="color: var(--${cls || 'tx3'}); margin-top: 1px; display: inline-flex">${icon(v.secret ? 'lock' : i, 13)}</span>
<span style="display: flex; flex-direction: column; min-width: 0; flex: 1"><span style="font-weight: 600; color: var(--tx)">${v.label}</span>
<span class="mono trunc" style="font-size: 10.5px; color: var(--tx3)">{${v.token}}${v.sources[0] ? ' · ' + v.sources[0].sheet : ''}</span></span>
${!v.setBy.length && !v.sources.length && v.kind !== 'env' ? html`<span class="pdot" style="background: var(--fail); margin-top: 5px" title="Used, never set"></span>` : ''}
</button>`;
}

function usePlace(S, u, label) {
  return html`<button class="card" style="text-align: left; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; width: 100%" data-act="build-jump-step" data-test="${u.test}" data-row="${u.row}">
<span style="font-size: 13px; font-weight: 600">${u.test} · step ${u.n}</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${label || ''}</span></button>`;
}

export function variableMap(S) {
  const m = bm();
  const groups = [['env', 'Environment'], ['set', 'Set by steps'], ['data', 'Data'], ['flag', 'Flags']];
  const bySecret = m.variables.filter((v) => v.secret);
  const rest = m.variables.filter((v) => !v.secret);
  const sel = S.build.selVariable ? m.variables.find((v) => v.key === S.build.selVariable) : (rest[0] || bySecret[0]);
  const left = html`<aside class="scroll" style="width: 320px; flex: none; border-right: 1px solid var(--line); overflow: auto; padding: 12px 10px">
${bySecret.length ? html`<span class="lbl" style="padding: 6px 8px 2px; display: block">Secrets</span>${bySecret.map((v) => varRow(S, v, sel && sel.key === v.key))}` : ''}
${groups.map(([k, label]) => { const vs = rest.filter((v) => v.kind === k); return vs.length ? html`<span class="lbl" style="padding: 8px 8px 2px; display: block">${label}</span>${vs.map((v) => varRow(S, v, sel && sel.key === v.key))}` : ''; })}
${!m.variables.length ? html`<div style="padding: 16px; color: var(--tx3); font-size: 12.5px">No variables yet.</div>` : ''}
</aside>`;
  if (!sel) return html`<div style="flex: 1; display: flex">${left}<main class="scroll" style="flex: 1; padding: 24px"><span style="color: var(--tx3)">Pick a variable.</span></main></div>`;
  const right = html`<main class="scroll" style="flex: 1; min-width: 0; overflow: auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 18px">
<div style="display: flex; align-items: flex-start; gap: 14px"><div style="display: flex; flex-direction: column; gap: 4px">
<span class="disp" style="font-size: 24px; font-weight: 700">${sel.label}</span>
<span class="mono" style="font-size: 12.5px; color: var(--tx3)">{${sel.token}} · set by ${sel.setBy.length} step${sel.setBy.length === 1 ? '' : 's'} · used by ${sel.usedBy.length} step${sel.usedBy.length === 1 ? '' : 's'}</span></div></div>
<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px">
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Kind</span><span style="font-weight: 600">${sel.kind === 'env' ? 'Environment table' : sel.kind === 'set' ? 'Saved by a step' : sel.kind === 'flag' ? 'Row flag' : 'Data column'}</span></div>
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Secret</span><span style="font-weight: 600">${sel.secret ? 'Yes · masked everywhere' : 'No'}</span></div>
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Environment-specific</span><span style="font-weight: 600">${sel.envSpecific ? 'Yes' : 'No'}</span></div></div>
${!sel.setBy.length && !sel.sources.length && sel.kind !== 'env' ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>Used, but nothing sets it: ${sel.neededBy.join(', ') || 'a step'} will fail on "variable ${sel.token} has no value".</span></div>` : ''}
<div style="display: flex; gap: 32px">
<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px"><span class="lbl">Set by</span>
${sel.setBy.length ? sel.setBy.map((u) => usePlace(S, u)) : html`<span style="font-size: 12.5px; color: var(--tx3)">${sel.sources.length ? 'A data column, not a step.' : 'Nothing sets it.'}</span>`}</div>
<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px"><span class="lbl">Used by</span>
${sel.usedBy.length ? sel.usedBy.map((u) => usePlace(S, u, u.column)) : html`<span style="font-size: 12.5px; color: var(--tx3)">Not used.</span>`}</div></div>
</main>`;
  return html`<div style="flex: 1; display: flex; min-height: 0">${left}${right}</div>`;
}
