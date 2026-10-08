/* Carrie: the unicorn scorekeeper as ONE widget for the QA app's live run screen. Phase 2, round 4.
 *
 *   const carrie = UnicornCarrie.create({ base: '/static/unicorn', onClose: () => {...} });
 *   carrie.update({ id: 'run:abc', passed: 3, failed: 1, total: 10, running: true, done: false });   // call it whenever the numbers may have changed
 *   carrie.hide();   carrie.destroy();
 *
 * It knows nothing about the QA app: it is given a snapshot of the numbers and works out what happened from the difference with the last one
 * (a new pass = onTestResult pass, a new fail = fail, running to done = onRunComplete), so the app only has to say how things stand.
 *  - The first time it sees a run it catches up SILENTLY (no celebration for a run that is already over, no replay of old results); a run it
 *    sees from its very start gets the "run started" excitement.
 *  - Everything lives in a shadow root on a fixed, click-through box in the bottom-right corner (its ids and CSS cannot touch the app's); only the
 *    small close button takes clicks. The rig, the boards and the canvas are built only when she is first shown, so Carrie mode off costs nothing.
 *  - Needs js/idle.js, js/fx.js and js/mood.js loaded first. Classic script (the app loads it with a plain script tag).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.UnicornCarrie = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var G = typeof globalThis !== 'undefined' ? globalThis : window;    // where idle.js / fx.js / mood.js put their objects
  var MAX_REACTIONS = 8;     // a bigger jump than this (a tab that was in the background) is caught up silently instead of replayed

  var CSS = [
    ':host { all: initial; position: fixed; right: 18px; bottom: 14px; z-index: 30; width: min(330px, 34vw); pointer-events: none; }',
    '[hidden] { display: none !important; }',
    '.wrap { position: relative; width: 100%; }',
    '.stage { position: relative; width: 100%; }',
    '.rig svg { display: block; width: 100%; height: auto; overflow: visible; filter: drop-shadow(0 6px 14px rgba(0, 0, 0, .18)); }',
    '.board { position: absolute; bottom: 5%; width: 21%; aspect-ratio: 1 / 1.02; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;',
    '  border-radius: 12px; background: var(--surface2, #fff); border: 2px solid var(--bd, #888); box-shadow: 0 6px 16px rgba(0, 0, 0, .22); font-family: inherit; color: var(--tx, #222); }',
    '.board b { font: 700 clamp(8px, 2.6vw, 10px)/1 system-ui, sans-serif; letter-spacing: .1em; color: #fff; background: var(--bd, #888); border-radius: 6px; padding: 3px 7px; }',
    '.board i { font: 800 clamp(18px, 6.4vw, 28px)/1.05 system-ui, sans-serif; font-style: normal; font-variant-numeric: tabular-nums; }',
    '.board::after { content: ""; position: absolute; left: 50%; bottom: -9px; width: 6px; height: 9px; margin-left: -3px; background: var(--bd, #888); border-radius: 0 0 3px 3px; opacity: .7; }',
    '.pass { left: 0; --bd: var(--pass, #34b27b); }',
    '.fail { right: 0; --bd: var(--fail, #e5534b); }',
    '.n.pop { animation: carrie-num .45s cubic-bezier(.3, 1.6, .5, 1); }',
    '.x { position: absolute; top: -4px; right: -2px; width: 22px; height: 22px; border: 0; border-radius: 50%; background: rgba(40, 30, 55, .55); color: #fff; font: 700 14px/22px system-ui, sans-serif;',
    '  cursor: pointer; pointer-events: auto; opacity: .45; padding: 0; }',
    '.x:hover, .x:focus-visible { opacity: 1; }',
    '.wrap.intro .stage { animation: carrie-in .95s cubic-bezier(.2, .9, .3, 1) both; transform-origin: 50% 96%; }',
    '.wrap.intro .board { animation: carrie-pop .5s .6s cubic-bezier(.3, 1.6, .5, 1) both; }',
    '@keyframes carrie-in { 0% { transform: translateX(125%) scale(.92, 1.08); } 55% { transform: translateX(-3%) scale(1.05, .93); } 75% { transform: translateX(0) scale(.97, 1.05); } 100% { transform: none; } }',
    '@keyframes carrie-pop { from { transform: scale(0); opacity: 0; } to { transform: none; opacity: 1; } }',
    '@keyframes carrie-num { from { transform: scale(1.6); } to { transform: none; } }',
    '@media (max-width: 760px) { :host { display: none; } }',
    '@media (prefers-reduced-motion: reduce) { .wrap.intro .stage, .wrap.intro .board, .n.pop { animation: none; } }'
  ].join('\n');

  function create(options) {
    options = options || {};
    var doc = options.document || document;
    var base = options.base || '/static/unicorn';
    var host = doc.createElement('div');
    host.id = 'carrie-root';
    var shadow = host.attachShadow({ mode: 'open' });
    shadow.innerHTML = '<style>' + CSS + '</style>' +
      '<div class="wrap" role="img" aria-label="Carrie the unicorn scorekeeper" hidden>' +
      '<div class="stage"><div class="rig"></div></div>' +
      '<div class="board pass"><b>PASS</b><i class="n">0</i></div><div class="board fail"><b>FAIL</b><i class="n">0</i></div>' +
      '<button class="x" type="button" aria-label="Hide Carrie" title="Hide Carrie (turn her back on in Run settings)">×</button></div>';
    (options.parent || doc.body).appendChild(host);
    var wrap = shadow.querySelector('.wrap'), stage = shadow.querySelector('.stage'), rig = shadow.querySelector('.rig');
    var passN = shadow.querySelector('.pass .n'), failN = shadow.querySelector('.fail .n');
    shadow.querySelector('.x').addEventListener('click', function () { if (options.onClose) options.onClose(); });

    var parts = null, building = null, destroyed = false;
    var subject = null, last = null, visible = false, pending = null;

    function build() {
      if (building) return building;
      building = fetch(base + '/svg/unicorn-front-sitting.svg').then(function (r) {
        if (!r.ok) throw new Error('Carrie: the rig did not load (' + r.status + ')');
        return r.text();
      }).then(function (text) {
        if (destroyed) return null;
        rig.innerHTML = text.replace(/^<\?xml[^>]*\?>\s*/, '');
        var svg = rig.querySelector('svg');
        svg.removeAttribute('width'); svg.removeAttribute('height');
        var idle = G.UnicornIdle.attach(svg, { autoStart: false });
        var fx = G.UnicornFx.attach(stage, { svg: svg });
        var ctl = G.UnicornMood.create(svg, { idle: idle, fx: fx });
        parts = { svg: svg, idle: idle, fx: fx, ctl: ctl };
        return parts;
      });
      return building;
    }

    function setBoards(snap, animate) {
      var changed = [[passN, snap.passed], [failN, snap.failed]];
      changed.forEach(function (c) {
        var text = String(c[1]);
        if (c[0].textContent === text) return;
        c[0].textContent = text;
        if (animate) { c[0].classList.remove('pop'); void c[0].offsetWidth; c[0].classList.add('pop'); }
      });
      wrap.setAttribute('aria-label', 'Carrie the unicorn scorekeeper: ' + snap.passed + ' passed, ' + snap.failed + ' failed' + (snap.done ? ', run finished' : ''));
    }

    /** First sight of a run: from its start (running, nothing finished) she is excited; otherwise she catches up silently. */
    function begin(snap) {
      var c = parts.ctl, finished = snap.passed + snap.failed;
      if (!snap.done && finished === 0) { c.onRunStart({ totalTests: snap.total }); }
      else {
        c.restore(snap);
        if (snap.done) parts.idle.stop(); else parts.idle.start();
      }
      setBoards(snap, false);
    }

    function follow(snap) {
      var c = parts.ctl, dp = snap.passed - last.passed, df = snap.failed - last.failed;
      if (dp < 0 || df < 0 || (last.done && !snap.done) || dp + df > MAX_REACTIONS) {       // not a simple step forward: catch up silently
        c.restore(snap);
        if (snap.done) parts.idle.stop(); else parts.idle.start();
        setBoards(snap, true);
        return;
      }
      var i;
      for (i = 0; i < dp; i += 1) c.onTestResult({ status: 'pass' });
      for (i = 0; i < df; i += 1) c.onTestResult({ status: 'fail' });
      if (snap.done && !last.done) c.onRunComplete({ passed: snap.passed, failed: snap.failed, total: snap.total });
      setBoards(snap, true);
    }

    function apply(snap) {
      if (!parts || destroyed) return;
      if (snap.id !== subject) { subject = snap.id; begin(snap); }
      else follow(snap);
      last = { passed: snap.passed, failed: snap.failed, done: snap.done };
    }

    function reveal() {
      if (visible) return;
      visible = true;
      wrap.hidden = false;
      wrap.classList.remove('intro'); void wrap.offsetWidth; wrap.classList.add('intro');      // her entrance: slides in with a squash and stretch, the boards pop up
    }

    return {
      host: host,
      /** The numbers as they stand now: {id, passed, failed, total, running, done}. Safe to call as often as you like. */
      update: function (snap) {
        if (destroyed) return Promise.resolve();
        pending = snap;
        return build().then(function () {
          if (!parts || destroyed || !pending) return;
          var s = pending; pending = null;
          reveal();
          apply(s);
        });
      },
      /** Out of sight (another page): everything stops, nothing is left running. */
      hide: function () {
        pending = null;
        if (!visible) return;
        visible = false; wrap.hidden = true;
        subject = null; last = null;                        // coming back means a fresh look at the run
        if (parts) { parts.idle.stop(); parts.fx.clear(); parts.ctl.reset(); }
      },
      state: function () {
        return { built: !!parts, visible: visible, subject: subject, mood: parts ? parts.ctl.getMood() : null, passed: passN.textContent, failed: failN.textContent,
                 idle: parts ? parts.idle.stats() : null, fx: parts ? parts.fx.stats() : null };
      },
      parts: function () { return parts; },
      destroy: function () {
        destroyed = true;
        if (parts) { parts.ctl.destroy(); parts.idle.destroy(); parts.fx.destroy(); }
        if (host.parentNode) host.parentNode.removeChild(host);
      }
    };
  }

  return { create: create };
}));
