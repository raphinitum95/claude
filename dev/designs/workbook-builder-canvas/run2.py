"""Run tab v2 (one list for many workbooks, one run plan, batch live view) and the Results tab."""
import json
from common import *

WB = [
    {'id': 'tx', 'name': 'Travelex Regression v9.1', 'file': 'UAT_AEM_Travelex Regression_v9.1.xlsx', 'color': 'var(--k-nav)', 'tests': [
        ('Owner_CRVD', 'web', 231, ['purchase', 'smoke'], 'fail', 521, '', True),
        ('PostDeparture', 'web', 244, ['servicing'], 'pass', 305, 'Owner_CRVD', True),
        ('Preview', 'web', 284, ['quote'], 'pass', 230, '', True),
        ('Owner_RVD', 'web', 243, ['purchase'], 'pass', 432, '', True),
        ('Owner_AZ', 'web', 318, ['purchase'], 'pass', 542, '', True),
        ('ANZ', 'web', 215, ['purchase'], 'fail', 362, '', True),
        ('Travelkore', 'web', 325, ['partner'], 'pass', 510, '', True),
        ('CW', 'web', 177, ['partner'], 'pend', 0, '', False),
        ('WM', 'web', 176, ['partner'], 'pass', 310, '', False)]},
    {'id': 'qf', 'name': 'Qantas Staff Daily Regression v1.1', 'file': 'UAT DT_Qantas StandAlone_Staff Daily Regression_v1.1.xlsx', 'color': 'var(--k-flow)', 'tests': [
        ('Qantas#1', 'web', 953, ['daily', 'purchase'], 'pass', 1320, '', True),
        ('Qantas#2', 'web', 953, ['daily', 'purchase'], 'flaky', 1290, '', True),
        ('Qantas_AgentPortal#1', 'web', 797, ['daily', 'agent'], 'pass', 1080, 'Qantas#1', True),
        ('PolicySearch#1', 'api', 2, ['daily', 'api'], 'pass', 20, 'Qantas_AgentPortal#1', True),
        ('AgentStandAlone#1', 'web', 847, ['daily', 'agent'], 'pass', 1150, '', True),
        ('Qantas_PROD#1', 'web', 139, ['prod-only'], 'pend', 0, '', False)]},
    {'id': 'ex', 'name': 'AEM Claims US Expedia', 'file': 'AEM_Claims_US_Expedia.xlsx', 'color': 'var(--k-input)', 'tests': [
        ('USClaims#1', 'web', 305, ['claims'], 'pass', 720, '', True),
        ('USClaimsStatus#1', 'web', 59, ['claims'], 'pass', 180, 'USClaims#1', True),
        ('US_EXPClaims#1', 'web', 189, ['claims', 'expedia'], 'fail', 480, '', True),
        ('US_EXPClaimsStatus#1', 'web', 66, ['claims', 'expedia'], 'pend', 190, 'US_EXPClaims#1', True),
        ('USPolicy#1', 'web', 97, ['policy'], 'pass', 240, '', True),
        ('USExpedia#1', 'web', 109, ['expedia'], 'pass', 300, '', True),
        ('PurchaseUS#1', 'api', 3, ['api'], 'pass', 40, '', True)]},
]


def run_side(active=True):
    return ('<aside style="width: 250px; flex: none; border-right: 1px solid var(--line); background: var(--rail); padding: 18px 14px; display: flex; flex-direction: column; gap: 18px">'
            '<button class="btn btn-pri" style="width: 100%; height: 42px; font-size: 14px">' + ic('plus', 17) + ' New run</button>'
            '<div style="display: flex; flex-direction: column; gap: 4px"><div class="lbl" style="padding: 0 8px 6px">Running now · 2</div>'
            '<button style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; border-radius: 12px; width: 100%; ' + ('background: var(--surface); border: 1px solid var(--line2); box-shadow: var(--shadow)' if active else 'border: 1px solid transparent') + '">'
            '<span style="width: 18px; height: 18px; display: grid; place-items: center; color: var(--acc)"><span class="dot" style="width: 10px; height: 10px"></span></span>'
            '<span style="min-width: 0; flex: 1"><span class="mono" style="display: block; font-size: 12px">Batch 0926-0944</span><span style="display: block; font-size: 12px; color: var(--tx2)">3 workbooks · 19 tests · 58%</span>'
            '<span style="display: flex; gap: 2px; height: 4px; margin-top: 8px; border-radius: 99px; overflow: hidden"><span style="flex: 7; background: var(--k-nav)"></span><span style="flex: 5; background: var(--k-flow)"></span><span style="flex: 4; background: var(--k-input)"></span><span style="flex: 12; background: var(--track)"></span></span></span></button>'
            '<button style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; border-radius: 12px; width: 100%; border: 1px solid transparent">'
            '<span style="width: 18px; height: 18px; display: grid; place-items: center; color: var(--acc)"><span class="dot" style="width: 10px; height: 10px"></span></span>'
            '<span style="min-width: 0; flex: 1"><span class="mono" style="display: block; font-size: 12px">Run 0926-1003</span><span style="display: block; font-size: 12px; color: var(--tx2)">Travelex · Owner_RVD · 12%</span>'
            '<span style="display: block; font-size: 11.5px; color: var(--tx3); margin-top: 2px">Started on its own · not in the batch</span>'
            '<span style="display: flex; height: 4px; margin-top: 8px; border-radius: 99px; overflow: hidden; background: var(--track)"><span style="width: 12%; background: var(--k-nav)"></span></span></span></button></div>'
            '<span style="font-size: 12px; color: var(--tx3); padding: 0 8px">Every run shares the same workers, so a new run never waits for a batch. It only joins a batch if you use “Add tests to this batch”.</span>'
            '<a href="ResultsHome.dc.html" style="margin-top: auto; display: flex; align-items: center; gap: 8px; padding: 10px; border-radius: 10px; border: 1px solid var(--line); font-size: 12.5px; color: var(--tx2); text-decoration: none">'
            + ic('history', 15) + '<span style="flex-grow: 1">Finished runs live in Results</span>' + ic('chevr', 13, 2) + '</a></aside>')


def app_header(active):
    return header(active, right=('<span class="chip">' + ic('cpu', 14) + ' 6 workers</span><span class="chip mono">' + ic('lock', 14) + ' 127.0.0.1:8765 · local only</span>'
                                 '<button class="icon-btn" aria-label="Switch between light and dark">' + ic('sun', 15) + '</button>'))


# ------------------------------------------------------------------------------------------------ New run (interactive)
SETUP = (root_open(1440, 1320, 'dark') + app_header('Run') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + run_side(False) +
    '<main style="flex-grow: 1; min-width: 0; padding: 30px 36px; display: flex; flex-direction: column; gap: 20px; overflow: hidden">'
    '<div style="display: flex; align-items: flex-end; gap: 14px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">New run</span>'
    '<span class="disp" style="font-size: 30px; font-weight: 700">What should run?</span></div><span style="flex-grow: 1"></span>'
    '<button class="btn">' + ic('upload', 14) + ' Add a workbook</button><button class="btn">' + ic('history', 14) + ' Same as last batch</button></div>'
    '<div style="display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 22px; align-items: start">'
    '<div style="display: flex; flex-direction: column; gap: 20px; min-width: 0">'
    # ---- what to run
    '<section class="card" style="overflow: hidden">'
    '<div style="padding: 14px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--line)">'
    '<div class="field" style="width: 260px; min-height: 34px">' + ic('search', 14) + '<span style="font-size: 12.5px; color: var(--tx3)">Find a test in any workbook</span></div>'
    '<span class="lbl" style="margin-left: 6px">Tags</span>'
    '<sc-for list="{{tags}}" as="t" hint-placeholder-count="5"><button class="tag {{t.cls}}" onClick="{{t.pick}}">{{t.name}}</button></sc-for>'
    '<span style="flex-grow: 1"></span><span class="mono" style="font-size: 12px; color: var(--tx2)">{{selTests}} tests · {{selBooks}} workbooks</span></div>'
    '<sc-for list="{{books}}" as="b" hint-placeholder-count="3">'
    '<div style="border-bottom: 1px solid var(--line)">'
    '<div style="display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--surface2)">'
    '<button onClick="{{b.toggleAll}}" aria-label="Select all tests in {{b.name}}" style="display: inline-flex"><span class="cbx {{b.cbx}}">{{b.cbxMark}}</span></button>'
    '<span style="width: 4px; height: 30px; border-radius: 4px; background: {{b.color}}"></span>'
    '<button onClick="{{b.toggleOpen}}" style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1">'
    '<b style="font-size: 14px">{{b.name}}</b><span class="mono trunc" style="font-size: 11px; color: var(--tx3)">{{b.file}}</span></button>'
    '<span style="font-size: 12.5px; color: var(--tx2); white-space: nowrap">{{b.count}}</span>'
    '<span class="tag">{{b.streams}}</span>'
    '<sc-if value="{{b.hasNote}}" hint-placeholder-val="{{false}}"><span class="tag tag-warn">{{b.note}}</span></sc-if>'
    '<button class="icon-btn" style="width: 28px; height: 28px" onClick="{{b.toggleOpen}}" aria-label="Show or hide tests">{{b.chev}}</button></div>'
    '<sc-if value="{{b.open}}" hint-placeholder-val="{{true}}">'
    '<sc-for list="{{b.tests}}" as="t" hint-placeholder-count="5">'
    '<div style="display: grid; grid-template-columns: 20px 18px minmax(0, 1fr) 150px 84px 70px 56px; gap: 12px; align-items: center; padding: 8px 16px 8px 30px; border-top: 1px solid var(--line); {{t.rowStyle}}">'
    '<button onClick="{{t.toggle}}" aria-label="Run {{t.name}}" style="display: inline-flex"><span class="cbx {{t.cbx}}">' + ic('check', 11, 3) + '</span></button>'
    '<span style="color: var(--tx3); display: inline-flex"><sc-if value="{{t.isApi}}" hint-placeholder-val="{{false}}">' + ic('api', 14) + '</sc-if><sc-if value="{{t.isWeb}}" hint-placeholder-val="{{true}}">' + ic('web', 14) + '</sc-if></span>'
    '<span style="display: flex; align-items: center; gap: 8px; min-width: 0"><b class="trunc" style="font-size: 13px">{{t.name}}</b>'
    '<sc-if value="{{t.hasWait}}" hint-placeholder-val="{{false}}"><span class="tag tag-acc" title="Uses a value that test sets">' + ic('arrowl', 11, 2) + ' after {{t.waits}}</span></sc-if>'
    '<sc-if value="{{t.hasOff}}" hint-placeholder-val="{{false}}"><span style="font-size: 11.5px; color: var(--tx3)">{{t.off}}</span></sc-if></span>'
    '<span style="display: flex; gap: 4px; overflow: hidden"><sc-for list="{{t.tags}}" as="g" hint-placeholder-count="1"><span class="tag">{{g}}</span></sc-for></span>'
    '<span class="mono" style="font-size: 11.5px; color: var(--tx3); text-align: right">{{t.steps}} steps</span>'
    '<span class="mono" style="font-size: 11.5px; color: var(--tx3); text-align: right">{{t.dur}}</span>'
    '<span style="display: flex; justify-content: flex-end" title="Last run"><span class="pill {{t.lastCls}}" style="height: 18px; font-size: 9.5px; padding: 0 6px">{{t.last}}</span></span></div>'
    '</sc-for></sc-if></div></sc-for></section>'
    # ---- run plan
    '<section class="card" style="overflow: hidden">'
    '<div style="padding: 14px 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--line)">'
    '<span class="ttl" style="font-size: 17px">Run plan</span><span style="font-size: 12.5px; color: var(--tx3)">One plan for everything you picked</span><span style="flex-grow: 1"></span>'
    '<div class="seg" style="width: 250px"><button class="{{segOrder}}" onClick="{{showOrder}}">Order</button><button class="{{segTime}}" onClick="{{showTime}}">Timeline</button></div></div>'
    '<sc-if value="{{isOrder}}" hint-placeholder-val="{{true}}">'
    '<div style="padding: 12px 16px 6px; font-size: 12.5px; color: var(--tx2)">Each row is a chain: a test that needs a value from another waits for it. Rows run side by side. Drag a chain up to start it earlier, or drag one test onto another to make it wait.</div>'
    '<div style="padding: 6px 16px 16px; display: flex; flex-direction: column; gap: 6px">'
    '<sc-for list="{{chains}}" as="c" hint-placeholder-count="6">'
    '<div style="display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface2)">'
    '<span style="color: var(--tx4); display: inline-flex; cursor: grab">' + ic('grip', 14) + '</span>'
    '<span class="mono" style="width: 22px; font-size: 11px; color: var(--tx3)">{{c.n}}</span>'
    '<sc-for list="{{c.items}}" as="i" hint-placeholder-count="2">'
    '<sc-if value="{{i.arrow}}" hint-placeholder-val="{{false}}"><span style="color: var(--tx3); display: inline-flex">' + ic('arrowr', 14, 2) + '</span></sc-if>'
    '<span style="display: inline-flex; align-items: center; gap: 7px; height: 28px; padding: 0 10px; border-radius: 8px; background: var(--surface); border: 1px solid var(--line2); font-size: 12.5px; font-weight: 600">'
    '<span class="pdot" style="background: {{i.color}}"></span>{{i.name}}<span class="mono" style="font-size: 10.5px; color: var(--tx3); font-weight: 500">{{i.dur}}</span></span>'
    '</sc-for><span style="flex-grow: 1"></span><span class="mono" style="font-size: 11px; color: var(--tx3)">{{c.total}}</span></div>'
    '</sc-for></div></sc-if>'
    '<sc-if value="{{isTime}}" hint-placeholder-val="{{false}}">'
    '<div style="padding: 12px 16px 6px; display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--tx2)">Estimated from each test’s last run. Longest chains start first.'
    '<span style="flex-grow: 1"></span><b style="color: var(--tx)">≈ {{estimate}}</b><span style="color: var(--tx3)">on {{workers}} workers</span></div>'
    '<div style="padding: 6px 16px 16px; display: flex; flex-direction: column; gap: 5px">'
    '<sc-for list="{{lanes}}" as="l" hint-placeholder-count="6">'
    '<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="width: 64px; font-size: 11px; color: var(--tx3)">worker {{l.n}}</span>'
    '<div style="flex-grow: 1; position: relative; height: 26px; border-radius: 6px; background: var(--track)">'
    '<sc-for list="{{l.bars}}" as="r" hint-placeholder-count="2"><span class="trunc" title="{{r.name}}" style="position: absolute; left: {{r.left}}%; width: {{r.width}}%; top: 2px; bottom: 2px; border-radius: 5px; padding: 0 6px; display: flex; align-items: center; font-size: 11px; font-weight: 600; color: var(--bg); background: {{r.color}}">{{r.label}}</span></sc-for>'
    '</div></div></sc-for>'
    '<div style="display: flex; justify-content: space-between; padding-left: 72px; font-size: 10.5px; color: var(--tx3)" class="mono"><span>0</span><span>{{half}}</span><span>{{estimate}}</span></div></div></sc-if>'
    '</section>'
    '</div>'
    # ---- right: settings + launch
    '<div style="display: flex; flex-direction: column; gap: 16px">'
    '<section class="card" style="padding: 18px; display: flex; flex-direction: column; gap: 16px; box-shadow: var(--glow); border-color: var(--acc-line)">'
    '<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px">'
    '<div><div class="lbl">Tests</div><div class="disp" style="font-size: 30px; font-weight: 700">{{selTests}}</div></div>'
    '<div><div class="lbl">Workbooks</div><div class="disp" style="font-size: 30px; font-weight: 700">{{selBooks}}</div></div>'
    '<div><div class="lbl">About</div><div class="disp" style="font-size: 30px; font-weight: 700">{{estimateShort}}</div></div></div>'
    '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Environment</span><div class="seg"><button>QA</button><button class="on uat">UAT</button><button>PROD</button></div></div>'
    '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Workers</span>'
    '<div style="display: flex; align-items: center; gap: 10px"><button class="icon-btn" onClick="{{less}}" aria-label="Fewer workers">' + ic('minus', 14, 2) + '</button>'
    '<span class="disp" style="font-size: 22px; font-weight: 700; width: 30px; text-align: center">{{workers}}</span>'
    '<button class="icon-btn" onClick="{{more}}" aria-label="More workers">' + ic('plus', 14, 2) + '</button>'
    '<span style="font-size: 12px; color: var(--tx3)">1 worker would take {{serial}}</span></div></div>'
    '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Browser</span><div class="seg"><button class="on">Chrome</button><button>Edge</button><button>Safari</button></div></div>'
    '<details class="more"><summary style="font-size: 13px; font-weight: 600; color: var(--acc); cursor: pointer">More settings · screenshots, retries, seed</summary></details>'
    '<button class="btn btn-pri btn-lg" style="width: 100%">' + ic('play', 15, 2) + ' Start {{selTests}} tests</button>'
    '<span style="font-size: 12px; color: var(--tx3); text-align: center">One batch, one results page. Each workbook still gets its own report.</span></section>'
    '<section class="card" style="padding: 16px 18px; display: flex; flex-direction: column; gap: 10px"><span class="ttl" style="font-size: 16px">Before it starts</span>'
    + ''.join('<div style="display: flex; gap: 10px; font-size: 12.5px"><span style="color: %s; display: inline-flex; margin-top: 2px">%s</span><span>%s</span></div>' % (c, ic(i, 14, 2), t) for c, i, t in (
        ('var(--pass)', 'check', 'Environment values present for UAT in all 3 workbooks'),
        ('var(--warn)', 'warn', '<b>Qantas_PROD#1</b> only runs on PROD, left out'),
        ('var(--warn)', 'bolt', '4 steps with side effects will place real UAT orders'),
        ('var(--pass)', 'check', 'Sign-in: 2 Qantas users, separate code windows'),
        ('var(--pass)', 'check', 'No workbook is open in Excel')))
    + '</section></div></div></main></div></div>')

SETUP_JS = r"""
var WB = %(wb)s;
function fmt(s) { if (s < 60) return s + 's'; var m = Math.round(s / 60); if (m < 60) return m + 'm'; return Math.floor(m / 60) + 'h ' + (m %% 60) + 'm'; }
class Component extends DCLogic {
  constructor(p) {
    super(p);
    var sel = {}; WB.forEach(function (b) { b.tests.forEach(function (t) { sel[b.id + '/' + t[0]] = t[7]; }); });
    this.state = { sel: sel, open: { tx: true, qf: true, ex: false }, view: (p && p.view) || 'order', workers: 6, tag: '' };
  }
  renderVals() {
    var s = this.state, self = this, ICON = { web: '%(web)s', api: '%(api)s' };
    var LAST = { pass: ['p-pass', 'pass'], fail: ['p-fail', 'fail'], flaky: ['p-warn', 'flaky'], pend: ['p-pend', '—'] };
    var chains = [], nSel = 0, nBooks = 0, serial = 0;
    var books = WB.map(function (b) {
      var on = b.tests.filter(function (t) { return s.sel[b.id + '/' + t[0]]; }).length;
      if (on) nBooks++;
      nSel += on;
      var steps = 0; b.tests.forEach(function (t) { if (s.sel[b.id + '/' + t[0]]) { steps += t[2]; serial += t[5]; } });
      // chains inside this workbook
      var heads = b.tests.filter(function (t) { return !t[6] && s.sel[b.id + '/' + t[0]]; });
      var nch = 0;
      heads.forEach(function (h) {
        var items = [h], cur = h[0], guard = 0;
        while (guard++ < 5) { var nx = b.tests.filter(function (t) { return t[6] === cur && s.sel[b.id + '/' + t[0]]; })[0]; if (!nx) break; items.push(nx); cur = nx[0]; }
        var tot = items.reduce(function (a, t) { return a + t[5]; }, 0); nch++;
        chains.push({ total: tot, items: items.map(function (t, k) { return { name: t[0], dur: fmt(t[5]), color: b.color, arrow: k > 0 }; }) });
      });
      var all = on === b.tests.length;
      return { name: b.name, file: b.file, color: b.color, open: !!s.open[b.id], chev: s.open[b.id] ? '▾' : '▸',
        cbx: on ? 'on' : '', cbxMark: on ? (all ? '✓' : '–') : '',
        count: on + ' of ' + b.tests.length + ' tests · ' + steps.toLocaleString() + ' steps', streams: nch + ' chain' + (nch === 1 ? '' : 's'),
        hasNote: b.id === 'qf', note: '1 PROD-only',
        toggleOpen: function () { var o = Object.assign({}, s.open); o[b.id] = !o[b.id]; self.setState({ open: o }); },
        toggleAll: function () { var x = Object.assign({}, s.sel); b.tests.forEach(function (t) { x[b.id + '/' + t[0]] = !on && t[0].indexOf('PROD') < 0; }); self.setState({ sel: x }); },
        tests: b.tests.filter(function (t) { return !s.tag || t[3].indexOf(s.tag) >= 0; }).map(function (t) {
          var k = b.id + '/' + t[0], v = !!s.sel[k];
          return { name: t[0], isApi: t[1] === 'api', isWeb: t[1] !== 'api', tags: t[3].slice(0, 2), steps: t[2], dur: t[5] ? fmt(t[5]) : '—', lastCls: LAST[t[4]][0], last: LAST[t[4]][1],
            hasWait: !!t[6], waits: t[6], hasOff: t[0].indexOf('PROD') >= 0, off: 'PROD only', cbx: v ? 'on' : '', rowStyle: v ? '' : 'opacity: .55',
            toggle: function () { var x = Object.assign({}, s.sel); x[k] = !v; self.setState({ sel: x }); } };
        }) };
    });
    chains.sort(function (a, b) { return b.total - a.total; });
    var W = s.workers, load = []; for (var i = 0; i < W; i++) load.push({ n: i + 1, t: 0, bars: [] });
    chains.forEach(function (c) {
      load.sort(function (a, b) { return a.t - b.t; });
      var w = load[0];
      c.items.forEach(function (it, k) { var d = c.items[k]; w.bars.push({ name: d.name, start: w.t, dur: 0, color: d.color, raw: d }); });
      var t0 = w.t;
      c.items.forEach(function (it) { var sec = WB.reduce(function (a, b) { var f = b.tests.filter(function (t) { return t[0] === it.name; })[0]; return f ? f[5] : a; }, 0);
        var bar = w.bars.filter(function (x) { return x.raw === it; })[0]; bar.start = t0; bar.dur = sec; t0 += sec; });
      w.t = t0;
    });
    load.sort(function (a, b) { return a.n - b.n; });
    var end = Math.max.apply(null, load.map(function (l) { return l.t; })) || 1;
    var lanes = load.map(function (l) { return { n: l.n, bars: l.bars.map(function (b) { return { name: b.name, label: b.dur / end > .08 ? b.name : '', left: (b.start / end * 100).toFixed(2), width: Math.max(b.dur / end * 100 - .4, .6).toFixed(2), color: b.color }; }) }; });
    var tags = ['purchase', 'daily', 'claims', 'smoke', 'agent'].map(function (g) { return { name: g, cls: s.tag === g ? 'tag-acc' : '', pick: function () { self.setState({ tag: s.tag === g ? '' : g }); } }; });
    return { books: books, tags: tags, selTests: nSel, selBooks: nBooks,
      chains: chains.map(function (c, i) { return { n: i + 1, items: c.items, total: fmt(c.total) }; }), lanes: lanes,
      estimate: fmt(end), half: fmt(Math.round(end / 2)), estimateShort: fmt(end), serial: fmt(serial), workers: W,
      less: function () { self.setState({ workers: Math.max(1, W - 1) }); }, more: function () { self.setState({ workers: Math.min(12, W + 1) }); },
      isOrder: s.view === 'order', isTime: s.view === 'time', segOrder: s.view === 'order' ? 'on' : '', segTime: s.view === 'time' ? 'on' : '',
      showOrder: function () { self.setState({ view: 'order' }); }, showTime: function () { self.setState({ view: 'time' }); } };
  }
}
"""


def setup_js(view):
    js = SETUP_JS.replace('%(wb)s', json.dumps(WB)).replace('%(web)s', ic('web', 14).replace("'", "\\'")).replace('%(api)s', ic('api', 14).replace("'", "\\'")).replace('%%', '%')
    return js.replace("(p && p.view) || 'order'", "(p && p.view) || '%s'" % view)


# ------------------------------------------------------------------------------------------------ Live batch
def live_batch():
    w, h = 1440, 1100
    books = [('Travelex Regression v9.1', 'var(--k-nav)', 7, 4, 1, 1, 1, '≈ 12m left'), ('Qantas Staff Daily Regression v1.1', 'var(--k-flow)', 5, 1, 0, 2, 2, '≈ 31m left'),
             ('AEM Claims US Expedia', 'var(--k-input)', 7, 3, 1, 2, 1, '≈ 14m left')]
    brow = ''.join('<button style="display: grid; grid-template-columns: 4px minmax(0, 1fr) 220px 170px 110px; gap: 14px; align-items: center; padding: 12px 16px; border-top: 1px solid var(--line); width: 100%%">'
                   '<span style="height: 28px; border-radius: 4px; background: %s"></span><b class="trunc" style="font-size: 13.5px">%s</b>'
                   '<span style="display: flex; height: 8px; border-radius: 99px; overflow: hidden; background: var(--track)"><span style="flex: %d; background: var(--pass)"></span><span style="flex: %d; background: var(--fail)"></span><span style="flex: %d; background: var(--acc)"></span><span style="flex: %d"></span></span>'
                   '<span style="display: flex; gap: 10px; font-size: 12px"><span style="color: var(--pass)">%d passed</span><span style="color: var(--fail)">%d failed</span><span style="color: var(--acc)">%d running</span></span>'
                   '<span class="mono" style="font-size: 11.5px; color: var(--tx3); text-align: right">%s</span></button>'
                   % (c, n, p, f, r, t - p - f - r, p, f, r, eta) for n, c, t, p, f, r, q, eta in books)
    lanes = [('Qantas#2', 'var(--k-flow)', 'Payment', 612, 953, 'Type Card number', ''), ('AgentStandAlone#1', 'var(--k-flow)', 'Policy search', 402, 847, 'Check Policy status is Active', ''),
             ('Travelkore', 'var(--k-nav)', 'Traveler info', 188, 325, 'Waiting for the page: 2 calls still loading', 'wait'), ('USClaimsStatus#1', 'var(--k-input)', 'Claim status', 31, 59, 'Check Status is Received', ''),
             ('USExpedia#1', 'var(--k-input)', 'Quote', 64, 109, 'Choose Plan in Plan', ''), ('Qantas_AgentPortal#1', 'var(--k-flow)', 'Sign in', 12, 797, 'Waiting for Qantas#1 → done, starting', '')]
    lcards = ''.join('<div class="card" style="padding: 12px; display: flex; flex-direction: column; gap: 9px">'
                     '<div style="display: flex; align-items: center; gap: 8px"><span class="pdot" style="background: %s"></span><b class="trunc" style="font-size: 13.5px">%s</b><span style="flex-grow: 1"></span><span class="mono" style="font-size: 11px; color: var(--tx3)">worker %d</span></div>'
                     '<div class="shot" style="height: 96px"><span class="mono" style="position: absolute; left: 8px; bottom: 6px; font-size: 10px; padding: 1px 6px; border-radius: 5px; background: var(--scrim); color: #fff">%s page</span></div>'
                     '<div style="height: 5px; border-radius: 99px; background: var(--track); overflow: hidden"><div style="width: %d%%; height: 100%%; background: %s"></div></div>'
                     '<div style="display: flex; gap: 8px; font-size: 12px"><span class="mono" style="color: var(--tx3)">%d / %d</span><span class="trunc" style="%s">%s</span></div></div>'
                     % (c, n, i + 1, pg, int(a / b * 100), c, a, b, 'color: var(--warn)' if st == 'wait' else 'color: var(--tx2)', txt)
                     for i, (n, c, pg, a, b, txt, st) in enumerate(lanes))
    fails = [('var(--k-nav)', 'Owner_CRVD', 'Step 228 · Card number not found · a backup found 1 match'), ('var(--k-nav)', 'ANZ', 'Step 212 · never reached the Payment page (hard stop)'),
             ('var(--k-input)', 'US_EXPClaims#1', 'Step 144 · Claim total is $1,240.00, expected $1,420.00')]
    frows = ''.join('<div style="display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-top: 1px solid var(--line)"><span class="pdot" style="background: %s"></span><b style="font-size: 13px">%s</b><span class="trunc" style="font-size: 12.5px; color: var(--tx2); flex-grow: 1">%s</span>'
                    '<a href="ResultsTest.dc.html" class="btn btn-sm" style="text-decoration: none">Look now</a></div>' % f for f in fails)
    body = (root_open(w, h, 'dark') + app_header('Run') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + run_side(True)
            + '<main style="flex-grow: 1; min-width: 0; padding: 28px 36px; display: flex; flex-direction: column; gap: 18px">'
            '<div style="display: flex; align-items: flex-end; gap: 14px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">Running · batch 0926-0944</span>'
            '<span class="disp" style="font-size: 30px; font-weight: 700">19 tests across 3 workbooks</span><span class="mono" style="font-size: 12.5px; color: var(--tx3)">UAT · Chrome · 6 workers · started 09:44 · ≈ 31m left</span>'
            '<span style="font-size: 12px; color: var(--tx3)">3 runs shown together: 0926-0944-tx · 0926-0944-qf · 0926-0944-ex. Each keeps its own folder and report.</span></div>'
            '<span style="flex-grow: 1"></span><button class="btn">' + ic('plus', 14) + ' Add tests to this batch</button><button class="btn btn-dng">' + ic('stop', 14) + ' Stop</button></div>'
            '<div style="display: flex; height: 14px; border-radius: 6px; overflow: hidden; gap: 2px"><span style="flex: 8; background: var(--pass)"></span><span style="flex: 2; background: var(--fail)"></span><span style="flex: 5; background: var(--acc)"></span><span style="flex: 5; background: var(--track)"></span></div>'
            '<div class="waitline" style="display: flex; gap: 9px; padding: 10px 12px; border-radius: 10px; background: var(--warn-soft); border: 1px solid var(--warn-line); font-size: 12.5px">' + ic('clock', 15, 2, 'color: var(--warn)') + '<span><b>Travelkore is waiting on purpose:</b> the Traveler info page still has 2 of its own calls loading (18 s). Nothing is stuck.</span></div>'
            '<section class="card" style="overflow: hidden"><div style="padding: 12px 16px; display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 17px">By workbook</span><span style="font-size: 12.5px; color: var(--tx3)">Click one to filter everything below</span></div>' + brow + '</section>'
            '<div style="display: flex; align-items: center; gap: 12px"><span class="ttl">Now running</span><span class="chip mono">6 of 6 workers</span><span style="flex-grow: 1"></span>'
            '<span style="font-size: 12.5px; color: var(--tx3)">Up next: Qantas_AgentPortal#1 → PolicySearch#1 · US_EXPClaimsStatus#1 (waits for US_EXPClaims#1, which failed: will be skipped)</span></div>'
            '<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px">' + lcards + '</div>'
            '<section class="card" style="overflow: hidden"><div style="padding: 12px 16px; display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 17px">Failed so far</span><span class="tag tag-fail">3</span>'
            '<span style="font-size: 12.5px; color: var(--tx3)">You don’t have to wait for the end to start looking.</span></div>' + frows + '</section>'
            '</main></div></div>')
    return body, w, h


# ------------------------------------------------------------------------------------------------ Results tab
def results_side(active='b1'):
    items = [('Today', [('b0', 'Batch 0926-1010', 're-run of batch 0925-1412 · 3 tests', 'pass', 'all 3 passed · 14m'), ('b1', 'Batch 0926-0944', '3 workbooks · 19 tests · UAT', 'run', '58% · running'), ('b1b', 'Run 0926-1003', 'Travelex · Owner_RVD · on its own', 'run', '12% · running'), ('b2', 'Run 0926-0812', 'Qantas Staff Daily · 5 tests · UAT', 'pass', '46m')]),
             ('Yesterday', [('b3', 'Batch 0925-1412', '3 workbooks · 19 tests · UAT', 'fail', '3 failed · 52m'), ('b4', 'Run 0925-0915', 'Travelex · 9 tests · QA', 'pass', '41m')]),
             ('24 Sep', [('b5', 'Batch 0924-1630', '2 workbooks · 13 tests · UAT', 'fail', '1 failed · 38m'), ('b6', 'Run 0924-0905', 'Qantas Staff Daily · PROD', 'pass', 'smoke · 9m')])]
    out = ''
    for day, rows in items:
        out += '<div class="lbl" style="padding: 8px 8px 4px">%s</div>' % day
        for k, t, s1, st, s2 in rows:
            col = {'run': 'var(--acc)', 'pass': 'var(--pass)', 'fail': 'var(--fail)'}[st]
            on = k == active
            out += ('<button style="display: flex; gap: 10px; align-items: flex-start; padding: 9px 10px; border-radius: 11px; width: 100%%; %s"><span class="pdot" style="margin-top: 6px; background: %s"></span>'
                    '<span style="min-width: 0; flex-grow: 1; display: flex; flex-direction: column"><span class="mono" style="font-size: 12px; font-weight: 600">%s</span><span class="trunc" style="font-size: 12px; color: var(--tx2)">%s</span>'
                    '<span style="font-size: 11.5px; color: %s">%s</span></span></button>' % ('background: var(--surface); border: 1px solid var(--line2)' if on else 'border: 1px solid transparent', col, t, s1, col, s2))
    return ('<aside class="scroll" style="width: 280px; flex: none; border-right: 1px solid var(--line); background: var(--rail); padding: 16px 12px; display: flex; flex-direction: column; gap: 4px; overflow: auto">'
            '<div class="field" style="min-height: 34px; margin-bottom: 6px">' + ic('search', 14) + '<span style="font-size: 12.5px; color: var(--tx3)">Find a run, test or policy no.</span></div>'
            '<div style="display: flex; gap: 4px; flex-wrap: wrap; padding: 0 2px 6px">' + ''.join('<span class="tag %s">%s</span>' % (c, t) for t, c in (('All workbooks ▾', ''), ('Any env ▾', ''), ('Failed only', 'tag-acc'))) + '</div>'
            + out + '</aside>')


def results_home():
    w, h = 1440, 1320
    groups = [
        ('gate', 'var(--fail)', 'Never reached a page', 'Page gate hard stops. Later steps were not run, so there is one cause, not a cascade.',
         [('var(--k-nav)', 'ANZ', 'Step 212 · Payment page · URL was /purchase/travelers?error=session', 'new')]),
        ('loc', 'var(--fail)', 'Element not found', 'The page arrived but something on it moved or changed.',
         [('var(--k-nav)', 'Owner_CRVD', 'Step 228 · Card number (in frame) · backup found 1 match', 'new')]),
        ('val', 'var(--fail)', 'Wrong value', 'The site showed something other than expected. Most likely a real site bug.',
         [('var(--k-input)', 'US_EXPClaims#1', 'Step 144 · Claim total $1,240.00, expected $1,420.00', 'again · 3rd run')]),
        ('skip', 'var(--pend)', 'Not run because of another failure', 'They wait for a test that failed.',
         [('var(--k-input)', 'US_EXPClaimsStatus#1', 'Needs CLAIM_NO from US_EXPClaims#1', '')]),
    ]
    gcards = ''
    for key, col, title, why, rows in groups:
        rr = ''.join('<div style="display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--line)"><span class="pdot" style="background: %s"></span><b style="font-size: 13px; width: 170px">%s</b>'
                     '<span class="trunc" style="font-size: 12.5px; color: var(--tx2); flex-grow: 1">%s</span>%s'
                     '<a class="btn btn-sm" href="ResultsTest.dc.html" style="text-decoration: none">Open</a>%s</div>'
                     % (c, n, d, ('<span class="tag %s">%s</span>' % ('tag-fail' if tag == 'new' else 'tag-warn', tag)) if tag else '',
                        '<a class="btn btn-sm btn-pri" href="EditorFix.dc.html" style="text-decoration: none">' + ic('pencil', 12) + ' Fix in builder</a>' if key in ('gate', 'loc') else '')
                     for c, n, d, tag in rows)
        gcards += ('<div style="border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--surface)">'
                   '<div style="padding: 11px 14px; display: flex; align-items: center; gap: 10px"><span class="pdot" style="width: 10px; height: 10px; background: %s"></span><b>%s</b><span class="tag">%d</span>'
                   '<span style="font-size: 12px; color: var(--tx3)">%s</span></div>%s</div>' % (col, title, len(rows), why, rr))
    # all tests table grouped by workbook with trend dots
    import random
    random.seed(4)
    def trend(last, flaky=False):
        seq = ['pass'] * 9 + [last]
        if flaky: seq = ['pass', 'fail', 'pass', 'pass', 'fail', 'pass', 'pass', 'pass', 'fail', 'pass']
        if last == 'fail' and not flaky: seq[6:] = ['pass', 'pass', 'pass', 'fail']
        return ''.join('<span style="width: 7px; height: 16px; border-radius: 2px; background: %s"></span>' % {'pass': 'var(--pass)', 'fail': 'var(--fail)', 'pend': 'var(--pend)'}[x] for x in seq)
    rows = ''
    for b in [WB[0], WB[1], WB[2]]:
        rows += ('<div style="display: flex; align-items: center; gap: 10px; padding: 9px 16px; background: var(--surface2); border-top: 1px solid var(--line)"><span style="width: 4px; height: 18px; border-radius: 3px; background: %s"></span>'
                 '<b style="font-size: 13px">%s</b><span style="flex-grow: 1"></span><a href="#" style="font-size: 12px">Report for this workbook</a></div>' % (b['color'], b['name']))
        for t in b['tests']:
            if not t[7]: continue
            st = t[4]
            if b['id'] == 'ex' and t[0] == 'US_EXPClaimsStatus#1': st = 'skip'
            pill = {'pass': ('p-pass', 'Passed'), 'fail': ('p-fail', 'Failed'), 'flaky': ('p-pass', 'Passed'), 'pend': ('p-pend', 'Not run'), 'skip': ('p-pend', 'Skipped')}[st]
            note = {'flaky': '<span class="tag tag-warn">flaky: failed 3 of last 10</span>', 'fail': '<span class="tag tag-fail">new failure</span>' if t[0] != 'US_EXPClaims#1' else '<span class="tag tag-fail">failing 3 runs</span>'}.get(st, '')
            if t[0] == 'Owner_RVD': note = '<span class="tag tag-pass">fixed since yesterday</span>'
            rows += ('<div style="display: grid; grid-template-columns: minmax(0, 1fr) 200px 90px 90px 110px; gap: 14px; align-items: center; padding: 8px 16px 8px 30px; border-top: 1px solid var(--line)">'
                     '<span style="display: flex; align-items: center; gap: 8px; min-width: 0"><b class="trunc" style="font-size: 13px">%s</b>%s</span>'
                     '<span style="display: flex; gap: 2px" title="Last 10 runs, oldest first">%s</span><span class="pill %s" style="justify-self: start">%s</span>'
                     '<span class="mono" style="font-size: 11.5px; color: var(--tx3)">%s</span><span class="mono" style="font-size: 11.5px; color: var(--tx3)">%d steps</span></div>'
                     % (t[0], note, trend('fail' if st == 'fail' else ('pend' if st in ('skip', 'pend') else 'pass'), st == 'flaky'), pill[0], pill[1], '%dm %02ds' % (t[5] // 60, t[5] % 60) if t[5] else '—', t[2]))
    kpis = ''.join('<div class="card" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 2px"><span class="lbl">%s</span><span class="disp" style="font-size: 28px; font-weight: 700; color: %s">%s</span><span style="font-size: 12px; color: var(--tx3)">%s</span></div>'
                   % k for k in (('Passed', 'var(--pass)', '15', 'of 19 tests'), ('Failed', 'var(--fail)', '3', '2 new since the last batch'), ('Skipped', 'var(--tx2)', '1', 'waited on a failed test'),
                                 ('Took', 'var(--tx)', '52m', '3h 40m on 1 worker')))
    body = (root_open(w, h, 'dark') + app_header('Results') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + results_side('b3')
            + '<main style="flex-grow: 1; min-width: 0; padding: 28px 36px; display: flex; flex-direction: column; gap: 18px">'
            '<div style="display: flex; align-items: flex-end; gap: 12px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">Batch 0925-1412 · UAT · Chrome</span>'
            '<span class="disp" style="font-size: 30px; font-weight: 700">3 tests failed, 2 of them new</span><span class="mono" style="font-size: 12.5px; color: var(--tx3)">3 workbooks · 19 tests · 25 Sep 14:12–15:04</span>'
            '<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--tx3)">Made of 3 runs, open one on its own:'
            '<a href="#" class="tag" style="text-decoration: none">0925-1412-tx</a><a href="#" class="tag" style="text-decoration: none">0925-1412-qf</a><a href="#" class="tag" style="text-decoration: none">0925-1412-ex</a></span></div><span style="flex-grow: 1"></span>'
            '<button class="btn" title="Starts a new batch labelled re-run of batch 0925-1412. These results never change.">' + ic('undo', 14) + ' Re-run 3 failed</button><a class="btn" href="ResultsCompare.dc.html" style="text-decoration: none">' + ic('history', 14) + ' Compare</a>'
            '<button class="btn">' + ic('upload', 14) + ' Share with the team</button><button class="btn btn-pri">' + ic('external', 14) + ' Report</button></div>'
            '<div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px">' + kpis + '</div>'
            '<div class="bn bn-acc">' + ic('undo', 15, 2, 'color: var(--acc)') + '<span style="flex-grow: 1"><b>Re-run on 26 Sep:</b> the 3 failed tests ran again as batch 0926-1010 and all passed. This page keeps the original results.</span><a class="btn btn-sm" href="#" style="text-decoration: none">Open batch 0926-1010</a></div>'
            '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span><b>What changed since the last batch:</b> Travelex site version changed (build 4.18 → 4.19) · Owner_CRVD was edited in Build (09:12, 6 steps) · same environment and browser.</span></div>'
            '<div style="display: flex; flex-direction: column; gap: 10px"><div style="display: flex; align-items: center; gap: 10px"><span class="ttl">Failures, grouped by cause</span><span style="font-size: 12.5px; color: var(--tx3)">Start at the top; the ones below often go away when it’s fixed.</span></div>' + gcards + '</div>'
            '<section class="card" style="overflow: hidden"><div style="padding: 12px 16px; display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 17px">All tests</span>'
            '<span style="flex-grow: 1"></span><div class="seg" style="width: 280px"><span class="on">By workbook</span><span>Failures first</span><span>Slowest</span></div></div>' + rows + '</section>'
            '</main></div></div>')
    return body, w, h


def results_test():
    w, h = 1440, 1080
    blocks = [('Setup', 7, 'pass'), ('Header links', 18, 'pass'), ('Start quote', 14, 'pass'), ('Trip details', 28, 'pass'), ('Travelers', 14, 'pass'), ('Promo?', 9, 'pass'),
              ('Plans', 91, 'pass'), ('quotePrice#1', 1, 'pass'), ('Compare price', 4, 'pass'), ('Each traveler ×2', 22, 'warn'), ('Address', 16, 'pass'), ('Payment', 25, 'fail'),
              ('Review', 12, 'pend'), ('Change plan', 9, 'pend'), ('Confirmation', 7, 'pend'), ('Policy tab', 7, 'pend'), ('policyRecord#1', 1, 'pend'), ('Finish', 2, 'pend')]
    col = {'pass': 'var(--pass)', 'fail': 'var(--fail)', 'warn': 'var(--warn)', 'pend': 'var(--pend)'}
    bmap = ''.join('<div title="%s" style="flex: %d 1 0; min-width: 44px; height: 54px; border-radius: 8px; padding: 6px 7px; display: flex; flex-direction: column; justify-content: space-between; background: color-mix(in srgb, %s 14%%, var(--surface)); border: 1px solid color-mix(in srgb, %s 45%%, transparent); %s">'
                   '<span class="trunc" style="font-size: 11px; font-weight: 600">%s</span><span class="mono" style="font-size: 10px; color: var(--tx3)">%d</span></div>'
                   % (n, max(c, 6), col[s], col[s], 'box-shadow: 0 0 0 2px var(--fail)' if s == 'fail' else '', n, c) for n, c, s in blocks)
    steps = [('224', 'pass', 'Arrived at: Payment page', '0.4 s'), ('225', 'pass', 'Check Amount due contains Quoted premium', '0.3 s'), ('226', 'pass', 'Switch into the card frame', '0.2 s'),
             ('227', 'pass', 'Click Card number', '0.1 s'), ('228', 'fail', 'Type •••• Test card into Card number', '30.0 s'), ('229–249', 'pend', '21 steps not run (If this step fails: stop the test)', '')]
    srows = ''.join('<div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 9px; %s"><span class="mono" style="width: 58px; font-size: 11.5px; color: var(--tx3)">%s</span>'
                    '<span class="pdot" style="background: %s"></span><span class="trunc" style="flex-grow: 1; font-size: 13px; %s">%s</span><span class="mono" style="font-size: 11px; color: var(--tx3)">%s</span></div>'
                    % ('background: var(--fail-soft); border: 1px solid var(--fail-line)' if s == 'fail' else '', n, col[s], 'font-weight: 650' if s == 'fail' else ('color: var(--tx3)' if s == 'pend' else ''), t, d)
                    for n, s, t, d in steps)
    hist = ''.join('<div style="display: flex; flex-direction: column; align-items: center; gap: 4px"><span style="width: 22px; height: %dpx; border-radius: 4px; background: %s"></span><span class="mono" style="font-size: 9.5px; color: var(--tx3)">%s</span></div>'
                   % (hgt, col[s], d) for hgt, s, d in ((44, 'pass', '16'), (46, 'pass', '17'), (43, 'pass', '18'), (47, 'pass', '19'), (45, 'pass', '22'), (48, 'pass', '23'), (44, 'pass', '24'), (52, 'fail', '25')))
    body = (root_open(w, h, 'dark') + app_header('Results') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + results_side('b3')
            + '<main style="flex-grow: 1; min-width: 0; padding: 26px 34px; display: flex; flex-direction: column; gap: 16px">'
            '<div style="display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--tx3)"><a href="ResultsHome.dc.html">Batch 0925-1412</a>' + ic('chevr', 12, 2) + '<span>Travelex Regression v9.1</span>' + ic('chevr', 12, 2) + '<span style="color: var(--tx)">Owner_CRVD</span></div>'
            '<div style="display: flex; align-items: flex-end; gap: 12px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="disp" style="font-size: 28px; font-weight: 700">Owner_CRVD failed at step 228 of 287</span>'
            '<span class="mono" style="font-size: 12.5px; color: var(--tx3)">UAT · Row 1 (NE · Basic) · worker 2 · 8m 41s · last passed 24 Sep</span></div><span style="flex-grow: 1"></span>'
            '<button class="btn">' + ic('undo', 14) + ' Re-run this test</button><a class="btn btn-pri" href="EditorFix.dc.html" style="text-decoration: none">' + ic('pencil', 14) + ' Fix in builder</a></div>'
            '<section class="card" style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px"><div style="display: flex; align-items: center; gap: 10px"><span class="lbl">Where it stopped</span>'
            '<span style="font-size: 12px; color: var(--tx3)">Same blocks as the builder’s test map</span></div><div style="display: flex; gap: 4px">' + bmap + '</div></section>'
            '<div style="display: grid; grid-template-columns: minmax(0, 1fr) 420px; gap: 16px; align-items: start">'
            '<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 4px"><div style="display: flex; align-items: center; gap: 10px; padding: 0 4px 8px"><span class="ttl" style="font-size: 16px">Payment block</span>'
            '<span style="flex-grow: 1"></span><div class="seg" style="width: 240px"><span class="on">Around the failure</span><span>All 287</span></div></div>' + srows +
            '<div style="margin-top: 10px; padding: 12px; border-radius: 11px; background: var(--surface2); border: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px">'
            '<span class="lbl">Also in this run</span>'
            '<span style="font-size: 12.5px"><span class="tag tag-warn">popup</span> Step 96 · feedback survey appeared, closed</span>'
            '<span style="font-size: 12.5px"><span class="tag tag-warn">flagged</span> Step 204 · Choose Gender failed, noted and kept going</span>'
            '<span style="font-size: 12.5px"><span class="tag">values</span> POLICY_NO not set (stopped before Confirmation) · Quoted premium 148.20 · Test card ••••</span></div></section>'
            '<div style="display: flex; flex-direction: column; gap: 14px">'
            '<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px"><span class="ttl" style="font-size: 16px">Step 228</span>'
            '<div class="shot" style="height: 180px"><div style="position: absolute; left: 90px; top: 70px; width: 170px; height: 30px; border: 2px solid var(--fail); border-radius: 5px; box-shadow: 0 0 0 3px var(--fail-soft)"></div>'
            '<span class="mono" style="position: absolute; left: 8px; bottom: 7px; font-size: 10px; padding: 2px 7px; border-radius: 5px; background: var(--scrim); color: #fff">at failure · 14:20:53</span></div>'
            '<div style="display: grid; grid-template-columns: 80px 1fr; gap: 7px 12px; font-size: 12.5px"><span style="color: var(--tx3)">Error</span><span>Not found after 30 s</span>'
            '<span style="color: var(--tx3)">Looked for</span><span class="mono" style="font-size: 11.5px">label “Card number” in frame “card”</span>'
            '<span style="color: var(--tx3)">Network</span><span>12 calls, all answered · no 4xx/5xx</span></div>'
            '<div style="display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: 11px; background: var(--acc-soft); border: 1px solid var(--acc-line)">'
            '<span style="font-size: 12.5px"><b>A backup found 1 likely match:</b> the label now reads “Card no.”</span>'
            '<button class="btn btn-pri" style="width: 100%">' + ic('check', 14, 2.4) + ' Accept new locator</button></div>'
            '<a href="#" style="font-size: 12.5px; font-weight: 600">Saved HTML, full error and network log</a></section>'
            '<section class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px"><div style="display: flex; align-items: center; gap: 8px"><span class="ttl" style="font-size: 16px">This test, last 8 runs</span><span style="flex-grow: 1"></span><span style="font-size: 12px; color: var(--tx3)">minutes · Sep</span></div>'
            '<div style="display: flex; align-items: flex-end; gap: 12px; height: 76px">' + hist + '</div>'
            '<span style="font-size: 12px; color: var(--tx2)">First failure. It passed 7 times in a row before the site update on 25 Sep.</span></section></div></div>'
            '</main></div></div>')
    return body, w, h


def results_compare():
    w, h = 1440, 900
    runs = ['09-18', '09-19', '09-22', '09-23', '09-24', '09-24', '09-25', '09-26']
    envs = ['UAT', 'UAT', 'QA', 'UAT', 'UAT', 'PROD', 'UAT', 'UAT']
    marks = {2: 'workbook edited', 6: 'site 4.19'}
    data = [('tx', 'Owner_CRVD', 'PPPPP-PF'), ('tx', 'ANZ', 'PPPPP-PF'), ('tx', 'Owner_RVD', 'PPPFFPPP'), ('tx', 'PostDeparture', 'PPPPP-PP'), ('tx', 'Travelkore', 'PPPPP-PP'),
            ('qf', 'Qantas#1', 'PPPPPPPP'), ('qf', 'Qantas#2', 'PFPPFPPF'), ('qf', 'AgentStandAlone#1', 'PPPPPPPP'), ('qf', 'Qantas_AgentPortal#1', 'PPPPPPPP'),
            ('ex', 'USClaims#1', 'PPPPP-PP'), ('ex', 'US_EXPClaims#1', 'PPPPP-FF'), ('ex', 'US_EXPClaimsStatus#1', 'PPPPP-SS')]
    cc = {'P': 'var(--pass)', 'F': 'var(--fail)', 'S': 'var(--pend)', '-': 'transparent'}
    colors = {b['id']: b['color'] for b in WB}
    head = ('<div style="display: grid; grid-template-columns: 240px repeat(8, minmax(0, 1fr)) 160px; gap: 6px; align-items: end; padding: 0 16px 8px">'
            '<span class="lbl">Test</span>' + ''.join('<span style="display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 11px"><span class="tag %s" style="height: 17px; font-size: 9.5px; visibility: %s">%s</span><b class="mono">%s</b><span style="color: %s">%s</span></span>'
                                                    % ('tag-warn', 'visible' if i in marks else 'hidden', marks.get(i, '.'), r, 'var(--fail)' if envs[i] == 'PROD' else 'var(--tx3)', envs[i]) for i, r in enumerate(runs))
            + '<span class="lbl">Verdict</span></div>')
    body_rows = ''
    for wid, name, seq in data:
        verdict = 'flaky' if seq.count('F') >= 2 and not seq.endswith('FF') and name != 'Owner_RVD' else ('broke on 25 Sep' if seq.endswith('F') else ('failing 2 runs' if seq.endswith('FF') else ('fixed' if 'F' in seq else 'stable')))
        if name == 'Owner_RVD': verdict = 'fixed on 24 Sep'
        if seq.endswith('SS'): verdict = 'skipped: waits on US_EXPClaims#1'
        vcol = {'flaky': 'tag-warn', 'stable': 'tag-pass'}.get(verdict.split(':')[0], 'tag-fail' if 'broke' in verdict or 'failing' in verdict else '')
        body_rows += ('<div style="display: grid; grid-template-columns: 240px repeat(8, minmax(0, 1fr)) 160px; gap: 6px; align-items: center; padding: 5px 16px; border-top: 1px solid var(--line)">'
                      '<span style="display: flex; align-items: center; gap: 8px; min-width: 0"><span class="pdot" style="background: %s"></span><span class="trunc" style="font-size: 13px; font-weight: 600">%s</span></span>' % (colors[wid], name)
                      + ''.join('<span style="height: 22px; border-radius: 5px; background: %s; %s" title="%s"></span>' % (cc[c], 'border: 1px dashed var(--line2)' if c == '-' else '', {'P': 'passed', 'F': 'failed', 'S': 'skipped', '-': 'not in this run'}[c]) for c in seq)
                      + '<span><span class="tag %s">%s</span></span></div>' % (vcol, verdict))
    body = (root_open(w, h, 'dark') + app_header('Results') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + results_side('b1')
            + '<main style="flex-grow: 1; min-width: 0; padding: 28px 34px; display: flex; flex-direction: column; gap: 16px">'
            '<div style="display: flex; align-items: flex-end; gap: 12px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">Compare</span>'
            '<span class="disp" style="font-size: 28px; font-weight: 700">Last 8 runs, all 3 workbooks</span></div><span style="flex-grow: 1"></span>'
            '<div class="seg" style="width: 300px"><span class="on">Pass / fail</span><span>Duration</span><span>Two runs</span></div><button class="btn">' + ic('download', 14) + ' CSV</button></div>'
            '<div style="display: flex; gap: 8px; flex-wrap: wrap">' + ''.join('<span class="chip %s">%s</span>' % (c, t) for t, c in (('Travelex', ''), ('Qantas Staff Daily', ''), ('Claims US Expedia', ''), ('UAT + QA + PROD', 'chip-acc'), ('Hide stable tests', ''))) + '</div>'
            '<section class="card" style="padding: 14px 0 8px">' + head + body_rows + '</section>'
            '<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px">'
            '<div class="bn bn-fail">' + ic('warn', 15, 2, 'color: var(--fail)') + '<span><b>2 tests broke on 25 Sep</b>, the day the Travelex site moved to 4.19. Both fail on the Payment page.</span></div>'
            '<div class="bn bn-warn">' + ic('repeat', 15, 2, 'color: var(--warn)') + '<span><b>Qantas#2 is flaky:</b> 3 of 8 runs failed, at different steps each time. Worth a look before trusting its result.</span></div>'
            '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Dashed = not in that run. Markers show when a workbook was edited in Build or the site version changed.</span></div></div>'
            '</main></div></div>')
    return body, w, h


if __name__ == '__main__':
    write('RunSetup.dc.html', page('New run · many workbooks', SETUP, 1440, 1320, setup_js('order')))
    write('RunSetupTimeline.dc.html', page('New run · timeline plan', SETUP, 1440, 1320, setup_js('time')))
    b, w, h = live_batch(); write('RunLiveBatch.dc.html', page('Live batch', b, w, h))
    b, w, h = results_home(); write('ResultsHome.dc.html', page('Results home', b, w, h))
    b, w, h = results_test(); write('ResultsTest.dc.html', page('Results · one test', b, w, h))
    b, w, h = results_compare(); write('ResultsCompare.dc.html', page('Results · compare runs', b, w, h))
