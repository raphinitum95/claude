// The Build window's overlay (P08, P09; Q6-Q9, Q34, Q41, Q50-Q53): injected by Playwright (context.add_init_script) into every document of the
// build browser - every page, frame and new window, again after every navigation - and never with a <script src> (the site's CSP does not apply).
//
// * The top window shows a small draggable pill: ● Rec · Pick · Check · Save · Wait until · what it is doing · Done.
// * Pick / Check / Save / Wait until: hovering outlines an element with its plain-words name; a click picks it (the site never sees that click)
//   and tells the builder, which works out the locator on the live page and sends back a card to show beside the element (for Check / Save /
//   Wait until: every kind of check, prefilled from the page, and "Add").
// * Recording (● Rec): the person's own clicks, typing, choices, ticks, Enter and the browser's Back button are sent to the builder, which
//   writes them as steps. Only events the browser marks isTrusted count (a site's script cannot fake one), and the page keeps them: recording
//   never stops or changes what the site sees. The locator of a clicked element is counted here, as the click happens, because the click may
//   take the page away before the builder could look (the builder recounts anything missing and makes the choice itself: locators.py).
// * "Which one?": the builder asks every document for the elements that match a text; they get numbered outlines and one is chosen here.
// * Prompts (typed text -> variable, a password -> secret, widget steps, a new page's fingerprint) show beside the field or at the bottom left.
//
// It talks to the builder through one binding, window.__rrBuildCall({kind, ...}) (context.expose_binding), and the builder talks to it with
// window.__rrBuild.apply(state). The site's own scripts can reach the binding too: without the session's key (KEY, only in this closure) a call
// can only say hello, switch a mode and report a pick, none of which changes the workbook. The binding is taken when this script starts, before
// any script of the site runs, so a site cannot wrap it to read the key. Everything drawn lives in a closed shadow root on an element of its
// own; presses on it are stopped in the capture phase on window before any listener of the site runs.
(() => {
  'use strict';
  if (window.__rrBuild) return;
  const CALL = '__rrBuildCall';
  const KEY = '__RR_KEY__';
  const BIND = typeof window[CALL] === 'function' ? window[CALL] : null;
  const TOP = window.top === window;
  const PRESS = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick', 'auxclick', 'contextmenu', 'touchstart', 'touchend'];
  const PICKING = ['pick', 'check', 'save', 'wait', 'which'];
  const INTERACTIVE = 'button, a[href], input, select, textarea, summary, label, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=checkbox], [role=radio], [role=switch]';
  const HEADINGS = 'h1, h2, h3, h4, h5, h6, [role=heading], legend, caption, [class*="title" i], [class*="heading" i], [class*="name" i]';
  const TEST_IDS = ['data-testid', 'data-test-id', 'data-test', 'data-qa', 'data-cy', 'data-automation-id', 'data-automation'];
  const OPTIONS = '[role=option], [role=listbox] li, .ui-menu-item, li[class*="suggestion" i], [class*="suggestion" i] li, [class*="autocomplete" i] li, [class*="typeahead" i] li';
  const NOT_TEXT = ['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'hidden', 'range', 'color'];
  const DATE_TYPES = ['date', 'datetime-local', 'month'];
  const KIND_WORDS = { button: 'button', link: 'link', field: 'text field', textbox: 'text box', dropdown: 'dropdown', checkbox: 'checkbox', radio: 'option',
    image: 'image', heading: 'heading', label: 'label', item: 'list item', cell: 'cell', text: 'text', element: 'element' };
  const NEEDS_EXPECTED = new Set(['text_is', 'text_contains', 'value', 'ticked', 'selected', 'enabled', 'gt', 'lt', 'between', 'regex', 'date_format', 'count', 'wait_text']);
  const CHOICE_WORDS = { keep: 'Keep as variable', fixed: 'Use fixed text', rename: 'Rename', raw: 'Keep raw clicks', unflag: 'Not a side effect', dismiss: 'OK',
    ungate: 'Remove the check' };

  const st = { mode: 'browse', label: '', card: null, which: null, drag: null, pos: null, rec: false, prompts: [], form: null, renaming: null, renameTo: '' };
  let host = null, root = null, picked = null, hoverEl = null, whichEls = [];
  const refs = new Map();                                    // id -> element, for the builder to find a recorded element again
  const sent = new WeakMap();                                // field -> the value last recorded for it
  const focusVal = new WeakMap();                            // field -> its value when it got focus
  let dateWatch = null;                                      // a read-only field (calendar) clicked while recording: {el, before, ref}
  let downChecked = null;                                    // picking: a check box's state when it was pressed ({el, checked})

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

  // a label's own words: without its help tooltip / info link / nested controls, and without the trailing "*" of a required field
  function labelText(l) {
    try {
      const copy = l.cloneNode(true);
      copy.querySelectorAll('a, button, [role="tooltip"], .customTooltip, input, select, textarea, .font-red').forEach((n) => n.remove());
      return short(clean(copy.textContent).replace(/[\s*:]+$/, ''));
    } catch (e) { return short(l.innerText); }
  }

  function labelOf(el) {
    try {
      if (el.labels && el.labels.length) return labelText(el.labels[0]);
      const by = el.getAttribute('aria-labelledby');
      if (by) { const l = document.getElementById(by.split(/\s+/)[0]); if (l) return labelText(l); }
      const wrap = el.closest('label');
      if (wrap) return labelText(wrap);
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

  // a short css path from the nearest ancestor that is unique on its own (stable id, or tag + stable classes found once): "specific to what was
  // chosen" without leaning on the element's own tag or on its position in the whole page.  '' when no ancestor anchors it.
  function anchorPath(el) {
    try { return anchorPathOf(el); } catch (e) { return ''; }        // (a locator hint must never stop a pick or a recorded click)
  }
  function anchorPathOf(el) {
    const parts = [];
    const own = (e) => { const cls = stableClasses(Array.from(e.classList || [])).slice(0, 2); return e.tagName.toLowerCase() + cls.map((c) => '.' + cssIdent(c)).join(''); };
    let e = el;
    for (let depth = 0; e && e.nodeType === 1 && e !== document.documentElement && e !== document.body && depth < 8; depth += 1, e = e.parentElement) {
      let seg;
      if (stableId(e.id) && /^[A-Za-z][\w-]*$/.test(e.id)) { parts.unshift('#' + e.id); return depth === 0 && parts.length === 1 ? '' : parts.join(' > '); }
      seg = own(e);
      const parent = e.parentElement;
      const same = parent ? Array.from(parent.children).filter((x) => x.matches(seg)) : [e];
      if (same.length > 1) seg += `:nth-of-type(${Array.from(parent.children).filter((x) => x.tagName === e.tagName).indexOf(e) + 1})`;
      parts.unshift(seg);
      if (depth > 0 && seg.includes('.')) {
        try { if (document.querySelectorAll(seg).length === 1) return parts.join(' > '); } catch (err) { /* keep climbing */ }
      }
    }
    return '';
  }

  // the real form control a custom widget keeps underneath (<select id="myMulti"> behind a multi-select made of divs, links and an input):
  // its id / name is the widget's name.  Only when exactly one such control sits in the nearest ancestor that has any.
  function ownerOf(el) {
    try {
      for (let c = el.parentElement, depth = 0; c && depth < 8 && c !== document.body && c !== document.documentElement; depth += 1, c = c.parentElement) {
        const found = Array.from(c.querySelectorAll('select, input[type="hidden"]')).filter((x) => x !== el && !el.contains(x)
          && (stableId(x.id) || stableId(x.getAttribute('name'))));
        if (found.length === 1) {
          const x = found[0];
          return { tag: x.tagName.toLowerCase(), id: x.id || '', name: x.getAttribute('name') || '', ctag: c.tagName.toLowerCase(), classes: Array.from(c.classList || []) };
        }
        if (found.length > 1) return null;
      }
    } catch (e) { /* no owner */ }
    return null;
  }

  // data-* attributes that say WHICH one this is (data-cmp-duplication-input-id on the inputs of a repeatable set, data-item-key...)
  const IDENTITY_DATA = /^data-.*(id|key|name|field)$/i;         // (not "index": that is a position, and positions change)
  function dataIdsOf(el) {
    const out = {};
    try {
      for (const a of Array.from(el.attributes || [])) {
        if (Object.keys(out).length >= 3) break;
        const v = String(a.value || '').trim();
        if (IDENTITY_DATA.test(a.name) && v && v.length <= 200 && !TEST_IDS.includes(a.name) && !/^data-(reactid|rr-)/i.test(a.name)) out[a.name] = v;
      }
    } catch (e) { /* none */ }
    return out;
  }

  // an empty box laid over (nearly) the whole page: the click-catcher a widget puts behind its open list
  function coversPage(el) {
    try {
      const r = el.getBoundingClientRect();
      return r.width >= innerWidth * 0.8 && r.height >= innerHeight * 0.8 && !clean(el.innerText) && el.tagName !== 'BODY' && el.tagName !== 'HTML';
    } catch (e) { return false; }
  }

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    const name = nameOf(el);
    const tid = TEST_IDS.find((a) => el.hasAttribute(a));
    let visible = true;
    try { visible = typeof el.checkVisibility === 'function' ? el.checkVisibility() : true; } catch (e) { /* old browser */ }
    let selected = '';
    try { if (tag === 'select' && el.selectedOptions && el.selectedOptions.length) selected = clean(el.selectedOptions[0].textContent); } catch (e) { /* not a select */ }
    return {
      tag, kind: kindOf(el), id: el.id || '', name: el.getAttribute('name') || '', type: el.getAttribute('type') || '',
      testid: tid ? { attr: tid, value: el.getAttribute(tid) } : null,
      ariaLabel: el.getAttribute('aria-label') || '', placeholder: el.getAttribute('placeholder') || '', title: el.getAttribute('title') || '',
      alt: el.getAttribute('alt') || '', href: tag === 'a' ? (el.getAttribute('href') || '') : '', value: el.getAttribute('value') || '',
      classes: Array.from(el.classList || []), text: short(el.innerText), label: labelOf(el),
      context: sameNameCount(el, name) > 1 || !name ? contextOf(el, name) : null,
      dataIds: dataIdsOf(el), owner: (stableId(el.getAttribute('name')) || short(el.getAttribute('aria-label'))) ? null : ownerOf(el), cover: coversPage(el), cssPath: cssPath(el), anchorPath: anchorPath(el), frame: TOP ? '' : (window.name || location.href),
      current: { value: 'value' in el && typeof el.value === 'string' && (el.getAttribute('type') || '').toLowerCase() !== 'password' ? el.value.slice(0, 200) : '', checked: !!el.checked,
        enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true', visible, selected },
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

  // ---- locator candidates, counted here (the same list as locators.candidates; the builder recounts any it does not find here) ---------
  const GEN_ID = /(\d{3,}|[0-9a-f]{8,}|^(ember|ext-gen|gwt-uid|yui_|j_id|mui-|radix-|headlessui-|react-|__bvid__|:r)|[-_:]\d+$|^[-_:])/i;
  const GEN_CLASS = /(\d{3,}|^css-|^sc-|^jsx-|^_|__[a-z0-9]{5,}$|[0-9a-f]{6,}|^(ng-|is-|has-|js-))/i;
  const STATE_CLASSES = new Set(['active', 'hover', 'focus', 'focused', 'selected', 'open', 'opened', 'closed', 'disabled', 'enabled', 'checked', 'visible',
    'hidden', 'show', 'shown', 'in', 'fade', 'collapsed', 'expanded', 'current', 'error', 'invalid', 'valid', 'dirty', 'touched', 'loading', 'loaded',
    'animated', 'on', 'off']);
  const stableId = (v) => { v = String(v || '').trim(); return !!v && v.length <= 60 && !v.includes(' ') && !GEN_ID.test(v); };
  const stableClasses = (cs) => (cs || []).filter((c) => c && !STATE_CLASSES.has(c.toLowerCase()) && !GEN_CLASS.test(c) && c.length <= 40).slice(0, 3);
  const cssString = (v) => '"' + String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const cssIdent = (n) => String(n).replace(/([^A-Za-z0-9_-])/g, '\\$1');
  function lit(v) {
    v = String(v);
    if (!v.includes("'")) return `'${v}'`;
    if (!v.includes('"')) return `"${v}"`;
    return 'concat(' + v.split("'").map((p) => `'${p}'`).join(', "\'", ') + ')';
  }
  const elementName = (d) => { for (const k of ['ariaLabel', 'label', 'text', 'value', 'placeholder', 'title', 'alt']) { const t = short(d[k]); if (t) return t; } return ''; };
  const isFieldDesc = (d) => ['field', 'textbox', 'dropdown', 'checkbox', 'radio'].includes(d.kind) || ['input', 'textarea', 'select'].includes(String(d.tag || '').toLowerCase());
  function textPred(d, text) {
    const tag = String(d.tag || '').toLowerCase();
    if (tag === 'input' && ['submit', 'button', 'reset'].includes(String(d.type || '').toLowerCase())) return `[@value=${lit(text)}]`;
    if (d.ariaLabel && short(d.ariaLabel) === text) return `[@aria-label=${lit(text)}]`;
    return `[normalize-space(.)=${lit(text)}]`;
  }
  function innerOf(d, name) {
    const tag = String(d.tag || '*').toLowerCase();
    if (name && !isFieldDesc(d)) return tag + textPred(d, name);
    for (const [attr, key] of [['name', 'name'], ['aria-label', 'ariaLabel'], ['placeholder', 'placeholder']]) {
      const v = d[key];
      if (v && (attr !== 'name' || stableId(v))) return `${tag}[@${attr}=${lit(String(v))}]`;
    }
    return tag;
  }
  function contextForms(d, name, heading) {
    const ctx = d.context || {};
    const anchor = `//${String(ctx.headingTag || '*').toLowerCase()}[normalize-space(.)=${lit(heading)}]/ancestor::${String(ctx.tag || '*').toLowerCase()}`;
    const inner = innerOf(d, name);
    const out = [];
    const cls = stableClasses(ctx.classes || []);
    if (cls.length) out.push({ findBy: 'BY_XPATH', value: `${anchor}[contains(concat(' ', normalize-space(@class), ' '), ${lit(' ' + cls[0] + ' ')})][1]//${inner}` });
    out.push({ findBy: 'BY_XPATH', value: `${anchor}[1]//${inner}` });
    return out;
  }
  function ownerForms(d, name) {
    const o = d.owner || {};
    const stag = String(o.tag || '*').toLowerCase();
    let control;
    if (o.id && stableId(o.id)) control = `//${stag}[@id=${lit(String(o.id))}]`;
    else if (o.name && stableId(o.name)) control = `//${stag}[@name=${lit(String(o.name))}]`;
    else return [];
    const tag = String(d.tag || '*').toLowerCase();
    let inner;
    if (name && !isFieldDesc(d)) {
      const pred = textPred(d, name);
      inner = tag + (pred.startsWith('[normalize-space') ? `[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')=${lit(name.toLowerCase())}]` : pred);
    } else inner = innerOf(d, name);
    if (inner === tag) {
      const own = stableClasses(d.classes || []);
      if (own.length) inner = `${tag}[contains(concat(' ', normalize-space(@class), ' '), ${lit(' ' + own[0] + ' ')})]`;
    }
    const cls = stableClasses(o.classes || []);
    const scope = `ancestor::${String(o.ctag || '*').toLowerCase()}` + (cls.length ? `[contains(concat(' ', normalize-space(@class), ' '), ${lit(' ' + cls[0] + ' ')})]` : '') + '[1]';
    return [{ findBy: 'BY_XPATH', value: `${control}/${scope}//${inner}` }];
  }
  function candidatesOf(d) {
    const tag = String(d.tag || '*').toLowerCase();
    const name = elementName(d);
    let heading = short((d.context || {}).heading || '');
    if (heading === name) heading = '';
    const out = [];
    if (stableId(d.id)) out.push({ findBy: 'BY_ID', value: d.id });
    const tid = d.testid || {};
    if (TEST_IDS.includes(tid.attr) && stableId(tid.value)) out.push({ findBy: 'BY_CSSSELECTOR', value: `[${tid.attr}=${cssString(tid.value)}]` });
    for (const [attr, raw] of Object.entries(d.dataIds || {})) {          // the attribute that tells the repeats apart, with the name when there is one
      const v = String(raw || '').trim();
      if (!v) continue;
      const base = (isFieldDesc(d) || tag === 'button') && stableId(d.name) ? `${tag}[name=${cssString(d.name)}]` : tag;
      out.push({ findBy: 'BY_CSSSELECTOR', value: `${base}[${attr}=${cssString(v)}]` });
    }
    const attrs = (isFieldDesc(d) || tag === 'button' ? [['name', d.name]] : []).concat([['aria-label', d.ariaLabel], ['placeholder', d.placeholder], ['title', d.title], ['alt', d.alt]]);
    for (const [attr, raw] of attrs) {
      const v = String(raw || '').trim();
      if (v && (attr !== 'name' || stableId(v)) && v.length <= 80) {
        let css = `${tag}[${attr}=${cssString(v)}]`;
        if (tag === 'input' && String(d.type || '').toLowerCase() === 'radio' && d.value) css += `[value=${cssString(d.value)}]`;
        out.push({ findBy: 'BY_CSSSELECTOR', value: css });
      }
    }
    const href = String(d.href || '');
    if (tag === 'a' && href && !href.includes('?') && !href.slice(1).includes('#') && href.length <= 120 && !/\d{4,}/.test(href)) out.push({ findBy: 'BY_CSSSELECTOR', value: `a[href=${cssString(href)}]` });
    if (name && !isFieldDesc(d)) {
      out.push({ findBy: 'BY_XPATH', value: `//${tag}${textPred(d, name)}` });
      if (textPred(d, name).startsWith('[normalize-space') && name !== name.toLowerCase()) {
        out.push({ findBy: 'BY_XPATH', value: `//${tag}[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')=${lit(name.toLowerCase())}]` });
      }
    }
    const label = short(d.label);
    if (label && isFieldDesc(d)) out.push({ findBy: 'BY_XPATH', value: `//label[normalize-space(.)=${lit(label)}]/following::${tag}[1]` });
    if (heading) out.push(...contextForms(d, name, heading));
    const cls = stableClasses(d.classes || []);
    if (cls.length) out.push({ findBy: 'BY_CSSSELECTOR', value: tag + cls.map((c) => '.' + cssIdent(c)).join('') });
    if (d.owner) out.push(...ownerForms(d, name));
    if (d.anchorPath) out.push({ findBy: 'BY_CSSSELECTOR', value: d.anchorPath });
    out.push({ findBy: 'BY_CSSSELECTOR', value: tag });
    if (d.cssPath) out.push({ findBy: 'BY_CSSSELECTOR', value: d.cssPath });
    return out;
  }
  const isShown = (x) => { try { const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(x).visibility !== 'hidden'; } catch (e) { return false; } };
  function counted(el, d) {
    const out = [];
    for (const c of candidatesOf(d)) {
      let list = [];
      try {
        if (c.findBy === 'BY_XPATH') {
          const r = document.evaluate(c.value, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
          for (let i = 0; i < r.snapshotLength; i += 1) list.push(r.snapshotItem(i));
        } else list = Array.from(document.querySelectorAll(c.findBy === 'BY_ID' ? `[id=${cssString(c.value)}]` : c.value));
      } catch (e) { continue; }
      const seen = list.length > 1 ? list.filter(isShown) : [];          // (only when hidden copies could matter)
      out.push({ findBy: c.findBy, value: c.value, count: list.length, position: list.indexOf(el), vcount: list.length > 1 ? seen.length : -1, vposition: seen.indexOf(el) });
    }
    return out;
  }

  function remember(el) {
    for (const [k, v] of refs) if (v === el) return k;
    const id = Math.random().toString(36).slice(2, 10) + refs.size.toString(36);
    refs.set(id, el);
    if (refs.size > 300) refs.delete(refs.keys().next().value);
    return id;
  }

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
button.on, button.pri { background: #5cc8ff; color: #06121c; }
button.rec { color: #b8c2cf; }
button.rec.live { background: rgba(255,107,107,.16); color: #ff8a80; box-shadow: inset 0 0 0 1px rgba(255,107,107,.45); }
button.rec .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
button[disabled] { opacity: .4; cursor: default; }
button.sm { height: 24px; padding: 0 9px; font-size: 11.5px; font-weight: 500; background: #2c3541; }
button.sm.on { background: #5cc8ff; color: #06121c; font-weight: 600; }
.sep { width: 1px; height: 20px; background: #3a4452; margin: 0 2px; }
.what { font: 11.5px ui-monospace, SFMono-Regular, Menlo, monospace; color: #b8c2cf; padding: 0 8px; white-space: nowrap; }
.box { position: fixed; z-index: 2147483646; pointer-events: none; border: 2px solid #5cc8ff; border-radius: 6px; box-shadow: 0 0 0 4px rgba(92,200,255,.22); }
.box.picked { border-color: #7ee2a8; box-shadow: 0 0 0 4px rgba(126,226,168,.25); }
.box.which { border-color: #f2c14e; box-shadow: 0 0 0 4px rgba(242,193,78,.25); }
.tag { position: absolute; left: -2px; top: -24px; height: 20px; padding: 0 7px; border-radius: 5px; background: #5cc8ff; color: #06121c;
  font: 600 11px ui-monospace, SFMono-Regular, Menlo, monospace; display: flex; align-items: center; white-space: nowrap; }
.num { position: absolute; right: -11px; top: -11px; width: 22px; height: 22px; border-radius: 50%; background: #f2c14e; color: #06121c;
  font: 700 12px ui-monospace, monospace; display: grid; place-items: center; }
.card, .pcard, .toast { position: fixed; z-index: 2147483647; width: 320px; border-radius: 14px; background: #1f2630; color: #e8edf3; border: 1px solid #3a4452;
  box-shadow: 0 24px 60px rgba(0,0,0,.45); display: flex; flex-direction: column; }
.card.form { width: 390px; }
.card .hd, .pcard .hd, .toast .hd { padding: 12px 14px 10px; border-bottom: 1px solid #333d4a; display: flex; flex-direction: column; gap: 3px; }
.t { font-size: 13px; font-weight: 700; }
.m { font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; color: #9aa6b5; word-break: break-all; }
.d { font-size: 11.5px; color: #9aa6b5; }
.bad { color: #ff8a80; }
.ft { padding: 8px 10px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.body { padding: 10px 14px; display: flex; flex-direction: column; gap: 10px; max-height: 60vh; overflow: auto; }
.grp { display: flex; flex-direction: column; gap: 5px; }
.lbl { font-size: 10.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #8a96a6; }
.row { display: flex; flex-wrap: wrap; gap: 4px; }
input.fld { all: unset; box-sizing: border-box; width: 100%; height: 30px; padding: 0 10px; border-radius: 8px; background: #151b23; border: 1px solid #3a4452;
  font: 12.5px ui-monospace, SFMono-Regular, Menlo, monospace; color: #e8edf3; }
input.fld:focus { border-color: #5cc8ff; }
.toasts { position: fixed; z-index: 2147483647; left: 16px; bottom: 16px; width: 380px; display: flex; flex-direction: column; gap: 8px; }
.toast { position: static; width: auto; }
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

  function btn(label, act, cls, data) {
    const b = el('button', cls || '', label);
    b.setAttribute('data-rr-act', act);
    for (const [k, v] of Object.entries(data || {})) b.setAttribute(`data-${k}`, v);
    return b;
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

  function beside(node, r, width, height) {
    const vw = window.innerWidth, vh = window.innerHeight;
    const left = r.right + 12 + width < vw ? r.right + 12 : Math.max(8, r.left - width - 12);
    const top = Math.min(Math.max(8, r.top), Math.max(8, vh - height));
    Object.assign(node.style, { left: `${left}px`, top: `${top}px` });
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
    const rec = btn(st.rec ? 'Rec' : 'Rec off', 'rec', `rec${st.rec ? ' live' : ''}`);
    rec.insertBefore(el('span', 'dot'), rec.firstChild);
    rec.title = st.rec ? 'Recording: clicks, typing and choices become steps. Click to stop.' : 'Record: your clicks, typing and choices become steps';
    pill.appendChild(rec);
    pill.appendChild(el('span', 'sep'));
    for (const [mode, label] of [['pick', 'Pick'], ['check', 'Check'], ['save', 'Save'], ['wait', 'Wait until']]) pill.appendChild(btn(label, mode, st.mode === mode ? 'on' : ''));
    pill.appendChild(el('span', 'sep'));
    pill.appendChild(el('span', 'what', st.label || 'Build window'));
    const done = btn('Done', 'done', 'pri');
    done.title = 'Finish: stop picking and recording (the Build tab shows what was recorded)';
    pill.appendChild(done);
    root.appendChild(pill);
  }

  function drawMarks() {
    if (!ensureHost()) return;
    clear('.box');
    if (picked && picked.isConnected && (st.card || PICKING.includes(st.mode))) outline(picked, 'picked', '');
    if (st.mode === 'which') whichEls.forEach((w, i) => { if (w.isConnected) outline(w, 'which', '', i + 1); });
    if (hoverEl && hoverEl.isConnected && PICKING.includes(st.mode)) outline(hoverEl, '', friendly(describe(hoverEl)));
  }

  function drawCard() {
    const focused = root && root.activeElement && root.activeElement.getAttribute ? root.activeElement.getAttribute('data-rr-field') : null;
    clear('.card');
    const c = st.card;
    if (!c || !picked || !picked.isConnected || !ensureHost()) return;
    const r = picked.getBoundingClientRect();
    const card = el('div', `card${c.form ? ' form' : ''}`);
    const hd = el('div', 'hd');
    hd.appendChild(el('span', 't', c.title || 'Picked'));
    for (const line of c.lines || []) hd.appendChild(el('span', `m${c.ok === false ? ' bad' : ''}`, line));
    card.appendChild(hd);
    if (c.form && c.ok !== false) formBody(card, c.form);
    const ft = el('div', 'ft');
    if (c.form && c.ok !== false) {
      const f = st.form;
      const add = btn(`Add ${c.form.purpose === 'save' ? 'save' : c.form.purpose === 'wait' ? 'wait' : 'check'} · step ${c.form.n}`, 'add', 'pri');
      if (!f.kind) add.setAttribute('disabled', '');
      ft.appendChild(add);
    } else ft.appendChild(btn('Pick again', st.mode === 'browse' ? 'pick' : st.mode, ''));
    ft.appendChild(btn(c.form ? 'Cancel' : 'Close', 'close-card', ''));
    card.appendChild(ft);
    beside(card, r, c.form ? 390 : 320, c.form ? 420 : 200);
    root.appendChild(card);
    if (focused) {
      const input = root.querySelector(`[data-rr-field="${focused}"]`);
      if (input) { input.focus(); try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) { /* not text */ } }
    }
  }

  function formBody(card, form) {
    const f = st.form;
    const body = el('div', 'body');
    const groups = [];
    for (const k of form.kinds) { let g = groups.find((x) => x.name === k.group); if (!g) { g = { name: k.group, kinds: [] }; groups.push(g); } g.kinds.push(k); }
    if (form.kinds.length > 1) {
      for (const g of groups) {
        const box = el('div', 'grp');
        box.appendChild(el('span', 'lbl', g.name));
        const row = el('div', 'row');
        for (const k of g.kinds) {
          const b = btn(k.label, 'kind', `sm${f.kind === k.id ? ' on' : ''}`, { kind: k.id });
          if (!k.enabled) { b.setAttribute('disabled', ''); b.title = k.why || ''; }
          row.appendChild(b);
        }
        box.appendChild(row);
        body.appendChild(box);
      }
    }
    if (NEEDS_EXPECTED.has(f.kind)) {
      const box = el('div', 'grp');
      box.appendChild(el('span', 'lbl', 'Expected · from the live page'));
      const input = el('input', 'fld');
      input.setAttribute('data-rr-field', 'expected');
      input.value = f.expected;
      box.appendChild(input);
      const vars = (form.variables || []).filter((v) => v.value === (form.kinds.find((k) => k.id === f.kind) || {}).expected);
      if (vars.length) {
        const row = el('div', 'row');
        row.appendChild(el('span', 'd', 'Swap for a variable:'));
        for (const v of vars) row.appendChild(btn(`{${v.token}}`, 'var', 'sm', { token: v.token }));
        box.appendChild(row);
      }
      body.appendChild(box);
    }
    if (form.purpose === 'save') {
      const box = el('div', 'grp');
      box.appendChild(el('span', 'lbl', 'Save it as the variable'));
      const input = el('input', 'fld');
      input.setAttribute('data-rr-field', 'token');
      input.value = f.token;
      box.appendChild(input);
      if (form.text) box.appendChild(el('span', 'd', `Now: ${form.text}`));
      body.appendChild(box);
    }
    card.appendChild(body);
  }

  function promptBox(p, cls) {
    const box = el('div', cls);
    const hd = el('div', 'hd');
    hd.appendChild(el('span', 't', p.text || ''));
    if (p.detail) hd.appendChild(el('span', 'd', p.detail));
    box.appendChild(hd);
    const ft = el('div', 'ft');
    if (st.renaming === p.id) {
      const input = el('input', 'fld');
      input.setAttribute('data-rr-field', 'rename');
      input.value = st.renameTo;
      ft.appendChild(input);
      ft.appendChild(btn('Rename', 'prompt', 'pri', { id: p.id, choice: 'rename' }));
      ft.appendChild(btn('Cancel', 'rename-cancel', ''));
    } else {
      for (const choice of p.choices || []) {
        if (choice === 'edit') continue;                                                 // (the fingerprint editor is in the Build tab)
        const label = choice === 'gate' ? 'Save fingerprint + add gate' : choice === 'dismiss' && p.kind === 'fingerprint' ? 'Not now' : CHOICE_WORDS[choice] || choice;
        ft.appendChild(btn(label, choice === 'rename' ? 'rename' : 'prompt', choice === 'gate' || choice === 'keep' ? 'pri' : '', { id: p.id, choice, token: p.token || '' }));
      }
    }
    box.appendChild(ft);
    return box;
  }

  function drawPrompts() {
    const focused = root && root.activeElement && root.activeElement.getAttribute ? root.activeElement.getAttribute('data-rr-field') : null;
    clear('.pcard');
    clear('.toasts');
    if (!st.prompts.length || !ensureHost()) return;
    const near = [...st.prompts].reverse().find((p) => p.ref && refs.has(p.ref) && refs.get(p.ref).isConnected);
    if (near) {
      const r = refs.get(near.ref).getBoundingClientRect();
      const card = promptBox(near, 'pcard');
      beside(card, r, 320, 160);
      root.appendChild(card);
    }
    if (TOP) {
      const rest = st.prompts.filter((p) => !p.ref).slice(-2);
      if (rest.length) {
        const stack = el('div', 'toasts');
        for (const p of rest) stack.appendChild(promptBox(p, 'toast'));
        root.appendChild(stack);
      }
    }
    if (focused === 'rename') { const input = root.querySelector('[data-rr-field="rename"]'); if (input) input.focus(); }
  }

  function redraw() {
    try { drawPill(); drawMarks(); drawCard(); drawPrompts(); } catch (e) { /* never break the page */ }
  }

  // ---- talking to the builder ---------------------------------------------------------------------------------------------------------
  function call(payload) {
    try {
      const fn = BIND || window[CALL];
      const body = BIND ? { ...payload, key: KEY } : payload;             // (the key only ever goes to the binding taken before the site ran)
      return typeof fn === 'function' ? Promise.resolve(fn(body)).catch(() => null) : Promise.resolve(null);
    } catch (e) { return Promise.resolve(null); }
  }

  function apply(state) {
    if (!state || typeof state !== 'object') return;
    if ('mode' in state) st.mode = state.mode || 'browse';
    if ('label' in state) st.label = state.label || '';
    if ('rec' in state) st.rec = !!state.rec;
    if ('prompts' in state) st.prompts = Array.isArray(state.prompts) ? state.prompts : [];
    if ('card' in state) {
      st.card = state.card || null;
      const form = st.card && st.card.form;
      if (!form) st.form = null;
      else if (!st.form || st.form.id !== st.card.id) {
        const k = form.kinds.find((x) => x.id === form.chosen) || {};
        st.form = { id: st.card.id, kind: form.chosen || '', expected: k.expected || '', token: form.token || '' };
      }
    }
    if (st.mode !== 'which') whichEls = [];
    if (st.mode === 'browse' && !st.card) hoverEl = null;
    redraw();
  }

  function diag(what, detail) { call({ kind: 'diag', what, detail: String(detail == null ? '' : detail).slice(0, 4000) }); }

  function pickNow(elm, wasChecked) {
    picked = elm;
    hoverEl = null;
    let d;
    try { d = describe(elm); } catch (e) {
      st.card = { title: 'Could not read this element', lines: [String(e && e.message || e)] };
      st.form = null;
      redraw();
      diag('pick-describe-failed', e && e.stack || e);
      return;
    }
    if (wasChecked != null) d.current.checked = wasChecked;          // (a check box flips while its click is dispatched; the pick undoes it)
    st.card = { title: friendly(d), lines: ['checking the locator on this page…'] };
    st.form = null;
    redraw();
    call({ kind: 'pick', element: d });
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

  // ---- recording (the page keeps every event: nothing here stops or changes it) ---------------------------------------------------------
  const isText = (e) => e instanceof HTMLTextAreaElement || (e instanceof HTMLInputElement && !NOT_TEXT.includes((e.type || '').toLowerCase()));
  const isToggle = (e) => e instanceof HTMLInputElement && ['checkbox', 'radio'].includes((e.type || '').toLowerCase());
  const recording = (ev) => st.rec && st.mode === 'browse' && ev.isTrusted && !inOverlay(ev);

  function recElement(elm) {
    const d = describe(elm);
    return { element: d, checks: counted(elm, d), ref: remember(elm) };
  }

  function send(what, elm, extra) { call({ kind: 'rec', what, ...(elm ? recElement(elm) : {}), ...(extra || {}) }); }

  function isOption(elm) {
    try {
      if (elm.closest(OPTIONS)) return true;
      const typed = document.activeElement;
      const owns = typed && typed.getAttribute && (typed.getAttribute('aria-controls') || typed.getAttribute('aria-owns'));
      return !!(owns && document.getElementById(owns) && document.getElementById(owns).contains(elm));
    } catch (e) { return false; }
  }

  function watchDate() {
    if (!dateWatch) return;
    const w = dateWatch;
    const look = () => {
      if (dateWatch !== w || !w.el.isConnected) return;
      if (w.el.value && w.el.value !== w.before) { dateWatch = null; send('date-picked', w.el, { value: w.el.value }); }
    };
    setTimeout(look, 150);
    setTimeout(look, 500);
  }

  const CALENDAR = '.ui-datepicker, .datepicker, .flatpickr-calendar, .react-datepicker, .pika-single, .daterangepicker, [class*="datepicker" i], [class*="calendar" i]';
  // the day a click on a calendar's cell picks, as YYYY-MM-DD ('' when the cell does not say: a month button, a heading)
  const MONTH_NAMES = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  const MONTH_RE = '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?';
  const isoOf = (y, m, day) => `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  // a whole date written in words or digits ("Sunday, October 6, 2026", "6 Oct 2026", "2026-10-06"), '' when the text has none
  function dateFromText(text) {
    const t = clean(text);
    let m = /(\d{4})-(\d{2})-(\d{2})/.exec(t);
    if (m) return m[0];
    m = new RegExp('(\\d{1,2})(?:st|nd|rd|th)?\\s+' + MONTH_RE + ',?\\s+(\\d{4})', 'i').exec(t);
    if (m) return isoOf(m[4], MONTH_NAMES.indexOf(m[2].toLowerCase()) + 1, m[1]);
    m = new RegExp(MONTH_RE + '\\s+(\\d{1,2})(?:st|nd|rd|th)?,?\\s+(\\d{4})', 'i').exec(t);
    if (m) return isoOf(m[3], MONTH_NAMES.indexOf(m[1].toLowerCase()) + 1, m[2]);
    return '';
  }

  function dayOf(elm) {
    // jQuery UI: <td data-month="8" data-year="2026"><a data-date="29">29</a></td> (data-date is the DAY number there, months count from 0)
    const td = elm.closest('td[data-month][data-year]');
    if (td) {
      const y = td.getAttribute('data-year'), m = td.getAttribute('data-month'), d = clean(td.textContent);
      if (/^\d{1,2}$/.test(d)) return `${y}-${String(+m + 1).padStart(2, '0')}-${d.padStart(2, '0')}`;
    }
    const cell = elm.closest('[data-date]');
    if (cell) {
      const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(cell.getAttribute('data-date') || '');
      if (iso) return iso[0];
    }
    // the cell (or something in it) names the whole date: aria-label / title / hidden text
    for (let e = elm, depth = 0; e && depth < 4; e = e.parentElement, depth += 1) {
      const named = dateFromText(`${e.getAttribute('aria-label') || ''} ${e.getAttribute('title') || ''} ${e.getAttribute('data-day') || ''}`)
        || dateFromText(e.textContent && e.textContent.length < 60 ? e.textContent : '');
      if (named) return named;
    }
    for (const e of elm.querySelectorAll('[aria-label], [title]')) {
      const named = dateFromText(`${e.getAttribute('aria-label') || ''} ${e.getAttribute('title') || ''}`);
      if (named) return named;
    }
    // a calendar that does not say: the day's number + the month heading of ITS month block ("October 2026"), looked for only inside the
    // calendar itself (never in the page around it: a "March 2025" in the small print must not become the month), nearest block first
    const dayEl = elm.closest('a, button, td, [role="gridcell"], [role="button"]') || elm;
    const dm = /^(?:\D*?)(\d{1,2})(?!\d)/.exec(clean(dayEl.textContent));
    const d = dm ? dm[1] : '';
    if (!d) return '';
    const cal = dayEl.closest(CALENDAR);
    if (!cal) return '';
    const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
    const head = /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(\d{4})$/i;
    const iso = (y, m, day) => `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    for (let box = dayEl.parentElement; box; box = box.parentElement) {
      for (const h of box.querySelectorAll('*')) {
        if (h.children.length > 3 || h.contains(dayEl) || h.tagName === 'OPTION') continue;
        const m = head.exec(clean(h.textContent));
        if (m) return iso(m[2], MONTHS.indexOf(m[1].toLowerCase()) + 1, d);
      }
      // month and year kept apart (two selects, or two spans)
      const mo = box.querySelector('.ui-datepicker-month, [class*="month" i]:not(table):not(td):not(tr)'), yr = box.querySelector('.ui-datepicker-year, [class*="year" i]');
      if (mo && yr) {
        const monthText = mo.tagName === 'SELECT' ? clean(mo.selectedOptions[0] && mo.selectedOptions[0].textContent) : clean(mo.textContent);
        const yearText = yr.tagName === 'SELECT' ? clean(yr.value) : clean(yr.textContent);
        const mi = MONTHS.indexOf(monthText.slice(0, 3).toLowerCase());
        if (mi >= 0 && /^\d{4}$/.test(yearText)) return iso(yearText, mi + 1, d);
      }
      if (box === cal) break;
    }
    return '';
  }

  // a field a calendar belongs to: read-only, a datepicker's own class, a date type, or a DD/MM/YYYY-style placeholder
  const isDateInput = (e) => e.readOnly || /datepicker/i.test(String(e.className || '')) || (e.getAttribute('data-cmp-type') || '').toLowerCase() === 'date'
    || /^[dmy]{1,4}([ ./-][dmy]{1,4}){2}$/i.test((e.getAttribute('placeholder') || '').trim());

  // inside a calendar's own box (an input that merely carries a "hasDatepicker" class is not the calendar)
  const inCalendar = (e) => { const c = e.closest(CALENDAR); return !!c && !(c instanceof HTMLInputElement || c instanceof HTMLTextAreaElement || c instanceof HTMLSelectElement); };

  function onRecClick(ev) {
    if (!recording(ev)) return;
    const elm = target(ev.target);
    if (!elm || elm === host) return;
    // a calendar that has just set its field (it sets the value without any event): say so before this next action is recorded, so the date
    // is not lost when the person moves on faster than the watch's own look
    if (dateWatch && dateWatch.el !== elm && !inCalendar(elm) && dateWatch.el.value && dateWatch.el.value !== dateWatch.before) {
      const w = dateWatch;
      dateWatch = null;
      send('date-picked', w.el, { value: w.el.value });
    }
    if (!dateWatch && !isText(elm) && inCalendar(elm)) {
      const date = dayOf(elm);
      if (!date && /\d/.test(clean(elm.textContent)) && clean(elm.textContent).length < 40) diag('calendar-day-unreadable', elm.closest(CALENDAR).outerHTML);
      send('cal-click', elm, { date, text: clean(elm.textContent).slice(0, 12) });
      return;
    }
    if (isText(elm) || elm instanceof HTMLSelectElement) {
      if (elm instanceof HTMLInputElement && isDateInput(elm) && !(dateWatch && dateWatch.el === elm)) {
        dateWatch = { el: elm, before: elm.value };
        send('date-open', elm);
      }
      return;                                                     // (a click into a field only focuses it: the typing is the step)
    }
    if (isToggle(elm)) return;                                     // (its change records it)
    const label = elm.closest('label');
    if (label && label.control) return;
    const option = isOption(elm);
    send('click', elm, option ? { option: true } : {});
    watchDate();
  }

  function onRecChange(ev) {
    if (!recording(ev)) return;
    const elm = ev.target;
    if (!(elm instanceof Element)) return;
    if (!dateWatch && elm.closest && inCalendar(elm) && (elm instanceof HTMLSelectElement)) return;      // (a calendar's month / year list: not a step)
    if (dateWatch && dateWatch.el === elm) { dateWatch = null; if (elm.value) send('date-picked', elm, { value: elm.value }); return; }
    if (isToggle(elm)) send('toggle', elm, { checked: !!elm.checked });
    else if (elm instanceof HTMLSelectElement) send('select', elm, { value: elm.selectedOptions && elm.selectedOptions.length ? clean(elm.selectedOptions[0].textContent) : '' });
    else if (elm instanceof HTMLInputElement && DATE_TYPES.includes((elm.type || '').toLowerCase())) send('date-picked', elm, { value: elm.value });
    else if (isText(elm)) {
      if (sent.get(elm) === elm.value) return;
      sent.set(elm, elm.value);
      send('type', elm, { value: elm.value, secret: (elm.type || '').toLowerCase() === 'password' });
    }
  }

  function onRecKey(ev) {
    if (!recording(ev) || ev.key !== 'Enter' || ev.isComposing) return;
    const elm = ev.target;
    if (!(elm instanceof HTMLInputElement) || !isText(elm)) return;
    const was = focusVal.has(elm) ? focusVal.get(elm) : elm.defaultValue;
    if (elm.value !== was && sent.get(elm) !== elm.value) {                // the typing first: Enter may leave the page before "change"
      sent.set(elm, elm.value);
      send('type', elm, { value: elm.value, secret: (elm.type || '').toLowerCase() === 'password' });
    }
    send('key', elm, { key: 'ENTER' });
  }

  function heading() {
    const all = document.querySelectorAll('h1, [role=heading][aria-level="1"], h2');
    for (const h of all) {
      let vis = true;
      try { vis = typeof h.checkVisibility === 'function' ? h.checkVisibility() : true; } catch (e) { /* old browser */ }
      if (vis && short(h.innerText)) return recElement(h);
    }
    return null;
  }

  function navType() {
    try { const n = performance.getEntriesByType('navigation')[0]; return n ? n.type : ''; } catch (e) { return ''; }
  }

  // ---- the card's form and the prompts ------------------------------------------------------------------------------------------------
  function onFormInput() {
    const t = root && root.activeElement;
    const field = t && t.getAttribute && t.getAttribute('data-rr-field');
    if (field === 'expected' && st.form) st.form.expected = t.value;
    else if (field === 'token' && st.form) st.form.token = t.value;
    else if (field === 'rename') st.renameTo = t.value;
  }

  function onFormKey(ev) {
    if (ev.key !== 'Enter') return;
    const t = root && root.activeElement;
    const field = t && t.getAttribute && t.getAttribute('data-rr-field');
    if (field === 'rename' && st.renaming) { call({ kind: 'prompt', id: st.renaming, choice: 'rename', token: st.renameTo }); st.renaming = null; }
    else if ((field === 'expected' || field === 'token') && st.form && st.form.kind) addCheck();
  }

  function addCheck() {
    const f = st.form;
    if (!f || !f.kind) return;
    st.card = { ...st.card, lines: ['adding the step…'] };
    call({ kind: 'check-add', check: f.kind, expected: f.expected, token: f.token });
  }

  // ---- events (capture phase on window: before any listener of the site) ----------------------------------------------------------------
  // A listener outside a closed shadow root never sees the nodes inside it (composedPath() stops at the host), so what was pressed is found
  // with the shadow root's own elementFromPoint, and what is being typed into with its activeElement.
  function inOverlay(ev) { return !!host && typeof ev.composedPath === 'function' && ev.composedPath().includes(host); }
  function innerAt(ev) { try { return root && ev.clientX != null ? root.elementFromPoint(ev.clientX, ev.clientY) : null; } catch (e) { return null; } }
  function closestAt(ev, selector) { const n = innerAt(ev); return n && n.closest ? n.closest(selector) : null; }

  function setMode(mode) {
    st.mode = st.mode === mode ? 'browse' : mode;
    st.card = null;
    st.form = null;
    redraw();
    call({ kind: 'mode', mode: st.mode });
  }

  function overlayAction(ev) {
    const b = closestAt(ev, '[data-rr-act]');
    if (!b || b.hasAttribute('disabled')) return;
    const act = b.getAttribute('data-rr-act');
    if (['pick', 'check', 'save', 'wait'].includes(act)) setMode(act);
    else if (act === 'done') {                    // finish what is going on: picking / checking, and recording (the server says what was recorded)
      st.mode = 'browse'; st.card = null; st.form = null; hoverEl = null; st.rec = false; redraw(); call({ kind: 'done' });
    }
    else if (act === 'close-card') { st.card = null; st.form = null; redraw(); }
    else if (act === 'rec') { st.rec = !st.rec; redraw(); call({ kind: 'record', on: st.rec }); }
    else if (act === 'kind' && st.form) {
      const form = st.card.form;
      const k = form.kinds.find((x) => x.id === b.getAttribute('data-kind'));
      if (k && k.enabled) { st.form.kind = k.id; st.form.expected = k.expected || ''; drawCard(); }
    } else if (act === 'var' && st.form) { st.form.expected = `{${b.getAttribute('data-token')}}`; drawCard(); }
    else if (act === 'add') addCheck();
    else if (act === 'rename') { st.renaming = b.getAttribute('data-id'); st.renameTo = b.getAttribute('data-token') || ''; drawPrompts(); }
    else if (act === 'rename-cancel') { st.renaming = null; drawPrompts(); }
    else if (act === 'prompt') {
      const id = b.getAttribute('data-id');
      const choice = b.getAttribute('data-choice');
      call({ kind: 'prompt', id, choice, token: choice === 'rename' ? st.renameTo : '' });
      st.renaming = null;
      st.prompts = st.prompts.filter((p) => p.id !== id);
      drawPrompts();
    }
  }

  function onPress(ev) {
    if (inOverlay(ev)) {
      ev.stopImmediatePropagation();
      if (ev.type === 'pointerdown' && TOP) {
        const grip = closestAt(ev, '[data-rr-drag]');
        const pill = root && root.querySelector('.pill');
        if (grip && pill) { const r = pill.getBoundingClientRect(); st.drag = { dx: ev.clientX - r.left, dy: ev.clientY - r.top }; ev.preventDefault(); }
      }
      if (ev.type === 'pointerup') st.drag = null;
      if (ev.type === 'mousedown') ev.preventDefault();                 // (pressing the pill must not take the focus from the page's field: its list would close)
      if (ev.type === 'click') { ev.preventDefault(); overlayAction(ev); }
      return;
    }
    if (!PICKING.includes(st.mode)) {
      if (ev.type === 'click') onRecClick(ev);
      return;
    }
    ev.stopImmediatePropagation();                                 // picking: the site never sees the press (no navigation, no toggle, no focus)
    ev.preventDefault();
    const t = target(ev.target);
    if (ev.type === 'pointerdown') downChecked = isToggle(t) ? { el: t, checked: !!t.checked } : null;
    if (ev.type === 'click') pickNow(t, downChecked && downChecked.el === t ? downChecked.checked : null);
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
    if (!PICKING.includes(st.mode)) return;
    const t = target(ev.target);
    if (t && t !== hoverEl) { hoverEl = t; drawMarks(); }
  }

  function onKey(ev) {
    if (inOverlay(ev)) { ev.stopImmediatePropagation(); onFormKey(ev); return; }
    if (PICKING.includes(st.mode) && ev.key === 'Escape') {
      ev.stopImmediatePropagation();
      ev.preventDefault();
      st.mode = 'browse';
      hoverEl = null;
      redraw();
      call({ kind: 'mode', mode: 'browse' });
      return;
    }
    if (ev.type === 'keydown') onRecKey(ev);
  }

  function onOverlayOnly(ev) {
    if (!inOverlay(ev)) return;
    ev.stopImmediatePropagation();
    if (ev.type === 'input') onFormInput();
  }

  for (const type of PRESS) window.addEventListener(type, onPress, { capture: true });
  for (const type of ['pointermove', 'mousemove', 'mouseover', 'mouseout']) window.addEventListener(type, onMove, { capture: true, passive: true });
  window.addEventListener('pointerup', () => { st.drag = null; }, { capture: true });
  window.addEventListener('keydown', onKey, { capture: true });
  for (const type of ['keyup', 'keypress', 'input', 'beforeinput', 'focusin', 'focusout']) window.addEventListener(type, onOverlayOnly, { capture: true });
  window.addEventListener('change', onRecChange, { capture: true, passive: true });
  window.addEventListener('focusin', (ev) => { if (isText(ev.target)) focusVal.set(ev.target, ev.target.value); }, { capture: true, passive: true });
  window.addEventListener('scroll', () => { if (st.mode !== 'browse' || st.card || st.prompts.length) { drawMarks(); drawCard(); drawPrompts(); } }, { capture: true, passive: true });
  window.addEventListener('resize', redraw, { passive: true });
  window.addEventListener('pageshow', (ev) => { if (ev.persisted) hello('back_forward'); });

  // the list a picked item belongs to (or the picked element itself when it is a list): what "the list shows item N" is checked against
  function listFor() {
    const el = picked;
    if (!el || !el.isConnected) return null;
    const ITEM = 'li, [role="option"], [role="listitem"], tr';
    const LISTS = 'ul, ol, [role="listbox"], [role="menu"], tbody, table';
    const shown = (x) => { const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(x).visibility !== 'hidden'; };
    const itemsOf = (box) => {
      const found = Array.from(box.querySelectorAll(ITEM)).filter(shown);
      return found.length ? found : Array.from(box.children).filter(shown);
    };
    let list = null, items = [];
    const own = itemsOf(el);
    if (own.length > 1 || el.matches(LISTS)) { list = el; items = own; }
    else {
      for (let up = el.parentElement, d = 0; up && d < 6 && up !== document.body; up = up.parentElement, d += 1) {
        const found = itemsOf(up);
        if (found.length > 1 || up.matches(LISTS)) { list = up; items = found; break; }
      }
    }
    if (!list) return null;
    const at = items.findIndex((i) => i === el || i.contains(el));
    const d = describe(list);
    return { element: d, checks: counted(list, d), ref: remember(list), n: at >= 0 ? at + 1 : 1, text: at >= 0 ? clean(items[at].innerText || items[at].textContent) : '', count: items.length };
  }

  Object.defineProperty(window, '__rrBuild', {
    value: Object.freeze({ apply, findAll, choose, listFor, picked: () => picked, describe: () => (picked ? describe(picked) : null), ref: (id) => refs.get(id) || null }),
    enumerable: false, configurable: false, writable: false,
  });

  function hello(nav) {
    const body = { kind: 'hello', top: TOP, url: location.href, nav: nav || navType() };
    if (TOP) { const h = heading(); if (h) body.heading = h; }
    return call(body).then((state) => { if (state) apply(state); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { redraw(); hello(); }, { once: true });
  else { redraw(); hello(); }
})();
