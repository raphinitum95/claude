/* Mood state machine for the unicorn rig. Phase 2, round 2: it turns test results into moods and small reactions.
 *
 *   const unicorn = UnicornMood.create(svg, { idle: UnicornIdle.attach(svg), config: { celebrate: 0.95, happy: 0.60 } });
 *   unicorn.onRunStart({ totalTests: 40 });         // totalTests is optional: a run of unknown length works on the running pass rate
 *   unicorn.onTestResult({ status: 'pass', name: 'Login' });
 *   unicorn.onRunComplete({ passed: 38, failed: 2, total: 40 });
 *   unicorn.setMood('angry');  unicorn.setMood(null);   // manual override, and back to automatic
 *
 * The mood is a PURE function of the running totals (`moodFor`), so it is easy to test and to change; this file knows nothing about the QA app.
 * A mood is a set of `data-*` attributes on #unicorn (see docs/rig-spec.md); the rig's own CSS poses her. Reactions (a sparkle, a flinch, a mane flick,
 * a celebration hop) are short, one-shot, and run on the idle loop (js/idle.js): this file adds no loop and no timer that keeps running at rest.
 * Classic script (works from file://). Defaults below are the brief's: 95 % celebrate, 60 % happy, below that sad.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.UnicornMood = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Mood -> the five rig attributes. The same table is in docs/rig-spec.md section 4 (a test keeps them equal). */
  var POSES = {
    neutral: { eyes: 'open', brows: 'neutral', mouth: 'neutral', ears: 'neutral', fx: 'none' },
    happy: { eyes: 'open', brows: 'up', mouth: 'smile', ears: 'neutral', fx: 'none' },
    excited: { eyes: 'wide', brows: 'up', mouth: 'open', ears: 'perk', fx: 'sparkle' },
    joyful: { eyes: 'closed', brows: 'up', mouth: 'open', ears: 'perk', fx: 'sparkle' },
    sad: { eyes: 'sad', brows: 'sad', mouth: 'frown', ears: 'droop', fx: 'rain' },
    scared: { eyes: 'scared', brows: 'scared', mouth: 'open', ears: 'flat', fx: 'sweat' },
    angry: { eyes: 'angry', brows: 'angry', mouth: 'frown', ears: 'back', fx: 'steam' }
  };

  var DEFAULTS = {
    celebrate: 0.95,        // final pass rate at or above this: joyful + a celebration
    happy: 0.60,            // at or above this: happy; below it: sad
    minResults: 3,          // fewer results than this and she stays neutral (no verdict from one or two tests)
    scaredStreak: 3,        // this many failures in a row mid-run: nervous (scared)
    startExcitedMs: 1500,   // excited for this long when a run starts
    passSparkleMs: 700,     // the small sparkle after a pass
    flinchMs: 380,          // ears go back for this long after a fail
    celebrateMs: 4500,      // how long the celebration lasts before she settles
    endSparkleMs: 1200,     // the small sparkle at a happy ending (60 to 95 %)
    restAfterMs: 2000,      // how long a happy ending lasts before she settles to rest
    sadRainMs: 5000         // how long it rains after a sad ending before the rain stops and she settles (the cloud stays)
  };

  function merge(base, extra) {
    var out = {}, k;
    for (k in base) out[k] = base[k];
    if (extra) for (k in extra) if (extra[k] !== undefined) out[k] = extra[k];
    return out;
  }

  /**
   * The mood for the running totals. totals = {passed, failed, failStreak, done}. Pure.
   *  - nothing yet, or fewer than `minResults` mid-run: neutral
   *  - mid-run: scared after `scaredStreak` failures in a row; else happy at or above the `happy` rate, sad below it
   *  - at the end (done): joyful at or above `celebrate`, happy at or above `happy`, sad below
   */
  function moodFor(totals, config) {
    var c = merge(DEFAULTS, config);
    var n = totals.passed + totals.failed;
    if (n === 0) return 'neutral';
    var atLeast = function (rate) { return totals.passed >= rate * n - 1e-9; };   // 19 of 20 is 95 %, whatever the float says
    if (totals.done) return atLeast(c.celebrate) ? 'joyful' : atLeast(c.happy) ? 'happy' : 'sad';
    if (n < c.minResults) return 'neutral';
    if ((totals.failStreak || 0) >= c.scaredStreak) return 'scared';
    return atLeast(c.happy) ? 'happy' : 'sad';
  }

  function create(target, options) {
    options = options || {};
    var rig = target.id === 'unicorn' ? target : target.querySelector('#unicorn');
    if (!rig) throw new Error('UnicornMood.create: no #unicorn in the element');
    var cfg = merge(DEFAULTS, options.config);
    var idle = options.idle || null;
    var fx = options.fx || null;                  // optional glitter / rain canvas (js/fx.js): sparkle(), celebrate(), rain(on)
    var onChange = options.onChange || null;
    var timers = options.timers || { set: function (f, ms) { return setTimeout(f, ms); }, clear: function (id) { clearTimeout(id); } };

    var totals, override = null, startBurst = false, flashes = [], restTimer = null, startTimer = null, rainOn = false, rainSuppressed = false;
    reset();

    function reset() {
      totals = { passed: 0, failed: 0, failStreak: 0, total: null, running: false, done: false };
    }
    function cancelTimers() {
      flashes.forEach(function (f) { timers.clear(f.timer); });
      flashes = [];
      if (restTimer) { timers.clear(restTimer); restTimer = null; }
      if (startTimer) { timers.clear(startTimer); startTimer = null; }
      startBurst = false;
    }
    function currentMood() {
      if (override) return override;
      if (startBurst) return 'excited';
      return moodFor(totals, cfg);
    }
    /** Write the attributes: the mood's pose, then any short-lived flash on top (a sparkle after a pass, ears back after a fail). */
    function apply() {
      var mood = currentMood();
      var attrs = merge(POSES[mood], null);
      flashes.forEach(function (f) {
        for (var k in f.attrs) { if (k === 'fx' && attrs.fx !== 'none') continue; attrs[k] = f.attrs[k]; }   // a flash never covers the mood's own effect (rain, sweat, steam)
      });
      Object.keys(attrs).forEach(function (k) { if (rig.getAttribute('data-' + k) !== attrs[k]) rig.setAttribute('data-' + k, attrs[k]); });
      rig.setAttribute('data-mood', mood);
      if (mood !== 'sad') rainSuppressed = false;
      var wantRain = mood === 'sad' && !rainSuppressed;
      if (wantRain !== rainOn) { rainOn = wantRain; if (fx && fx.rain) fx.rain(wantRain); }
      if (onChange) onChange(mood, copy(totals));
      return mood;
    }
    function flash(attrs, ms) {
      var f = { attrs: attrs };
      f.timer = timers.set(function () { flashes = flashes.filter(function (x) { return x !== f; }); apply(); }, ms);
      flashes.push(f);
      apply();
    }
    function copy(t) { return { passed: t.passed, failed: t.failed, failStreak: t.failStreak, total: t.total, running: t.running, done: t.done }; }
    function react(name) { if (idle && idle.react) idle.react(name); }
    function spark() { if (fx && fx.sparkle) fx.sparkle(); }
    function wake() { if (idle && idle.start) idle.start(); }
    function restAfter(ms) {
      restTimer = timers.set(function () {
        restTimer = null;
        if (rainOn) { rainSuppressed = true; apply(); }          // the rain stops with her; the cloud and the sad pose stay
        if (idle && idle.settle) idle.settle();
      }, ms);
    }

    var api = {
      /** A run begins: totals reset, she is excited for a moment, then the mood follows the results. */
      onRunStart: function (info) {
        cancelTimers(); reset(); override = null; rainSuppressed = false;
        totals.running = true;
        totals.total = info && info.totalTests != null ? info.totalTests : null;
        startBurst = true;
        startTimer = timers.set(function () { startTimer = null; startBurst = false; apply(); }, cfg.startExcitedMs);
        wake();
        return apply();
      },
      /** One test finished. A pass: a small sparkle and a mane flick. A fail: a flinch with the ears back. */
      onTestResult: function (result) {
        var status = result && result.status;
        if (status !== 'pass' && status !== 'fail') throw new TypeError("onTestResult: status must be 'pass' or 'fail'");
        if (totals.done) { cancelTimers(); reset(); rainSuppressed = false; }                // a result after the end of a run starts a new, open-ended one
        if (!totals.running) { totals.running = true; wake(); }
        if (restTimer) { timers.clear(restTimer); restTimer = null; }
        if (status === 'pass') {
          totals.passed += 1; totals.failStreak = 0;
          if (POSES[currentMood()].fx === 'none') flash({ fx: 'sparkle' }, cfg.passSparkleMs);     // not over the sad cloud / the sweat drop / steam
          react('maneFlick'); spark();
        } else {
          totals.failed += 1; totals.failStreak += 1;
          flash({ ears: 'back' }, cfg.flinchMs);
          react('flinch');
        }
        var after = apply();
        if (after === 'sad' && fx && fx.rain) fx.rain(true);       // every failure renews the rain
        return after;
      },
      /** The run is over: the final tier decides (joyful / happy / sad), then she settles to rest. */
      onRunComplete: function (summary) {
        cancelTimers();
        if (summary && summary.passed != null) { totals.passed = summary.passed; totals.failed = summary.failed || 0; }
        if (summary && summary.total != null) totals.total = summary.total;
        totals.running = false; totals.done = true; totals.failStreak = 0;
        var mood = apply();
        if (mood === 'joyful') { wake(); react('hop'); if (fx && fx.celebrate) fx.celebrate(); restAfter(cfg.celebrateMs); }
        else if (mood === 'happy') { flash({ fx: 'sparkle' }, cfg.endSparkleMs); react('maneFlick'); spark(); restAfter(cfg.restAfterMs); }
        else restAfter(mood === 'sad' ? cfg.sadRainMs : cfg.restAfterMs);
        return mood;
      },
      /** Manual override: a mood name, or null to go back to the automatic mood. */
      setMood: function (name) {
        if (name !== null && name !== undefined && !POSES[name]) throw new Error('unknown mood: ' + name);
        override = name || null;
        return apply();
      },
      getMood: function () { return currentMood(); },
      getTotals: function () { return copy(totals); },
      reset: function () { cancelTimers(); reset(); override = null; rainSuppressed = false; return apply(); },
      destroy: function () { cancelTimers(); if (fx && fx.rain && rainOn) fx.rain(false); rainOn = false; }
    };
    apply();
    return api;
  }

  return { POSES: POSES, DEFAULTS: DEFAULTS, moodFor: moodFor, create: create };
}));
