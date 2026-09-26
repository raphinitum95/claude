// Build-tab dialogs: new workbook, environments table, page fingerprint, file changed on disk, and history.
import { html, raw } from '../../util.js';
import { icon } from '../../icons.js';
import { bm } from './actions.js';

const backdrop = (inner) => html`<div class="modal-back" data-act="close-modal" data-backdrop>${inner}</div>`;
const closeBtn = html`<button class="modal-x" data-act="close-modal" aria-label="Close">${icon('x', 16)}</button>`;

function dialogShell(title, sub, inner, footer, opts = {}) {
  return html`<div class="card modal ${opts.wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${title}" style="${opts.width ? `width: min(${opts.width}px, 100%)` : ''}">
<div style="display: flex; gap: 12px; align-items: flex-start"><div style="display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0"><span class="ttl">${title}</span>
${sub ? html`<span style="font-size: 13px; color: var(--tx2)">${sub}</span>` : ''}</div>${closeBtn}</div>
<div class="scroll" style="overflow: auto; margin-top: 14px; display: flex; flex-direction: column; gap: 16px; max-height: 60vh">${inner}</div>
<div style="margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); display: flex; align-items: center; gap: 8px">${footer}</div></div>`;
}

// ---- new workbook ---------------------------------------------------------------------------------------------
export function newWorkbookDialog(m) {
  const envs = m.envs.map((e, i) => html`<tr data-key="e-${i}"><td><input class="fld mono" style="height: 30px; font-size: 12px" value="${e.name}" placeholder="ENV" data-input="build-nw-env-name" data-i="${i}"></td>
<td><input class="fld mono" style="height: 30px; font-size: 12px" value="${e.domain}" placeholder="example.com" data-input="build-nw-env-domain" data-i="${i}"></td>
<td style="text-align: center"><input type="checkbox" class="cb" ${e.production ? raw('checked') : ''} data-change="build-nw-env-prod" data-i="${i}" aria-label="${e.name || 'Environment'} is production"></td>
<td><button class="icon-btn" style="width: 26px; height: 26px" data-act="build-nw-remove-env" data-i="${i}" aria-label="Remove environment">${icon('x', 12)}</button></td></tr>`);
  const inner = html`<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Name</span>
<input class="fld" value="${m.name}" placeholder="My regression" data-input="build-nw-name" autofocus>
<span class="mono" style="font-size: 12px; color: var(--tx3)">Saved as workbooks/${m.name || '(name)'}.xlsx</span></div>
<div style="display: flex; flex-direction: column; gap: 6px"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">Environments and their domain</span><span style="flex: 1"></span>
<button class="btn btn-ghost btn-sm" data-act="build-nw-add-env">${icon('plus', 12)} Environment</button></div>
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Environment</th><th>Domain</th><th>Production</th><th></th></tr></thead><tbody>${envs}</tbody></table></div>
<span style="font-size: 12px; color: var(--tx3)">Production always blocks steps with side effects and asks for a typed confirmation.</span></div>
${m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>` : ''}`;
  const footer = html`<span style="flex: 1"></span><button class="btn" data-act="close-modal">Cancel</button>
<button class="btn btn-pri ${m.busy ? 'busy' : ''}" data-act="build-nw-create" ${m.busy ? raw('disabled') : ''}>Create workbook</button>`;
  return backdrop(dialogShell('New workbook', 'One screen, then you are building.', inner, footer, { width: 640 }));
}

export function newTestDialog(m) {
  const inner = html`<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Test name</span>
<input class="fld" value="${m.name}" placeholder="Purchase" data-input="build-nt-name" autofocus autocomplete="off"></div>
${m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>` : ''}`;
  const footer = html`<span style="flex: 1"></span><button class="btn" data-act="close-modal">Cancel</button>
<button class="btn btn-pri ${m.busy ? 'busy' : ''}" data-act="build-nt-create" ${m.busy ? raw('disabled') : ''}>Create test</button>`;
  return backdrop(dialogShell('New test', 'A new sheet with the 26 standard columns.', inner, footer, { width: 460 }));
}

// ---- environments -----------------------------------------------------------------------------------------------
export function environmentsDialog(m) {
  const head = html`<tr><th style="width: 190px">Variable</th>${m.names.map((n) => html`<th>${n}${m.production.includes(n) ? html` <span class="tag tag-fail">production</span>` : ''}</th>`)}<th style="width: 40px"></th></tr>`;
  const body = m.rows.map((r, i) => html`<tr data-key="r-${i}"><td><input class="fld mono" style="height: 30px; font-size: 12px" value="${r.variable}" placeholder="DOMAIN" data-input="build-env-var" data-i="${i}"></td>
${m.names.map((n) => html`<td><input class="fld mono" style="height: 30px; font-size: 11.5px" value="${r.values[n] || ''}" data-input="build-env-cell" data-i="${i}" data-env="${n}"></td>`)}
<td><button class="icon-btn" style="width: 26px; height: 26px" data-act="build-env-remove-row" data-i="${i}" aria-label="Remove row">${icon('x', 12)}</button></td></tr>`);
  const inner = html`<div style="display: flex; align-items: center; gap: 8px"><span style="font-size: 12.5px; color: var(--tx2)">Secret values live in secrets.env; use {SECRET:NAME} instead of typing one here.</span></div>
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead>${head}</thead><tbody>${body}</tbody></table></div>
<div style="display: flex; gap: 8px"><button class="btn btn-sm" data-act="build-env-add-row">${icon('plus', 12)} Variable</button><button class="btn btn-sm" data-act="build-env-add-col">${icon('plus', 12)} Environment</button></div>
${m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>` : ''}`;
  const footer = html`<span style="flex: 1"></span><span style="font-size: 12px; color: var(--tx3)">The run picks the environment; these fill in.</span>
<button class="btn btn-pri ${m.busy ? 'busy' : ''}" data-act="build-env-save" ${m.busy ? raw('disabled') : ''}>Done</button>`;
  return backdrop(dialogShell('Environment variables', 'The test stays the same everywhere. Only these change per environment.', inner, footer, { width: 900, wide: true }));
}

// ---- fingerprints ----------------------------------------------------------------------------------------------
export function fingerprintsListDialog() {
  const m = bm();
  const rows = m.fingerprints;
  const inner = html`${rows.length ? rows.map((f) => html`<div class="scard" data-key="fp-${f.name}">
<span style="color: var(--pass); display: inline-flex">${icon('gate', 15)}</span>
<button data-act="build-fp-edit" data-name="${f.name}" style="flex: 1; text-align: left; min-width: 0"><b>${f.name}</b> <span class="mono" style="font-size: 11px; color: var(--tx3)">${f.urlContains || f.landmark}</span></button>
<span style="font-size: 11.5px; color: var(--tx3)">used by ${f.usedBy.length}</span>
<button class="icon-btn" style="width: 26px; height: 26px" data-act="build-fp-delete" data-name="${f.name}" aria-label="Delete ${f.name}">${icon('trash', 12)}</button></div>`)
    : html`<span style="color: var(--tx3); font-size: 12.5px">No page fingerprints yet.</span>`}`;
  const footer = html`<button class="btn btn-sm" data-act="build-fp-new">${icon('plus', 12)} New fingerprint</button><span style="flex: 1"></span><button class="btn" data-act="close-modal">Close</button>`;
  return backdrop(dialogShell('Page fingerprints', 'How ASSERT_PAGE knows a test really arrived.', inner, footer, { width: 560 }));
}

export function fingerprintDialog(m) {
  const inner = html`<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Name</span>
<input class="fld" value="${m.name}" placeholder="Payment page" data-input="build-fp-name" autofocus></div>
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; box-shadow: none"><b style="font-size: 12.5px">1 · The address</b>
<input class="fld mono" style="font-size: 12.5px" value="${m.urlContains}" placeholder="/purchase/payment" data-input="build-fp-url"><span style="font-size: 11.5px; color: var(--tx3)">Text the URL must contain. {DOMAIN} etc. allowed.</span></div>
<div style="text-align: center; font: 700 12px var(--f-mono); color: var(--tx3)">AND</div>
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; box-shadow: none"><b style="font-size: 12.5px">2 · A landmark on the page</b>
<input class="fld mono" style="font-size: 12.5px" value="${m.landmark}" placeholder="css=h1 or text=Payment details" data-input="build-fp-landmark">
<input class="fld" style="font-size: 12.5px" value="${m.landmarkText}" placeholder="Text the landmark must contain (optional)" data-input="build-fp-landmark-text"></div>
<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Notes</span><textarea class="fld" style="height: 50px; padding: 8px 10px" data-input="build-fp-notes">${m.notes}</textarea></div>
<div class="bn bn-fail">${icon('gate', 15, 'color: var(--fail)')}<span><b>A failed gate always stops the test</b>, even with Ignore_not_existing_object = Y.</span></div>
${m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>` : ''}`;
  const footer = html`<span style="flex: 1"></span><button class="btn" data-act="close-modal">Cancel</button>
<button class="btn btn-pri ${m.busy ? 'busy' : ''}" data-act="build-fp-save" ${m.busy ? raw('disabled') : ''}>Save fingerprint</button>`;
  return backdrop(dialogShell('Page fingerprint', 'How every test knows it really arrived.', inner, footer, { width: 560 }));
}

// ---- file changed on disk ------------------------------------------------------------------------------------
export function fileChangedDialog(m) {
  const inner = html`<div class="bn bn-warn">${icon('warn', 15, 'color: var(--warn)')}<span><b>The workbook changed on disk</b> (saved outside this session). Reload to take that version, or save anyway to overwrite it with your draft.</span></div>
${m.loading ? html`<div style="color: var(--tx3); font-size: 12.5px">Comparing…</div>` : m.changes.length
    ? html`<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Where</th><th>Step</th><th>What</th></tr></thead><tbody>
${m.changes.map((c, i) => html`<tr data-key="c-${i}"><td>${c.test || ''}</td><td class="mono">${c.n || c.row || ''}</td><td><span class="tag ${c.kind === 'removed' ? 'tag-fail' : c.kind === 'added' ? 'tag-acc' : ''}">${c.kind}</span></td></tr>`)}
</tbody></table></div>` : html`<span style="font-size: 12.5px; color: var(--tx3)">No changes to compare yet.</span>`}
${m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>` : ''}`;
  const footer = html`<button class="btn ${m.busy ? 'busy' : ''}" data-act="build-fc-reload" ${m.busy ? raw('disabled') : ''}>Reload from disk</button>
<span style="flex: 1"></span><button class="btn btn-pri ${m.busy ? 'busy' : ''}" data-act="build-fc-save-anyway" ${m.busy ? raw('disabled') : ''}>Save anyway</button>`;
  return backdrop(dialogShell('The workbook changed on disk', 'Reload it, or overwrite it with your draft.', inner, footer, { width: 640, wide: true }));
}

// ---- history --------------------------------------------------------------------------------------------------
export function historyDialog(m) {
  const left = m.items.map((h) => html`<button class="rail-item ${m.sel === h.id ? 'on' : ''}" style="height: auto; padding: 8px 10px; flex-direction: column; align-items: flex-start; gap: 1px" data-key="h-${h.id}" data-act="build-hist-pick" data-id="${h.id}">
<b style="font-size: 12.5px">${new Date(h.when).toLocaleString()}</b><span class="mono" style="font-size: 10.5px; color: var(--tx3)">${h.id}</span></button>`);
  const diff = m.diff ? m.diff.changes : null;
  const inner = html`<div style="display: flex; gap: 14px; min-height: 300px">
<div style="width: 240px; flex: none; display: flex; flex-direction: column; gap: 3px">${m.items.length ? left : html`<span style="color: var(--tx3); font-size: 12.5px; padding: 6px">No saves yet.</span>`}</div>
<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px">
${diff === null ? html`<span style="color: var(--tx3); font-size: 12.5px">Pick a save to compare with now.</span>`
    : diff.length === 0 ? html`<span style="color: var(--tx3); font-size: 12.5px">No differences from the current draft.</span>`
    : html`<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Test</th><th>Step</th><th>Change</th></tr></thead><tbody>
${diff.map((c, i) => html`<tr data-key="d-${i}"><td>${c.test || ''}</td><td class="mono">${c.n || c.row || ''}</td><td><span class="tag ${c.kind === 'removed' ? 'tag-fail' : c.kind === 'added' ? 'tag-acc' : ''}">${c.kind}</span></td></tr>`)}
</tbody></table></div>`}</div></div>
${m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>` : ''}`;
  const footer = html`<span style="font-size: 12px; color: var(--tx3)">Restoring makes a new draft; nothing is lost.</span><span style="flex: 1"></span>
<button class="btn" data-act="close-modal">Close</button>
<button class="btn btn-pri ${m.busy ? 'busy' : ''}" data-act="build-hist-restore" data-id="${m.sel || ''}" ${!m.sel || m.busy ? raw('disabled') : ''}>Restore this save</button>`;
  return backdrop(dialogShell('History', 'Every save to Excel keeps a timestamped backup.', inner, footer, { width: 900, wide: true }));
}

// ---- generic raw-sheet grid (Settings / a Params sheet from the rail) -------------------------------------------
export function gridDialog(m) {
  const inner = m.loading ? html`<span style="color: var(--tx3); font-size: 12.5px">Loading ${m.sheetName}…</span>`
    : m.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${m.error}</span></div>`
    : html`<div class="scroll" style="max-height: 56vh; overflow: auto; border: 1px solid var(--line); border-radius: 10px">
<table class="tbl mono" style="font-size: 11.5px"><thead><tr>${m.grid.headers.map((h) => html`<th>${h}</th>`)}</tr></thead>
<tbody>${m.grid.rows.map((row, i) => html`<tr data-key="gr-${i}">${row.map((c) => html`<td>${c == null ? '' : String(c)}</td>`)}</tr>`)}</tbody></table></div>`;
  const footer = html`<span style="flex: 1"></span><button class="btn" data-act="close-modal">Close</button>`;
  return backdrop(dialogShell(m.title, m.sheetName, inner, footer, { width: 900, wide: true }));
}

export function lockedDialog(m) {
  const inner = html`<div class="bn bn-warn">${icon('lock', 16, 'color: var(--warn)')}<span><b>Close it in Excel to save.</b> ${m.message}</span></div>`;
  const footer = html`<span style="flex: 1"></span><button class="btn btn-pri" data-act="close-modal">OK</button>`;
  return backdrop(dialogShell('Excel has this workbook open', '', inner, footer, { width: 480 }));
}
