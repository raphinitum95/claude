/* Idle animation for the unicorn rig (svg/unicorn-front-sitting.svg). Phase 2, round 1: breathing, blinking, tail swish, ear flick, mane sway.
 *
 * Why it is built this way (the QA app runs several test workers on the same machine, so she has to stay cheap):
 *  - ONE loop for everything, capped at 30 fps (a requestAnimationFrame that skips frames), not a CSS animation per part.
 *  - The motion is a pure function of a virtual clock (`createEngine`), with the randomness injected: no DOM, so the timing is testable.
 *  - Only a part whose transform really changed is written to (`stats().writes` counts them).
 *  - The loop stops when the tab is hidden, when she scrolls out of view, under prefers-reduced-motion, and `settle()` eases her to rest and stops it.
 *  - It only ever sets an inline `transform` on parts that have no mood pose of their own (ears and eyelids only when the mood leaves them alone),
 *    and it clears that inline transform when it stops, so the CSS mood states of the rig keep working.
 *
 * Classic script (no modules) so it also works from file:// (preview.html). Use:
 *     const idle = UnicornIdle.attach(document.querySelector('svg'));   // starts at once
 *     idle.settle();  idle.start();  idle.setIntensity(0.5);  idle.stop();  idle.destroy();
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.UnicornIdle = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var TAU = Math.PI * 2;
  var BLINK_MS = 220;          // close 70, hold 40, open 110
  var DOUBLE_BLINK_GAP_MS = 330;
  var EAR_FLICK_MS = 320;
  var REACTION_MS = { maneFlick: 800, flinch: 380, hop: 840 };   // short one-shot reactions added on top of the idle motion
  var LOCKS = [1, 2, 3, 4, 5, 6];
  // sway of each mane lock: [amplitude in degrees, period in ms, phase]; different periods so the locks never move in step
  var LOCK_SWAY = [[2.2, 5200, 0.0], [1.6, 4300, 1.7], [1.4, 6100, 3.1], [1.4, 5700, 4.4], [1.7, 4700, 2.3], [2.4, 5400, 5.5]];

  function easeInOut(x) { x = x < 0 ? 0 : x > 1 ? 1 : x; return x * x * (3 - 2 * x); }

  /** One blink: 0 = lids open, 1 = shut. `u` is the time since it began in ms. */
  function blinkShape(u) {
    if (u <= 0 || u >= BLINK_MS) return 0;
    if (u < 70) return easeInOut(u / 70);
    if (u < 110) return 1;
    return 1 - easeInOut((u - 110) / 110);
  }

  /**
   * The motion itself. `step(dtMs)` advances a virtual clock (it only runs while the loop runs, so a hidden tab never makes her jump) and returns the pose:
   *   head {ty, rot}, body {sx, sy}, neck {ty}, heart {ty, s}, tail {rot}, front {rot}, locks [6 x rot], ear {side: -1 left | 0 | 1 right, rot}, lid 0..1.
   * Units: px and degrees about the pivots the SVG's CSS already sets.
   */
  function createEngine(options) {
    options = options || {};
    var random = options.random || Math.random;
    var intensity = options.intensity == null ? 1 : options.intensity;
    var t = 0;
    var calm = 1;                // 1 = fully alive, 0 = at rest (settle() ramps it down)
    var calmFrom = 1, calmMs = 0, calmElapsed = 0, settling = false;
    var blink = null, earFlick = null, reactions = [];
    var nextBlink = between(2200, 4000), nextEar = between(5000, 9000);
    var blinks = 0;

    function between(a, b) { return a + (b - a) * random(); }

    function step(dtMs) {
      t += dtMs;
      if (settling) {
        calmElapsed += dtMs;
        calm = calmMs <= 0 ? 0 : calmFrom * (1 - easeInOut(calmElapsed / calmMs));
        if (calmElapsed >= calmMs) calm = 0;
      }
      var amp = calm * intensity;

      // blink: every 3 to 5 s (random), one time in six as a double blink; none are started while settling
      if (!blink && !settling && t >= nextBlink) {
        blink = { at: t, dbl: random() < 1 / 6 };
        blinks += 1;
      }
      var lid = 0;
      if (blink) {
        var u = t - blink.at;
        lid = Math.max(blinkShape(u), blink.dbl ? blinkShape(u - DOUBLE_BLINK_GAP_MS) : 0);
        if (u >= (blink.dbl ? DOUBLE_BLINK_GAP_MS : 0) + BLINK_MS) { blink = null; nextBlink = t + between(3000, 5000); }
      }

      // ear flick: now and then one ear twitches outward and back
      if (!earFlick && !settling && t >= nextEar) earFlick = { at: t, side: random() < 0.5 ? -1 : 1 };
      var ear = { side: 0, rot: 0 };
      if (earFlick) {
        var e = (t - earFlick.at) / EAR_FLICK_MS;
        if (e >= 1) { earFlick = null; nextEar = t + between(6000, 12000); }
        else ear = { side: earFlick.side, rot: earFlick.side * 11 * Math.sin(Math.PI * e) * (1 - 0.3 * e) * intensity };
      }

      // one-shot reactions (a result came in): mane flick, flinch, a celebration hop of three shrinking bounces
      var extra = { headTy: 0, headRot: 0, bodySy: 0, hop: 0, locks: [0, 0, 0, 0, 0, 0] };
      for (var r = reactions.length - 1; r >= 0; r -= 1) {
        var ru = t - reactions[r].at, rname = reactions[r].name, rdur = REACTION_MS[rname];
        if (ru >= rdur) { reactions.splice(r, 1); continue; }
        if (rname === 'maneFlick') {
          for (var li = 0; li < 6; li += 1) extra.locks[li] += 5.5 * Math.exp(-ru / 240) * Math.sin(ru / 60 + li * 0.9) * intensity;
        } else if (rname === 'flinch') {
          var env = Math.sin(Math.PI * ru / rdur);
          extra.headTy += 3.2 * env * intensity; extra.headRot -= 2 * env * intensity; extra.bodySy -= 0.008 * env * intensity;
        } else if (rname === 'hop') {
          var k = Math.floor(ru / 280);
          extra.hop = Math.max(extra.hop, 14 * Math.pow(0.55, k) * Math.abs(Math.sin(Math.PI * (ru % 280) / 280)) * intensity);
        }
      }

      var inhale = (Math.sin((t / 3600) * TAU) + 1) / 2;           // breathing: one breath every 3.6 s
      var locks = [];
      for (var i = 0; i < LOCK_SWAY.length; i += 1) {
        locks.push(extra.locks[i] + amp * LOCK_SWAY[i][0] * Math.sin((t / LOCK_SWAY[i][1]) * TAU + LOCK_SWAY[i][2]));
      }
      return {
        head: { ty: -1.4 * inhale * amp + extra.headTy, rot: 0.5 * amp * Math.sin((t / 7000) * TAU) + extra.headRot },
        body: { sx: 1 + 0.004 * inhale * amp, sy: 1 + 0.010 * inhale * amp + extra.bodySy },
        hop: extra.hop,
        neck: { ty: -1.0 * inhale * amp },
        heart: { ty: -0.8 * inhale * amp, s: 1 + 0.03 * inhale * amp },
        tail: { rot: amp * (3.2 * Math.sin((t / 5200) * TAU) + 1.2 * Math.sin((t / 2300) * TAU + 1)) },
        front: { rot: amp * 0.8 * Math.sin((t / 4800) * TAU + 0.5) },
        locks: locks,
        ear: ear,
        lid: lid
      };
    }

    return {
      step: step,
      setIntensity: function (x) { intensity = Math.max(0, x); },
      /** Ease to rest over `ms`. A blink or ear flick already under way finishes first. */
      settle: function (ms) { settling = true; calmFrom = calm; calmMs = ms == null ? 700 : ms; calmElapsed = 0; },
      /** Come back to life (also cancels a settle). */
      wake: function () { settling = false; calm = 1; },
      /** Blink on the next frame (used by the preview button; a result could use it for a reaction). */
      blinkNow: function () { if (!blink) nextBlink = t; },
      atRest: function () { return settling && calm === 0 && !blink && !earFlick && reactions.length === 0; },
      /** Start a one-shot reaction ('maneFlick', 'flinch', 'hop'). Ignored while settling. Returns whether it started. */
      trigger: function (name) { if (settling || !REACTION_MS[name]) return false; reactions.push({ name: name, at: t }); return true; },
      blinkCount: function () { return blinks; }
    };
  }

  function fmt(x) { return (Math.round(x * 100) / 100).toString(); }
  function r3(x) { return Math.round(x * 1000) / 1000; }

  /** Connect an engine to the rig inside `svg` (the <svg> element, or any element that contains #unicorn). */
  function attach(svg, options) {
    options = options || {};
    var doc = svg.ownerDocument, win = doc.defaultView;
    var rig = svg.querySelector('#unicorn');
    var fps = options.fps || 30, frameMs = 1000 / fps;
    var engine = createEngine({ random: options.random, intensity: options.intensity });
    var parts = {};
    ['head-rig', 'neck', 'body', 'chest-heart', 'tail', 'front-leg-left', 'front-leg-right', 'mane-back', 'ear-left', 'ear-right', 'eyelid-left', 'eyelid-right']
      .concat(LOCKS.map(function (n) { return 'mane-lock-' + n; }))
      .forEach(function (id) { parts[id] = svg.querySelector('#' + id); });
    var applied = {};
    var stats = { frames: 0, writes: 0 };
    var wanted = options.autoStart !== false;
    var hidden = !!doc.hidden, offscreen = false;
    var reduceQuery = win.matchMedia ? win.matchMedia('(prefers-reduced-motion: reduce)') : null;
    var reduced = !!(reduceQuery && reduceQuery.matches);
    var raf = 0, last = null, finishedSettle = false;

    function write(id, value) {
      var el = parts[id];
      if (!el || applied[id] === value) return;
      applied[id] = value;
      el.style.transform = value;
      stats.writes += 1;
    }
    function clearAll() { Object.keys(parts).forEach(function (id) { if (parts[id]) { parts[id].style.transform = ''; } }); applied = {}; }
    function state(name) { return rig ? rig.getAttribute('data-' + name) : null; }

    function applyPose(p) {
      var up = -p.hop;                                  // a hop lifts everything but the shadow
      write('head-rig', 'translateY(' + fmt(p.head.ty + up) + 'px) rotate(' + fmt(p.head.rot) + 'deg)');
      write('neck', 'translateY(' + fmt(p.neck.ty + up) + 'px)');
      write('body', 'translateY(' + fmt(up) + 'px) scale(' + r3(p.body.sx) + ',' + r3(p.body.sy) + ')');
      write('chest-heart', 'translateY(' + fmt(p.heart.ty + up) + 'px) scale(' + r3(p.heart.s) + ')');
      write('tail', 'translateY(' + fmt(up) + 'px) rotate(' + fmt(p.tail.rot) + 'deg)');
      write('front-leg-left', 'translateY(' + fmt(up) + 'px) rotate(' + fmt(p.front.rot) + 'deg)');
      write('front-leg-right', 'translateY(' + fmt(up) + 'px) rotate(' + fmt(-p.front.rot) + 'deg)');
      write('mane-back', p.hop > 0.01 ? 'translateY(' + fmt(up) + 'px)' : '');
      for (var i = 0; i < LOCKS.length; i += 1) write('mane-lock-' + LOCKS[i], 'rotate(' + fmt(p.locks[i]) + 'deg)');
      // ears and eyelids already have a CSS pose in the sad / angry / scared / droop moods: only touch them when the mood leaves them alone
      var earsFree = (state('ears') || 'neutral') === 'neutral';
      write('ear-left', earsFree && p.ear.side === -1 ? 'rotate(' + fmt(p.ear.rot) + 'deg)' : '');
      write('ear-right', earsFree && p.ear.side === 1 ? 'rotate(' + fmt(p.ear.rot) + 'deg)' : '');
      var eyes = state('eyes') || 'open';
      var canBlink = eyes === 'open' || eyes === 'wide' || eyes === 'scared';
      var lid = canBlink && p.lid > 0.005 ? 'scaleY(' + r3(p.lid) + ')' : '';
      write('eyelid-left', lid);
      write('eyelid-right', lid);
    }

    function frame(now) {
      raf = 0;
      if (!running()) return;
      if (last === null) last = now;
      var dt = now - last;
      if (dt < frameMs - 3) { raf = win.requestAnimationFrame(frame); return; }
      last = now;
      stats.frames += 1;
      applyPose(engine.step(Math.min(dt, 100)));       // a long gap (a stalled tab) is never played back as a jump
      if (engine.atRest()) { finishedSettle = true; wanted = false; clearAll(); return; }
      raf = win.requestAnimationFrame(frame);
    }
    function running() { return wanted && !hidden && !offscreen && !reduced; }
    function sync() {
      if (running()) { if (!raf) { last = null; raf = win.requestAnimationFrame(frame); } }
      else if (raf) { win.cancelAnimationFrame(raf); raf = 0; }
    }

    function onVisibility() { hidden = !!doc.hidden; sync(); }
    function onReduce() { reduced = !!reduceQuery.matches; if (reduced) { if (raf) { win.cancelAnimationFrame(raf); raf = 0; } clearAll(); } sync(); }
    doc.addEventListener('visibilitychange', onVisibility);
    if (reduceQuery && reduceQuery.addEventListener) reduceQuery.addEventListener('change', onReduce);
    var observer = null;
    if (win.IntersectionObserver) {
      observer = new win.IntersectionObserver(function (entries) {
        offscreen = !entries[entries.length - 1].isIntersecting;
        sync();
      });
      observer.observe(svg);
    }
    sync();

    return {
      /** Start (or restart) the idle loop at full life. */
      start: function () { engine.wake(); wanted = true; finishedSettle = false; sync(); },
      /** Stop at once and put every part back to its CSS pose. */
      stop: function () { wanted = false; sync(); clearAll(); },
      /** Ease to rest, then stop by itself (call this when the run ends). */
      settle: function (ms) { if (reduced) { clearAll(); return; } engine.settle(ms); wanted = true; sync(); },
      setIntensity: function (x) { engine.setIntensity(x); },
      blinkNow: function () { engine.blinkNow(); },
      /** A one-shot reaction on top of the idle motion ('maneFlick', 'flinch', 'hop'); skipped while the loop is not running. */
      react: function (name) { return running() ? engine.trigger(name) : false; },
      isRunning: function () { return !!raf; },
      settled: function () { return finishedSettle; },
      stats: function () { return { frames: stats.frames, writes: stats.writes, running: !!raf, reducedMotion: reduced, hidden: hidden, offscreen: offscreen }; },
      destroy: function () {
        wanted = false; sync(); clearAll();
        doc.removeEventListener('visibilitychange', onVisibility);
        if (reduceQuery && reduceQuery.removeEventListener) reduceQuery.removeEventListener('change', onReduce);
        if (observer) observer.disconnect();
      }
    };
  }

  return { createEngine: createEngine, attach: attach, blinkShape: blinkShape };
}));
