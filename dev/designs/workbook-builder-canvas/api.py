"""API/XML test editor (Q18/Q19), request import options, and the concurrency scenario board (Q35/Q36)."""
from common import *

W, H = 1440, 960


def api_toolbar():
    return ('<div style="height: 52px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 16px; border-bottom: 1px solid var(--line); background: var(--rail)">'
            '<span class="chip" style="height: 28px; color: var(--k-api)">' + ic('api', 14) + ' API test</span>'
            '<span class="mono" style="font-size: 12px; color: var(--tx3)">9 steps · called by Owner_CRVD at step 182</span>'
            '<span style="width: 1px; height: 22px; background: var(--line)"></span>'
            '<button class="chip">' + ic('arrowr', 13, 2) + ' Needs 4</button><button class="chip">' + ic('arrowl', 13, 2) + ' Provides 2</button>'
            '<span style="flex-grow: 1"></span>'
            '<label style="display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--tx3)">Building with<button class="chip chip-acc" style="height: 30px">' + ic('table', 13) + ' Row 1 · NE · Basic ' + ic('chevron', 13, 2) + '</button></label>'
            '<div class="seg" style="width: 190px"><span class="on">JSON</span><span>XML</span></div></div>')


def steps_col():
    steps = [('1', 'api', 'Send', 'POST quote request', True), ('2', 'check', 'Check', 'status is 200', False), ('3', 'check', 'Check', '$.plan.code is {PLAN}', False),
             ('4', 'check', 'Check', '$.travelers.length is {TRAVELER_COUNT}', False), ('5', 'check', 'Check', '$.currency is USD', False),
             ('6', 'save', 'Save', '$.premium.total as {API_PREMIUM}', False), ('7', 'save', 'Save', '$.quoteId as {QUOTE_ID}', False),
             ('8', 'check', 'Check', 'plans[code = {PLAN}].eligible is true', False), ('9', 'save', 'Save', 'header x-request-id as {REQ_ID}', False)]
    rows = ''.join('<button class="scard" style="min-height: 38px; font-size: 12.5px; padding: 5px 10px; %s"><span class="mono" style="width: 16px; font-size: 11px; color: var(--tx3)">%s</span>%s<span class="trunc mono" style="font-size: 11.5px">%s</span></button>'
                   % ('border-color: var(--acc); background: var(--sel-bg)' if on else '', n, badge(k, v), t.replace('{', '').replace('}', '')) for n, k, v, t, on in steps)
    return ('<div class="scroll" style="width: 300px; flex: none; border-right: 1px solid var(--line); padding: 14px 12px; display: flex; flex-direction: column; gap: 5px; overflow: auto">'
            '<div style="display: flex; align-items: center; justify-content: space-between; padding: 0 2px 6px"><span class="lbl">Steps</span><button class="btn btn-ghost btn-sm">' + ic('plus', 13, 2.2) + ' Add</button></div>'
            + rows + '<span style="font-size: 11.5px; color: var(--tx3); padding: 8px 4px">Checks and saves are added by clicking values in the response →</span></div>')


def req_panel():
    tabs_ = '<div class="seg" style="width: 100%"><span class="on">Form</span><span>Paste cURL</span><span>Postman collection</span><span>From template</span></div>'
    hdrs = [('Content-Type', 'application/json', ''), ('Accept', 'application/json', ''), ('x-api-key', '{API_KEY}', 'env'), ('x-run-id', '{RUN_ID}', 'var')]
    htab = ''.join('<tr><td class="mono">%s</td><td>%s</td></tr>' % (k, (var(v.strip('{}'), v.strip('{}'), env=(t == 'env')) if t else '<span class="mono">%s</span>' % v)) for k, v, t in hdrs)
    body = ('<div class="mono" style="font-size: 12.5px; line-height: 1.9; padding: 12px 14px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line); color: var(--tx2)">'
            '{<br>&nbsp;&nbsp;"plan": "' + var('Plan', 'PLAN') + '",<br>&nbsp;&nbsp;"destination": "' + var('Destination', 'DESTINATION') + '",<br>'
            '&nbsp;&nbsp;"tripCost": ' + var('Trip cost', 'TRIP_COST') + ',<br>&nbsp;&nbsp;"travelers": ' + var('Traveler count', 'TRAVELER_COUNT') + ',<br>'
            '&nbsp;&nbsp;"promoCode": "' + var('Promo code', 'PROMO_CODE') + '",<br>&nbsp;&nbsp;"departDate": "' + var('Departure date', 'DEPART_DATE') + '"<br>}</div>')
    return ('<div class="scroll" style="flex-grow: 1; min-width: 0; padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; overflow: auto">'
            '<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="font-size: 12px; color: var(--tx3)">Step 1</span>' + badge('api', 'Send') +
            '<span class="disp" style="font-size: 19px; font-weight: 700">Price the quote</span></div>' + tabs_ +
            '<div style="display: flex; gap: 8px"><button class="btn" style="width: 96px; justify-content: space-between; color: var(--k-api)">POST ' + ic('chevron', 13, 2) + '</button>'
            '<div class="field" style="flex-grow: 1; min-height: 32px">' + var('Base URL', 'BASE_URL', env=True) + '<span class="mono" style="font-size: 12.5px">/bin/travelex/purchase/quote</span></div>'
            '<button class="btn btn-pri">' + ic('play', 12, 2) + ' Send now</button></div>'
            '<span style="font-size: 12px; color: var(--tx3)">Sends with UAT values and Row 1. Base URL and API key come from the environment table.</span>'
            '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Headers</span>'
            '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><tbody>' + htab + '</tbody></table></div></div>'
            '<div style="display: flex; flex-direction: column; gap: 6px"><div style="display: flex; align-items: center; gap: 8px"><span class="lbl">Body · JSON</span><span style="flex-grow: 1"></span>'
            '<button class="btn btn-ghost btn-sm">' + ic('braces', 13) + ' Insert variable</button></div>' + body + '</div></div>')


def resp_panel():
    def line(indent, key, val, kind='', sel=False, arr=False):
        vcol = {'n': 'var(--k-api)', 's': 'var(--k-check)', 'b': 'var(--k-nav)', '': 'var(--tx2)'}[kind]
        st = 'background: var(--acc-soft); box-shadow: inset 0 0 0 1px var(--acc-line);' if sel else ''
        return ('<button style="display: flex; align-items: center; gap: 6px; width: 100%%; height: 26px; padding: 0 8px 0 %dpx; border-radius: 6px; %s" class="mono">'
                '<span style="color: var(--tx3); font-size: 12px">%s</span><span style="font-size: 12px; color: %s">%s</span></button>' % (8 + indent * 18, st, key, vcol, val))
    tree = (line(0, '▾ {', '', '') + line(1, 'quoteId:', '"Q-2209-44817"', 's') + line(1, 'currency:', '"USD"', 's')
            + line(1, '▾ plan:', '{ … }', '') + line(2, 'code:', '"Basic"', 's') + line(1, '▾ premium:', '{ … }', '')
            + line(2, 'base:', '139.00', 'n') + line(2, 'fees:', '9.20', 'n') + line(2, 'total:', '148.20', 'n', True)
            + line(1, 'travelers:', '[ 2 items ]', '') + line(1, '▾ plans:', '[ 3 items ]', '') + line(2, '▸ 0:', '{ code: "Basic", eligible: true }', '')
            + line(2, '▸ 1:', '{ code: "Plus", eligible: true }', '') + line(2, '▸ 2:', '{ code: "Max", eligible: false }', '') + line(0, '}', '', ''))
    pop = ('<div class="menu" style="position: absolute; left: 150px; top: 262px; width: 330px; padding: 12px; display: flex; flex-direction: column; gap: 10px; z-index: 3">'
           '<div style="display: flex; align-items: center; gap: 8px"><b style="font-size: 13px">premium.total = 148.20</b><span style="flex-grow: 1"></span><span class="tag">number</span></div>'
           '<div style="display: flex; flex-wrap: wrap; gap: 4px">' + ''.join('<button class="btn btn-sm %s" style="font-weight: 500">%s</button>' % ('btn-pri' if t == 'Save as variable' else '', t)
                                                                           for t in ('Is', 'Contains', 'Greater than', 'Between', 'Matches pattern', 'Save as variable')) + '</div>'
           '<div class="field"><span class="var">' + ic('braces', 11, 2.2) + 'Quoted premium</span><span class="mono" style="font-size: 11px; color: var(--tx3)">{API_PREMIUM}</span></div>'
           '<span style="font-size: 12px; color: var(--tx2)">Path, written for you (you can edit it)</span>'
           '<div class="field mono" style="font-size: 12px">$.premium.total</div>'
           '<button class="btn btn-sm btn-pri">Add as step 6</button></div>')
    arr = ('<div class="menu" style="position: absolute; left: 150px; top: 568px; width: 340px; padding: 12px; display: flex; flex-direction: column; gap: 8px; z-index: 3">'
           '<b style="font-size: 13px">You clicked an item in a list. Which do you mean?</b>'
           '<button class="mitem">' + ic('target', 14) + '<span style="flex-grow: 1">This item <span class="mono" style="color: var(--tx3); font-size: 11px">plans[0]</span></span></button>'
           '<button class="mitem on">' + ic('braces', 14) + '<span style="flex-grow: 1">The item where code = <span class="var">Plan</span></span></button>'
           '<span class="mono" style="font-size: 11px; color: var(--tx3)">$.plans[?(@.code==\'{PLAN}\')].eligible</span></div>')
    return ('<div style="width: 520px; flex: none; border-left: 1px solid var(--line); background: var(--rail); display: flex; flex-direction: column; position: relative">'
            '<div style="padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 16px">Response</span>'
            '<span class="pill p-pass">200 OK</span><span class="mono" style="font-size: 11.5px; color: var(--tx3)">412 ms · UAT · 26 Sep 09:38</span><span style="flex-grow: 1"></span>'
            '<div class="seg" style="width: 150px"><span class="on">Tree</span><span>Raw</span></div></div>'
            '<span style="padding: 10px 16px 0; font-size: 12px; color: var(--tx3)">Click any value to check it or save it.</span>'
            '<div class="scroll" style="flex-grow: 1; overflow: auto; padding: 8px 10px">' + tree + '</div>' + pop + arr + '</div>')


def api_editor():
    return (root_open(W, H, 'dark') + header('Build', middle=('<span class="trunc" style="font-size: 13px; color: var(--tx3)">UAT_AEM_Travelex Regression_v9.1.xlsx</span>' + ic('chevr', 13, 2.2, 'color: var(--tx3)')
                                                             + '<span class="disp" style="font-size: 17px; font-weight: 700">quotePrice#1</span>'),
                                            right='<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--tx3)">' + ic('check', 13, 2.4, 'color: var(--pass)') + ' Draft autosaved 09:41</span><button class="btn btn-pri">' + ic('download', 15, 2) + ' Save to Excel</button>')
            + api_toolbar() + '<div style="flex-grow: 1; display: flex; min-height: 0">' + rail_workbook('quotePrice#1')
            + '<div style="flex-grow: 1; min-width: 0; display: flex">' + steps_col() + req_panel() + resp_panel() + '</div></div></div>')


def api_import():
    w, h = 1440, 640
    col = lambda title, sub, inner, on=False: ('<div class="card" style="flex: 1; min-width: 0; padding: 18px; display: flex; flex-direction: column; gap: 12px; %s">'
                                               '<span class="ttl" style="font-size: 17px">%s</span><span style="font-size: 12.5px; color: var(--tx3)">%s</span>%s</div>'
                                               % ('border-color: var(--acc)' if on else '', title, sub, inner))
    curl = ('<div class="mono" style="font-size: 11.5px; line-height: 1.7; padding: 12px; border-radius: 10px; background: var(--bg); border: 1px solid var(--line); color: var(--tx2); word-break: break-all">'
            'curl -X POST \'https://uat.travelex-insurance.test/bin/travelex/purchase/quote\' -H \'Content-Type: application/json\' -H \'x-api-key: ••••••\' --data \'{"plan":"Basic","destination":"Italy","tripCost":2500,"travelers":2}\'</div>'
            '<span class="lbl">We found</span>'
            '<div style="display: flex; flex-direction: column; gap: 6px; font-size: 12.5px">'
            '<span style="display: flex; gap: 8px; align-items: center">' + ic('check', 13, 2.4, 'color: var(--pass)') + ' Domain → ' + var('Base URL', 'BASE_URL', env=True) + '</span>'
            '<span style="display: flex; gap: 8px; align-items: center">' + ic('check', 13, 2.4, 'color: var(--pass)') + ' API key → ' + var('API key', 'API_KEY', env=True) + ' (not stored in the sheet)</span>'
            '<span style="display: flex; gap: 8px; align-items: center">' + ic('check', 13, 2.4, 'color: var(--pass)') + ' 4 body values match Row 1 → ' + var('Plan') + var('Destination') + ' …</span></div>'
            '<button class="btn btn-pri">Create request</button>')
    postman = ('<div class="field">' + ic('upload', 14) + '<span class="mono" style="font-size: 12px">Travelex Quote API.postman_collection.json</span></div>'
               '<div style="display: flex; flex-direction: column; gap: 4px">'
               + ''.join('<button class="mitem" style="height: 32px">%s<span class="badge k-api" style="width: 44px">%s</span><span class="mono trunc" style="font-size: 12px; flex-grow: 1">%s</span></button>' % (cbx(on), m, p)
                         for on, m, p in ((True, 'POST', '/purchase/quote'), (True, 'GET', '/purchase/quote/:quoteId'), (False, 'POST', '/purchase/bind'), (False, 'GET', '/policy/:policyNo')))
               + '</div><span style="font-size: 12px; color: var(--tx3)">Postman variables like quoteId are mapped to workbook variables in the next step.</span>'
               '<button class="btn btn-pri">Import 2 requests</button>')
    tmpl = ('<div class="field">' + ic('search', 14) + '<span style="font-size: 12.5px; color: var(--tx3)">api_templates/</span></div>'
            '<div style="display: flex; flex-direction: column; gap: 4px">'
            + ''.join('<button class="mitem%s">%s<span class="mono trunc" style="font-size: 12px; flex-grow: 1">%s</span><span class="tag">%s</span></button>' % (' on' if on else '', ic('filetext', 14), f, t)
                      for on, f, t in ((True, 'quote_request.json', 'Replace 6'), (False, 'bind_request.json', 'Replace 11'), (False, 'policy_lookup.xml', 'Output 3')))
            + '</div><div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Template field</th><th>Filled with</th></tr></thead><tbody>'
            + ''.join('<tr><td class="mono">%s</td><td>%s</td></tr>' % (a, b) for a, b in (('#PLAN#', var('Plan')), ('#DEST#', var('Destination')), ('#TRIPCOST#', var('Trip cost')), ('#PROMO#', '<span class="tag tag-warn">choose…</span>')))
            + '</tbody></table></div><button class="btn btn-pri">Use template</button>')
    body = (root_open(w, h, 'dark') + '<div style="padding: 26px 28px; display: flex; flex-direction: column; gap: 16px; height: 100%">'
            '<div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">New API request · three ways in</span>'
            '<span class="disp" style="font-size: 24px; font-weight: 700">Start from what you already have</span>'
            '<span style="font-size: 13px; color: var(--tx2)">The Form tab is always there. Recorded site traffic is not a source.</span></div>'
            '<div style="display: flex; gap: 16px; flex-grow: 1">'
            + col('Paste cURL', 'Copy as cURL from the browser or a colleague.', curl, True)
            + col('Postman collection', 'Pick the requests to bring in.', postman)
            + col('From an existing template', 'The Replace / Output files the runner already uses.', tmpl)
            + '</div></div></div>')
    return body, w, h


def scenario():
    w, h = 1440, 820
    lanes = [('A', 'PostDeparture', 'Row 1 · agent Ana', 'web'), ('B', 'PostDeparture', 'Row 2 · agent Ben', 'web'), ('C', 'policyRecord#1', 'Row 1', 'xml')]
    # timeline x positions for blocks per lane
    blocks = {
        'A': [(40, 150, 'Sign in', ''), (210, 170, 'Open policy {POLICY_NO}', ''), (400, 150, 'Edit address', ''), (640, 150, 'Save changes', 'side'), (820, 170, 'Check “Saved”', '')],
        'B': [(40, 150, 'Sign in', ''), (210, 170, 'Open policy {POLICY_NO}', ''), (400, 150, 'Edit phone', ''), (900, 150, 'Save changes', 'side'), (1070, 220, 'Check “Changed by another user”', '')],
        'C': [(1120, 170, 'Read policy record', ''), ],
    }
    lane_y = {'A': 40, 'B': 160, 'C': 280}
    parts = []
    for key, name, row, kind in lanes:
        y = lane_y[key]
        parts.append('<div style="position: absolute; left: 0; top: %dpx; width: 1100px; height: 1px; background: var(--line)"></div>' % (y + 70))
        for x, bw, t, flag in blocks[key]:
            t2 = t.replace('{POLICY_NO}', '<span class="var" style="font-size: 11px">Policy number</span>')
            parts.append('<div class="card" style="position: absolute; left: %dpx; top: %dpx; width: %dpx; height: 54px; padding: 8px 10px; display: flex; flex-direction: column; justify-content: center; gap: 3px; border-radius: 10px">'
                         '<span style="font-size: 12.5px; font-weight: 600; line-height: 1.25">%s</span>%s</div>'
                         % (x, y + 8, bw, t2, '<span class="tag tag-warn" style="align-self: flex-start">' + ic('bolt', 10) + ' side effects</span>' if flag == 'side' else ''))
    sync = ('<div style="position: absolute; left: 590px; top: 10px; width: 2px; height: 250px; background: var(--acc)"></div>'
            '<div style="position: absolute; left: 540px; top: -14px; padding: 2px 8px; border-radius: 6px; background: var(--acc); color: var(--acc-tx); font-size: 11px; font-weight: 700; white-space: nowrap">SYNC 1 · all wait here</div>')
    order = ('<svg width="1300" height="400" style="position: absolute; left: 0; top: 0; overflow: visible" aria-hidden="true">'
             '<path d="M715,110 C780,110 830,190 900,196" fill="none" stroke="var(--k-flow)" stroke-width="2" stroke-dasharray="6 4"></path><path d="M900,196 l-9,-5 l2,9 z" fill="var(--k-flow)"></path>'
             '<text x="760" y="140" fill="var(--k-flow)" font-size="11.5" font-family="JetBrains Mono, monospace">A before B</text>'
             '<path d="M1180,250 L1180,286" stroke="var(--k-flow)" stroke-width="2" stroke-dasharray="6 4"></path></svg>')
    lane_heads = ''.join('<div style="height: 120px; display: flex; align-items: center; gap: 10px; padding: 0 14px; border-bottom: 1px solid var(--line)">'
                         '<span class="mono" style="width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; background: var(--acc-soft); color: var(--acc); font-weight: 700">%s</span>'
                         '<div style="display: flex; flex-direction: column; min-width: 0"><span style="display: flex; align-items: center; gap: 6px; font-weight: 700">%s%s</span><span style="font-size: 12px; color: var(--tx3)">%s</span></div></div>'
                         % (k, ic(kind, 14), n, r) for k, n, r, kind in lanes)
    body = (root_open(w, h, 'dark') + header('Build', middle='<span class="trunc" style="font-size: 13px; color: var(--tx3)">Travelex Regression v9.1</span>' + ic('chevr', 13, 2.2, 'color: var(--tx3)') + '<span class="disp" style="font-size: 17px; font-weight: 700">Two agents edit one policy</span>',
                                             right='<button class="btn">' + ic('play', 12, 2) + ' Try it on UAT</button><button class="btn btn-pri">' + ic('download', 15, 2) + ' Save to Excel</button>')
            + '<div style="height: 52px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 16px; border-bottom: 1px solid var(--line); background: var(--rail)">'
            '<span class="chip" style="height: 28px">' + ic('sync', 14) + ' Scenario</span><span style="font-size: 12.5px; color: var(--tx3)">Runs as one unit and reports per lane. For concurrency cases, not load.</span>'
            '<span style="flex-grow: 1"></span><button class="btn btn-sm">' + ic('plus', 13, 2.2) + ' Lane</button><button class="btn btn-sm">' + ic('sync', 13) + ' Sync line</button><button class="btn btn-sm">' + ic('arrowr', 13) + ' Order marker</button></div>'
            '<div style="flex-grow: 1; display: flex; min-height: 0">'
            '<div style="width: 250px; flex: none; border-right: 1px solid var(--line); background: var(--rail); padding-top: 30px">' + lane_heads + '</div>'
            '<div class="scroll" style="flex-grow: 1; overflow: auto; position: relative; padding: 30px 0 0 20px"><div style="position: relative; width: 1320px; height: 380px">' + ''.join(parts) + sync + order + '</div>'
            '<div style="display: flex; gap: 12px; padding: 0 20px 20px 0">'
            '<div class="bn" style="flex: 1">' + ic('key', 15, 1.8, 'color: var(--tx3)') + '<span><b>Sign-in codes.</b> Ana and Ben use different users. If two lanes share a user, they get separate one-time-code windows, so the scenario takes about 30 s longer.</span></div>'
            '<div class="bn" style="flex: 1">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Lanes A and B are the same test with their own data row. Steps between sync lines run at the same time.</span></div></div></div>'
            '<aside style="width: 320px; flex: none; border-left: 1px solid var(--line); background: var(--rail); padding: 18px 16px; display: flex; flex-direction: column; gap: 14px">'
            '<span class="lbl">Selected</span><span class="ttl">Sync 1 · all wait here</span>'
            '<span style="font-size: 12.5px; color: var(--tx2)">Every lane stops here until all have arrived, then they carry on together.</span>'
            '<div style="display: flex; flex-direction: column; gap: 6px">'
            + ''.join('<div class="field" style="min-height: 34px"><span class="mono" style="color: var(--acc); font-weight: 700">%s</span><span style="flex-grow: 1">after “%s”</span></div>' % (k, t) for k, t in (('A', 'Edit address'), ('B', 'Edit phone')))
            + '<div class="field" style="min-height: 34px; color: var(--tx3)"><span class="mono" style="font-weight: 700">C</span><span style="flex-grow: 1">not in this sync</span></div></div>'
            '<div style="display: flex; justify-content: space-between; align-items: center"><span style="font-size: 13px; color: var(--tx2)">Give up waiting after</span><span class="mono" style="font-size: 12px">120 s</span></div>'
            '<div class="hr"></div><span class="lbl">Order marker</span><span style="font-size: 12.5px; color: var(--tx2)">A’s “Save changes” finishes before B’s starts.</span></aside>'
            '</div></div>')
    return body, w, h


if __name__ == '__main__':
    write('ApiEditor.dc.html', page('API test editor', api_editor(), W, H))
    b, w, h = api_import()
    write('ApiImport.dc.html', page('New API request', b, w, h))
    b, w, h = scenario()
    write('Scenario.dc.html', page('Concurrency scenario', b, w, h))
