// The single state object every view renders from, plus a coalescing re-render trigger.
export const S = {
  cfg: null,                 // GET /api/config
  pre: null,                 // GET /api/preflight
  runs: [],                  // GET /api/runs
  workbooks: [],             // GET /api/workbooks
  route: { name: 'new', id: null },
  now: Date.now(),
  online: true,
  nr: freshForm(),           // the New run form
  view: null,                // the run being viewed (see actions.openRun)
  modal: null,               // { kind, ... }
  build: freshBuild(),       // the Workbook Builder (views/build/*)
};

/** The Build tab's state: which workbook and screen, the model from the server, and the test editor's own UI state. */
export function freshBuild() {
  return {
    name: null, model: null, loading: false, error: null,
    screen: 'map',            // 'map' | 'variables' | 'test'
    testId: null,
    keywords: null,            // GET /api/build/keywords, loaded once and kept across workbooks
    selVariable: null,
    env: '',                  // '' = the workbook's own default (Global!Environment)
    pendingSel: null,         // a step row to select once its test finishes loading (variable map "jump to step")
    busy: false,              // an edit/undo/redo/save round-trip is in flight
    ed: freshEditor(),
  };
}

/** Per-test editor UI: which block and step are shown, selection, view mode, and the drawer/menu/problems panels. */
export function freshEditor() {
  return {
    block: 0, sel: null, multi: [],
    mode: 'cards',            // 'cards' | 'grid'
    grid: null,               // the raw sheet, loaded lazily for the grid view
    drawer: false, drawerGrid: undefined, drawerSheetName: null,
    buildingWith: null,       // which data row the inspector previews with (client-side only; no build session yet)
    problems: false, menu: false, menuQuery: '',
  };
}

/** What the form knows about one chosen workbook: what was read from it, which of its tests are ticked, and its own run order. */
export function freshBook() {
  return {
    load: 'idle', info: null, err: null, sel: {}, audit: null,
    chains: [], chainsSource: 'none', chainsDirty: false, order: null, orderKey: '', orderAsked: '', orderError: '',      // tests that run one after another; what the server says will wait for what
  };
}

/** Form state for a new run. Run settings always start from config.yaml so a run is never launched with stale choices.
 *  Several workbooks can be chosen (`books`, each with its own state in `bk`): they become one run each, on one set of workers, and share every setting below. */
export function freshForm(cfg) {
  return {
    books: [], bk: {}, checkWb: null,
    env: '', browser: cfg ? cfg.browser : '', workers: cfg ? cfg.workers : 3, shots: cfg ? cfg.screenshots : 'every_step', retries: cfg ? cfg.retries : 0,
    seed: '', pdf: cfg ? cfg.pdf : false, harvest: cfg ? cfg.harvest : false, headed: false, nice: cfg ? cfg.nice : true,
    noReport: false, upload: null, uploadErr: null, drag: false, cmd: null, cmdKey: '', banner: null, starting: false,
    showMore: false, wbq: '', wbSort: 'new', wbLimit: 6,
  };
}

let renderer = () => {};
let queued = false;
export function setRenderer(fn) { renderer = fn; }
export function rerender() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; renderer(); });
}
