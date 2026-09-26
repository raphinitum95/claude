// Screen 1: set up a run.  Every option `regrunner run` has is a control here, and the command line shown
// next to the Run button is built by the server from the very same request the button sends.
import { html, raw, cx } from '../util.js';
import { icon, pill } from '../icons.js';
import { num, bytes, modified, plural } from '../fmt.js';
import { banner, btn } from './shell.js';
import { filterWorkbooks, highlight, recentlyRun, MORE } from '../wbfilter.js';
import { browserLabel, browserChip } from '../browsers.js';

// ---- derived form state ---------------------------------------------------------------------------------
// Several workbooks can be chosen: each is a run of its own on one set of workers, with its own tests and run order; the settings are shared.
export const formTests = (S, name) => { const b = S.nr.bk[name]; return b && b.info ? b.info.tests : []; };
export const chosenTests = (S, name) => formTests(S, name).filter((t) => S.nr.bk[name].sel[t.id]);
/** Every ticked test of every chosen workbook, each carrying the workbook it belongs to (`wb`). */
export const allChosen = (S) => S.nr.books.flatMap((name) => chosenTests(S, name).map((t) => ({ ...t, wb: name })));
/** The workbook the "Check the workbook first" tools act on: the one picked there, else the first chosen. */
export const checkName = (S) => (S.nr.books.includes(S.nr.checkWb) ? S.nr.checkWb : S.nr.books[0] || null);
export const shortName = (name) => String(name).replace(/\.(xlsx|xlsm)$/i, '');

/** The environments the run will use: the one picked, else what each chosen workbook says (`Global!Environment`). */
export function envList(S) {
  if (S.nr.env) return [S.nr.env.toUpperCase()];
  const out = [];
  for (const name of S.nr.books) {
    const b = S.nr.bk[name];
    const e = b && b.info && b.info.environment ? String(b.info.environment).toUpperCase() : '';
    if (e && !out.includes(e)) out.push(e);
  }
  return out;
}
export const effEnv = (S) => envList(S).join(' + ');
export const hasProd = (S) => envList(S).includes('PROD');
export const booksReady = (S) => S.nr.books.length > 0 && S.nr.books.every((n) => S.nr.bk[n].load === 'ok');

/** The exact request the Run button sends (and the command preview is built from).  One workbook: the plain form; several: one entry each. */
export function buildRequest(S, extra = {}) {
  const f = S.nr;
  const picks = f.books.map((name) => {
    const tests = formTests(S, name);
    const chosen = chosenTests(S, name);
    const b = f.bk[name];
    const all = tests.length > 0 && chosen.length === tests.length;
    return { workbook: name, all, tests: all ? [] : chosen.map((t) => t.id),
             chains: b.chains.length ? b.chains : (b.chainsSource === 'none' ? null : []) };        // nothing to say unless there are chains (or the saved ones were cleared)
  });
  const shared = {
    env: f.env || null, browser: f.browser || null, workers: f.workers,
    screenshots: f.shots, retries: f.retries, seed: f.seed === '' ? null : Number(f.seed), pdf: f.pdf, harvest: f.harvest,
    headed: f.headed, nice: f.nice, no_report: f.noReport,
  };
  return picks.length === 1 ? { ...picks[0], ...shared, ...extra } : { workbooks: picks, ...shared, ...extra };
}

/** What the server knows about one browser (installed here?), or undefined until the preflight answers. */
export const browserOption = (S, id) => ((S.pre && S.pre.browsers) || []).find((b) => b.id === id);

/** The launch check for the browser picked on the form; null while the answer for it is still on its way (or for an older server that only knows one browser). */
export function browserCheck(S) {
  const pre = S.pre;
  if (!pre) return null;
  if (!pre.browsers) return pre.browser || pre.chromium || null;              // a server from before the Browser setting: it only ever checked one browser
  const chosen = pre.browsers.find((b) => b.selected);
  return chosen && chosen.id === S.nr.browser ? pre.browser : null;
}

/** Runs that are going, and whether a run started now shares their workers.  join: the same browser and window mode, so it is added to them;
 *  mismatch: they are the only workers there can be and use something else; own: there is room for workers of its own; none: nothing is going. */
export function poolState(S) {
  const f = S.nr;
  const active = S.runs.filter((r) => r.active);
  if (!active.length) return { kind: 'none', active };
  const pools = new Map();
  for (const r of active) if (r.pool) pools.set(r.pool.id, r.pool);
  const list = [...pools.values()];
  const limit = (S.cfg && S.cfg.max_concurrent_runs) || 1;
  const same = list.find((p) => p.joinable && p.browser === f.browser && p.headed === !!f.headed);
  if (same) return { kind: 'join', pool: same, active };
  if (list.length && list.length >= limit && list.some((p) => p.joinable)) return { kind: 'mismatch', pool: list.find((p) => p.joinable), active };
  return { kind: 'own', active };
}

/** Chosen workbooks that a run is already busy with: two runs of one workbook would place the same orders twice, so the server refuses it. */
export function runningNow(S) {
  const active = S.runs.filter((r) => r.active);
  return S.nr.books.map((name) => ({ name, run: active.find((r) => String(r.workbook || '').split(/[\\/]/).pop().toLowerCase() === name.toLowerCase()) })).filter((x) => x.run);
}

export function preflightItems(S) {
  const items = [];
  const f = S.nr;
  const pre = S.pre;
  const envs = envList(S);
  const names = f.books;
  const multi = names.length > 1;
  const noun = multi ? 'Workbooks' : 'Workbook';
  const bc = browserCheck(S);
  items.push(bc ? { kind: bc.status, label: bc.label || 'Browser', detail: bc.status === 'ok' ? (bc.data && bc.data.text ? `${bc.data.text} launches headless. No window will open.` : 'Launches headless. No window will open.') : bc.detail }
                : { kind: 'pend', label: browserLabel(f.browser) || 'Browser', detail: 'Checking…' });
  const picked = browserOption(S, f.browser);
  if (picked && picked.approximate) items.push({ kind: 'warn', label: 'Safari here is WebKit', detail: picked.what });
  if (!names.length) {
    items.push({ kind: 'err', label: 'No workbook', detail: 'Drop or pick an Excel workbook.' });
  } else {
    const loaded = names.filter((n) => f.bk[n].load === 'ok');
    const bad = names.filter((n) => f.bk[n].load === 'error');
    if (bad.length) items.push({ kind: 'err', label: noun, detail: multi ? `${bad.join(', ')} could not be read. Remove ${bad.length === 1 ? 'it' : 'them'} or choose another.` : 'Could not be read. Choose another.' });
    else if (loaded.length < names.length) items.push({ kind: 'pend', label: noun, detail: 'Reading…' });
    else {
      const w = loaded.reduce((a, n) => a + f.bk[n].info.warnings.length, 0);
      const sheets = loaded.reduce((a, n) => a + f.bk[n].info.sheets, 0);
      const warned = `${w ? `, ${w} warning${w === 1 ? '' : 's'}` : ', no warnings'}`;
      items.push({ kind: w ? 'warn' : 'ok', label: noun, detail: multi
        ? `${loaded.length} workbooks read (${sheets} test sheets${warned}). Each becomes a run of its own; they share the workers.`
        : `${sheets} test sheet${sheets === 1 ? '' : 's'} read${warned}.` });
    }
    for (const n of loaded) {
      if (!chosenTests(S, n).length) items.push({ kind: 'err', label: multi ? `No tests selected · ${n}` : 'No tests selected', detail: `Pick at least one test to run${multi ? `, or untick ${n}` : ''}.` });
    }
    for (const { name, run } of runningNow(S)) {
      items.push({ kind: 'err', label: `Already running · ${name}`, detail: `${name} is being run right now (${run.run_id}). Two runs of one workbook would place the same orders twice: wait for it or cancel it.` });
    }
  }
  const asking = allChosen(S).filter((t) => t.asks > 0);
  if (asking.length) items.push({ kind: 'warn', label: 'Will ask you for input', detail: `${asking.map((t) => (multi ? `${shortName(t.wb)} · ` : '') + t.id).join(', ')} pause${asking.length === 1 ? 's' : ''} and ask a question on the run screen (a code, a name...). Stay near it: an unanswered question fails its step after 5 minutes.` });
  const loadedNames = names.filter((n) => f.bk[n].load === 'ok');
  if (loadedNames.length) {                                        // the run order: working it out, what it found, or why it could not
    const failed = loadedNames.find((n) => f.bk[n].orderError);
    const waiting = loadedNames.some((n) => !f.bk[n].order);
    const streams = loadedNames.reduce((a, n) => a + (f.bk[n].order ? f.bk[n].order.streams.length : 0), 0);
    items.push(failed ? { kind: 'warn', label: 'Run order', detail: `Could not be worked out${multi ? ` for ${failed}` : ''} (${f.bk[failed].orderError}). The run works it out itself when it starts.` }
      : waiting ? { kind: 'pend', label: 'Run order', detail: 'Working out which tests wait for which…' }
      : { kind: 'ok', label: 'Run order', detail: streams ? `${streams} stream${streams === 1 ? '' : 's'}: a test that uses a value another test sets waits for it; streams that do not touch each other run side by side. See Run order below the tests.`
                                                        : 'No test waits for another: everything runs side by side.' });
  }
  const problems = loadedNames.flatMap((n) => (f.bk[n].order ? f.bk[n].order.notes : []).filter((x) => x.kind === 'missing' || x.kind === 'conflict').map((x) => ({ ...x, wb: n })));      // from the server: what nothing sets, what a chain contradicts
  if (problems.length) {
    items.push({ kind: 'warn', label: problems.some((x) => x.kind === 'missing') ? 'A test uses an empty parameter' : 'A chain contradicts the data',
      detail: `${problems.map((x) => (multi ? `${shortName(x.wb)}: ` : '') + x.message).join(' ')} An empty parameter is asked for on the run screen when the step is reached (used for this run only); if nobody answers, the step fails instead of typing the parameter's name.` });
  }
  if (envs.includes('PROD')) items.push({ kind: 'err', label: 'PROD is locked', detail: 'Needs your explicit confirmation before it starts (--allow-prod).' });
  if (S.cfg) {
    for (const env of envs) {
      const set = S.cfg.tokens && S.cfg.tokens[env];
      const cookie = S.cfg.cookie_name;
      items.push(set ? { kind: 'ok', label: `${cookie} · ${env}`, detail: 'Set in secrets.env. It is added as a cookie to every test.' }
                     : { kind: 'warn', label: `${cookie} · ${env}`, detail: `Not set. Every test sends it as a cookie, so a captcha may appear: the test stops there and a browser window opens for you to solve it. Add RECAPTCHA_BYPASS_TOKEN_${env} to secrets.env to avoid that.` });
    }
  }
  if (pre) {
    items.push(pre.sso.present ? { kind: 'ok', label: 'SSO session (Zscaler / Okta)', detail: 'A saved session is reused by every headless test.', action: 'Sign in again' }
                               : { kind: 'warn', label: 'SSO session (Zscaler / Okta)', detail: `No saved session at ${pre.sso.display}. Sign in once and every headless test reuses it.`, action: 'Sign in…' });
    const bad = pre.folders.filter((x) => x.status !== 'ok');
    items.push(bad.length ? { kind: 'err', label: 'Folders', detail: bad.map((x) => x.detail).join(' ') } : { kind: 'ok', label: 'Folders', detail: 'workbooks/ and runs/ are writable.' });
    if (pre.publish) items.push({ kind: pre.publish.status, label: pre.publish.label, detail: pre.publish.detail });
  }
  return items;
}

// ---- section: workbook -------------------------------------------------------------------------------------
function dropzone(S) {
  const f = S.nr;
  if (f.upload) {
    return html`<div style="border: 1px solid var(--line2); border-radius: 13px; padding: 14px 16px; background: var(--surface2)">
<div style="display: flex; align-items: center; gap: 10px"><span style="color: var(--acc); display: inline-flex">${icon('grid', 18)}</span>
<span style="font-weight: 600; font-size: 13px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">${f.upload.name}</span>
<span class="mono" style="font-size: 12px; color: var(--tx2)">${Math.round(f.upload.pct * 100)}%</span>
<button aria-label="Cancel upload" data-act="cancel-upload" style="color: var(--tx2); display: inline-flex">${icon('x', 16)}</button></div>
<div class="bar" style="margin-top: 11px"><div style="width: ${Math.round(f.upload.pct * 100)}%"></div></div></div>`;
  }
  if (f.drag) {
    return html`<div class="drop over" data-dropzone style="border: 1.5px solid var(--acc); border-radius: 14px; height: 112px; display: flex; align-items: center; justify-content: center; gap: 12px; background: var(--acc-soft); color: var(--acc); font-weight: 650">${icon('upload', 22)} Release to upload</div>`;
  }
  return html`<div class="drop" data-dropzone style="border: 1.5px dashed var(--line2); border-radius: 14px; min-height: 112px; display: flex; align-items: center; gap: 18px; padding: 16px 24px; background: var(--surface2)">
<div style="width: 54px; height: 54px; flex: none; border-radius: 15px; background: var(--acc-soft); border: 1px solid var(--acc-line); color: var(--acc); display: grid; place-items: center">${icon('upload', 24)}</div>
<div style="display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0">
<div style="font-weight: 650; font-size: 16px">Drop Excel workbooks here</div>
<div style="color: var(--tx2); font-size: 13px">or <label class="lnk" for="file-input" style="cursor: pointer">browse your files</label> · .xlsx or .xlsm · up to ${(S.cfg && S.cfg.max_upload_mb) || 50} MB · stays on this machine</div></div>
<input id="file-input" class="sr" type="file" accept=".xlsx,.xlsm" multiple data-change="file-picked" aria-label="Choose Excel workbooks"></div>`;
}

function workbookRow(S, w) {
  const f = S.nr;
  const on = f.books.includes(w.name);
  const b = on ? f.bk[w.name] : null;
  let status = '';
  if (on && b.load === 'loading') status = html`<span class="pill p-pend"><span class="spin" style="display: inline-flex">${icon('refresh', 12)}</span> Reading</span>`;
  else if (on && b.load === 'ok') status = html`<span class="pill p-pass">${icon('check', 12)} Read OK</span>`;
  else if (on && b.load === 'error') status = html`<span class="pill p-fail">${icon('x', 12)} Unreadable</span>`;
  return html`<label class="trow" data-key="${w.name}" style="display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 13px; border: 1px solid ${on ? 'var(--acc-line)' : 'var(--line)'}; background: ${on ? 'var(--acc-soft)' : 'transparent'}; cursor: pointer">
<input type="checkbox" name="workbook" class="sr" value="${w.name}" ${on ? raw('checked') : ''} data-change="pick-workbook" aria-label="Run ${w.name}">
<div style="width: 42px; height: 42px; flex: none; border-radius: 11px; background: var(--surface); border: 1px solid var(--line2); display: grid; place-items: center; color: var(--pass)">${icon('grid', 20)}</div>
<div style="flex: 1; min-width: 0"><div style="font-weight: 650; font-size: 14.5px; overflow-wrap: anywhere">${highlight(w.name, S.nr.wbq)}</div>
<div class="mono" style="font-size: 11.5px; color: var(--tx2); margin-top: 2px">${bytes(w.size)} · modified ${modified(w.modified)}</div></div>
${status}
<button type="button" class="wb-del" data-act="ask-delete-wb" data-field="${w.name}" aria-label="Delete ${w.name}" title="Delete this workbook">${icon('trash', 16)}</button>
<span aria-hidden="true" style="width: 20px; height: 20px; flex: none; border-radius: 6px; border: 1.5px solid ${on ? 'var(--acc)' : 'var(--line2)'}; background: ${on ? 'var(--acc)' : 'transparent'}; color: var(--bg); display: grid; place-items: center">${on ? icon('check', 13) : ''}</span></label>`;
}

function stat(value, label, color) {
  return html`<div style="padding: 12px 14px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line)">
<div class="disp" style="font-size: 26px; font-weight: 700; line-height: 1.1${color ? '; color: ' + color : ''}">${value}</div><div style="font-size: 12px; color: var(--tx2)">${label}</div></div>`;
}

const SEARCH_FROM = 6;            // a folder this small needs no search box

function workbookList(S) {
  const f = S.nr;
  const all = S.workbooks;
  if (!all.length) {
    return html`<div class="lbl" style="margin: 20px 0 9px">In workbooks/ · 0</div>
<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 22px 16px; text-align: center"><div style="color: var(--tx3); display: inline-flex">${icon('grid', 26)}</div>
<div style="font-weight: 650; margin-top: 8px">No workbooks yet</div><div style="font-size: 12.5px; color: var(--tx2); margin-top: 2px">Drop one on the upload area to begin.</div></div>`;
  }
  const matches = filterWorkbooks(all, f.wbq, f.wbSort);
  const shown = matches.slice(0, f.wbLimit);
  const pinned = all.filter((w) => f.books.includes(w.name) && !shown.includes(w));          // the chosen ones never disappear behind a search or the cap
  const searchable = all.length >= SEARCH_FROM || f.wbq;
  const left = matches.length - shown.length;
  const recent = !f.wbq && all.length > 8 ? recentlyRun(S.runs, all) : [];
  const sortBtn = (key, label) => html`<button class="lnk" data-act="wb-sort" data-field="${key}" aria-pressed="${f.wbSort === key}" style="${f.wbSort === key ? '' : 'color: var(--tx3); font-weight: 500'}">${label}</button>`;
  return html`<div style="display: flex; align-items: center; gap: 12px; margin: 20px 0 9px"><div class="lbl">In workbooks/ · ${f.wbq ? `${matches.length} of ${all.length}` : all.length}</div>
<span style="font-size: 12px; color: var(--tx3)">Tick one or more: each becomes a run of its own, on shared workers</span>
${searchable ? html`<div style="margin-left: auto; display: flex; gap: 12px; align-items: center"><span class="lbl" style="letter-spacing: .05em">Sort</span>${sortBtn('new', 'Newest')}${sortBtn('name', 'A–Z')}</div>` : ''}</div>
${searchable ? html`<div class="field" style="position: relative; margin-bottom: 10px">
<span aria-hidden="true" style="position: absolute; left: 13px; top: 50%; transform: translateY(-50%); color: var(--tx3); display: inline-flex; pointer-events: none">${icon('search', 16)}</span>
<input id="wb-search" class="fld" type="text" style="padding-left: 38px; padding-right: 38px" placeholder="Search ${all.length} workbooks by name…" aria-label="Search workbooks" autocomplete="off" spellcheck="false" value="${f.wbq}" data-input="wb-search" data-enter="wb-search-enter" data-esc="wb-search-clear">
${f.wbq ? html`<button aria-label="Clear search" data-act="wb-search-clear" style="position: absolute; right: 11px; top: 50%; transform: translateY(-50%); color: var(--tx2); display: inline-flex">${icon('x', 16)}</button>` : ''}</div>` : ''}
${recent.length ? html`<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px"><span class="lbl">Recently run</span>
${recent.map((name) => html`<button class="chip" data-key="recent-${name}" data-act="pick-workbook-name" data-field="${name}" title="${name}" aria-pressed="${String(f.books.includes(name))}" style="cursor: pointer; max-width: 300px; overflow: hidden; text-overflow: ellipsis${f.books.includes(name) ? '; border-color: var(--acc-line); color: var(--acc)' : ''}">${name}</button>`)}</div>` : ''}
<div class="sr" role="status" aria-live="polite">${f.wbq ? `${matches.length} of ${all.length} workbooks match` : ''}</div>
${pinned.length ? html`<div class="lbl" style="margin: 2px 0 7px">Selected${f.wbq && pinned.some((w) => !matches.includes(w)) ? ' (some not in this search)' : ''}</div>
<div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px" role="group" aria-label="Selected workbooks">${pinned.map((w) => workbookRow(S, w))}</div>` : ''}
${matches.length
    ? html`<div style="display: flex; flex-direction: column; gap: 8px" role="group" aria-label="Workbooks">${shown.map((w) => workbookRow(S, w))}</div>
${left > 0 ? html`<div style="display: flex; justify-content: center; margin-top: 12px"><button class="btn btn-ghost btn-sm" data-act="wb-more">Show ${Math.min(MORE, left)} more · ${left} left</button></div>` : ''}`
    : html`<div style="border: 1.5px dashed var(--line2); border-radius: 13px; padding: 20px 16px; text-align: center"><div style="font-weight: 650">No workbook matches “${f.wbq}”</div>
<div style="font-size: 12.5px; color: var(--tx2); margin-top: 3px">Try fewer or shorter words, or <button class="lnk" data-act="wb-search-clear">clear the search</button>. A workbook that is not in the folder yet can be dropped on the upload area above.</div></div>`}
`;
}

/** What was found in each chosen workbook: read errors, warnings, and the numbers (one workbook: four tiles; several: a row each). */
function bookNotes(S) {
  const f = S.nr;
  const multi = f.books.length > 1;
  const errored = f.books.filter((n) => f.bk[n].load === 'error');
  const warned = f.books.filter((n) => f.bk[n].load === 'ok' && f.bk[n].info.warnings.length);
  const loaded = f.books.filter((n) => f.bk[n].load === 'ok');
  const loading = f.books.filter((n) => f.bk[n].load === 'loading');
  return html`${errored.map((n) => { const b = f.bk[n]; return html`<div style="margin-top: 14px" data-key="err-${n}">${banner('fail', 'failc', html`<b>Could not read ${n}.</b> ${b.err.message}`,
    html`${btn(multi ? 'Remove it' : 'Choose another', 'choose-another', { wb: n })}${btn(b.err.showDetails ? 'Hide details' : 'Show details', 'toggle-details', { cls: 'btn-ghost', wb: n })}`,
    b.err.showDetails ? html`<div class="code" style="font-size: 11px; line-height: 1.55; white-space: pre-wrap; max-height: 220px; overflow: auto">${b.err.details || b.err.message}</div>` : '')}</div>`; })}
${warned.map((n) => { const info = f.bk[n].info; return html`<div style="margin-top: 14px" data-key="warn-${n}">${banner('warn', 'warn',
    html`<b>${multi ? `${n}: ` : ''}${info.warnings.length} workbook warning${info.warnings.length === 1 ? '' : 's'}.</b> The run can still start.`, '',
    html`<ul style="display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--tx2)">${info.warnings.slice(0, 6).map((w) => html`<li>${w}</li>`)}${info.warnings.length > 6 ? html`<li>… ${info.warnings.length - 6} more (see Lint)</li>` : ''}</ul>`)}</div>`; })}
${!multi && loaded.length === 1 ? (() => { const info = f.bk[loaded[0]].info; return html`<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 14px">
${stat(info.sheets, 'test sheets')}${stat(info.flagged, 'flagged Y in DataSheets')}${stat(info.environment || '–', 'Global!Environment')}
${stat(info.warnings.length, 'workbook warnings', info.warnings.length ? 'var(--warn)' : 'var(--pass)')}</div>`; })()
  : multi && loaded.length ? html`<div style="margin-top: 14px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden" role="table" aria-label="Chosen workbooks">
<div style="display: grid; grid-template-columns: minmax(0, 1fr) 84px 84px 84px 72px; gap: 12px; padding: 9px 14px; background: var(--surface2)"><span class="lbl">Workbook</span><span class="lbl">Sheets</span><span class="lbl">Flagged Y</span><span class="lbl">Env</span><span class="lbl">Warn</span></div>
${loaded.map((n) => { const info = f.bk[n].info; return html`<div style="display: grid; grid-template-columns: minmax(0, 1fr) 84px 84px 84px 72px; gap: 12px; padding: 10px 14px; border-top: 1px solid var(--line); font-size: 12.5px" data-key="sum-${n}">
<span style="overflow-wrap: anywhere; font-weight: 600">${n}</span><span class="mono">${info.sheets}</span><span class="mono">${info.flagged}</span><span class="mono">${info.environment || '–'}</span><span class="mono" style="${info.warnings.length ? 'color: var(--warn)' : ''}">${info.warnings.length}</span></div>`; })}</div>` : ''}
${loading.length && !loaded.length ? html`<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 14px">${[1, 2, 3, 4].map(() => html`<div class="skel" style="height: 68px"></div>`)}</div>` : ''}`;
}

function workbookCard(S) {
  const f = S.nr;
  return html`<section class="card" style="padding: 22px">
<div style="display: flex; align-items: center; gap: 12px; margin-bottom: 18px"><div class="step-n">1</div><h2 class="ttl">Workbook${f.books.length > 1 ? 's' : ''}</h2>
${f.books.length > 1 ? html`<span class="chip mono">${f.books.length} chosen</span>` : ''}
<span class="chip mono" style="margin-left: auto">${icon('folder', 14)} workbooks/</span></div>
${dropzone(S)}
${f.uploadErr ? html`<div style="margin-top: 10px">${banner('fail', 'failc', f.uploadErr)}</div>` : ''}
${workbookList(S)}
${bookNotes(S)}
</section>`;
}

// ---- section: tests -------------------------------------------------------------------------------------------
function tagSet(S, name) {
  const tags = {};
  for (const t of formTests(S, name)) for (const g of t.tags || []) (tags[g] = tags[g] || []).push(t.id);
  return tags;
}

/** The tests of one chosen workbook.  A card per workbook: which tests run is decided for each on its own. */
function testsCard(S, name, index) {
  const f = S.nr;
  const b = f.bk[name];
  const multi = f.books.length > 1;
  const tests = formTests(S, name);
  const maxSteps = Math.max(1, ...tests.map((t) => t.steps));
  const tags = tagSet(S, name);
  const chosen = chosenTests(S, name).map((t) => t.id).sort().join('|');
  const fromConfig = S.cfg && Object.keys(S.cfg.tags || {}).some((g) => tags[g]);
  const w = html`data-wb="${name}"`;
  return html`<section class="card" style="padding: 22px 0 8px" data-key="tests-${name}">
<div style="display: flex; align-items: center; gap: 12px; padding: 0 22px; flex-wrap: wrap">${index === 0 ? html`<div class="step-n">2</div>` : ''}<h2 class="ttl">Tests</h2>
${multi ? html`<span class="chip mono" style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" title="${name}">${icon('grid', 14)} ${name}</span>` : ''}
<span class="mono" style="font-size: 12.5px; color: var(--tx2)">${chosenTests(S, name).length} of ${tests.length} selected</span>
<div style="margin-left: auto; display: flex; align-items: center; gap: 14px">
<button class="lnk" data-act="sel-defaults" ${w}>Workbook defaults</button><button class="lnk" data-act="sel-all" ${w}>All</button><button class="lnk" data-act="sel-none" ${w}>None</button></div></div>
${Object.keys(tags).length ? html`<div style="display: flex; align-items: center; gap: 10px; padding: 14px 22px 4px; flex-wrap: wrap"><span class="lbl">Tags</span>
${Object.entries(tags).map(([g, ids]) => html`<button class="${cx('chip', ids.slice().sort().join('|') === chosen && 'chip-acc')}" data-act="sel-tag" data-tag="${g}" ${w} aria-pressed="${String(ids.slice().sort().join('|') === chosen)}">${g} · ${ids.length}</button>`)}
<span style="font-size: 12px; color: var(--tx3)">${fromConfig ? 'from config.yaml' : 'from the workbook'}</span></div>` : ''}
<div style="display: grid; grid-template-columns: 20px minmax(0, 1fr) 118px 92px; gap: 16px; padding: 9px 22px; border-top: 1px solid var(--line); background: var(--surface2); margin-top: 14px">
<span></span><span class="lbl">Test</span><span class="lbl">Steps</span><span class="lbl">Flags</span></div>
${b.load === 'loading' ? [1, 2, 3].map(() => html`<div style="padding: 12px 22px; border-top: 1px solid var(--line)"><div class="skel" style="height: 40px"></div></div>`) : ''}
${b.load === 'ok' && !tests.length ? html`<div style="padding: 22px; border-top: 1px solid var(--line); color: var(--tx2)">This workbook has no UI test sheets.</div>` : ''}
${tests.map((t) => {
    const on = !!b.sel[t.id];
    return html`<label class="trow" data-key="${t.id}" style="display: grid; grid-template-columns: 20px minmax(0, 1fr) 118px 92px; gap: 16px; align-items: center; padding: 12px 22px; border-top: 1px solid var(--line); cursor: ${t.runnable ? 'pointer' : 'not-allowed'}; background: ${on ? 'var(--acc-soft)' : 'transparent'}">
<input type="checkbox" class="cb" ${on ? raw('checked') : ''} ${t.runnable ? '' : raw('disabled')} data-change="toggle-test" data-id="${t.id}" ${w} aria-label="Run ${t.id}${multi ? ` in ${name}` : ''}">
<div style="min-width: 0"><div style="display: flex; align-items: center; gap: 9px"><span class="mono" style="font-weight: 600; font-size: 13.5px">${t.id}</span>${t.kind === 'api' ? html`<span class="tag" title="An API test: sends a request and checks the JSON answer; no browser">API</span>` : ''}<span class="mono" style="font-size: 11px; color: var(--tx3)">${t.scenario}</span></div>
<div style="color: var(--tx2); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${t.description}</div></div>
<div><div class="mono" style="font-size: 13px">${t.steps}</div><div class="bar" style="height: 4px; margin-top: 6px"><div style="width: ${Math.round((100 * t.steps) / maxSteps)}%"></div></div></div>
<div style="display: flex; flex-direction: column; gap: 5px; align-items: flex-start">
${t.enabled ? html`<span class="tag tag-acc">default Y</span>` : ''}
${t.runnable ? '' : html`<span class="tag tag-fail" title="The parameter sheet has no row with blnExecute=Y">no param row</span>`}</div></label>`;
  })}
</section>`;
}

// ---- section: run order ---------------------------------------------------------------------------------------------
/** Which tests wait for which, in one chosen workbook.  Tests that use a value another test sets wait for it; a chain fixes an order by hand (arrows). */
function orderCard(S, name, index) {
  const f = S.nr;
  const b = f.bk[name];
  const o = b.order;
  if (b.load !== 'ok' || !o) return '';
  const multi = f.books.length > 1;
  const streams = o.streams || [];
  const hints = (o.notes || []).filter((x) => x.kind === 'parallel' || x.kind === 'chain_unknown' || x.kind === 'after_ui');
  if (!streams.length && !hints.length && !b.chains.length) return '';
  const w = html`data-wb="${name}"`;
  const arrow = (id, dir, glyph, label, off) => html`<button class="stp" style="width: 30px; height: 28px" data-act="order-move" data-id="${id}" data-dir="${dir}" ${w} aria-label="${label} ${id}${multi ? ` in ${name}` : ''}" ${off ? raw('disabled') : ''}>${glyph}</button>`;
  return html`<section class="card" style="padding: 22px 0 6px" id="${index === 0 ? 'run-order' : `run-order-${index + 1}`}" data-key="order-${name}">
<div style="display: flex; align-items: center; gap: 12px; padding: 0 22px; flex-wrap: wrap"><h2 class="ttl">Run order</h2>
${multi ? html`<span class="chip mono" style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" title="${name}">${icon('grid', 14)} ${name}</span>` : ''}
<span class="chip mono">${streams.length} stream${streams.length === 1 ? '' : 's'}</span>
<div style="margin-left: auto; display: flex; align-items: center; gap: 14px">
${b.chainsDirty ? html`<span class="mono" style="font-size: 11.5px; color: var(--warn)">not saved</span>` : b.chainsSource === 'saved' ? html`<span class="mono" style="font-size: 11.5px; color: var(--tx3)">saved for this workbook</span>` : ''}
${b.chainsDirty ? html`<button class="lnk" data-act="order-save" ${w}>Save this order</button>` : ''}
${b.chains.length ? html`<button class="lnk" data-act="order-reset" ${w}>Clear chains</button>` : ''}</div></div>
<p style="font-size: 12.5px; color: var(--tx2); margin: 8px 22px 12px">A test that uses a value another test sets waits for it. Streams that do not touch each other run side by side. Use the arrows to make tests in a stream run one after another in the order shown.</p>
${streams.map((st, i) => html`<div style="border-top: 1px solid var(--line); padding: 12px 22px 8px" data-key="stream-${i}">
<div style="display: flex; align-items: center; gap: 9px; margin-bottom: 6px"><span class="lbl">Stream ${i + 1}</span>${st.params.map((x) => html`<span class="tag tag-acc">${x}</span>`)}</div>
${st.tests.map((t, k) => {
    const waits = (o.deps[t] || []).filter((d) => st.tests.includes(d));
    return html`<div style="display: grid; grid-template-columns: 26px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 7px 0" data-key="ord-${t}">
<span class="mono" style="width: 24px; height: 24px; border-radius: 50%; background: var(--acc-soft); color: var(--acc); border: 1px solid var(--acc-line); display: grid; place-items: center; font-size: 11.5px; font-weight: 600">${st.levels[t] + 1}</span>
<div style="min-width: 0"><b class="mono" style="font-size: 13px">${t}</b>${(formTests(S, name).find((x) => x.id === t) || {}).kind === 'api' ? html` <span class="tag">API</span>` : ''}<div class="mono" style="font-size: 11.5px; color: var(--tx3)">${waits.length ? `waits for ${waits.join(', ')}` : 'starts first'}</div></div>
<div style="display: flex; gap: 4px">${arrow(t, -1, '↑', 'Run earlier:', k === 0)}${arrow(t, 1, '↓', 'Run later:', k === st.tests.length - 1)}</div></div>`;
  })}</div>`)}
${hints.map((x) => html`<div style="display: flex; gap: 10px; padding: 11px 22px; border-top: 1px solid var(--line); font-size: 12.5px; color: var(--tx2)" data-key="hint-${x.test}"><span style="color: var(--warn); display: inline-flex; margin-top: 1px">${icon('warn', 16)}</span><span>${x.message}</span></div>`)}
</section>`;
}

// ---- section: settings ---------------------------------------------------------------------------------------------
const stepper = (key, label, value) => html`<div style="display: flex; align-items: center; height: 42px; border: 1px solid var(--line2); border-radius: 11px; overflow: hidden; background: var(--bg); width: max-content">
<button class="stp" aria-label="Fewer ${label}" data-act="step" data-field="${key}" data-d="-1">${icon('minus', 16)}</button>
<div class="mono" style="width: 42px; text-align: center; font-size: 17px; font-weight: 600" aria-live="polite">${value}</div>
<button class="stp" aria-label="More ${label}" data-act="step" data-field="${key}" data-d="1">${icon('plus', 16)}</button></div>`;

const toggle = (key, title, flag, sub, on, subColor) => html`<label style="display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface2); cursor: pointer">
<span style="flex: 1; min-width: 0"><span style="display: block; font-weight: 600; font-size: 13.5px">${title}</span>
${sub ? html`<span style="display: block; font-size: 12px; color: ${subColor || 'var(--tx3)'}; margin-top: 2px">${sub}</span>` : ''}
${flag ? html`<span class="flag" style="display: block; margin-top: 2px">${flag}</span>` : ''}</span>
<input type="checkbox" class="sw" ${on ? raw('checked') : ''} data-change="toggle" data-field="${key}" aria-label="${title}"></label>`;

/** "Not downloaded yet. Run: /path/python -m playwright install webkit" -> the sentence, then the command as code. */
function withCommand(text) {
  const at = String(text).indexOf('Run: ');
  return at < 0 ? text : html`${text.slice(0, at + 4)} <code class="mono" style="user-select: all; overflow-wrap: anywhere">${text.slice(at + 5)}</code>`;
}

/** Which browser the tests run in: Chrome / Edge / Safari (WebKit) / Chromium.  One that is not on this computer is greyed out and says why. */
function browserControl(S) {
  const f = S.nr;
  const kinds = (S.cfg && S.cfg.browsers) || [];
  if (!kinds.length) return '';                                   // a server from before the Browser setting: nothing to choose from
  const opt = (id) => browserOption(S, id);
  const down = (id) => { const o = opt(id); return !!o && !o.installed && f.browser !== id; };
  // Chromium is a download some networks block: offer it only once it is known to be here, or when it is already what is picked (config.yaml chose it)
  const shown = kinds.filter((k) => k.id !== 'chromium' || k.id === f.browser || (opt('chromium') && opt('chromium').installed));
  const cur = kinds.find((k) => k.id === f.browser);
  const bc = browserCheck(S);
  const status = !S.pre || !bc ? html`<span style="color: var(--tx3)">Checking ${cur ? cur.label : 'the browser'}…</span>`
    : bc.status === 'ok' ? html`<span style="color: var(--pass); display: inline-flex; vertical-align: -3px">${icon('check', 15)}</span> ${bc.data && bc.data.text ? bc.data.text : bc.label} starts fine.${f.headed ? ' Its windows will be shown while the tests run.' : ' It runs headless, so no window opens.'}`
    : html`<span style="color: var(--fail)">${withCommand(bc.detail)}</span>`;
  const missing = shown.filter((k) => down(k.id));
  return html`<div style="margin-top: 24px"><div style="display: flex; align-items: baseline; margin-bottom: 9px"><span class="lbl" id="lbl-browser">Browser</span><span class="flag" style="margin-left: auto">--browser</span></div>
<div class="seg" role="group" aria-labelledby="lbl-browser">${shown.map((k) => html`<button class="${cx(f.browser === k.id && 'on')}" aria-pressed="${String(f.browser === k.id)}" data-act="set" data-field="browser" data-val="${k.id}" data-browser="${k.id}" ${down(k.id) ? raw('disabled') : ''} title="${down(k.id) ? opt(k.id).detail : k.what}">${k.short}</button>`)}</div>
<div id="browser-note" style="font-size: 12.5px; color: var(--tx2); margin-top: 10px; line-height: 1.5">${status}</div>
${cur && cur.approximate ? html`<div style="display: flex; gap: 9px; margin-top: 8px; font-size: 12px; color: var(--tx2); line-height: 1.5"><span style="color: var(--warn); display: inline-flex; margin-top: 2px; flex: none">${icon('warn', 14)}</span><span><b>Safari here means WebKit.</b> ${cur.what}</span></div>` : ''}
${missing.map((k) => html`<div style="font-size: 12px; color: var(--tx3); margin-top: 6px; line-height: 1.5" data-key="missing-${k.id}"><b style="color: var(--tx2)">${k.short}:</b> ${withCommand(opt(k.id).detail)}</div>`)}</div>`;
}

function settingsCard(S) {
  const f = S.nr;
  const cfg = S.cfg || {};
  const envs = envList(S);
  const own = [...new Set(f.books.map((n) => (f.bk[n].info && f.bk[n].info.environment) || '').filter(Boolean))];
  const envDefs = [['', `Workbook default${own.length ? ' · ' + own.join(' + ') : ''}`, '', 2.1], ['QA', 'QA', 'qa', 1], ['UAT', 'UAT', 'uat', 1], ['PROD', 'PROD', 'prod', 1]];
  const pool = poolState(S);
  const shots = [['every_step', 'Every step'], ['on_failure', 'Failures'], ['off', 'Off']];
  const max = cfg.max_workers || 8;
  return html`<section class="card" style="padding: 22px">
<div style="display: flex; align-items: center; gap: 12px"><div class="step-n">3</div><h2 class="ttl">Run settings</h2><span class="chip mono" style="margin-left: auto">defaults from config.yaml</span></div>
<div style="margin-top: 22px"><div style="display: flex; align-items: baseline; margin-bottom: 9px"><span class="lbl" id="lbl-env">Environment</span><span class="flag" style="margin-left: auto">--env</span></div>
<div class="seg" role="group" aria-labelledby="lbl-env">${envDefs.map(([val, label, tone, flex]) => html`<button class="${cx(f.env === val && 'on', f.env === val && tone)}" style="flex: ${flex}" aria-pressed="${String(f.env === val)}" data-act="set" data-field="env" data-val="${val}">${label}</button>`)}</div>
${envs.length ? html`<div style="display: flex; align-items: center; gap: 10px; margin-top: 11px; font-size: 12.5px; color: var(--tx2); flex-wrap: wrap">
${envs.map((env) => { const tokenSet = cfg.tokens && cfg.tokens[env]; return html`<span class="${cx('tag', !tokenSet && 'tag-warn')}" data-key="tok-${env}">${icon('key', 11)} ${cfg.cookie_name} · ${env}: ${tokenSet ? 'set' : 'missing'}</span>`; })}<span>Read from secrets.env. The value is never typed into this page.</span></div>` : ''}
${f.books.length > 1 ? html`<div style="font-size: 12px; color: var(--tx3); margin-top: 9px">${f.env ? `All ${f.books.length} workbooks run in ${f.env}.` : 'Each workbook uses its own Global!Environment unless one is picked here.'}</div>` : ''}</div>
${browserControl(S)}
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 26px; margin-top: 24px">
<div><div style="display: flex; align-items: baseline; margin-bottom: 9px"><span class="lbl">Workers</span><span class="flag" style="margin-left: auto">--workers</span></div>
<div style="display: flex; align-items: center; gap: 14px">${stepper('workers', 'workers', f.workers)}
<div style="display: flex; gap: 4px; flex: 1" aria-hidden="true">${Array.from({ length: max }, (_, i) => html`<div style="flex: 1; height: 10px; border-radius: 3px; background: ${i < f.workers ? 'var(--acc)' : 'var(--line2)'}"></div>`)}</div></div>
<div style="font-size: 12px; color: var(--tx3); margin-top: 8px">${pool.kind === 'join' ? html`Shared with the run in progress: it keeps the workers it started with (${pool.pool.runs.length} run${pool.pool.runs.length === 1 ? '' : 's'} on them), and more are added up to this number.`
  : f.books.length > 1 ? `Each worker is an isolated browser. Max ${max}. The workers are shared by all ${f.books.length} workbooks.` : `Each worker is an isolated browser. Max ${max}.`}</div></div>
<div><div style="display: flex; align-items: baseline; margin-bottom: 9px"><span class="lbl" id="lbl-shots">Screenshots</span><span class="flag" style="margin-left: auto">--screenshots</span></div>
<div class="seg" role="group" aria-labelledby="lbl-shots">${shots.map(([val, label]) => html`<button class="${cx(f.shots === val && 'on')}" aria-pressed="${String(f.shots === val)}" data-act="set" data-field="shots" data-val="${val}">${label}</button>`)}</div>
<div style="font-size: 12px; color: var(--tx3); margin-top: 8px">JPEG after each step, about 20 ms each.</div></div></div>
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 26px; margin-top: 24px">
<div><div style="display: flex; align-items: baseline; margin-bottom: 9px"><span class="lbl">Retries</span><span class="flag" style="margin-left: auto">--retries</span></div>${stepper('retries', 'retries', f.retries)}
<div style="font-size: 12px; color: var(--tx3); margin-top: 8px">Re-run a failed test up to N times.</div></div>
<div><div style="display: flex; align-items: baseline; margin-bottom: 9px"><label class="lbl" for="seed">Seed</label><span class="flag" style="margin-left: auto">--seed</span></div>
<input id="seed" type="text" inputmode="numeric" class="fld" placeholder="random" value="${f.seed}" data-input="seed" autocomplete="off">
<div style="font-size: 12px; color: var(--tx3); margin-top: 8px">Fix RANDBETWEEN so generated data repeats.</div></div></div>
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 26px">
${toggle('pdf', 'PDF report', '--pdf', '', f.pdf)}
${toggle('harvest', 'Harvest selectors', '--harvest', '', f.harvest)}
${toggle('headed', 'Show browsers', '--headed', 'Takes focus. Debugging only.', f.headed, 'var(--warn)')}
${toggle('nice', 'Low OS priority', '', f.nice ? 'Off adds --no-nice' : 'On adds --nice', f.nice)}</div>
<details class="more" style="margin-top: 16px" ${f.showMore ? raw('open') : ''}>
<summary data-act="toggle-more">More options</summary>
<div style="margin-top: 12px">${toggle('noReport', 'Skip the HTML report', '--no-report', 'Only results.json is written.', f.noReport)}</div></details>
</section>`;
}

// ---- right column -------------------------------------------------------------------------------------------------------
function plan(S, sorted) {
  const k = Math.max(1, Math.min(S.nr.workers, sorted.length));
  const lanes = Array.from({ length: k }, (_, i) => ({ name: `W${i + 1}`, items: [], total: 0, pad: 0 }));
  const multi = S.nr.books.length > 1;
  for (const t of sorted) {
    const lane = lanes.reduce((m, x) => (x.total < m.total ? x : m), lanes[0]);
    lane.items.push({ id: multi ? `${shortName(t.wb)} · ${t.id}` : t.id, steps: t.steps });
    lane.total += t.steps;
  }
  const longest = Math.max(0, ...lanes.map((l) => l.total));
  lanes.forEach((l) => { l.pad = Math.max(0, longest - l.total) || (l.items.length ? 0 : 1); });
  return { lanes, longest, idle: S.nr.workers - k };
}

function tokenSpan(t) {
  const color = { cmd: 'var(--tx)', arg: 'var(--tx2)', flag: 'var(--acc)', value: 'var(--tx)' }[t.k] || 'var(--tx)';
  return html`<span style="color: ${color}; white-space: nowrap">${t.t}</span> `;      // a real space, so the text copies and reads as a command
}

/** The browser this run will use, in the shape the run screens use (so the chip reads the same before, during and after). */
function chosenBrowser(S) {
  const f = S.nr;
  const o = browserOption(S, f.browser);
  const bc = browserCheck(S);
  const text = bc && bc.status === 'ok' && bc.data && bc.data.text ? bc.data.text : browserLabel(f.browser);
  return { id: f.browser, text, approximate: !!(o && o.approximate) || f.browser === 'safari', what: o ? o.what : '' };
}

function launchCard(S) {
  const f = S.nr;
  const chosen = allChosen(S);
  const n = chosen.length;
  const steps = chosen.reduce((a, t) => a + t.steps, 0);
  const multi = f.books.length > 1;
  const envText = effEnv(S) || '–';
  const isProd = hasProd(S);
  const envColor = isProd ? 'var(--fail)' : envList(S).includes('QA') ? 'var(--warn)' : 'var(--acc)';
  const bc = browserCheck(S);
  const pool = poolState(S);
  const emptyBook = f.books.some((name) => f.bk[name].load === 'ok' && !chosenTests(S, name).length);
  const blocked = n === 0 || !booksReady(S) || emptyBook || runningNow(S).length > 0 || pool.kind === 'mismatch' || f.starting || (S.pre && !bc) || (bc && bc.status === 'err');       // the picked browser must have been checked, and be ready
  const label = f.starting ? 'Starting…' : !f.books.length ? 'Pick a workbook' : n === 0 || emptyBook ? 'Select tests to run' : isProd ? 'Review and run on PROD…'
    : `Run ${n} test${n === 1 ? '' : 's'}${multi ? ` in ${f.books.length} workbooks` : ''}`;
  const tone = isProd ? ['var(--fail-soft)', 'var(--fail-line)', 'var(--fail)'] : ['var(--warn-soft)', 'var(--warn-line)', 'var(--warn)'];
  return html`<section class="card" style="padding: 22px; display: flex; flex-direction: column; gap: 18px; box-shadow: var(--glow); border-color: var(--acc-line)">
<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px">
<div><div class="lbl">Tests</div><div class="disp" style="font-size: 34px; font-weight: 700; line-height: 1.15">${n}</div></div>
<div><div class="lbl">Steps</div><div class="disp" style="font-size: 34px; font-weight: 700; line-height: 1.15">${num(steps)}</div></div>
<div><div class="lbl">Environment</div><div class="disp" style="font-size: ${envText.length > 8 ? 22 : 34}px; font-weight: 700; line-height: ${envText.length > 8 ? 1.9 : 1.15}; color: ${envColor}">${envText}</div></div></div>
${multi ? html`<div id="launch-books" style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: -6px; font-size: 12.5px; color: var(--tx2)"><span class="lbl">Runs</span><b class="mono" style="color: var(--tx)">${f.books.length}</b><span>one per workbook, on ${f.workers} shared worker${f.workers === 1 ? '' : 's'}</span></div>` : ''}
${f.browser ? html`<div id="launch-browser" style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: -6px; font-size: 12.5px; color: var(--tx2)"><span class="lbl">Browser</span>${browserChip(chosenBrowser(S))}<span>${f.headed ? 'windows are shown' : 'headless'}</span></div>` : ''}
<div style="display: flex; gap: 11px; padding: 13px 14px; border-radius: 12px; background: ${tone[0]}; border: 1px solid ${tone[1]}">
<span style="color: ${tone[2]}; display: inline-flex; margin-top: 1px">${icon('warn', 18)}</span>
<div style="font-size: 12.5px; line-height: 1.5; color: var(--tx)"><b style="color: ${tone[2]}">${isProd ? 'Production.' : 'Live transaction.'}</b>
${isProd ? 'This places real orders and sends real emails. You will be asked to type PROD to confirm.' : `Every run of ${multi ? 'these workbooks' : 'this workbook'} completes real purchases and confirmation emails on ${envText === '–' ? 'the environment it targets' : envText}.`}</div></div>
<button class="btn btn-pri btn-lg ${f.starting ? 'busy' : ''}" data-act="launch" ${blocked ? raw('disabled') : ''}>${icon('play', 18)} ${label}</button>
<div><div style="display: flex; align-items: center; margin-bottom: 8px"><span class="lbl">Same run from the terminal</span>
<button class="btn btn-ghost btn-sm" style="margin-left: auto; padding: 0 8px" data-act="copy-cmd">${icon('copy', 14)} Copy</button></div>
<div class="code" aria-label="Command line for this run"><span style="color: var(--tx3)">$ </span>${f.cmd ? f.cmd.tokens.map(tokenSpan) : html`<span style="color: var(--tx3)">…</span>`}</div></div>
</section>`;
}

function planCard(S) {
  const sorted = allChosen(S).slice().sort((a, b) => b.steps - a.steps);
  const { lanes, longest, idle } = plan(S, sorted);
  return html`<section class="card" style="padding: 22px">
<div style="display: flex; align-items: center; gap: 12px"><h2 class="ttl" style="font-size: 17px">Execution plan</h2><span class="chip mono" style="margin-left: auto">longest first</span></div>
<p style="color: var(--tx2); font-size: 12.5px; margin-top: 8px">Tests run in parallel across workers, never within one test. ${S.nr.books.length > 1 ? 'The workers are shared by all the workbooks: a free worker goes to the workbook with the fewest tests going, and takes its longest waiting test.' : 'A free worker takes the longest waiting test.'}</p>
<div style="margin-top: 14px; display: flex; flex-direction: column; gap: 8px">
${lanes.map((lane) => html`<div style="display: flex; align-items: center; gap: 10px" data-key="${lane.name}"><div class="mono" style="width: 26px; font-size: 11.5px; color: var(--tx3)">${lane.name}</div>
<div style="flex: 1; display: flex; gap: 4px; height: 36px; min-width: 0">
${lane.items.map((it) => html`<div style="flex: ${it.steps} 1 0; min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 0 9px; border-radius: 8px; background: var(--acc-soft); border: 1px solid var(--acc-line); font: 500 11px var(--f-mono); overflow: hidden; white-space: nowrap"><span style="overflow: hidden; text-overflow: ellipsis">${it.id}</span><span style="color: var(--tx3)">${it.steps}</span></div>`)}
<div style="flex: ${lane.pad} 1 0"></div></div></div>`)}</div>
<div style="display: flex; gap: 8px; margin-top: 14px; font-size: 12px; color: var(--tx2); flex-wrap: wrap">
<span class="tag">${idle > 0 ? `${idle} idle worker${idle === 1 ? '' : 's'}` : `all ${S.nr.workers} workers busy`}</span><span class="tag">longest lane ${num(longest)} steps</span></div></section>`;
}

function checkCard(S) {
  const f = S.nr;
  const name = checkName(S);
  const book = name ? f.bk[name] : null;
  const a = book ? book.audit : null;
  const ready = !!book && book.load === 'ok';
  const row = (iconName, title, text, button, act, extra, last) => html`<div style="display: flex; gap: 12px; padding: ${last ? '14px 0 0' : '14px 0'}; border-top: 1px solid var(--line)">
<span style="color: var(--acc); margin-top: 2px">${icon(iconName, 18)}</span>
<div style="flex: 1; min-width: 0"><div style="font-weight: 600; font-size: 13px">${title}</div><div style="color: var(--tx2); font-size: 12.5px">${text}</div>${extra || ''}</div>
<button class="btn btn-sm" data-act="${act}" ${ready ? '' : raw('disabled')}>${button}</button></div>`;
  return html`<section class="card" style="padding: 22px">
<div style="display: flex; align-items: center; gap: 12px"><h2 class="ttl" style="font-size: 17px">Check the workbook first</h2><span class="chip" style="margin-left: auto">optional</span></div>
<p style="color: var(--tx2); font-size: 12.5px; margin-top: 8px">None of these open a browser or place a transaction.</p>
${f.books.length > 1 ? html`<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px"><span class="lbl">Workbook</span>
${f.books.map((n) => html`<button class="${cx('chip', n === name && 'chip-acc')}" data-key="chk-${n}" data-act="check-wb" data-wb="${n}" aria-pressed="${String(n === name)}" title="${n}" style="max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">${shortName(n)}</button>`)}</div>` : ''}
<div style="display: flex; flex-direction: column; margin-top: 8px">
${row('list', 'Lint', 'Flags steps that will not behave as authored, such as Output with no comparison or getAttribute("value") checks.', 'Run lint', 'lint')}
${row('term', 'Dry-run plan', 'Every step that would run, after token substitution and gating.', 'Preview', 'plan')}
${row('target', 'Locator health', a && a !== 'loading'
      ? `${num(a.map_entries)} generic locators in selectors.yaml cover ${a.covered_pct}% of locator uses; ${a.convertible_pct}% could be converted.`
      : a === 'loading' ? 'Checking locators…' : 'How many locators are resilient generic ones rather than XPaths.', 'Audit', 'audit',
      a && a !== 'loading' ? html`<div class="bar" style="margin-top: 9px"><div style="width: ${a.covered_pct}%; background: var(--pass)"></div></div>` : '', true)}
</div></section>`;
}

function preflightCard(S) {
  const items = preflightItems(S);
  const nErr = items.filter((i) => i.kind === 'err').length;
  const nWarn = items.filter((i) => i.kind === 'warn').length;
  const cls = nErr ? 'p-fail' : nWarn ? 'p-warn' : 'p-pass';
  const text = nErr ? `${nErr} blocking` : nWarn ? `${nWarn} warning${nWarn === 1 ? '' : 's'}` : 'Ready';
  const glyph = { ok: ['passc', 'var(--pass)'], warn: ['warn', 'var(--warn)'], err: ['failc', 'var(--fail)'], pend: ['dashed', 'var(--tx3)'] };
  return html`<section class="card" id="preflight" style="padding: 20px 22px 8px">
<div style="display: flex; align-items: center; gap: 12px; padding-bottom: 8px"><h2 class="ttl" style="font-size: 17px">Preflight</h2>
<button class="btn btn-ghost btn-sm" style="padding: 0 8px" data-act="doctor" aria-label="Re-check everything">${icon('refresh', 14)}</button>
<span class="pill ${cls}" style="margin-left: auto">${text}</span></div>
${items.map((p) => html`<div style="display: flex; gap: 12px; padding: 13px 0; border-top: 1px solid var(--line)" data-key="${p.label}">
<span style="color: ${glyph[p.kind][1]}; margin-top: 1px">${icon(glyph[p.kind][0], 18)}</span>
<div style="flex: 1; min-width: 0"><div style="font-weight: 600; font-size: 13px">${p.label}</div><div style="color: var(--tx2); font-size: 12.5px; overflow-wrap: anywhere">${p.detail}</div></div>
${p.action ? html`<button class="btn btn-sm" data-act="signin">${p.action}</button>` : ''}</div>`)}</section>`;
}

// ---- banners above the form ------------------------------------------------------------------------------------------------
function formBanner(S) {
  const b = S.nr.banner;
  const pool = poolState(S);
  const n = pool.active.length;
  if (b && b.kind === 'busy') {                                   // the server said no: something is already going
    return banner('warn', 'warn', html`<b>${b.message}</b>`, b.run_id ? html`${btn('Open run', 'open-run', { id: b.run_id })}${btn('Cancel it', 'cancel-run', { id: b.run_id, cls: 'btn-dng' })}` : '');
  }
  if (pool.kind === 'mismatch') {
    const p = pool.pool;
    const first = pool.active.find((r) => r.pool && r.pool.id === p.id) || pool.active[0];
    const label = ((S.cfg && S.cfg.browsers) || []).find((k) => k.id === p.browser);
    return banner('warn', 'warn', html`<b>${plural(n, 'run')} in progress</b> with ${label ? label.label : p.browser}, ${p.headed ? 'windows shown' : 'headless'}. Runs share one set of workers, so a run started now must use the same browser and window mode.`,
      html`${btn('Use their settings', 'match-pool')}${btn('Open run', 'open-run', { id: first.run_id })}${btn('Cancel it', 'cancel-run', { id: first.run_id, cls: 'btn-dng' })}`);
  }
  if (pool.kind === 'join') {
    const first = pool.active.find((r) => r.pool && r.pool.id === pool.pool.id) || pool.active[0];
    return banner('acc', 'info', html`<b>${plural(n, 'run')} in progress.</b> A run started now joins ${n === 1 ? 'it' : 'them'} and shares the workers: they split between the runs, and the total stays what was asked for.`,
      html`${btn('Open run', 'open-run', { id: first.run_id })}`);
  }
  if (!b) return '';
  if (b.kind === 'selection') return banner('fail', 'failc', html`<b>${b.message}</b>`);
  return banner('fail', 'failc', b.message);
}

export function newRunView(S) {
  const f = S.nr;
  return html`<div class="page">
<div style="display: flex; flex-direction: column; gap: 12px; max-width: 720px"><div class="eyebrow">New run</div>
<h1 class="disp" style="font-size: 44px; line-height: 1.04; font-weight: 700; margin: 0">Set up a regression run</h1>
<p style="color: var(--tx2); font-size: 15.5px; max-width: 640px; margin: 0">Pick one or more workbooks, choose the tests, launch. Each workbook is a run of its own, and they share the workers. Everything runs headless in the background at lowered priority, so your keyboard, mouse and focus stay yours.</p></div>
${formBanner(S)}
<div class="split">
<div class="col">${workbookCard(S)}${f.books.map((name, i) => html`${testsCard(S, name, i)}${orderCard(S, name, i)}`)}${settingsCard(S)}</div>
<div class="col">${launchCard(S)}${planCard(S)}${checkCard(S)}${preflightCard(S)}</div></div></div>`;
}
