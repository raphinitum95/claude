/* Glitter and rain for the unicorn: ONE canvas laid over the rig, ONE loop. Phase 2, round 3.
 *
 *   const fx = UnicornFx.attach(stageElement, { svg });   // stageElement = the element that holds the <svg>
 *   fx.sparkle();         // a few tiny sparkles by the horn (a test passed)
 *   fx.celebrate();       // glitter fountains from the horn and both sides (a great run)
 *   fx.rain(true);        // rain falls from the cloud (the sad mood); rain(false) lets the last drops finish
 *   fx.burst({ x, y, count });   // a glitter burst anywhere (x, y in the rig's 600 x 600 units)
 *
 * Cheap on purpose (the QA app runs several test workers on the same machine):
 *  - the loop only runs WHILE there are particles (or rain): at rest nothing runs, the canvas is cleared, no timer is left;
 *  - at most `max` particles at any moment (default 90), whatever is asked for; no shadowBlur, no filters, a capped devicePixelRatio;
 *  - capped at 30 fps, paused while the tab is hidden or she is scrolled out of view, and a no-op under prefers-reduced-motion;
 *  - rain stops by itself after `rainMaxMs` unless it is renewed (a new failure renews it).
 * The motion is a pure engine (`createEngine`, injected randomness, no DOM) so it can be tested exactly; `attach` only draws it.
 * Classic script (works from file://). Coordinates are the rig's viewBox units (0..600).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.UnicornFx = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var VB = 600;
  var COLORS = ['#FFF3B8', '#FCE09E', '#FDB1D3', '#CB9AE5', '#86D4D5', '#FFFFFF'];   // the rig's palette: gold, pink, lilac, teal, white
  var HORN = { x: 266, y: 34 };
  // where rain may fall: beside her head on both sides, and a short fall onto the top of her head. [x0, x1, y it ends at, weight]
  var RAIN_LANES = [[96, 166, 330, 3], [374, 444, 330, 3], [214, 326, 128, 2]];
  var RAIN_FROM_Y = 52, RAIN_PER_SECOND = 40, RAIN_LIVE_MAX = 34, RAIN_SPEED = 330;
  var GRAVITY = 240;          // units per second squared
  var CELEBRATE_PARTS = [     // [x, y, count, spreadStart, spreadEnd (degrees, 0 = right, -90 = up), speed, delay ms]
    [HORN.x, HORN.y, 22, -150, -30, 190, 0], [120, 170, 14, -170, -80, 170, 140], [420, 170, 14, -100, -10, 170, 140], [HORN.x, HORN.y, 16, -140, -40, 150, 520]
  ];

  /** The motion: no DOM, randomness injected. `step(dtMs)` returns the live particles. */
  function createEngine(options) {
    options = options || {};
    var random = options.random || Math.random;
    var max = options.max || 90;
    var list = [], pending = [], rainOn = false, rainAcc = 0, t = 0;

    function between(a, b) { return a + (b - a) * random(); }
    function room() { return max - list.length; }

    function spawnGlitter(spec) {
      var n = Math.min(spec.count == null ? 12 : spec.count, room());
      for (var i = 0; i < n; i += 1) {
        var a = between(spec.from == null ? -180 : spec.from, spec.to == null ? 0 : spec.to) * Math.PI / 180;
        var sp = (spec.speed || 120) * between(0.55, 1.1);
        list.push({
          kind: 'glitter', x: spec.x + between(-4, 4), y: spec.y + between(-3, 3), vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
          age: 0, life: (spec.life || 1500) * between(0.7, 1.15), size: between(2.4, 6.2) * (spec.size || 1), color: COLORS[Math.floor(random() * COLORS.length)],
          phase: random() * 6.28, rot: random() * 1.57, spin: between(-2, 2), gravity: spec.gravity == null ? GRAVITY : spec.gravity
        });
      }
    }
    function spawnRain() {
      var live = 0, i;
      for (i = 0; i < list.length; i += 1) if (list[i].kind === 'rain') live += 1;
      if (live >= RAIN_LIVE_MAX || room() <= 0) return;
      var total = 0;
      for (i = 0; i < RAIN_LANES.length; i += 1) total += RAIN_LANES[i][3];
      var pick = random() * total, lane = RAIN_LANES[0];
      for (i = 0; i < RAIN_LANES.length; i += 1) { pick -= RAIN_LANES[i][3]; if (pick <= 0) { lane = RAIN_LANES[i]; break; } }
      list.push({ kind: 'rain', x: between(lane[0], lane[1]), y: RAIN_FROM_Y + between(0, 8), vx: -14, vy: RAIN_SPEED * between(0.85, 1.15), yEnd: lane[2], age: 0, life: 9999 });
    }

    function step(dtMs) {
      t += dtMs;
      var k = dtMs / 1000;
      for (var p = pending.length - 1; p >= 0; p -= 1) {
        if (t >= pending[p].at) { spawnGlitter(pending[p].spec); pending.splice(p, 1); }
      }
      if (rainOn) {
        rainAcc += RAIN_PER_SECOND * k;
        while (rainAcc >= 1) { rainAcc -= 1; spawnRain(); }
      }
      for (var i = list.length - 1; i >= 0; i -= 1) {
        var q = list[i];
        q.age += dtMs;
        if (q.kind === 'rain') {
          q.x += q.vx * k; q.y += q.vy * k;
          if (q.y >= q.yEnd) { list.splice(i, 1); continue; }
          q.alpha = 0.9 * Math.min(1, (q.yEnd - q.y) / 36, q.age / 80);
        } else {
          if (q.age >= q.life) { list.splice(i, 1); continue; }
          q.vx *= 1 - Math.min(1, 1.6 * k); q.vy = q.vy * (1 - Math.min(1, 1.6 * k)) + q.gravity * k;
          q.x += q.vx * k; q.y += q.vy * k; q.rot += q.spin * k;
          var life = q.age / q.life;
          q.alpha = Math.min(1, (1 - life) * 2.2) * (0.65 + 0.35 * Math.sin(q.age / 70 + q.phase));
        }
      }
      return list;
    }

    return {
      step: step,
      /** A burst of glitter: {x, y, count, from, to (degrees), speed, life (ms), size, gravity, delay (ms)}. Never more than `max` particles are alive. */
      glitter: function (spec) { if (spec.delay) pending.push({ at: t + spec.delay, spec: spec }); else spawnGlitter(spec); },
      sparkle: function () { spawnGlitter({ x: HORN.x + between(-26, 26), y: HORN.y + between(-6, 22), count: 3, from: -130, to: -50, speed: 26, life: 900, size: 0.8, gravity: -10 }); },
      celebrate: function () {
        CELEBRATE_PARTS.forEach(function (c) { pending.push({ at: t + c[6], spec: { x: c[0], y: c[1], count: c[2], from: c[3], to: c[4], speed: c[5], life: 1700 } }); });
      },
      rain: function (on) { rainOn = !!on; if (!rainOn) rainAcc = 0; },
      isRaining: function () { return rainOn; },
      live: function () { return list.length; },
      /** Anything left to draw or to spawn? The loop runs only while this is true. */
      busy: function () { return list.length > 0 || pending.length > 0 || rainOn; },
      clear: function () { list.length = 0; pending.length = 0; rainOn = false; rainAcc = 0; },
      particles: function () { return list; }
    };
  }

  /** Lay one canvas over the rig inside `container` and draw the engine on it, only while there is something to draw. */
  function attach(container, options) {
    options = options || {};
    var doc = container.ownerDocument, win = doc.defaultView;
    var svg = options.svg || container.querySelector('svg');
    var fps = options.fps || 30, frameMs = 1000 / fps;
    var engine = createEngine({ random: options.random, max: options.max });
    var rainMaxMs = options.rainMaxMs == null ? 30000 : options.rainMaxMs;
    var reduceQuery = win.matchMedia ? win.matchMedia('(prefers-reduced-motion: reduce)') : null;
    var reduced = !!(reduceQuery && reduceQuery.matches);
    var hidden = !!doc.hidden, offscreen = false;
    var stats = { frames: 0, drawn: 0 };
    var raf = 0, last = null, rainTimer = null, rainLeft = 0;

    if (win.getComputedStyle(container).position === 'static') container.style.position = 'relative';
    var canvas = doc.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.cssText = 'position:absolute;pointer-events:none;left:0;top:0;';
    container.appendChild(canvas);
    var ctx = canvas.getContext('2d');
    var geo = { scale: 1, margin: 0, dpr: 1 };

    // the canvas covers the svg plus a margin all round, so glitter can float outside her silhouette
    function resize() {
      var r = svg.getBoundingClientRect(), c = container.getBoundingClientRect();
      var margin = Math.round(r.width * 0.2);
      var dpr = Math.min(win.devicePixelRatio || 1, 2);
      var w = Math.max(1, Math.round(r.width + 2 * margin)), h = Math.max(1, Math.round(r.height + 2 * margin));
      canvas.style.left = (r.left - c.left - margin) + 'px'; canvas.style.top = (r.top - c.top - margin) + 'px';
      canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      geo = { scale: r.width / VB, margin: margin, dpr: dpr };
    }
    resize();

    function draw(list) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      var s = geo.scale * geo.dpr, m = geo.margin * geo.dpr, drops = [], i, q;
      for (i = 0; i < list.length; i += 1) {
        q = list[i];
        if (q.kind === 'rain') { drops.push(q); continue; }
        var r = q.size * (0.7 + 0.3 * Math.sin(q.age / 90 + q.phase)) * s * 1.6;
        ctx.globalAlpha = Math.max(0, q.alpha);
        ctx.fillStyle = q.color;
        var cx = m + q.x * s, cy = m + q.y * s, c = Math.cos(q.rot), sn = Math.sin(q.rot);
        ctx.beginPath();                                     // a four-point star (two thin diamonds): cheap to fill
        ctx.moveTo(cx + c * r, cy + sn * r); ctx.lineTo(cx - sn * r * 0.28, cy + c * r * 0.28); ctx.lineTo(cx - c * r, cy - sn * r);
        ctx.lineTo(cx + sn * r * 0.28, cy - c * r * 0.28); ctx.closePath();
        ctx.moveTo(cx - sn * r, cy + c * r); ctx.lineTo(cx - c * r * 0.28, cy - sn * r * 0.28); ctx.lineTo(cx + sn * r, cy - c * r);
        ctx.lineTo(cx + c * r * 0.28, cy + sn * r * 0.28); ctx.closePath();
        ctx.fill();
      }
      if (drops.length) {
        ctx.lineWidth = Math.max(1.5, 2.6 * s); ctx.lineCap = 'round'; ctx.strokeStyle = '#6FB3E8';
        for (i = 0; i < drops.length; i += 1) {              // each drop is a short streak; the alpha is per drop, so strokes are not batched
          q = drops[i]; ctx.globalAlpha = Math.max(0, q.alpha);
          ctx.beginPath(); ctx.moveTo(m + q.x * s, m + q.y * s); ctx.lineTo(m + (q.x - q.vx * 0.05) * s, m + (q.y - q.vy * 0.05) * s); ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      stats.drawn += list.length;
    }

    function running() { return engine.busy() && !hidden && !offscreen && !reduced; }
    function frame(now) {
      raf = 0;
      if (!running()) return;
      if (last === null) last = now;
      var dt = now - last;
      if (dt < frameMs - 3) { raf = win.requestAnimationFrame(frame); return; }
      last = now;
      stats.frames += 1;
      draw(engine.step(Math.min(dt, 100)));
      if (engine.busy()) raf = win.requestAnimationFrame(frame);
      else { ctx.clearRect(0, 0, canvas.width, canvas.height); last = null; }     // nothing left: the canvas is empty and nothing runs
    }
    function sync() {
      if (running()) { if (!raf) { last = null; raf = win.requestAnimationFrame(frame); } }
      else if (raf) { win.cancelAnimationFrame(raf); raf = 0; }
    }
    function onVisibility() { hidden = !!doc.hidden; sync(); }
    function onReduce() { reduced = !!reduceQuery.matches; if (reduced) api.clear(); sync(); }
    doc.addEventListener('visibilitychange', onVisibility);
    if (reduceQuery && reduceQuery.addEventListener) reduceQuery.addEventListener('change', onReduce);
    var observer = null, resizer = null;
    if (win.IntersectionObserver) {
      observer = new win.IntersectionObserver(function (entries) { offscreen = !entries[entries.length - 1].isIntersecting; sync(); });
      observer.observe(svg);
    }
    if (win.ResizeObserver) { resizer = new win.ResizeObserver(resize); resizer.observe(svg); } else win.addEventListener('resize', resize);

    function stopRainTimer() { if (rainTimer) { win.clearTimeout(rainTimer); rainTimer = null; } }
    var api = {
      canvas: canvas,
      /** A glitter burst: {x, y, count, from, to, speed, life, size}. Anything not given has a sensible default. */
      burst: function (spec) { if (reduced) return; engine.glitter(merge({ x: HORN.x, y: HORN.y, count: 24, from: -180, to: 0, speed: 160 }, spec)); sync(); },
      sparkle: function () { if (reduced) return; engine.sparkle(); sync(); },
      celebrate: function () { if (reduced) return; engine.celebrate(); sync(); },
      /** Rain falls while on (renewing it restarts its time limit); off lets the drops in the air finish. */
      rain: function (on) {
        if (reduced) return;
        stopRainTimer();
        engine.rain(on);
        if (on && rainMaxMs > 0) rainTimer = win.setTimeout(function () { rainTimer = null; engine.rain(false); sync(); }, rainMaxMs);
        sync();
      },
      isRaining: function () { return engine.isRaining(); },
      clear: function () { stopRainTimer(); engine.clear(); ctx.clearRect(0, 0, canvas.width, canvas.height); sync(); },
      stats: function () { return { frames: stats.frames, drawn: stats.drawn, live: engine.live(), running: !!raf, raining: engine.isRaining(), reducedMotion: reduced, hidden: hidden, offscreen: offscreen, width: canvas.width, height: canvas.height }; },
      destroy: function () {
        stopRainTimer(); engine.clear(); sync();
        doc.removeEventListener('visibilitychange', onVisibility);
        if (reduceQuery && reduceQuery.removeEventListener) reduceQuery.removeEventListener('change', onReduce);
        if (observer) observer.disconnect();
        if (resizer) resizer.disconnect(); else win.removeEventListener('resize', resize);
        if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
      }
    };
    return api;
  }

  function merge(base, extra) { var out = {}, k; for (k in base) out[k] = base[k]; if (extra) for (k in extra) out[k] = extra[k]; return out; }

  return { createEngine: createEngine, attach: attach, COLORS: COLORS };
}));
