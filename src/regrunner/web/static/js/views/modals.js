// Dialogs: PROD confirmation, one-time SSO sign-in, lint / dry-run / audit, selector merge, logs, doctor.
import { html, raw, cx } from '../util.js';
import { icon } from '../icons.js';
import { num, plural } from '../fmt.js';
import { banner, btn } from './shell.js';
import { allChosen, envList, shortName } from './newrun.js';

/** ``locked``: something is in flight that closing the dialog would not stop, so it cannot be closed until it answers (the X is greyed out, the backdrop does nothing). */
function frame(title, body, { wide, danger, locked, id = 'dlg-title' } = {}) {
  return html`<div class="modal-back" ${locked ? '' : raw('data-act="close-modal" data-backdrop')}>
<div class="card modal ${cx(wide && 'wide', danger && 'danger')}" role="dialog" aria-modal="true" aria-labelledby="${id}" ${locked ? raw('aria-busy="true"') : ''}>
<div style="display: flex; align-items: flex-start; gap: 12px"><h3 class="disp" id="${id}" style="font-size: 24px; font-weight: 700; line-height: 1.15; margin: 0">${title}</h3>
<button class="modal-x" data-act="close-modal" aria-label="Close" ${locked ? raw('disabled') : ''}>${icon('x', 18)}</button></div>${body}</div></div>`;
}

const spinner = (text) => html`<div style="display: flex; align-items: center; gap: 10px; padding: 26px 0; color: var(--tx2)"><span class="spin" style="display: inline-flex">${icon('refresh', 18)}</span> ${text}</div>`;

// ---- PROD confirmation ----------------------------------------------------------------------------------------
function prod(S, m) {
  const f = S.nr;
  const chosen = allChosen(S);
  const steps = chosen.reduce((a, t) => a + t.steps, 0);
  const books = f.books;
  const prodBooks = f.env ? books : books.filter((n) => f.bk[n].info && String(f.bk[n].info.environment).toUpperCase() === 'PROD');
  const set = S.cfg && S.cfg.tokens && S.cfg.tokens.PROD;
  const ok = m.text.trim() === 'PROD';
  const starting = !!f.starting;                                   // confirmed: the server is reading the workbook and starting the runner (seconds on a big workbook)
  return frame('Run on PROD?', html`
<div style="width: 44px; height: 44px; border-radius: 13px; background: var(--fail-soft); border: 1px solid var(--fail-line); color: var(--fail); display: grid; place-items: center; margin-top: 12px">${icon('warn', 22)}</div>
<p style="font-size: 13px; color: var(--tx2); margin-top: 12px; line-height: 1.55">PROD runs are real transactions on the live site: real orders, real emails. None of it can be undone from here.</p>
<div class="kv" style="grid-template-columns: 96px 1fr; margin-top: 18px; padding: 14px 16px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line); font-size: 12.5px">
${books.length > 1 ? html`<span>Workbooks</span><span class="mono" style="overflow-wrap: anywhere">${books.map((n) => shortName(n)).join(', ')}</span>` : ''}
${books.length > 1 && prodBooks.length !== books.length ? html`<span>On PROD</span><span class="mono" style="overflow-wrap: anywhere">${prodBooks.map((n) => shortName(n)).join(', ')}</span>` : ''}
<span>Tests</span><span class="mono">${chosen.length} · ${num(steps)} steps</span><span>Workers</span><span class="mono">${f.workers}</span>
<span>Token</span><span><span class="tag ${set ? '' : 'tag-warn'}">${S.cfg ? S.cfg.cookie_name : ''} · PROD: ${set ? 'set' : 'missing'}</span></span></div>
<div style="margin-top: 18px"><label class="lbl" for="prod-text" style="display: block; margin-bottom: 8px">Type PROD to confirm</label>
<input id="prod-text" class="fld" type="text" autocomplete="off" spellcheck="false" style="letter-spacing: .1em; border-color: var(--fail-line)" value="${m.text}" data-input="prod-text" data-enter="confirm-prod" ${starting ? raw('readonly') : ''}></div>
<div style="display: flex; gap: 10px; margin-top: 20px"><button class="btn" style="flex: 1" data-act="close-modal" ${starting ? raw('disabled') : ''}>Cancel</button>
<button class="btn btn-dng ${starting ? 'busy' : ''}" style="flex: 1.4; border-color: var(--fail)" data-act="confirm-prod" ${starting ? raw('aria-disabled="true"') : ok ? '' : raw('disabled')}>${starting
  ? html`<span class="spin" style="display: inline-flex">${icon('refresh', 16)}</span> Starting the run…` : 'Run on PROD'}</button></div>
${starting
  ? html`<div id="prod-starting" style="margin-top: 14px">${banner('acc', 'info', html`<b>Info:</b> your confirmation was received and the run is starting. Reading the workbook and starting the runner can take several seconds on a large workbook. Keep this window open; the run screen opens by itself.`)}</div>`
  : html`<div class="flag" style="margin-top: 12px; text-align: center">adds --allow-prod</div>`}`, { danger: true, locked: starting });
}

// ---- delete a workbook ------------------------------------------------------------------------------------------------
function deleteWb(S, m) {
  return frame('Delete this workbook?', html`
<div style="width: 44px; height: 44px; border-radius: 13px; background: var(--fail-soft); border: 1px solid var(--fail-line); color: var(--fail); display: grid; place-items: center; margin-top: 12px">${icon('trash', 22)}</div>
<div class="mono" style="margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line); font-size: 12.5px; overflow-wrap: anywhere">${m.name}</div>
<p style="font-size: 13px; color: var(--tx2); margin-top: 12px; line-height: 1.55">It leaves the list. Past runs are not touched (each keeps its own copy of the workbook it ran), and the file is moved to <span class="mono">workbooks/.trash/</span> rather than erased, so it can be put back by hand.</p>
${m.error ? html`<div style="margin-top: 12px">${banner('fail', 'failc', m.error)}</div>` : ''}
<div style="display: flex; gap: 10px; margin-top: 20px"><button class="btn" style="flex: 1" data-act="close-modal">Keep it</button>
<button class="btn btn-dng ${m.busy ? 'busy' : ''}" style="flex: 1.4; border-color: var(--fail)" data-act="confirm-delete-wb" ${m.busy ? raw('disabled') : ''}>${icon('trash', 15)} ${m.busy ? 'Deleting…' : 'Delete workbook'}</button></div>`, { danger: true });
}

// ---- SSO sign-in -------------------------------------------------------------------------------------------------------
function signin(S, m) {
  const opened = m.stage === 'open' || m.stage === 'saving';
  const step = (state, n, title, text) => html`<div style="display: flex; gap: 14px; padding-bottom: ${n === 3 ? 0 : 16}px">
${state === 'done' ? html`<span style="width: 24px; height: 24px; flex: none; border-radius: 50%; background: var(--pass-soft); border: 1px solid var(--pass-line); color: var(--pass); display: grid; place-items: center">${icon('check', 13)}</span>`
    : state === 'now' ? html`<span class="mono" style="width: 24px; height: 24px; flex: none; border-radius: 50%; background: var(--acc-soft); border: 1px solid var(--acc); color: var(--acc); display: grid; place-items: center; font-size: 11px; font-weight: 600">${n}</span>`
    : html`<span class="mono" style="width: 24px; height: 24px; flex: none; border-radius: 50%; border: 1.5px dashed var(--pend); color: var(--tx3); display: grid; place-items: center; font-size: 11px">${n}</span>`}
<div><div style="font-weight: 600; font-size: 13px; ${state === 'todo' ? 'color: var(--tx2)' : ''}">${title}</div>${text ? html`<div style="font-size: 12px; color: var(--tx2)">${text}</div>` : ''}</div></div>`;
  return frame('Save an SSO session', html`
<p style="font-size: 13px; color: var(--tx2); margin-top: 8px; line-height: 1.55">Every headless test reuses this session, so you sign in once.</p>
<div style="margin-top: 16px"><label class="lbl" for="signin-url" style="display: block; margin-bottom: 8px">Site to sign in to</label>
<input id="signin-url" class="fld" type="url" style="font-size: 12.5px" value="${m.url}" data-input="signin-url" placeholder="https://…" ${opened ? raw('readonly') : ''} autocomplete="off"></div>
${m.error ? html`<div style="margin-top: 12px">${banner('fail', 'failc', m.error)}</div>` : ''}
<div style="display: flex; flex-direction: column; margin-top: 20px">
${step(opened ? 'done' : 'now', 1, opened ? 'A browser window opened' : 'Open the sign-in window', opened ? 'This is the only run that shows a window.' : 'A visible browser window will open on this computer.')}
${step(opened ? 'now' : 'todo', 2, 'Sign in yourself in that window', opened ? 'SSO and MFA are yours to complete. Nothing you type is seen or stored here.' : '')}
${step('todo', 3, 'Come back and save', '')}</div>
<div style="display: flex; gap: 10px; margin-top: 22px"><button class="btn" style="flex: 1" data-act="signin-cancel">Cancel</button>
${opened ? html`<button class="btn btn-pri ${m.stage === 'saving' ? 'busy' : ''}" style="flex: 1.6" data-act="signin-save">${icon('lock', 15)} ${m.stage === 'saving' ? 'Saving…' : "I'm signed in, save"}</button>`
         : html`<button class="btn btn-pri ${m.stage === 'opening' ? 'busy' : ''}" style="flex: 1.6" data-act="signin-open">${icon('external', 15)} ${m.stage === 'opening' ? 'Opening…' : 'Open sign-in window'}</button>`}</div>
<div style="font-size: 12px; color: var(--tx3); margin-top: 14px; line-height: 1.5">Saved to <span class="mono">.auth/state.json</span>, readable only by you. Delete the file to sign out. Logins that need MFA on every run are not automated.</div>`);
}

// ---- lint ----------------------------------------------------------------------------------------------------------------
const SEV = { error: ['failc', 'var(--fail)', 'tag-fail'], warning: ['warn', 'var(--warn)', 'tag-warn'], info: ['list', 'var(--tx3)', ''] };

function lint(S, m) {
  if (m.loading) return frame('Lint', spinner('Checking every step…'), { wide: true });
  if (m.error) return frame('Lint', html`<div style="margin-top: 14px">${banner('fail', 'failc', m.error)}</div>`, { wide: true });
  const d = m.data;
  const rows = d.findings.filter((f) => m.filter === 'all' || f.severity === m.filter);
  const tab = (key, label, n) => html`<button class="${cx('chip', m.filter === key && 'chip-acc')}" data-act="lint-filter" data-val="${key}" aria-pressed="${String(m.filter === key)}">${label} · ${n}</button>`;
  return frame('Lint', html`
<p style="font-size: 13px; color: var(--tx2); margin: 8px 0 14px">Steps that will not behave the way the author probably assumes. Nothing here changes a run.</p>
<div class="tab-row" style="margin-bottom: 14px">${tab('all', 'All', d.findings.length)}${tab('error', 'Errors', d.counts.error)}${tab('warning', 'Warnings', d.counts.warning)}${tab('info', 'Notes', d.counts.info)}</div>
${rows.length ? html`<div class="scroll-y"><table class="tbl"><thead><tr><th style="width: 92px">Level</th><th style="width: 130px">Test</th><th style="width: 60px">Row</th><th>What</th></tr></thead><tbody>
${rows.map((f) => html`<tr><td><span class="tag ${SEV[f.severity][2]}">${f.severity}</span></td><td class="mono">${f.test}</td><td class="mono">${f.row ?? ''}</td><td style="overflow-wrap: anywhere">${f.message}</td></tr>`)}</tbody></table></div>`
  : html`<div style="padding: 24px; text-align: center; color: var(--tx2); border: 1.5px dashed var(--line2); border-radius: 13px">${d.findings.length ? 'Nothing at this level.' : 'No findings. The workbook looks consistent.'}</div>`}`, { wide: true });
}

// ---- dry-run plan ----------------------------------------------------------------------------------------------------------
function plan(S, m) {
  const d = m.data[m.test];
  const q = m.filter.trim().toLowerCase();
  const steps = d ? d.steps.filter((s) => !q || `${s.action} ${s.name} ${s.target} ${s.value}`.toLowerCase().includes(q)) : [];
  return frame('Dry-run plan', html`
<p style="font-size: 13px; color: var(--tx2); margin: 8px 0 14px">Every step that would run, after token substitution and gating. No browser is opened.</p>
<div class="tab-row" style="margin-bottom: 12px">${m.tests.map((id) => html`<button class="${cx('chip mono', m.test === id && 'chip-acc')}" data-act="plan-test" data-id="${id}" aria-pressed="${String(m.test === id)}">${id}</button>`)}</div>
<div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px"><input class="fld" style="max-width: 320px; height: 36px; font-family: var(--f-body); font-size: 13px" type="search" placeholder="Filter steps" aria-label="Filter steps" value="${m.filter}" data-input="plan-filter">
${d ? html`<span class="mono" style="font-size: 12px; color: var(--tx2)">${steps.length === d.count ? `${d.count} steps` : `${steps.length} of ${d.count} steps`}${d.truncated ? ' (first 5,000)' : ''}</span>` : ''}</div>
${m.error ? banner('fail', 'failc', m.error) : m.loading && !d ? spinner('Working out the steps…')
  : html`<div class="scroll-y"><table class="tbl"><thead><tr><th style="width: 52px">#</th><th style="width: 56px">Row</th><th style="width: 150px">Action</th><th>Step</th><th>Target</th><th>Value</th></tr></thead><tbody>
${steps.map((s) => html`<tr data-key="${s.n}"><td class="mono">${s.n}</td><td class="mono">${s.row}</td><td class="mono">${s.action}</td><td style="overflow-wrap: anywhere">${s.name}</td><td class="mono" style="overflow-wrap: anywhere">${s.target}</td><td class="mono" style="overflow-wrap: anywhere">${s.value}</td></tr>`)}</tbody></table></div>`}`, { wide: true });
}

// ---- audit -----------------------------------------------------------------------------------------------------------------
function audit(S, m) {
  if (m.loading) return frame('Locator health', spinner('Scoring every locator…'), { wide: true });
  if (m.error) return frame('Locator health', html`<div style="margin-top: 14px">${banner('fail', 'failc', m.error)}</div>`, { wide: true });
  const d = m.data;
  const box = (v, l, c) => html`<div style="padding: 12px 14px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line)"><div class="disp" style="font-size: 26px; font-weight: 700; line-height: 1.1; ${c ? 'color: ' + c : ''}">${v}</div><div style="font-size: 12px; color: var(--tx2)">${l}</div></div>`;
  return frame('Locator health', html`
<p style="font-size: 13px; color: var(--tx2); margin: 8px 0 16px">How resilient the workbook's locators are. Generic id / name / data-* locators survive page changes; positional and text-based XPaths do not.</p>
<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px">${box(num(d.uses), 'locator uses')}${box(d.covered_pct + '%', `covered by selectors.yaml (${num(d.map_entries)} entries)`, 'var(--pass)')}
${box(d.convertible_pct + '%', 'could be converted safely', 'var(--acc)')}${box(num(d.labels.weak), 'uses of weak locators', d.labels.weak ? 'var(--warn)' : '')}</div>
<div class="bar" style="margin-top: 14px"><div style="width: ${d.covered_pct}%; background: var(--pass)"></div></div>
<div class="lbl" style="margin: 20px 0 9px">Weakest locators, most fragile first</div>
<div class="scroll-y"><table class="tbl"><thead><tr><th style="width: 56px">Score</th><th style="width: 56px">Uses</th><th>Locator</th><th>Why</th></tr></thead><tbody>
${d.weakest.map((w) => html`<tr><td class="mono">${w.score}</td><td class="mono">${w.uses}</td><td class="mono" style="overflow-wrap: anywhere">${w.value}${w.css ? html`<div style="color: var(--acc); margin-top: 3px">→ ${w.css}</div>` : ''}</td>
<td style="font-size: 12px; color: var(--tx2)">${(w.reasons || []).join('; ')}${w.mapped ? html` <span class="tag tag-acc">in selectors.yaml</span>` : ''}</td></tr>`)}</tbody></table></div>
<div class="code" style="margin-top: 14px"><span style="color: var(--tx3)">$ </span>regrunner selectors migrate &lt;workbook&gt;</div>`, { wide: true });
}

// ---- selector merge ----------------------------------------------------------------------------------------------------------
function selectors(S, m) {
  if (m.loading) return frame('Review locators', spinner('Reading what the run learned…'), { wide: true });
  if (m.error) return frame('Review locators', html`<div style="margin-top: 14px">${banner('fail', 'failc', m.error)}</div>`, { wide: true });
  const d = m.data;
  const picked = d.suggestions.filter((s) => m.picked[s.key]).length;
  if (m.result) {
    return frame('Locators merged', html`<div style="margin-top: 14px">${banner('acc', 'passc', html`<b>${plural(m.result.added, 'locator')} added</b> to selectors.yaml (${num(m.result.total)} in total). The workbook was not modified; legacy XPaths stay as fallbacks.`)}</div>
<div style="display: flex; margin-top: 18px"><button class="btn btn-pri" style="margin-left: auto" data-act="close-modal">Done</button></div>`);
  }
  return frame('Review locators', html`
<p style="font-size: 13px; color: var(--tx2); margin: 8px 0 14px">Each of these was unique on the live page and clearly steadier than the workbook's XPath. Untick any you do not want.</p>
${d.suggestions.length ? html`<div class="scroll-y"><table class="tbl"><thead><tr><th style="width: 34px"></th><th>Workbook locator</th><th>Becomes</th><th style="width: 70px">Used</th></tr></thead><tbody>
${d.suggestions.map((s) => html`<tr data-key="${s.key}"><td><input type="checkbox" class="cb" ${m.picked[s.key] ? raw('checked') : ''} data-change="pick-suggestion" data-field="${s.key}" aria-label="Merge ${s.key}"></td>
<td class="mono" style="overflow-wrap: anywhere">${s.key}</td><td class="mono" style="color: var(--acc); overflow-wrap: anywhere">${s.use[0]}<div style="color: var(--tx3)">${s.kind} · score ${s.score} (was ${s.legacy_score})</div></td><td class="mono">${s.uses}×</td></tr>`)}</tbody></table></div>`
  : html`<div style="padding: 24px; text-align: center; color: var(--tx2); border: 1.5px dashed var(--line2); border-radius: 13px">${d.already ? `All ${d.already} suggestions are already in selectors.yaml.` : 'This run found nothing safe to suggest.'}</div>`}
${d.skipped.length ? html`<p style="font-size: 12px; color: var(--tx3); margin-top: 12px">${plural(d.skipped.length, 'locator')} skipped: not unique, not clearly steadier, or different steps disagreed.</p>` : ''}
<div style="display: flex; gap: 10px; margin-top: 18px"><button class="btn" data-act="close-modal">Cancel</button>
<button class="btn btn-pri ${m.applying ? 'busy' : ''}" style="margin-left: auto" data-act="apply-selectors" ${picked && !m.applying ? '' : raw('disabled')}>${icon('target', 16)} Merge ${plural(picked, 'locator')}</button></div>`, { wide: true });
}

// ---- log / doctor ---------------------------------------------------------------------------------------------------------------
function log(S, m) {
  return frame('Runner log', m.loading ? spinner('Reading the log…') : html`<div class="code" style="margin-top: 14px; max-height: 60vh; overflow: auto; white-space: pre-wrap; font-size: 11.5px; line-height: 1.55">${m.lines.length ? m.lines.join('\n') : 'The log is empty.'}</div>`, { wide: true });
}

function doctor(S, m) {
  const glyph = { ok: ['passc', 'var(--pass)'], warn: ['warn', 'var(--warn)'], err: ['failc', 'var(--fail)'] };
  return frame('Doctor', m.loading ? spinner('Launching a headless browser and checking the setup…') : html`
<p style="font-size: 13px; color: var(--tx2); margin: 8px 0 6px">The same checks as <span class="mono">regrunner doctor</span>. Nothing here touches a website.</p>
${(m.data ? m.data.checks : []).map((c) => html`<div style="display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid var(--line)"><span style="color: ${glyph[c.status][1]}; margin-top: 1px">${icon(glyph[c.status][0], 18)}</span>
<div style="min-width: 0"><div style="font-weight: 600; font-size: 13px">${c.label}</div><div style="color: var(--tx2); font-size: 12.5px; overflow-wrap: anywhere">${c.detail}</div></div></div>`)}
${m.error ? banner('fail', 'failc', m.error) : ''}`);
}

export function modalView(S) {
  const m = S.modal;
  if (!m) return '';
  switch (m.kind) {
    case 'prod': return prod(S, m);
    case 'delete-wb': return deleteWb(S, m);
    case 'signin': return signin(S, m);
    case 'lint': return lint(S, m);
    case 'plan': return plan(S, m);
    case 'audit': return audit(S, m);
    case 'selectors': return selectors(S, m);
    case 'log': return log(S, m);
    case 'doctor': return doctor(S, m);
    case 'lightbox': return html`<div class="lightbox" data-act="close-modal" role="dialog" aria-modal="true" aria-label="Screenshot"><img src="${m.src}" alt="Screenshot, enlarged"></div>`;
    default: return '';
  }
}
