// The Build window's overlay (P08; Q50): injected by Playwright (context.add_init_script) into every document of the build browser - every
// page, frame and new window, again after every navigation - and never with a <script src> (the site's CSP does not apply to it).
//
// * The top window shows a small draggable pill: Pick · what it is doing · Done.
// * In Pick mode, hovering outlines an element with its plain-words name; a click picks it (the site never sees that click) and tells the
//   builder, which works out the locator on the live page and sends back a card to show beside the element.
// * "Which one?": the builder asks every document for the elements that match a text; they get numbered outlines and one is chosen here
//   (a click) or in the Build tab.
//
// It talks to the builder through one binding, window.__rrBuildCall({kind, ...}) (context.expose_binding), and the builder talks to it with
// window.__rrBuild.apply(state).  Everything it draws lives in a closed shadow root on an element of its own; events on it are stopped in the
// capture phase on window before any listener of the site runs (this script runs before the site's scripts, so its listeners come first).
(() => {
  'use strict';
  if (window.__rrBuild) return;
  const CALL = '__rrBuildCall';
  const TOP = window.top === window;
  const PRESS = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick', 'auxclick', 'contextmenu', 'touchstart', 'touchend'];
  const INTERACTIVE = 'button, a[href], input, select, textarea, summary, label, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=checkbox], [role=radio], [role=switch]';
  const HEADINGS = 'h1, h2, h3, h4, h5, h6, [role=heading], legend, caption, [class*="title" i], [class*="heading" i], [class*="name" i]';
  const TEST_IDS = ['data-testid', 'data-test-id', 'data-test', 'data-qa', 'data-cy', 'data-automation-id', 'data-automation'];
  const KIND_WORDS = { button: 'button', link: 'link', field: 'text field', textbox: 'text box', dropdown: 'dropdown', checkbox: 'checkbox', radio: 'option',
    image: 'image', heading: 'heading', label: 'label', item: 'list item', cell: 'cell', text: 'text', element: 'element' };

  const st = { mode: 'browse', label: '', card: null, which: null, drag: null, pos: null };
  let host = null, root = null, picked = null, hoverEl = null, whichEls = [];

  // ---- reading an element --------------------------------------------------------------------------------------------------------------
  const clean = (t) => String(t == null ? '' : t).replace(/\s+/g, ' ').trim();
  const short = (t) => { const c = clean(t); return c.length && c.length <= 80 ? c : ''; };

  function kindOf(el) {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (role === 'button' || tag === 'button' || (tag === 'input' && ['submit', 'button', 'reset', 'image'].includes(type))) return 'button';
    if (role === 'link' || (tag === 'a' && el.hasAttribute('href'))) return 'link';
    if ((tag === 'input' && type === 'checkbox') || role === 'checkbox' || role === 'switch') return 'checkbox';
    if ((tag === 'input' && type === 'radio') || role === 'radio') return 'radio';
    if (tag === 'select' || role === 'combobox' || role === 'listbox') return 'dropdown';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') return 'field';
    if (tag === 'img' || role === 'img') return 'image';
    if (/^h[1-6]$/.test(tag) || role === 'heading') return 'heading';
    if (tag === 'label') return 'label';
    if (tag === 'li' || role === 'listitem' || role === 'option' || role === 'menuitem' || role === 'tab') return 'item';
    if (tag === 'td' || tag === 'th' || role === 'cell' || role === 'gridcell') return 'cell';
    if (clean(el.innerText)) return 'text';
    return 'element';
  }

  function labelOf(el) {
    try {
      if (el.labels && el.labels.length) return short(el.labels[0].innerText);
      const by = el.getAttribute('aria-labelledby');
      if (by) { const l = document.getElementById(by.split(/\s+/)[0]); if (l) return short(l.innerText); }
      const wrap = el.closest('label');
      if (wrap) return short(wrap.innerText);
    } catch (e) { /* not a labelable element */ }
    return '';
  }

  function nameOf(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    return short(el.getAttribute('aria-label')) || (['input', 'select', 'textarea'].includes(tag) ? labelOf(el) : '')
      || (tag === 'input' && ['submit', 'button', 'reset'].includes(type) ? short(el.value) : '') || short(el.innerText)
      || short(el.getAttribute('placeholder')) || short(el.getAttribute('title')) || short(el.getAttribute('alt'));
  }

  function sameNameCount(el, name) {
    if (!name) return 0;
    let n = 0;
    for (const other of document.getElementsByTagName(el.tagName)) { if (nameOf(other) === name) n += 1; if (n > 1) break; }
    return n;
  }

  function containerKind(c) {
    const cls = (typeof c.className === 'string' ? c.className : '').toLowerCase();
    const tag = c.tagName.toLowerCase();
    const role = (c.getAttribute('role') || '').toLowerCase();
    if (/card|tile|plan|product/.test(cls) || tag === 'article') return 'card';
    if (tag === 'tr' || role === 'row') return 'row';
    if (tag === 'li' || role === 'listitem') return 'item';
    if (tag === 'form') return 'form';
    if (tag === 'dialog' || role === 'dialog') return 'dialog';
    if (/panel/.test(cls)) return 'panel';
    return 'section';
  }

  function contextOf(el, name) {
    let c = el.parentElement;
    for (let depth = 0; c && depth < 8 && c !== document.body && c !== document.documentElement; depth += 1, c = c.parentElement) {
      for (const h of c.querySelectorAll(HEADINGS)) {
        if (h === el || h.contains(el) || el.contains(h)) continue;
        const heading = short(h.innerText);
        if (!heading || heading === name) continue;
        return { kind: containerKind(c), tag: c.tagName.toLowerCase(), heading, headingTag: h.tagName.toLowerCase(), id: c.id || '',
          classes: Array.from(c.classList || []) };
      }
    }
    return null;
  }

  function cssPath(el) {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && e !== document.documentElement; e = e.parentElement) {
      const tag = e.tagName.toLowerCase();
      if (e.id && /^[A-Za-z][\w-]*$/.test(e.id) && !/\d{3,}/.test(e.id)) { parts.unshift('#' + e.id); return parts.join(' > '); }
      const parent = e.parentElement;
      const same = parent ? Array.from(parent.children).filter((x) => x.tagName === e.tagName) : [e];
      parts.unshift(same.length > 1 ? `${tag}:nth-of-type(${same.indexOf(e) + 1})` : tag);
    }
    return parts.join(' > ');
  }

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    const name = nameOf(el);
    const tid = TEST_IDS.find((a) => el.hasAttribute(a));
    let visible = true;
    try { visible = typeof el.checkVisibility === 'function' ? el.checkVisibility() : true; } catch (e) { /* old browser */ }
    return {
      tag, kind: kindOf(el), id: el.id || '', name: el.getAttribute('name') || '', type: el.getAttribute('type') || '',
      testid: tid ? { attr: tid, value: el.getAttribute(tid) } : null,
      ariaLabel: el.getAttribute('aria-label') || '', placeholder: el.getAttribute('placeholder') || '', title: el.getAttribute('title') || '',
      alt: el.getAttribute('alt') || '', href: tag === 'a' ? (el.getAttribute('href') || '') : '', value: el.getAttribute('value') || '',
      classes: Array.from(el.classList || []), text: short(el.innerText), label: labelOf(el),
      context: sameNameCount(el, name) > 1 || !name ? contextOf(el, name) : null,
      cssPath: cssPath(el), frame: TOP ? '' : (window.name || location.href),
      current: { value: 'value' in el && typeof el.value === 'string' ? el.value.slice(0, 200) : '', checked: !!el.checked,
        enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true', visible },
    };
  }

  function friendly(d) {
    const name = short(d.ariaLabel) || d.label || d.text || short(d.value) || short(d.placeholder) || short(d.title) || short(d.alt);
    let out = KIND_WORDS[d.kind] || 'element';
    if (name) out += ` “${name}”`;
    if (d.context && d.context.heading && d.context.heading !== name) out += ` · ${d.context.kind} “${d.context.heading}”`;
    return out;
  }

  const target = (el) => {
    if (!(el instanceof Element)) return null;
    const hit = el.closest(INTERACTIVE);
    return hit && (hit === el || hit.contains(el)) ? hit : el;
  };

  // ---- drawing -----------------------------------------------------------------------------------------------------------------------
  const CSS = `
:host { all: initial; }
* { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.pill { position: fixed; z-index: 2147483647; top: 14px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 4px;
  padding: 5px 6px 5px 8px; border-radius: 14px; background: #1f2630; color: #e8edf3; border: 1px solid #3a4452; box-shadow: 0 14px 40px rgba(0,0,0,.35);
  font-size: 12.5px; user-select: none; }
.pill.moved { transform: none; }
.grip { cursor: grab; color: #8a96a6; padding: 0 3px; font-size: 14px; line-height: 1; }
button { all: unset; height: 28px; padding: 0 11px; border-radius: 8px; font-size: 12.5px; font-weight: 600; cursor: pointer; display: inline-flex;
  align-items: center; gap: 6px; color: #e8edf3; }
button:hover { background: #2c3541; }
button.on { background: #5cc8ff; color: #06121c; }
button.pri { background: #5cc8ff; color: #06121c; }
.sep { width: 1px; height: 20px; background: #3a4452; margin: 0 2px; }
.what { font: 11.5px ui-monospace, SFMono-Regular, Menlo, monospace; color: #b8c2cf; padding: 0 8px; white-space: nowrap; }
.box { position: fixed; z-index: 2147483646; pointer-events: none; border: 2px solid #5cc8ff; border-radius: 6px; box-shadow: 0 0 0 4px rgba(92,200,255,.22); }
.box.picked { border-color: #7ee2a8; box-shadow: 0 0 0 4px rgba(126,226,168,.25); }
.box.which { border-color: #f2c14e; box-shadow: 0 0 0 4px rgba(242,193,78,.25); }
.tag { position: absolute; left: -2px; top: -24px; height: 20px; padding: 0 7px; border-radius: 5px; background: #5cc8ff; color: #06121c;
  font: 600 11px ui-monospace, SFMono-Regular, Menlo, monospace; display: flex; align-items: center; white-space: nowrap; }
.num { position: absolute; right: -11px; top: -11px; width: 22px; height: 22px; border-radius: 50%; background: #f2c14e; color: #06121c;
  font: 700 12px ui-monospace, monospace; display: grid; place-items: center; }
.card { position: fixed; z-index: 2147483647; width: 320px; border-radius: 14px; background: #1f2630; color: #e8edf3; border: 1px solid #3a4452;
  box-shadow: 0 24px 60px rgba(0,0,0,.45); display: flex; flex-direction: column; }
.card .hd { padding: 12px 14px 10px; border-bottom: 1px solid #333d4a; display: flex; flex-direction: column; gap: 3px; }
.card .t { font-size: 13px; font-weight: 700; }
.card .m { font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; color: #9aa6b5; word-break: break-all; }
.card .bad { color: #ff8a80; }
.card .ft { padding: 8px 10px 10px; display: flex; gap: 6px; flex-wrap: wrap; }
`;

  function ensureHost() {
    if (host && host.isConnected) return true;
    const parent = document.documentElement;
    if (!parent) return false;
    host = document.createElement('rr-build-overlay');
    host.setAttribute('aria-hidden', 'true');
    root = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = CSS;
    root.appendChild(style);
    parent.appendChild(host);
    return true;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function clear(selector) { if (root) root.querySelectorAll(selector).forEach((n) => n.remove()); }

  function outline(elm, cls, label, num) {
    const r = elm.getBoundingClientRect();
    if (!r.width && !r.height) return;
    const box = el('div', `box ${cls || ''}`);
    Object.assign(box.style, { left: `${r.left - 3}px`, top: `${r.top - 3}px`, width: `${r.width + 6}px`, height: `${r.height + 6}px` });
    if (label) box.appendChild(el('span', 'tag', label));
    if (num != null) box.appendChild(el('span', 'num', String(num)));
    root.appendChild(box);
  }

  function drawPill() {
    clear('.pill');
    if (!TOP || !ensureHost()) return;
    const pill = el('div', 'pill');
    pill.setAttribute('data-rr', 'pill');
    if (st.pos) { pill.classList.add('moved'); pill.style.left = `${st.pos.x}px`; pill.style.top = `${st.pos.y}px`; }
    const grip = el('span', 'grip', '⠇');
    grip.setAttribute('data-rr-drag', '1');
    grip.title = 'Drag the pill';
    pill.appendChild(grip);
    const pick = el('button', st.mode === 'pick' ? 'on' : '', 'Pick');
    pick.setAttribute('data-rr-act', 'pick');
    pill.appendChild(pick);
    pill.appendChild(el('span', 'sep'));
    pill.appendChild(el('span', 'what', st.label || 'Build window'));
    const done = el('button', 'pri', 'Done');
    done.setAttribute('data-rr-act', 'done');
    pill.appendChild(done);
    root.appendChild(pill);
  }

  function drawMarks() {
    if (!ensureHost()) return;
    clear('.box');
    if (picked && picked.isConnected && (st.card || st.mode === 'pick')) outline(picked, 'picked', '');
    if (st.mode === 'which') whichEls.forEach((w, i) => { if (w.isConnected) outline(w, 'which', '', i + 1); });
    if (hoverEl && hoverEl.isConnected && (st.mode === 'pick' || st.mode === 'which')) outline(hoverEl, '', friendly(describe(hoverEl)));
  }

  function drawCard() {
    clear('.card');
    const c = st.card;
    if (!c || !picked || !picked.isConnected || !ensureHost()) return;
    const r = picked.getBoundingClientRect();
    const card = el('div', 'card');
    const hd = el('div', 'hd');
    hd.appendChild(el('span', 't', c.title || 'Picked'));
    for (const line of c.lines || []) hd.appendChild(el('span', `m${c.ok === false ? ' bad' : ''}`, line));
    card.appendChild(hd);
    const ft = el('div', 'ft');
    if (c.use) { const b = el('button', 'pri', c.use); b.setAttribute('data-rr-act', 'use'); ft.appendChild(b); }
    const again = el('button', '', 'Pick again');
    again.setAttribute('data-rr-act', 'pick');
    ft.appendChild(again);
    const close = el('button', '', 'Close');
    close.setAttribute('data-rr-act', 'close-card');
    ft.appendChild(close);
    card.appendChild(ft);
    const vw = window.innerWidth, vh = window.innerHeight;
    const left = r.right + 12 + 320 < vw ? r.right + 12 : Math.max(8, r.left - 332);
    const top = Math.min(Math.max(8, r.top), Math.max(8, vh - 200));
    Object.assign(card.style, { left: `${left}px`, top: `${top}px` });
    root.appendChild(card);
  }

  function redraw() {
    try { drawPill(); drawMarks(); drawCard(); } catch (e) { /* never break the page */ }
  }

  // ---- talking to the builder ---------------------------------------------------------------------------------------------------------
  function call(payload) {
    try {
      const fn = window[CALL];
      return typeof fn === 'function' ? Promise.resolve(fn(payload)).catch(() => null) : Promise.resolve(null);
    } catch (e) { return Promise.resolve(null); }
  }

  function apply(state) {
    if (!state || typeof state !== 'object') return;
    if ('mode' in state) st.mode = state.mode || 'browse';
    if ('label' in state) st.label = state.label || '';
    if ('card' in state) st.card = state.card || null;
    if (st.mode !== 'which') whichEls = [];
    if (st.mode === 'browse' && !st.card) hoverEl = null;
    redraw();
  }

  function pickNow(elm) {
    picked = elm;
    hoverEl = null;
    st.card = { title: friendly(describe(elm)), lines: ['checking the locator on this page…'] };
    redraw();
    call({ kind: 'pick', element: describe(elm) });
  }

  // Elements that match a text (and a kind), for "which one?": visible ones only, in document order.
  function findAll(query) {
    const want = clean(query && query.text).toLowerCase();
    const kind = (query && query.kind) || '';
    whichEls = [];
    if (!want) { redraw(); return []; }
    const all = document.querySelectorAll(kind === 'button' ? 'button, input[type=submit], input[type=button], [role=button]'
      : kind === 'link' ? 'a[href], [role=link]' : kind === 'field' ? 'input, textarea, select' : '*');
    for (const e of all) {
      if (host && (e === host)) continue;
      if (kind === '' && e.children.length && Array.from(e.children).some((ch) => clean(ch.innerText).toLowerCase() === want)) continue;   // the innermost only
      const name = nameOf(e).toLowerCase();
      if (name !== want) continue;
      let vis = true;
      try { vis = typeof e.checkVisibility === 'function' ? e.checkVisibility() : true; } catch (err) { /* old browser */ }
      if (vis) whichEls.push(e);
      if (whichEls.length >= 20) break;
    }
    st.mode = 'which';
    redraw();
    return whichEls.map((e) => describe(e));
  }

  function choose(i) {
    const e = whichEls[i];
    if (!e) return null;
    picked = e;
    st.mode = 'browse';
    whichEls = [];
    redraw();
    return describe(e);
  }

  // ---- events (capture phase on window: before any listener of the site) ----------------------------------------------------------------
  function inOverlay(ev) { return !!host && typeof ev.composedPath === 'function' && ev.composedPath().includes(host); }

  function overlayAction(ev) {
    const path = ev.composedPath();
    const btn = path.find((n) => n instanceof Element && n.hasAttribute('data-rr-act'));
    if (!btn) return;
    const act = btn.getAttribute('data-rr-act');
    if (act === 'pick') { st.mode = st.mode === 'pick' ? 'browse' : 'pick'; st.card = null; redraw(); call({ kind: 'mode', mode: st.mode }); }
    else if (act === 'done') { st.mode = 'browse'; st.card = null; hoverEl = null; redraw(); call({ kind: 'mode', mode: 'browse' }); }
    else if (act === 'close-card') { st.card = null; redraw(); }
    else if (act === 'use') { call({ kind: 'use' }); }
  }

  function onPress(ev) {
    if (inOverlay(ev)) {
      ev.stopImmediatePropagation();
      if (ev.type === 'pointerdown' && TOP) {
        const grip = ev.composedPath().find((n) => n instanceof Element && n.hasAttribute('data-rr-drag'));
        const pill = root && root.querySelector('.pill');
        if (grip && pill) { const r = pill.getBoundingClientRect(); st.drag = { dx: ev.clientX - r.left, dy: ev.clientY - r.top }; ev.preventDefault(); }
      }
      if (ev.type === 'pointerup') st.drag = null;
      if (ev.type === 'click') { ev.preventDefault(); overlayAction(ev); }
      return;
    }
    if (st.mode !== 'pick' && st.mode !== 'which') return;
    ev.stopImmediatePropagation();                                 // picking: the site never sees the press (no navigation, no toggle, no focus)
    ev.preventDefault();
    if (ev.type === 'click') pickNow(target(ev.target));
  }

  function onMove(ev) {
    if (st.drag) {
      ev.stopImmediatePropagation();
      st.pos = { x: Math.max(0, ev.clientX - st.drag.dx), y: Math.max(0, ev.clientY - st.drag.dy) };
      const pill = root && root.querySelector('.pill');
      if (pill) { pill.classList.add('moved'); pill.style.left = `${st.pos.x}px`; pill.style.top = `${st.pos.y}px`; }
      return;
    }
    if (inOverlay(ev)) { ev.stopImmediatePropagation(); return; }
    if (st.mode !== 'pick' && st.mode !== 'which') return;
    const t = target(ev.target);
    if (t && t !== hoverEl) { hoverEl = t; drawMarks(); }
  }

  function onKey(ev) {
    if (inOverlay(ev)) { ev.stopImmediatePropagation(); return; }
    if ((st.mode === 'pick' || st.mode === 'which') && ev.key === 'Escape') {
      ev.stopImmediatePropagation();
      ev.preventDefault();
      st.mode = 'browse';
      hoverEl = null;
      redraw();
      call({ kind: 'mode', mode: 'browse' });
    }
  }

  for (const type of PRESS) window.addEventListener(type, onPress, { capture: true });
  for (const type of ['pointermove', 'mousemove', 'mouseover', 'mouseout']) window.addEventListener(type, onMove, { capture: true, passive: true });
  window.addEventListener('pointerup', () => { st.drag = null; }, { capture: true });
  window.addEventListener('keydown', onKey, { capture: true });
  window.addEventListener('scroll', () => { if (st.mode !== 'browse' || st.card) { drawMarks(); drawCard(); } }, { capture: true, passive: true });
  window.addEventListener('resize', redraw, { passive: true });

  Object.defineProperty(window, '__rrBuild', {
    value: Object.freeze({ apply, findAll, choose, picked: () => picked, describe: () => (picked ? describe(picked) : null) }),
    enumerable: false, configurable: false, writable: false,
  });

  const hello = () => call({ kind: 'hello', top: TOP, url: location.href }).then((state) => { if (state) apply(state); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { redraw(); hello(); }, { once: true });
  else { redraw(); hello(); }
})();
