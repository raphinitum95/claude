"""Workbook map (first screen, Q22/Q46) in both themes, and the variable map."""
from common import *

W, H = 1440, 960


def wb_header(active_tab):
    tabs_ = ''.join(
        '<a href="#" %s style="height: 32px; display: flex; align-items: center; gap: 7px; padding: 0 12px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none; %s">%s %s</a>'
        % ((('aria-current="page"', 'background: var(--surface3); color: var(--tx); box-shadow: 0 0 0 1px var(--line2)') if t == active_tab else ('', 'color: var(--tx2)')) + (ic(i, 14), t))
        for t, i in (('Tests', 'layers'), ('Variables', 'braces'), ('Scenarios', 'sync'), ('Environments', 'globe'), ('Page fingerprints', 'gate')))
    return (
        header('Build', middle='<span class="trunc" style="font-size: 13px; color: var(--tx3)">workbooks/</span>',
               right=('<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--tx3)">' + ic('check', 13, 2.4, 'color: var(--pass)') + ' Draft autosaved 09:41</span>'
                      '<button class="btn btn-sm chip-warn" style="border-radius: 8px">' + ic('warn', 14) + ' Problems 7</button>'
                      '<button class="icon-btn" aria-label="History">' + ic('history', 15) + '</button>'
                      '<button class="btn btn-pri">' + ic('download', 15, 2) + ' Save to Excel</button>'))
        + '<div style="flex: none; padding: 20px 28px 0; display: flex; flex-direction: column; gap: 14px; border-bottom: 1px solid var(--line); background: var(--rail)">'
        '<div style="display: flex; align-items: flex-end; gap: 16px">'
        '<div style="display: flex; flex-direction: column; gap: 4px; min-width: 0"><span class="eyebrow">Workbook</span>'
        '<div style="display: flex; align-items: center; gap: 10px"><span class="disp" style="font-size: 30px; font-weight: 700; line-height: 1.1">Travelex Regression v9.1</span>'
        '<button class="btn btn-ghost btn-sm" aria-label="Rename workbook">' + ic('pencil', 14) + '</button></div>'
        '<span class="mono" style="font-size: 12px; color: var(--tx3)">UAT_AEM_Travelex Regression_v9.1.xlsx · 11 tests · 52 variables · saved to Excel 26 Sep 09:12</span></div>'
        '<span style="flex-grow: 1"></span>'
        '<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">Environment</span><div class="seg" style="width: 250px"><span>QA</span><span class="on uat">UAT</span><span>PROD</span></div></div>'
        '<button class="btn">' + ic('settings', 14) + ' Settings</button>'
        '<button class="btn">' + ic('dup', 14) + ' Duplicate</button>'
        '<button class="btn">' + ic('rec', 14, 2, 'color: var(--fail)') + ' Record a test</button>'
        '<button class="btn btn-pri">' + ic('plus', 14, 2.2) + ' New test ' + ic('chevron', 13, 2) + '</button></div>'
        '<nav style="display: flex; gap: 4px; padding-bottom: 10px" aria-label="Workbook views">' + tabs_ + '</nav></div>')


CARD_W, CARD_H = 318, 150
TESTS = [
    # name, kind, steps, last, on, params, tags, comment, x, y, order, needs, provides
    ('Owner_CRVD', 'web', 287, 'fail', True, 'Params_1', ['purchase', 'smoke'], 'Full purchase, 2 travelers', 32, 28, 1, 14, 4),
    ('quotePrice#1', 'api', 9, 'pass', True, '—', ['api'], 'Called by Owner_CRVD at step 182', 430, 28, '', 3, 2),
    ('Preview', 'web', 64, 'pass', True, 'Params_1', ['quote'], 'Opens a saved quote', 828, 28, 3, 1, 0),
    ('policyRecord#1', 'xml', 8, 'pass', True, '—', ['xml'], 'Called by Owner_CRVD at step 285', 430, 206, '', 1, 1),
    ('PostDeparture', 'web', 77, 'pass', True, 'Params_1', ['servicing'], 'Claims after the trip starts', 828, 206, 2, 2, 0),
    ('Owner_RVD', 'web', 214, 'pass', True, 'Params_1', ['purchase'], '', 32, 384, 4, 11, 2),
    ('Owner_AZ', 'web', 188, 'pass', True, 'Params_1', ['purchase'], 'Arizona rules', 430, 384, 5, 11, 2),
    ('ANZ', 'web', 240, 'pass', True, 'Params_1', ['purchase', 'anz'], '', 828, 384, 6, 12, 2),
    ('WM', 'web', 121, 'pass', True, 'Params_1', ['partner'], 'White-label partner site', 32, 562, 7, 9, 1),
    ('CW', 'web', 96, 'pend', False, 'Params_1', ['partner'], 'Off until the partner page ships', 430, 562, '–', 9, 1),
    ('Travelkore', 'web', 133, 'pass', True, 'Params_1', ['partner'], '', 828, 562, 8, 10, 1),
]
LAST = {'pass': ('p-pass', 'Passed', 'check'), 'fail': ('p-fail', 'Failed', 'x'), 'pend': ('p-pend', 'Not run', 'dashed')}
KNAME = {'web': 'Website', 'api': 'API', 'xml': 'XML'}


def test_card(t):
    name, kind, steps, last, on, params, tags, comment, x, y, order, needs, provides = t
    lc, lt, li = LAST[last]
    return (
        '<div class="card" style="position: absolute; left: %dpx; top: %dpx; width: %dpx; height: %dpx; padding: 12px 14px; display: flex; flex-direction: column; gap: 9px; border-radius: 13px; %s">'
        % (x, y, CARD_W, CARD_H, 'opacity: .6' if not on else ('border-color: var(--acc); box-shadow: 0 0 0 3px var(--acc-soft)' if name == 'Owner_CRVD' else ''))
        + '<div style="display: flex; align-items: center; gap: 8px">'
        + ('<span class="mono" style="width: 20px; height: 20px; border-radius: 6px; display: grid; place-items: center; font-size: 10.5px; color: var(--tx3); border: 1px solid var(--line2)" title="Run order">%s</span>' % order if order != '' else
           '<span style="width: 20px; display: inline-flex; color: var(--tx3)" title="Runs when called">' + ic('call', 14) + '</span>')
        + '<span style="color: var(--k-%s); display: inline-flex">%s</span>' % ({'web': 'nav', 'api': 'api', 'xml': 'xml'}[kind], ic(kind, 16))
        + '<a href="Editor.dc.html" class="disp trunc" style="font-size: 16px; font-weight: 700; color: var(--tx)">%s</a>' % name
        + '<span style="flex-grow: 1"></span>' + sw(on, 'Runs in this workbook') + '</div>'
        + '<div style="display: flex; align-items: center; gap: 6px"><span class="pill %s">%s %s</span><span class="mono" style="font-size: 11.5px; color: var(--tx3)">%s · %d steps</span>'
        % (lc, ic(li, 11, 3), lt, KNAME[kind], steps)
        + '<span style="flex-grow: 1"></span><button class="chip" style="height: 24px; font-size: 11.5px">' + ic('table', 12) + ' %s</button></div>' % params
        + '<div style="display: flex; align-items: center; gap: 5px">' + ''.join('<span class="tag">%s</span>' % g for g in tags)
        + '<span style="flex-grow: 1"></span><span style="font-size: 11.5px; color: var(--tx3)">needs %d · gives %d</span></div>' % (needs, provides)
        + '<span class="trunc" style="font-size: 12px; color: var(--tx2)">%s</span>' % (comment or '<span style="color: var(--tx4)">Add a comment</span>')
        + '</div>')


def lines():
    # anchors
    def R(x, y): return (x + CARD_W, y + CARD_H / 2)
    def L(x, y): return (x, y + CARD_H / 2)
    segs = []
    def solid(a, b, label, lx, ly):
        (x1, y1), (x2, y2) = a, b
        mx = (x1 + x2) / 2
        segs.append('<path d="M%d,%d C%d,%d %d,%d %d,%d" fill="none" stroke="var(--acc)" stroke-width="2"></path><path d="M%d,%d l-7,-4 v8 z" fill="var(--acc)"></path>' % (x1, y1, mx, y1, mx, y2, x2 - 1, y2, x2, y2))
        segs.append('<text x="%d" y="%d" fill="var(--acc)" font-size="11" font-family="JetBrains Mono, monospace">%s</text>' % (lx, ly, label))
    def dashed(a, b, label, lx, ly):
        (x1, y1), (x2, y2) = a, b
        mx = (x1 + x2) / 2
        segs.append('<path d="M%d,%d C%d,%d %d,%d %d,%d" fill="none" stroke="var(--k-input)" stroke-width="1.8" stroke-dasharray="5 5"></path><path d="M%d,%d l-7,-4 v8 z" fill="var(--k-input)"></path>' % (x1, y1, mx, y1, mx, y2, x2 - 1, y2, x2, y2))
        segs.append('<text x="%d" y="%d" fill="var(--k-input)" font-size="11" font-family="JetBrains Mono, monospace">%s</text>' % (lx, ly, label))
    solid(R(32, 28), L(430, 28), 'calls', 360, 96)
    solid(R(32, 28), L(430, 206), 'calls', 360, 240)
    dashed(R(430, 28), L(828, 28), 'QUOTE_ID', 752, 96)
    dashed(R(430, 206), L(828, 206), 'POLICY_STATUS', 736, 274)
    # Owner_CRVD -> PostDeparture (needs POLICY_NO): route under the api/xml cards
    segs.append('<path d="M190,178 C190,370 600,360 700,360 S800,300 828,290" fill="none" stroke="var(--k-input)" stroke-width="1.8" stroke-dasharray="5 5"></path><path d="M828,290 l-8,-2 l5,7 z" fill="var(--k-input)"></path>')
    segs.append('<text x="470" y="374" fill="var(--k-input)" font-size="11" font-family="JetBrains Mono, monospace">POLICY_NO</text>')
    return '<svg width="1180" height="740" style="position: absolute; left: 0; top: 0" aria-hidden="true">' + ''.join(segs) + '</svg>'


def run_order_panel():
    rows = [('1', 'Owner_CRVD', 'first: others need its values'), ('↳', 'quotePrice#1', 'runs inside Owner_CRVD, step 182'), ('↳', 'policyRecord#1', 'runs inside Owner_CRVD, step 285'),
            ('2', 'PostDeparture', 'needs POLICY_NO, POLICY_STATUS'), ('3', 'Preview', 'needs QUOTE_ID'), ('4', 'Owner_RVD', 'no dependency · your order'),
            ('5', 'Owner_AZ', 'no dependency · your order'), ('6', 'ANZ', 'no dependency · your order'), ('7', 'WM', 'no dependency · your order'), ('8', 'Travelkore', 'no dependency · your order'),
            ('–', 'CW', 'off')]
    return ('<aside style="width: 300px; flex: none; border-left: 1px solid var(--line); background: var(--rail); display: flex; flex-direction: column; gap: 14px; padding: 18px 16px; overflow: auto" class="scroll">'
            '<div style="display: flex; align-items: center; gap: 8px"><span class="ttl" style="font-size: 17px">Run order</span><span style="flex-grow: 1"></span><span class="tag">auto</span></div>'
            '<span style="font-size: 12px; color: var(--tx3)">Dependencies decide the order. Drag tests that don\'t depend on anything.</span>'
            '<div style="display: flex; flex-direction: column; gap: 3px">'
            + ''.join('<div style="display: flex; align-items: center; gap: 9px; padding: 6px 8px; border-radius: 8px; %s"><span class="mono" style="width: 18px; font-size: 11px; color: var(--tx3); text-align: center">%s</span>'
                      '<div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1"><span style="font-size: 13px; font-weight: 600">%s</span><span class="trunc" style="font-size: 11.5px; color: var(--tx3)">%s</span></div>%s</div>'
                      % ('background: var(--surface)' if n.isdigit() and int(n) <= 3 else '', n, name, why, ('<span style="color: var(--tx4); display: inline-flex">' + ic('grip', 14) + '</span>') if 'your order' in why else '')
                      for n, name, why in rows)
            + '</div><div class="hr"></div>'
            '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Legend</span>'
            '<span style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx2)"><svg width="30" height="8"><path d="M0,4 H30" stroke="var(--acc)" stroke-width="2"></path></svg> calls it mid-way, then carries on</span>'
            '<span style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx2)"><svg width="30" height="8"><path d="M0,4 H30" stroke="var(--k-input)" stroke-width="1.8" stroke-dasharray="5 5"></path></svg> needs a value from it</span>'
            '<span style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx2)"><span class="pdot" style="background: var(--pass)"></span> last result · switch = runs</span></div>'
            '<div class="hr"></div>'
            '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">New test types</span>'
            + ''.join('<div style="display: flex; align-items: center; gap: 9px; font-size: 12.5px; color: %s">%s<span style="flex-grow: 1">%s</span>%s</div>'
                      % ('var(--tx)' if on else 'var(--tx3)', ic(i, 15), t, '' if on else '<span class="tag">later</span>')
                      for i, t, on in (('web', 'Website', True), ('api', 'API (REST)', True), ('xml', 'XML', True), ('mail', 'Email inbox', False), ('filetext', 'Documents (PDF, files)', False),
                                       ('db', 'Database (SQL)', False), ('queue', 'SOAP / message queues', False)))
            + '</div></aside>')


def workbook_map(theme):
    body = root_open(W, H, theme) + wb_header('Tests') + \
        '<div style="flex-grow: 1; display: flex; min-height: 0">' \
        '<main class="scroll" style="flex-grow: 1; min-width: 0; overflow: auto; position: relative; background-image: linear-gradient(var(--grid) 1px, transparent 1px), linear-gradient(90deg, var(--grid) 1px, transparent 1px); background-size: 44px 44px">' \
        '<div style="position: relative; width: 1180px; height: 740px; margin: 0 0 0 0">' + lines() + ''.join(test_card(t) for t in TESTS) + '</div></main>' \
        + run_order_panel() + '</div></div>'
    return body


def variable_map():
    groups = [
        ('Environment', [('Domain', 'DOMAIN', 'env', 'UAT: uat.travelex-insurance.test', ''), ('Base URL', 'BASE_URL', 'env', 'https://{DOMAIN}', ''), ('API key', 'API_KEY', 'env', 'missing on PROD', 'warn')]),
        ('Secrets', [('Test card', 'SECRET:TEST_CARD', 'sec', '••••', ''), ('Card CVV', 'SECRET:CARD_CVV', 'sec', '••••', ''), ('UAT password', 'SECRET:UAT_PASSWORD', 'sec', '••••', '')]),
        ('Set by steps', [('Policy number', 'POLICY_NO', 'set', 'Owner_CRVD · step 272', ''), ('Quoted premium', 'API_PREMIUM', 'set', 'quotePrice#1 · step 6', ''), ('Quote id', 'QUOTE_ID', 'set', 'quotePrice#1 · step 7', ''),
                          ('Policy status', 'POLICY_STATUS', 'set', 'policyRecord#1 · step 7', ''), ('Discount', 'DISCOUNT', 'set', 'Owner_CRVD · steps 88, 90', ''), ('Run id', 'RUN_ID', 'set', '=TEXT(NOW(),"yymmddhhmm")', '')]),
        ('Params_1 · trip', [('Destination', 'DESTINATION', 'data', 'Italy · Japan · Mexico …', ''), ('Plan', 'PLAN', 'data', 'Basic · Max', ''), ('Promo code', 'PROMO_CODE', 'data', 'empty in 5 rows', ''),
                             ('Disclosure 35', 'DISCLOSURE_35', 'data', 'used, never set', 'fail')]),
        ('Params_2 · travelers', [('Traveler first name', 'FIRST_NAME', 'data', 'Jane · Omar', ''), ('Traveler last name', 'LAST_NAME', 'data', 'Doe · Haddad', '')]),
    ]
    items = []
    for g, vs in groups:
        items.append('<span class="lbl" style="padding: 10px 8px 4px; display: block">%s</span>' % g)
        for label, tok, kind, sub, st in vs:
            on = tok == 'POLICY_NO'
            dot = {'warn': '<span class="pdot" style="background: var(--warn)"></span>', 'fail': '<span class="pdot" style="background: var(--fail)"></span>'}.get(st, '')
            items.append('<button class="rail-item%s" style="height: auto; padding: 6px 10px; align-items: flex-start">'
                         '<span style="color: %s; display: inline-flex; margin-top: 2px">%s</span><span style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1">'
                         '<span style="font-weight: 600; color: var(--tx)">%s</span><span class="mono trunc" style="font-size: 10.5px; color: var(--tx3)">{%s} · %s</span></span>%s</button>'
                         % (' on' if on else '', {'env': 'var(--k-nav)', 'sec': 'var(--tx3)', 'set': 'var(--k-save)', 'data': 'var(--k-input)'}[kind],
                            ic({'env': 'globe', 'sec': 'lock', 'set': 'braces', 'data': 'table'}[kind], 14), label, tok, sub, dot))
    left = ('<aside class="scroll" style="width: 340px; flex: none; border-right: 1px solid var(--line); background: var(--rail); overflow: auto; padding: 14px 10px">'
            '<div class="field" style="margin-bottom: 6px">' + ic('search', 14) + '<span style="color: var(--tx3); font-size: 12.5px">Find a variable</span></div>' + ''.join(items) + '</aside>')

    def node(x, y, w, title, sub, tone, link=True):
        col = {'set': 'var(--k-save)', 'use': 'var(--k-input)'}[tone]
        return ('<a href="Editor.dc.html" class="card" style="position: absolute; left: %dpx; top: %dpx; width: %dpx; padding: 10px 12px; display: flex; flex-direction: column; gap: 3px; border-radius: 11px; border-color: color-mix(in srgb, %s 45%%, var(--line)); color: var(--tx); text-decoration: none">'
                '<span style="font-size: 13px; font-weight: 600">%s</span><span class="mono" style="font-size: 11px; color: var(--tx3)">%s</span></a>' % (x, y, w, col, title, sub))
    uses = [('Owner_CRVD · step 273', 'Check Policy number contains TX'), ('Owner_CRVD · step 281', 'Tab 2 · Check Policy number is {POLICY_NO}'),
            ('policyRecord#1 · request', 'GET /policy/{POLICY_NO}.xml'), ('policyRecord#1 · step 3', 'Check /Policy/Number is {POLICY_NO}'),
            ('PostDeparture · step 4', 'Type {POLICY_NO} into Policy number'), ('PostDeparture · step 12', 'Check Claim policy is {POLICY_NO}')]
    graph = ('<div style="position: relative; height: 470px">'
             '<svg width="760" height="470" style="position: absolute; left: 0; top: 0" aria-hidden="true">'
             + ''.join('<path d="M250,215 C330,215 330,%d 410,%d" fill="none" stroke="var(--k-input)" stroke-width="1.8"></path>' % (30 + i * 76, 30 + i * 76) for i in range(len(uses)))
             + '</svg>'
             + node(0, 180, 250, 'Owner_CRVD · step 272', 'Save Policy number text', 'set')
             + ''.join(node(410, 6 + i * 76, 330, u, d, 'use') for i, (u, d) in enumerate(uses))
             + '</div>')
    right = ('<main class="scroll" style="flex-grow: 1; min-width: 0; overflow: auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 18px">'
             '<div style="display: flex; align-items: flex-start; gap: 14px"><div style="display: flex; flex-direction: column; gap: 4px">'
             '<span class="disp" style="font-size: 26px; font-weight: 700">Policy number</span>'
             '<span class="mono" style="font-size: 12.5px; color: var(--tx3)">{POLICY_NO} · set by 1 step · used by 6 steps in 3 tests</span></div><span style="flex-grow: 1"></span>'
             '<button class="btn">' + ic('pencil', 14) + ' Rename everywhere</button><button class="btn">' + ic('search', 14) + ' Find uses</button></div>'
             '<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px">'
             '<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Friendly label</span><span style="font-weight: 600">Policy number</span></div>'
             '<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Last value · run 0925-1412</span><span class="mono">TX-40218873</span></div>'
             '<div class="card" style="padding: 12px 14px; display: flex; flex-direction: column; gap: 4px"><span class="lbl">Kind</span><span style="font-weight: 600">Saved by a step, shared across the run</span></div></div>'
             '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Owner_CRVD provides it, so PostDeparture runs after Owner_CRVD. Click any box to jump to that step.</span></div>'
             '<div style="display: flex; gap: 40px; font-size: 12px; color: var(--tx3)"><span class="lbl" style="width: 250px">Set by</span><span class="lbl" style="margin-left: 120px">Used by</span></div>'
             + graph + '</main>')
    return root_open(W, H, 'dark') + wb_header('Variables') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + left + right + '</div></div>'


if __name__ == '__main__':
    write('WorkbookMap.dc.html', page('Workbook map', workbook_map('dark'), W, H))
    write('WorkbookMapLight.dc.html', page('Workbook map · light', workbook_map('light'), W, H))
    write('VariableMap.dc.html', page('Variable map', variable_map(), W, H))
