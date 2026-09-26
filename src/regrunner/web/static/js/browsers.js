// Which browser a run used and how a person reads it.  The runner records it (name, engine, version, headless) in run_started,
// run.json and results.json; a run from before that was recorded is worked out from its saved settings and says so.
import { html } from './util.js';
import { icon } from './icons.js';

const NAMES = { chrome: 'Google Chrome', msedge: 'Microsoft Edge', safari: 'Safari (WebKit)', chromium: 'Chromium' };
const SHORT = { chrome: 'Chrome', msedge: 'Edge', safari: 'Safari', chromium: 'Chromium' };
const SAFARI_NOTE = "WebKit, the engine Safari is built on, run through Playwright. Playwright cannot drive the Safari application itself, so this is not Safari.app.";

export const browserLabel = (id) => NAMES[id] || id || '';
export const browserShort = (id) => SHORT[id] || id || '';

/** The record of the browser a run used, from the first source that has it (the live run, run.json, results.json); older runs fall back to their saved config. */
export function browserOf(...sources) {
  for (const s of sources) if (s && s.browser && s.browser.id) return s.browser;
  const cfg = sources.map((s) => s && s.config && s.config.browser).find(Boolean);
  if (!cfg) return { id: 'unknown', label: 'Browser not recorded', short: '', text: 'Not recorded', version: '', recorded: false, approximate: false, what: 'This run did not record which browser it used.', headless: true };   // never guess
  const id = NAMES[cfg.name] ? cfg.name : NAMES[cfg.channel] ? cfg.channel : 'chromium';
  const meta = sources.find((s) => s && s.params && s.params.headless !== undefined);
  return { id, label: NAMES[id], short: SHORT[id], text: NAMES[id], version: '', recorded: false, approximate: id === 'safari', what: id === 'safari' ? SAFARI_NOTE : '',
           headless: meta ? meta.params.headless !== false : true };
}

/** A chip: "Google Chrome 141.0.7390.55", "Safari (WebKit 26.6)", "No browser (API tests only)". */
export function browserChip(b) {
  if (!b) return '';
  const why = b.id === 'none' ? b.what : b.approximate ? b.what || SAFARI_NOTE : b.recorded === false && b.id !== 'unknown' ? 'This run did not record its browser: this is what its saved settings select. The exact version is unknown.' : b.what || '';
  return html`<span class="chip" data-browser="${b.id}" title="${why}">${icon('globe', 14)} ${b.text}${b.recorded === false && b.id !== 'unknown' ? html` <span style="color: var(--tx3)">(version not recorded)</span>` : ''}</span>`;
}
