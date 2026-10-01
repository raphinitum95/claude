// The Build tab's Variables screen (#/build/<wb>/variables): every variable of the workbook, and the one picked, editable.
// Add a variable (test data with a value per data row, a value per environment, or a secret), rename it (the list of every cell that changes
// is shown first, and every {TOKEN} in the steps follows), edit its values, delete it. Most edits are plain ops through applyOps (one undo
// step each: add_variable, set_variable, set_cell, set_environments, delete_variable); the values on screen, the rename and a secret's value
// go through web/variables_api.py. A secret's value only ever goes to secrets.env: the page shows "set" / "not set", never the value.
// The Environments dialog stays for the environments themselves (their names, which one is production).
// "Make unique each run" (brief: dev/claude/CONTEXT_unique_variables.md): a variable whose copies ({NAME#1}, {NAME#2}) are its start + random
// characters, new on every run; set_variable ops carry unique / uniqueBase / uniqueFormat / uniqueLength.
import { S, rerender } from '../../state.js';
import { html, raw, cx, toast } from '../../util.js';
import { icon } from '../../icons.js';
import { api } from '../../api.js';
import { bm, applyOps } from './actions.js';

const enc = encodeURIComponent;
const VKIND = { env: ['globe', 'k-nav', 'Environment'], set: ['braces', 'k-save', 'Set by steps'], data: ['table', 'k-input', 'Data'], flag: ['flag', 'k-flow', 'Flag'] };
const TOKEN_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const UFORMATS = [['letters', 'Letters only'], ['mixed', 'Letters and numbers'], ['digits', 'Numbers only']];
const UCHARS = { letters: 'abcdefghijklmnopqrstuvwxyz', mixed: 'abcdefghijklmnopqrstuvwxyz0123456789', digits: '0123456789' };
const NAME_LIKE = /NAME|SURNAME|FIRST|LAST|GIVEN|FAMILY|MIDDLE|CITY|TOWN|STREET/i;      // (variables.py default_unique_format: letters for names)
const defaultFormat = (token) => (NAME_LIKE.test(token || '') ? 'letters' : 'mixed');
/** What a copy could look like: an example only (every run makes its own). */
function sampleOf(base, format, length) {
  const chars = UCHARS[format] || UCHARS.mixed;
  let out = '';
  for (let i = 0; i < Math.max(1, Math.min(Number(length) || 8, 64)); i++) out += chars[(i * 7 + 3 * (base || '').length + i * i) % chars.length];
  return (base || '') + out;
}

// What this screen knows beyond the model (module state: it follows S.build.name + the variable on screen + the model version).
const vs = { key: '', loading: false, detail: null, error: null, rename: null, del: false, secret: {}, adding: null };

const selected = () => {
  const m = bm();
  if (!m) return null;
  if (S.build.selVariable === '+new') return null;
  const rest = m.variables.filter((v) => !v.secret);
  return (S.build.selVariable && m.variables.find((v) => v.key === S.build.selVariable)) || rest[0] || m.variables[0] || null;
};
const keyOf = (v) => `${S.build.name}|${v.key}|${bm().version}`;

async function load(v) {
  const key = keyOf(v);
  if (vs.key === key || vs.loading) return;
  if (!vs.key.startsWith(`${S.build.name}|${v.key}|`)) Object.assign(vs, { rename: null, del: false, secret: {}, detail: null });
  vs.loading = true;
  try {
    vs.detail = await api(`/api/build/workbooks/${enc(S.build.name)}/variables/${enc(v.key)}/values`);
    vs.error = null;
  } catch (e) { vs.error = e; vs.detail = null; }
  vs.key = key; vs.loading = false;
  rerender();
}

/** The environment table as a set_environments op, after `change(rows)` edits its rows (every other row, name and tick kept as they are). */
function environmentsOp(change) {
  const e = bm().environments;
  const rows = e.rows.map((r) => ({ variable: r.variable, required: !!r.required, secret: !!r.secret, values: { ...r.values } }));
  change(rows);
  return { op: 'set_environments', names: e.names.slice(), production: e.production.slice(), rows };
}

// ---- the list -------------------------------------------------------------------------------------------------------------------
function varRow(v, on) {
  const [i, cls] = v.secret ? ['lock', ''] : (VKIND[v.kind] || VKIND.data);
  return html`<button class="rail-item ${on ? 'on' : ''}" style="height: auto; padding: 7px 10px; align-items: flex-start" data-key="v-${v.key}" data-act="build-select-variable" data-field="${v.key}">
<span style="color: var(--${cls || 'tx3'}); margin-top: 1px; display: inline-flex">${icon(v.secret ? 'lock' : i, 13)}</span>
<span style="display: flex; flex-direction: column; min-width: 0; flex: 1"><span style="font-weight: 600; color: var(--tx)">${v.label}</span>
<span class="mono trunc" style="font-size: 10.5px; color: var(--tx3)">{${v.secret ? 'SECRET:' : ''}${v.token}}${v.sources[0] ? ' · ' + v.sources[0].sheet : ''}</span></span>
${!v.setBy.length && !v.sources.length && v.kind !== 'env' && !v.secret && !v.unique ? html`<span class="pdot" style="background: var(--fail); margin-top: 5px" title="Used, never set"></span>` : ''}
</button>`;
}

function usePlace(u, label) {
  return html`<button class="card" style="text-align: left; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; width: 100%" data-act="build-jump-step" data-test="${u.test}" data-row="${u.row}">
<span style="font-size: 13px; font-weight: 600">${u.test} · step ${u.n}</span><span class="mono" style="font-size: 11px; color: var(--tx3)">${label || ''}</span></button>`;
}

function listPane(m, sel) {
  const groups = [['env', 'Environment'], ['set', 'Set by steps'], ['data', 'Data'], ['flag', 'Flags']];
  const secrets = m.variables.filter((v) => v.secret);
  const rest = m.variables.filter((v) => !v.secret);
  const adding = S.build.selVariable === '+new';
  return html`<aside class="scroll b-lcol" style="--w: 320px; overflow: auto; padding: 12px 10px">
<button class="btn btn-sm ${adding ? 'btn-pri' : ''}" style="width: 100%; justify-content: center; margin-bottom: 8px" data-act="bv-new" id="bv-new">${icon('plus', 13)} New variable</button>
${secrets.length ? html`<span class="lbl" style="padding: 6px 8px 2px; display: block">Secrets</span>${secrets.map((v) => varRow(v, !adding && sel && sel.key === v.key))}` : ''}
${groups.map(([k, label]) => { const list = rest.filter((v) => v.kind === k); return list.length ? html`<span class="lbl" style="padding: 8px 8px 2px; display: block">${label}</span>${list.map((v) => varRow(v, !adding && sel && sel.key === v.key))}` : ''; })}
${!m.variables.length ? html`<div style="padding: 16px; color: var(--tx3); font-size: 12.5px">No variables yet.</div>` : ''}
</aside>`;
}

// ---- the variable on screen ------------------------------------------------------------------------------------------------------
function header(sel) {
  const r = vs.rename;
  const domain = sel.key === 'DOMAIN' && sel.kind === 'env';
  return html`<div style="display: flex; align-items: flex-start; gap: 14px; flex-wrap: wrap"><div style="display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 240px">
<input class="fld" id="bv-label" style="font: 700 20px var(--f-display); letter-spacing: -.02em; height: 40px" value="${sel.label}" data-change="bv-label" aria-label="What this variable is (its label)" title="A label: how the builder shows this variable. It changes nothing in the steps.">
<span class="mono" style="font-size: 12.5px; color: var(--tx3)">{${sel.secret ? 'SECRET:' : ''}${sel.token}} · set by ${sel.setBy.length} step${sel.setBy.length === 1 ? '' : 's'} · used by ${sel.usedBy.length} step${sel.usedBy.length === 1 ? '' : 's'}</span></div>
<div style="display: flex; gap: 8px">${domain ? '' : html`<button class="btn btn-sm" data-act="bv-rename-open" ${r ? raw('disabled') : ''}>${icon('pencil', 13)} Rename</button>`}
${deletable(sel) ? html`<button class="btn btn-sm btn-ghost" style="color: var(--fail)" data-act="bv-delete-ask" id="bv-delete">${icon('trash', 13)} Delete</button>` : ''}</div></div>
${r ? renamePanel(sel, r) : ''}${vs.del ? deletePanel(sel) : ''}`;
}

function deletable(sel) {
  if (sel.key === 'DOMAIN' && sel.kind === 'env') return false;          // every environment needs the address its tests open
  return sel.sources.length > 0 || sel.kind === 'env' || (sel.secret && !sel.sources.length) || sel.labelSet;
}

function renamePanel(sel, r) {
  const changes = r.changes || [];
  return html`<div class="card" id="bv-rename" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; box-shadow: none; border-color: var(--acc-line)">
<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap"><b style="font-size: 13px">Rename {${sel.token}} to</b>
<input class="fld mono" id="bv-rename-to" style="height: 32px; width: 240px; max-width: 100%; font-size: 13px" value="${r.to}" placeholder="NEW_NAME" data-input="bv-rename-to" data-enter="bv-rename-preview" autofocus>
<button class="btn btn-sm" data-act="bv-rename-preview" ${r.busy ? raw('disabled') : ''}>Show what changes</button>
<span style="flex: 1"></span><button class="btn btn-sm btn-ghost" data-act="bv-rename-cancel">Cancel</button></div>
${r.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${r.error}</span></div>` : ''}
${r.changes ? html`<div style="font-size: 12.5px; color: var(--tx2)">${changes.length ? `${changes.length} cell${changes.length === 1 ? '' : 's'} change:` : 'Nothing else refers to it: only the name changes.'}</div>
${changes.length ? html`<div class="scroll" style="max-height: 240px; overflow: auto; border: 1px solid var(--line); border-radius: 10px"><table class="tbl" id="bv-rename-changes"><thead><tr><th>Sheet</th><th>Row</th><th>Column</th><th>Now</th><th>Becomes</th></tr></thead><tbody>
${changes.map((c) => html`<tr><td>${c.sheet}</td><td class="mono">${c.row}</td><td>${c.header}</td><td class="mono" style="max-width: 260px; overflow-wrap: anywhere">${c.before}</td><td class="mono" style="max-width: 260px; overflow-wrap: anywhere">${c.after}</td></tr>`)}</tbody></table></div>` : ''}
${r.secrets && r.secrets.length ? html`<div style="font-size: 12px; color: var(--tx2)">${icon('lock', 12)} secrets.env: the value${r.secrets.length === 1 ? '' : 's'} of the old name ${r.secrets.length === 1 ? 'is' : 'are'} copied to ${r.secrets.join(', ')} (the old ${r.secrets.length === 1 ? 'entry stays' : 'entries stay'}, so an undo still works).</div>` : ''}
<div style="display: flex; gap: 8px"><button class="btn btn-pri btn-sm ${r.busy ? 'busy' : ''}" data-act="bv-rename-apply" id="bv-rename-apply" ${r.busy ? raw('disabled') : ''}>Rename ${changes.length ? `and change ${changes.length} cell${changes.length === 1 ? '' : 's'}` : ''}</button>
<span style="font-size: 12px; color: var(--tx3); align-self: center">One undo step. Saved to Excel with the rest of your edits.</span></div>` : ''}
</div>`;
}

function deletePanel(sel) {
  const used = sel.usedBy.length;
  return html`<div class="bn bn-fail" id="bv-delete-confirm" style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">${icon('warn', 15, 'color: var(--fail)')}
<span style="flex: 1; min-width: 240px"><b>Delete {${sel.token}}?</b> ${sel.sources.length ? `Its data column${sel.sources.length === 1 ? ' is' : 's are'} emptied (${sel.sources.map((s) => s.sheet).join(', ')}). ` : ''}${sel.kind === 'env' ? 'Its row goes from the environment table. ' : ''}${sel.secret ? 'Its value in secrets.env stays: remove it there by hand if nothing else uses it. ' : ''}
${used ? `${used} step${used === 1 ? ' uses' : 's use'} it and will fail on "variable ${sel.token} has no value" until changed.` : 'No step uses it.'}</span>
<button class="btn btn-sm btn-dng" data-act="bv-delete-go" id="bv-delete-go">Delete</button><button class="btn btn-sm" data-act="bv-delete-cancel">Keep it</button></div>`;
}

function dataValues(d) {
  return d.sources.map((src) => html`<div style="display: flex; flex-direction: column; gap: 8px" data-key="src-${src.sheet}">
<div style="display: flex; align-items: baseline; gap: 8px"><span class="lbl">Value per data row</span><span class="mono" style="font-size: 11.5px; color: var(--tx3)">${src.sheet} · ${src.column}${src.tests.length ? ` · used by the test${src.tests.length === 1 ? '' : 's'} ${src.tests.join(', ')}` : ''}</span></div>
${src.rows.length ? html`<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th style="width: 90px">Data row</th><th>Label</th><th style="width: 45%">Value</th></tr></thead><tbody>
${src.rows.map((r) => html`<tr data-key="dr-${src.sheet}-${r.row}" style="${r.enabled === false ? 'opacity: .6' : ''}"><td class="mono">${r.row}${r.enabled === false ? ' (off)' : ''}</td><td>${r.label || html`<span style="color: var(--tx3)">–</span>`}</td>
<td>${r.masked ? html`<span class="mono" style="font-size: 12px; color: var(--warn)" title="A secret typed into the workbook: anyone with the file can read it. Put {SECRET:NAME} there and its value in secrets.env.">•••••• typed into the workbook</span>`
    : r.formula ? html`<span class="mono" style="font-size: 12px; color: var(--tx2); overflow-wrap: anywhere" title="A formula: edit it in the Excel grid">${r.value}</span>`
    : html`<input class="fld mono" style="height: 30px; font-size: 12.5px" value="${r.value ?? ''}" data-change="bv-data-cell" data-sheet="${src.sheet}" data-row="${r.row}" data-column="${src.column}" aria-label="Value in data row ${r.row}">`}</td></tr>`)}
</tbody></table></div>` : html`<span style="font-size: 12.5px; color: var(--tx3)">${src.sheet} has no data row yet.</span>`}</div>`);
}

function envValues(sel, d, m) {
  const row = d.environment;
  const envs = m.environments;
  if (!row) return '';
  if (envs.source !== 'rr') {
    return html`<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Value per environment</span>
<div style="font-size: 12.5px; color: var(--tx2)">From the workbook's legacy Environments sheet: change it there in Excel.</div>
${envs.names.map((n) => html`<div style="display: flex; gap: 10px; font-size: 12.5px"><b style="width: 90px">${n}</b><span class="mono">${row.values[n] || '–'}</span></div>`)}</div>`;
  }
  return html`<div style="display: flex; flex-direction: column; gap: 8px"><div style="display: flex; align-items: baseline; gap: 10px"><span class="lbl">Value per environment</span>
<span style="font-size: 11.5px; color: var(--tx3)">The run fills {${sel.token}} with the one of the environment it runs in.</span><span style="flex: 1"></span>
<label style="display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--tx2)"><input type="checkbox" class="cb" ${row.required || sel.key === 'DOMAIN' ? raw('checked') : ''} ${sel.key === 'DOMAIN' ? raw('disabled') : ''} data-change="bv-env-required">Required (a run refuses to start without it)</label></div>
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl" id="bv-env-values"><thead><tr><th style="width: 140px">Environment</th><th>Value</th></tr></thead><tbody>
${envs.names.map((n) => html`<tr data-key="ev-${n}"><td><b>${n}</b>${envs.production.includes(n) ? html` <span class="tag tag-fail">production</span>` : ''}</td>
<td>${row.secret ? html`<span class="mono" style="font-size: 12px; color: var(--tx2)">${row.values[n] || '–'}</span>`
    : html`<input class="fld mono" style="height: 30px; font-size: 12.5px" value="${row.values[n] || ''}" data-change="bv-env-cell" data-env="${n}" aria-label="Value in ${n}">`}</td></tr>`)}
</tbody></table></div>
${row.secret && row.typedIn && row.typedIn.length ? html`<div class="bn bn-warn">${icon('warn', 15, 'color: var(--warn)')}<span>A secret is typed into the workbook for ${row.typedIn.join(', ')} (shown as ••••••): anyone with the file can read it. Put {SECRET:${sel.token}} there instead (Environments) and its value in secrets.env below.</span></div>` : ''}</div>`;
}

function secretValues(sel, d) {
  const st = d.secret;
  if (!st) return '';
  const names = d.environments.names;
  const rows = [...names.map((n) => [n, n, st.environments[n], st.perEnvironment[n]]), ['', 'Every environment', st.everywhere, st.everywhere]];
  return html`<div style="display: flex; flex-direction: column; gap: 8px" id="bv-secret"><div style="display: flex; align-items: baseline; gap: 10px"><span class="lbl">Value in secrets.env</span>
<span style="font-size: 11.5px; color: var(--tx3)">Never in the workbook, never shown here. Typing a new one replaces the old.</span></div>
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th style="width: 160px">Environment</th><th style="width: 140px">Now</th><th>New value</th><th style="width: 80px"></th></tr></thead><tbody>
${rows.map(([env, label, has, own]) => html`<tr data-key="sv-${env || 'all'}"><td>${env ? html`<b>${label}</b>` : html`<span style="color: var(--tx2)">${label}</span>`}<div class="mono" style="font-size: 10.5px; color: var(--tx3)">RR_SECRET_${env ? env.toUpperCase() + '_' : ''}${sel.token.toUpperCase()}</div></td>
<td>${has ? html`<span class="pill p-pass">${icon('check', 11)} ${own ? 'set' : 'from every env.'}</span>` : html`<span class="pill p-pend">not set</span>`}</td>
<td><input class="fld mono" type="password" autocomplete="new-password" style="height: 30px; font-size: 12.5px" value="" placeholder="••••••" data-input="bv-secret-value" data-env="${env}" aria-label="New value for ${label}"></td>
<td><button class="btn btn-sm" data-act="bv-secret-save" data-env="${env}">Save</button></td></tr>`)}
</tbody></table></div></div>`;
}

/** "Make unique each run": the tick, what a copy starts with, what its random part is made of, and the copies the steps use. */
function uniquePanel(sel, d) {
  if (sel.secret) return '';
  const u = sel.unique;
  const own = (d.sources[0] && d.sources[0].rows.find((r) => r.value)) || null;
  const start = u ? (u.base || (own ? own.value : '')) : '';
  const made = new Set(sel.copiesMade || []);
  return html`<div class="card" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px" id="bv-unique">
<label style="display: flex; align-items: center; gap: 8px; font-weight: 600"><input type="checkbox" class="cb" id="bv-unique-on" ${u ? raw('checked') : ''} data-change="bv-unique-on">Make unique each run</label>
<span style="font-size: 12.5px; color: var(--tx2)">${u ? html`Each copy a step types (${sel.token} #1, #2...) is its start plus random characters, made the first time a run needs it and the same for every later step and test of that run. A new run makes new ones.`
    : html`Tick it when the site must never see the same value twice (a name, an email): steps then pick a copy (#1, #2...) and every run gets fresh ones.`}</span>
${u ? html`<div style="display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 2fr) minmax(0, 1fr); gap: 12px">
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Starts with</span><input class="fld mono" id="bv-unique-base" value="${u.base}" placeholder="${own ? `${own.value} (its value in data row ${own.row})` : 'nothing: random characters only'}" data-change="bv-unique-base" aria-label="What a copy starts with"></label>
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Random part</span><select class="fld" id="bv-unique-format" data-change="bv-unique-format" aria-label="What the random part is made of">${UFORMATS.map(([k, label]) => html`<option value="${k}" ${u.format === k ? raw('selected') : ''}>${label}</option>`)}</select></label>
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Length</span><input class="fld mono" id="bv-unique-length" type="number" min="1" max="64" value="${u.length}" data-change="bv-unique-length" aria-label="How many random characters"></label></div>
<span style="font-size: 12.5px; color: var(--tx2)">A copy looks like <b class="mono" style="color: var(--tx)">${sampleOf(start, u.format, u.length)}</b>${u.format !== 'letters' && NAME_LIKE.test(sel.token) ? ' · a name field may refuse numbers: "Letters only" is safer' : ''}</span>
<div style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center"><span class="lbl" style="margin-right: 4px">Copies the steps use</span>
${(sel.copies || []).length ? sel.copies.map((n) => html`<span class="chip mono ${made.has(n) ? '' : 'chip-warn'}" title="${made.has(n) ? 'A step types it: made the first time a run needs it' : 'Only checked: no step types it, so a run never makes it'}">#${n}${made.has(n) ? '' : ' (only checked)'}</span>`)
    : html`<span style="font-size: 12.5px; color: var(--tx3)">None yet: pick "${sel.token}" in a step's value and choose "a new one".</span>`}</div>` : ''}
</div>`;
}

function detailPane(S_, m, sel) {
  const d = vs.detail;
  const ready = d && vs.key === keyOf(sel);
  return html`<main class="scroll" style="flex: 1; min-width: 0; overflow: auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 18px" id="bv-detail">
${header(sel)}
<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px">
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Kind</span><span style="font-weight: 600">${sel.kind === 'env' ? 'Environment table' : sel.kind === 'set' ? 'Saved by a step' : sel.kind === 'flag' ? 'Row flag' : sel.secret && !sel.sources.length ? 'Secret' : sel.unique && !sel.sources.length ? 'New each run' : 'Data column'}</span></div>
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Secret</span><span style="font-weight: 600">${sel.secret ? 'Yes · masked everywhere' : 'No'}</span></div>
<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Environment-specific</span><span style="font-weight: 600">${sel.envSpecific ? 'Yes' : 'No'}</span></div></div>
${!sel.setBy.length && !sel.sources.length && sel.kind !== 'env' && !sel.secret && !sel.unique ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>Used, but nothing sets it: ${sel.neededBy.join(', ') || 'a step'} will fail on "variable ${sel.token} has no value".</span></div>` : ''}
${vs.error && !ready ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${vs.error.message}</span></div>` : ''}
${!ready ? (vs.error ? '' : html`<div class="skel" style="height: 90px"></div>`) : html`
${uniquePanel(sel, d)}${dataValues(d)}${envValues(sel, d, m)}${secretValues(sel, d)}
${sel.kind === 'set' && !sel.sources.length ? html`<div style="font-size: 12.5px; color: var(--tx2)">A step saves it while the test runs: there is no stored value to edit. Change or remove the step${sel.setBy.length === 1 ? '' : 's'} that set${sel.setBy.length === 1 ? 's' : ''} it.</div>` : ''}`}
<div style="display: flex; gap: 32px">
<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px"><span class="lbl">Set by</span>
${sel.setBy.length ? sel.setBy.map((u) => usePlace(u)) : html`<span style="font-size: 12.5px; color: var(--tx3)">${sel.sources.length ? 'A data column, not a step.' : sel.kind === 'env' ? 'The environment table.' : sel.secret ? 'secrets.env.' : 'Nothing sets it.'}</span>`}</div>
<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px"><span class="lbl">Used by</span>
${sel.usedBy.length ? sel.usedBy.map((u) => usePlace(u, u.column)) : html`<span style="font-size: 12.5px; color: var(--tx3)">Not used.</span>`}</div></div>
</main>`;
}

// ---- a new variable -------------------------------------------------------------------------------------------------------------
function freshAdding(m) {
  const web = m.tests.filter((t) => t.kind === 'web');
  return { token: '', label: '', kind: web.length ? 'data' : 'env', test: web[0] ? web[0].id : '', value: '', env: {}, busy: false, error: '', format: '', length: '8' };
}

function addPane(m) {
  const a = vs.adding || (vs.adding = freshAdding(m));
  const envs = m.environments;
  const web = m.tests.filter((t) => t.kind === 'web');
  const kinds = [['data', 'Test data', 'A value per data row of one test (its Params sheet).', !web.length && 'No website test yet.'],
    ['env', 'Per environment', 'One value for each environment (QA, UAT...), like DOMAIN.', envs.source === 'legacy' && 'This workbook keeps its environments in the legacy Environments sheet: add it there in Excel.'],
    ['secret', 'Secret', 'A password or key: its value goes in secrets.env, never in the workbook.', ''],
    ['unique', 'New each run', 'A start (qalast) plus random characters: every run makes fresh copies (#1, #2...).', '']];
  const test = web.find((t) => t.id === a.test);
  const token = a.token.trim();
  const taken = token && m.variables.some((v) => v.key === token.toUpperCase());
  return html`<main class="scroll" style="flex: 1; min-width: 0; overflow: auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 18px; max-width: 860px" id="bv-add">
<h1 class="disp" style="font-size: 22px; margin: 0">New variable</h1>
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Name (what steps write as {NAME})</span>
<input class="fld mono" id="bv-add-token" value="${a.token}" placeholder="FIRST_NAME" data-input="bv-add-field" data-field="token" autofocus>
${token && !TOKEN_RE.test(token) ? html`<span style="font-size: 12px; color: var(--fail)">Letters, digits and _ only, starting with a letter.</span>` : taken ? html`<span style="font-size: 12px; color: var(--fail)">There is already a variable called ${token}.</span>` : ''}</label>
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Label (optional)</span><input class="fld" value="${a.label}" placeholder="First name" data-input="bv-add-field" data-field="label"></label></div>
<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">What kind</span>
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px">${kinds.map(([k, label, what, off]) => html`<button class="card ${cx(a.kind === k && 'on')}" style="text-align: left; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; ${a.kind === k ? 'border-color: var(--acc); box-shadow: var(--glow)' : ''}; ${off ? 'opacity: .55' : ''}" data-act="bv-add-kind" data-val="${k}" ${off ? raw(`disabled title="${off.replace(/"/g, '&quot;')}"`) : ''} aria-pressed="${String(a.kind === k)}">
<b style="font-size: 13px">${label}</b><span style="font-size: 12px; color: var(--tx2)">${off || what}</span></button>`)}</div></div>
${a.kind === 'data' ? html`<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">For the test</span><select class="fld" data-change="bv-add-test">${web.map((t) => html`<option value="${t.id}" ${t.id === a.test ? raw('selected') : ''}>${t.id}</option>`)}</select>
<span style="font-size: 12px; color: var(--tx3)">${test && test.paramSheet ? `A new column in ${test.paramSheet}.` : `${a.test || 'It'} has no data sheet yet: ${a.test}_Params is made, with one data row.`}</span></label>
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Value (every data row)</span><input class="fld mono" value="${a.value}" placeholder="Ann" data-input="bv-add-field" data-field="value"></label></div>` : ''}
${a.kind === 'env' ? html`<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Value per environment</span>
${envs.source !== 'rr' ? html`<div class="bn bn-warn">${icon('warn', 15, 'color: var(--warn)')}<span>This workbook has no environment table yet. Adding one means every run of it must pick an environment (${envs.names.join(', ')}); change the list under Environments.</span></div>` : ''}
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><tbody>${envs.names.map((n) => html`<tr data-key="ae-${n}"><td style="width: 140px"><b>${n}</b></td><td><input class="fld mono" style="height: 30px; font-size: 12.5px" value="${a.env[n] || ''}" data-input="bv-add-env" data-env="${n}" aria-label="Value in ${n}"></td></tr>`)}</tbody></table></div></div>` : ''}
${a.kind === 'secret' ? html`<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Value in secrets.env (optional now: you can add it later)</span>
<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><tbody>${[...envs.names, ''].map((n) => html`<tr data-key="as-${n || 'all'}"><td style="width: 180px">${n ? html`<b>${n}</b>` : html`<span style="color: var(--tx2)">Every environment</span>`}</td>
<td><input class="fld mono" type="password" autocomplete="new-password" style="height: 30px; font-size: 12.5px" value="" placeholder="••••••" data-input="bv-add-env" data-env="${n}" aria-label="Secret value for ${n || 'every environment'}"></td></tr>`)}</tbody></table></div>
<span style="font-size: 12px; color: var(--tx3)">Steps use it as {SECRET:${token || 'NAME'}}. The workbook only says it is a secret.</span></div>` : ''}
${a.kind === 'unique' ? html`<div style="display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 2fr) minmax(0, 1fr); gap: 14px">
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Starts with</span><input class="fld mono" value="${a.value}" placeholder="qalast" data-input="bv-add-field" data-field="value"></label>
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Random part</span><select class="fld" data-change="bv-add-format">${UFORMATS.map(([k, label]) => html`<option value="${k}" ${(a.format || defaultFormat(token)) === k ? raw('selected') : ''}>${label}</option>`)}</select></label>
<label style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Length</span><input class="fld mono" type="number" min="1" max="64" value="${a.length}" data-input="bv-add-field" data-field="length"></label></div>
<span style="font-size: 12px; color: var(--tx3)">A copy looks like <b class="mono">${sampleOf(a.value, a.format || defaultFormat(token), a.length)}</b>. Steps use {${token || 'NAME'}#1}, {${token || 'NAME'}#2}...: you pick which one in the step.</span>` : ''}
${a.error ? html`<div class="bn bn-fail">${icon('warn', 15, 'color: var(--fail)')}<span>${a.error}</span></div>` : ''}
<div style="display: flex; gap: 8px"><button class="btn btn-pri ${a.busy ? 'busy' : ''}" data-act="bv-add-create" id="bv-add-create" ${a.busy || !token || !TOKEN_RE.test(token) || taken ? raw('disabled') : ''}>${icon('plus', 14)} Add ${token || 'the variable'}</button>
<button class="btn" data-act="bv-add-cancel">Cancel</button></div>
</main>`;
}

export function variableMap(S_) {
  const m = bm();
  const sel = selected();
  const adding = S.build.selVariable === '+new';
  const left = listPane(m, sel);
  if (adding) return html`<div class="b-cols">${left}${addPane(m)}</div>`;
  if (!sel) return html`<div class="b-cols">${left}<main class="scroll" style="flex: 1; padding: 24px"><span style="color: var(--tx3)">No variables yet: add one.</span></main></div>`;
  load(sel);
  return html`<div class="b-cols">${left}${detailPane(S_, m, sel)}</div>`;
}

// ---- doing ------------------------------------------------------------------------------------------------------------------------
async function renamePreview() {
  const sel = selected();
  const r = vs.rename;
  if (!sel || !r) return;
  const to = r.to.trim();
  if (!TOKEN_RE.test(to)) { r.error = 'Letters, digits and _ only, starting with a letter.'; r.changes = null; rerender(); return; }
  r.busy = true; r.error = ''; rerender();
  try {
    const out = await api(`/api/build/workbooks/${enc(S.build.name)}/variables/rename-preview`, { method: 'POST', body: { from: sel.token, to } });
    r.changes = out.changes; r.secrets = out.secrets; r.previewed = to;
  } catch (e) { r.error = e.message; r.changes = null; }
  r.busy = false; rerender();
}

async function renameApply() {
  const sel = selected();
  const r = vs.rename;
  if (!sel || !r) return;
  if (r.previewed !== r.to.trim()) { await renamePreview(); return; }          // (always show what changes before changing it)
  r.busy = true; rerender();
  try {
    const out = await api(`/api/build/workbooks/${enc(S.build.name)}/variables/rename${S.build.env ? `?env=${enc(S.build.env)}` : ''}`,
      { method: 'POST', body: { from: sel.token, to: r.previewed, version: bm().version } });
    S.build.model = out.model;
    S.build.selVariable = r.previewed.toUpperCase();
    vs.rename = null; vs.key = '';
    toast(`Renamed to ${r.previewed}${out.secretsCopied && out.secretsCopied.length ? `; secrets.env has it as ${out.secretsCopied.join(', ')} too` : ''}.`, 5000);
  } catch (e) { r.error = e.message; r.busy = false; }
  rerender();
}

async function saveSecret(env) {
  const sel = selected();
  const value = vs.secret[env || ''] || '';
  if (!sel || !value) { toast('Type the value first.'); return; }
  try {
    await api(`/api/build/workbooks/${enc(S.build.name)}/variables/secret`, { method: 'POST', body: { name: sel.token, environment: env || '', value } });
    delete vs.secret[env || ''];
    vs.key = '';                                                          // read the status again (set / not set)
    toast(`Saved in secrets.env${env ? ` for ${env}` : ' for every environment'}.`);
  } catch (e) { toast(e.message, 6000); }
  rerender();
}

async function createVariable() {
  const a = vs.adding;
  if (!a) return;
  const token = a.token.trim();
  const label = a.label.trim();
  let ops;
  if (a.kind === 'data') ops = [{ op: 'add_variable', token, test: a.test, value: a.value, ...(label ? { label } : {}) }];
  else if (a.kind === 'env') {
    ops = [environmentsOp((rows) => rows.push({ variable: token, required: false, secret: false, values: { ...a.env } }))];
    if (label) ops.push({ op: 'set_variable', token, label, envSpecific: true });
  } else if (a.kind === 'unique') {
    ops = [{ op: 'set_variable', token, unique: true, uniqueBase: a.value, uniqueFormat: a.format || defaultFormat(token), uniqueLength: Number(a.length) || 8, ...(label ? { label } : {}) }];
  } else ops = [{ op: 'set_variable', token, secret: true, ...(label ? { label } : {}) }];
  a.busy = true; a.error = ''; rerender();
  const applied = await applyOps(ops, { quiet: true });
  if (!applied) { a.busy = false; a.error = 'The variable could not be added (see the message above), or the workbook changed: try again.'; rerender(); return; }
  if (a.kind === 'secret') {
    for (const [env, value] of Object.entries(a.env)) {
      if (!value) continue;
      try { await api(`/api/build/workbooks/${enc(S.build.name)}/variables/secret`, { method: 'POST', body: { name: token, environment: env, value } }); }
      catch (e) { toast(e.message, 6000); }
    }
  }
  vs.adding = null; vs.key = '';
  S.build.selVariable = token.toUpperCase();
  toast(`${token} added.`);
  rerender();
}

export const acts = {
  'bv-new'() { S.build.selVariable = '+new'; vs.adding = freshAdding(bm()); rerender(); },
  'bv-add-kind'(el) { if (vs.adding) { vs.adding.kind = el.dataset.val; vs.adding.env = {}; rerender(); } },
  'bv-add-cancel'() { vs.adding = null; S.build.selVariable = null; rerender(); },
  'bv-add-create': createVariable,
  'bv-rename-open'() { const sel = selected(); if (sel) { vs.rename = { to: sel.token, changes: null, secrets: [], busy: false, error: '' }; vs.del = false; rerender(); } },
  'bv-rename-cancel'() { vs.rename = null; rerender(); },
  'bv-rename-preview': renamePreview,
  'bv-rename-apply': renameApply,
  'bv-delete-ask'() { vs.del = true; vs.rename = null; rerender(); },
  'bv-delete-cancel'() { vs.del = false; rerender(); },
  async 'bv-delete-go'() {
    const sel = selected();
    if (!sel) return;
    const applied = await applyOps([{ op: 'delete_variable', token: sel.token }]);
    if (applied) { vs.del = false; vs.key = ''; S.build.selVariable = null; toast(`${sel.token} deleted.`); rerender(); }
  },
  'bv-secret-save'(el) { saveSecret(el.dataset.env); },
};

export const changes = {
  'bv-label'(el) {
    const sel = selected();
    const label = el.value.trim();
    if (sel && label && label !== sel.label) applyOps([{ op: 'set_variable', token: sel.token, label }]);
  },
  'bv-data-cell'(el) {
    const { sheet, row, column } = el.dataset;
    applyOps([{ op: 'set_cell', sheet, row: Number(row), column, value: el.value === '' ? null : el.value }]);
  },
  'bv-env-cell'(el) {
    const sel = selected();
    if (!sel) return;
    const env = el.dataset.env;
    applyOps([environmentsOp((rows) => { const r = rows.find((x) => x.variable.toUpperCase() === sel.key); if (r) r.values[env] = el.value; })]);
  },
  'bv-env-required'(el) {
    const sel = selected();
    if (!sel) return;
    applyOps([environmentsOp((rows) => { const r = rows.find((x) => x.variable.toUpperCase() === sel.key); if (r) r.required = el.checked; })]);
  },
  'bv-add-test'(el) { if (vs.adding) { vs.adding.test = el.value; rerender(); } },
  'bv-add-format'(el) { if (vs.adding) { vs.adding.format = el.value; rerender(); } },
  'bv-unique-on'(el) {
    const sel = selected();
    if (sel) applyOps([{ op: 'set_variable', token: sel.token, unique: el.checked, ...(el.checked && !sel.unique ? { uniqueFormat: defaultFormat(sel.token), uniqueLength: 8 } : {}) }]);
  },
  'bv-unique-base'(el) { const sel = selected(); if (sel && sel.unique) applyOps([{ op: 'set_variable', token: sel.token, uniqueBase: el.value }]); },
  'bv-unique-format'(el) { const sel = selected(); if (sel && sel.unique) applyOps([{ op: 'set_variable', token: sel.token, uniqueFormat: el.value }]); },
  'bv-unique-length'(el) {
    const sel = selected();
    const n = Number(el.value);
    if (!sel || !sel.unique) return;
    if (!Number.isInteger(n) || n < 1 || n > 64) { toast('The random part is 1 to 64 characters long.'); el.value = sel.unique.length; return; }
    applyOps([{ op: 'set_variable', token: sel.token, uniqueLength: n }]);
  },
};

export const inputs = {
  'bv-rename-to'(el) { if (vs.rename) { vs.rename.to = el.value; vs.rename.changes = vs.rename.previewed === el.value.trim() ? vs.rename.changes : null; rerender(); } },
  'bv-add-field'(el) { if (vs.adding) { vs.adding[el.dataset.field] = el.value; rerender(); } },
  'bv-add-env'(el) { if (vs.adding) vs.adding.env[el.dataset.env] = el.value; },
  'bv-secret-value'(el) { vs.secret[el.dataset.env || ''] = el.value; },
};

export const enters = {
  'bv-rename-preview': renamePreview,
};

// ---- Download: say what is not in the file --------------------------------------------------------------------------------------
/** Before a workbook that uses secrets is downloaded: their values live in secrets.env on this computer, not in the file. */
export function downloadSecretsDialog(m) {
  const n = m.secrets.length;
  return html`<div class="modal-back" data-act="close-modal" data-backdrop><div class="card modal" role="dialog" aria-modal="true" aria-label="Secrets are not in the file" style="width: min(560px, 100%)" id="bv-download-secrets">
<div style="display: flex; gap: 12px; align-items: flex-start"><span style="color: var(--warn); display: inline-flex; margin-top: 2px">${icon('lock', 20)}</span>
<div style="display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0"><span class="ttl">The file has no secret values</span>
<span style="font-size: 13px; color: var(--tx2)">${m.name} uses ${n} secret${n === 1 ? '' : 's'}. ${n === 1 ? 'Its value lives' : 'Their values live'} in secrets.env on this computer, never in the workbook.</span></div>
<button class="modal-x" data-act="close-modal" aria-label="Close">${icon('x', 16)}</button></div>
<div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px">${m.secrets.map((s) => html`<span class="tag mono">{SECRET:${s}}</span>`)}</div>
<p style="font-size: 12.5px; color: var(--tx2); line-height: 1.55; margin-top: 12px">Whoever gets this file adds their own values to their secrets.env: <span class="mono">RR_SECRET_&lt;ENV&gt;_&lt;NAME&gt;</span> for one environment, or <span class="mono">RR_SECRET_&lt;NAME&gt;</span> for every one (their Build tab's Variables screen does it for them). Until then the steps that use ${n === 1 ? 'it' : 'them'} fail with "no value".</p>
<div style="margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); display: flex; align-items: center; gap: 8px"><span style="flex: 1"></span>
<button class="btn" data-act="close-modal">Cancel</button><button class="btn btn-pri" data-act="build-download-go" data-name="${m.name}" id="bv-download-go">${icon('download', 14)} Download</button></div></div></div>`;
}
