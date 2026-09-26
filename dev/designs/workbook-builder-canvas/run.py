"""Run-section enhancements (screen group 6): New run with environment block + scenario, live scenario lanes, Results additions."""
from common import *


def app_header(active):
    return header(active, right=('<span class="chip">' + ic('cpu', 14) + ' 4 workers</span><span class="chip">' + ic('zap', 14) + ' Smart waits</span>'
                                 '<span class="chip mono">' + ic('lock', 14) + ' 127.0.0.1:8765 · local only</span><button class="icon-btn" aria-label="Switch between light and dark">' + ic('sun', 15) + '</button>'))


def runs_side(active_id=None):
    runs = [('0926-0944', 'Two agents edit one policy · 64%', 'run', True), ('0925-1412', 'Owner_CRVD, ANZ + 7 · 41m', 'fail', False), ('0925-0915', '11 tests · 52m', 'pass', False), ('0924-1630', 'Owner_RVD · 9m', 'pass', False)]
    items = ''
    for rid, sub, st, active in runs:
        on = rid == active_id
        glyph = ('<span style="width: 18px; height: 18px; display: grid; place-items: center; color: var(--acc)"><span class="dot" style="width: 10px; height: 10px"></span></span>' if st == 'run'
                 else '<span style="display: inline-flex; color: %s">%s</span>' % ('var(--pass)' if st == 'pass' else 'var(--fail)', ic('passc' if st == 'pass' else 'failc', 18)))
        items += ('<button style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; border-radius: 12px; width: 100%%; %s">%s<span style="min-width: 0; flex: 1"><span class="mono" style="display: block; font-size: 12px; font-weight: 500">%s</span>'
                  '<span style="display: block; font-size: 12px; color: var(--tx2); margin-top: 1px">%s</span>%s</span></button>'
                  % ('background: var(--surface); border: 1px solid var(--line2); box-shadow: var(--shadow)' if on else 'border: 1px solid transparent', glyph, rid, sub,
                     '<div style="height: 4px; margin-top: 8px; border-radius: 99px; background: var(--track); overflow: hidden"><div style="width: 64%; height: 100%; background: var(--acc)"></div></div>' if st == 'run' else ''))
    return ('<aside style="width: 264px; flex: none; border-right: 1px solid var(--line); background: var(--rail); padding: 20px 16px; display: flex; flex-direction: column; gap: 20px">'
            '<button class="btn btn-pri" style="width: 100%; height: 44px; font-size: 14px">' + ic('plus', 18) + ' New run</button>'
            '<div><div class="lbl" style="padding: 0 10px 8px">Active · 1</div>' + items.split('</button>', 1)[0] + '</button></div>'
            '<div><div class="lbl" style="padding: 0 10px 8px">Recent</div><div style="display: flex; flex-direction: column; gap: 4px">' + items.split('</button>', 1)[1] + '</div></div></aside>')


def new_run():
    w, h = 1440, 1000
    tests = [(True, 'web', 'Owner_CRVD', '287 steps · 1 step with side effects'), (True, 'web', 'ANZ', '240 steps'), (True, 'web', 'PostDeparture', '77 steps · needs Owner_CRVD first'),
             (False, 'web', 'Owner_RVD', '214 steps'), (True, 'sync', 'Two agents edit one policy', 'scenario · 3 lanes · runs as one unit')]
    trows = ''.join('<div style="display: flex; align-items: center; gap: 12px; padding: 11px 16px; border-top: 1px solid var(--line)">%s<span style="color: var(--tx3); display: inline-flex">%s</span>'
                    '<b style="font-size: 13.5px">%s</b><span style="font-size: 12.5px; color: var(--tx3)">%s</span><span style="flex-grow: 1"></span>%s</div>'
                    % (cbx(on), ic(k, 15), n, d, '<span class="tag tag-acc">scenario</span>' if k == 'sync' else '') for on, k, n, d in tests)
    left = ('<div style="display: flex; flex-direction: column; gap: 22px; min-width: 0">'
            '<section class="card" style="overflow: hidden"><div style="padding: 16px; display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 17px">What to run</span><span class="mono" style="font-size: 12px; color: var(--tx3)">Travelex Regression v9.1</span>'
            '<span style="flex-grow: 1"></span><span class="tag">4 tests · 1 scenario</span></div>' + trows + '</section>'
            '<section class="card" style="padding: 18px; display: flex; flex-direction: column; gap: 14px"><span class="ttl" style="font-size: 17px">Environment</span>'
            '<div class="seg"><button>QA</button><button>UAT</button><button class="on prod">PROD</button></div>'
            '<div class="bn bn-fail" role="alert">' + ic('warn', 16, 2, 'color: var(--fail)') + '<span><b>Can’t start on PROD.</b> 2 required environment variables have no value for PROD: '
            '<span class="mono">DOMAIN</span>, <span class="mono">API_KEY</span>.<span style="display: flex; gap: 8px; margin-top: 8px"><a class="btn btn-sm" href="DlgEnvironments.dc.html" style="text-decoration: none">Open Build › Environments</a><button class="btn btn-sm btn-ghost">Use UAT instead</button></span></span></div>'
            '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Filled in from the environment table</span>'
            '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><tbody>'
            '<tr><td class="mono">DOMAIN</td><td><span class="tag tag-fail">missing</span></td></tr><tr><td class="mono">BASE_URL</td><td class="mono" style="color: var(--tx3)">https://{DOMAIN}</td></tr>'
            '<tr><td class="mono">API_KEY</td><td><span class="tag tag-fail">missing</span></td></tr><tr><td class="mono">PAYMENT_GATEWAY</td><td class="mono">live</td></tr></tbody></table></div></div></section>'
            '<section class="card" style="padding: 18px; display: flex; flex-direction: column; gap: 12px"><span class="ttl" style="font-size: 17px">Steps with side effects</span>'
            '<div style="display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; background: var(--fail-soft); border: 1px solid var(--fail-line)">'
            + ic('bolt', 15, 2, 'color: var(--fail)') + '<b style="font-size: 13px">Owner_CRVD · step 260 · Click Purchase</b><span style="flex-grow: 1"></span><span class="pill p-fail">blocked on PROD</span></div>'
            '<span style="font-size: 12.5px; color: var(--tx3)">On PROD the test stops before this step and reports it as blocked. On QA and UAT, full runs click it as usual.</span></section></div>')
    right = ('<div style="display: flex; flex-direction: column; gap: 22px">'
             '<section class="card" style="padding: 18px; display: flex; flex-direction: column; gap: 12px"><span class="ttl" style="font-size: 17px">Preflight</span>'
             + ''.join('<div style="display: flex; gap: 10px; font-size: 13px"><span style="color: %s; display: inline-flex; margin-top: 2px">%s</span><span>%s</span></div>' % (c, ic(i, 15, 2), t) for c, i, t in (
                 ('var(--fail)', 'x', '<b>Environment variables</b> · DOMAIN, API_KEY missing for PROD'),
                 ('var(--pass)', 'check', 'Order: Owner_CRVD runs before PostDeparture (needs POLICY_NO)'),
                 ('var(--pass)', 'check', 'Page fingerprints: 9 defined, all used'),
                 ('var(--warn)', 'warn', 'PROD is production: you’ll type PROD to confirm'),
                 ('var(--pass)', 'check', 'Secrets: 3 found in secrets.env for PROD')))
             + '</section><button class="btn btn-lg btn-pri" disabled="" style="opacity: .45; width: 100%">' + ic('play', 16, 2) + ' Start run</button>'
             '<span style="font-size: 12.5px; color: var(--tx3); text-align: center">Checked again on the server before anything starts.</span></div>')
    body = (root_open(w, h, 'dark') + app_header('Run') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + runs_side()
            + '<main style="flex-grow: 1; min-width: 0; padding: 36px 40px; display: flex; flex-direction: column; gap: 24px; overflow: hidden">'
            '<div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">New run</span><span class="disp" style="font-size: 30px; font-weight: 700">Travelex Regression v9.1</span></div>'
            '<div style="display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 24px; align-items: start">' + left + right + '</div></main></div></div>')
    write('RunNew.dc.html', page('New run · environment blocked', body, w, h))


def live_scenario():
    w, h = 1440, 900
    lanes = [('A', 'PostDeparture · row 1 · agent Ana', 'At sync 2', 58, 'wait', ['Sign in', 'Open policy', 'Edit address', 'SYNC 1 · released 14:02:14', 'Save changes (A before B)', 'SYNC 2 · waiting for B']),
             ('B', 'PostDeparture · row 2 · agent Ben', 'Running step 31', 44, 'run', ['Sign in', 'Open policy', 'Edit phone', 'SYNC 1 · released 14:02:14', 'waiting for A to save · done', 'Save changes ← now']),
             ('C', 'policyRecord#1 · row 1', 'Queued after SYNC 2', 0, 'pend', ['Read policy record'])]
    cols = ''
    for k, name, state, pct, st, events in lanes:
        col = {'wait': 'var(--warn)', 'run': 'var(--acc)', 'pend': 'var(--pend)'}[st]
        ev = ''.join('<div style="display: flex; align-items: center; gap: 9px; padding: 8px 10px; border-radius: 9px; font-size: 12.5px; %s">%s<span>%s</span></div>'
                     % ('background: var(--acc-soft); border: 1px solid var(--acc-line)' if e.startswith('SYNC') else ('border: 1px solid var(--line2)' if '← now' in e or 'waiting for B' in e else ''),
                        ('<span style="color: var(--acc); display: inline-flex">' + ic('sync', 14) + '</span>') if e.startswith('SYNC') else ('<span style="color: var(--pass); display: inline-flex">' + ic('check', 13, 2.4) + '</span>' if '←' not in e and 'waiting for B' not in e and st != 'pend' else '<span class="dot" style="color: ' + col + '"></span>'),
                        e) for e in events)
        cols += ('<section class="card" style="flex: 1; min-width: 0; padding: 16px; display: flex; flex-direction: column; gap: 12px">'
                 '<div style="display: flex; align-items: center; gap: 10px"><span class="mono" style="width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; background: var(--acc-soft); color: var(--acc); font-weight: 700">%s</span>'
                 '<div style="display: flex; flex-direction: column; min-width: 0"><b class="trunc">%s</b><span style="font-size: 12px; color: %s">%s</span></div></div>'
                 '<div style="height: 6px; border-radius: 99px; background: var(--track); overflow: hidden"><div style="width: %d%%; height: 100%%; background: %s"></div></div>%s</section>'
                 % (k, name, col, state, pct, col, ev))
    body = (root_open(w, h, 'dark') + app_header('Run') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + runs_side('0926-0944')
            + '<main style="flex-grow: 1; min-width: 0; padding: 32px 40px; display: flex; flex-direction: column; gap: 20px">'
            '<div style="display: flex; align-items: flex-end; gap: 14px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">Scenario · live</span>'
            '<span class="disp" style="font-size: 30px; font-weight: 700">Two agents edit one policy</span><span class="mono" style="font-size: 12.5px; color: var(--tx3)">run 0926-0944 · UAT · started 14:01:32</span></div>'
            '<span style="flex-grow: 1"></span><span class="pill p-run"><span class="dot"></span>Running</span><button class="btn btn-dng">' + ic('stop', 14) + ' Stop</button></div>'
            '<div style="display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line2); font-size: 12.5px">'
            '<span class="lbl">Sync points</span><span class="tag tag-pass">' + ic('check', 11, 2.4) + ' SYNC 1 · all arrived · released 14:02:14</span>'
            '<span class="tag tag-pass">' + ic('check', 11, 2.4) + ' A saved before B</span><span class="tag tag-warn">SYNC 2 · A waiting 00:12 · B not there yet</span></div>'
            '<div style="display: flex; gap: 16px; align-items: flex-start">' + cols + '</div>'
            '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Results report each lane on its own. A lane that fails still releases the others at the next sync point, so one failure never hangs the scenario.</span></div>'
            '</main></div></div>')
    write('RunLiveScenario.dc.html', page('Live scenario run', body, w, h))


def results():
    w, h = 1440, 1260
    gate = ('<div style="display: grid; grid-template-columns: minmax(0, 1fr) 232px; gap: 20px; padding: 18px; border-radius: 14px; background: var(--surface); border: 1px solid var(--fail-line)">'
            '<div style="display: flex; flex-direction: column; gap: 12px; min-width: 0">'
            '<div style="display: flex; align-items: center; gap: 9px; flex-wrap: wrap"><span class="pill p-fail">' + ic('gate', 11, 2.4) + ' Hard stop</span><b class="mono" style="font-size: 13px">Step 212</b><span class="mono" style="font-size: 11.5px; color: var(--tx3)">row 220 · ASSERT_PAGE</span></div>'
            '<div style="font-weight: 650; font-size: 16px">Never reached the Payment page</div>'
            '<div style="display: grid; grid-template-columns: 112px 1fr; gap: 9px 14px; font-size: 13px">'
            '<span style="color: var(--tx3)">Address</span><span style="display: flex; gap: 8px; align-items: center">' + ic('x', 13, 2.4, 'color: var(--fail)') + '<span>URL was <span class="mono" style="font-size: 12px">/purchase/travelers?error=session</span>, expected it to contain <span class="mono" style="font-size: 12px">/purchase/payment</span></span></span>'
            '<span style="color: var(--tx3)">Landmark</span><span style="display: flex; gap: 8px; align-items: center">' + ic('x', 13, 2.4, 'color: var(--fail)') + ' Heading “Payment details” not on the page</span>'
            '<span style="color: var(--tx3)">After it</span><span>28 steps not run. A page gate never lets later steps fail one after another.</span></div>'
            '<div style="display: flex; gap: 8px"><a class="btn btn-sm btn-pri" href="EditorFix.dc.html" style="text-decoration: none">' + ic('pencil', 13) + ' Fix in builder</a><button class="btn btn-sm">Edit Payment page fingerprint</button></div></div>'
            '<div class="shot" style="height: 150px"><div style="position: absolute; left: 14px; top: 14px; right: 14px; display: flex; flex-direction: column; gap: 7px">'
            '<span style="height: 10px; width: 55%; border-radius: 4px; background: var(--line2)"></span><span style="height: 30px; border-radius: 6px; background: var(--fail-soft); border: 1px solid var(--fail-line)"></span>'
            '<span style="height: 8px; width: 80%; border-radius: 4px; background: var(--line2)"></span><span style="height: 8px; width: 70%; border-radius: 4px; background: var(--line2)"></span></div>'
            '<span class="mono" style="position: absolute; left: 8px; bottom: 7px; font-size: 10px; padding: 2px 7px; border-radius: 5px; background: var(--scrim); color: #fff">at the gate</span></div></div>')
    step = ('<div style="display: grid; grid-template-columns: minmax(0, 1fr) 232px; gap: 20px; padding: 18px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line2)">'
            '<div style="display: flex; flex-direction: column; gap: 12px; min-width: 0">'
            '<div style="display: flex; align-items: center; gap: 9px"><span class="pill p-fail">' + ic('x', 11, 3) + ' Failed</span><b class="mono" style="font-size: 13px">Step 228</b><span class="mono" style="font-size: 11.5px; color: var(--tx3)">row 236 · SET · inside frame: card</span></div>'
            '<div style="font-weight: 650; font-size: 16px">Type <span class="var secret">' + ic('lock', 11, 2.2) + '•••• Test card</span> into Card number</div>'
            '<div style="display: grid; grid-template-columns: 112px 1fr; gap: 9px 14px; font-size: 13px">'
            '<span style="color: var(--tx3)">Error</span><span>Element not found after 30 s</span>'
            '<span style="color: var(--tx3)">Locator</span><span class="mono" style="font-size: 12px">label “Card number” in frame “card”</span>'
            '<span style="color: var(--tx3)">Value</span><span class="mono" style="font-size: 12px">•••• (secret, never shown)</span></div>'
            '<div style="display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: 11px; background: var(--acc-soft); border: 1px solid var(--acc-line)">'
            '<span style="font-size: 13px"><b>A backup found 1 likely match.</b> <span style="color: var(--tx2)">The step still failed; nothing was healed.</span></span>'
            '<span style="font-size: 12.5px; color: var(--tx2)">Label changed to “Card no.” · proposed <span class="mono" style="font-size: 12px; color: var(--tx)">data-testid = card-number</span></span>'
            '<div style="display: flex; gap: 8px"><button class="btn btn-sm btn-pri">Accept new locator</button><a class="btn btn-sm" href="EditorFix.dc.html" style="text-decoration: none">' + ic('pencil', 13) + ' Fix in builder</a></div></div></div>'
            '<div class="shot" style="height: 150px"><div style="position: absolute; left: 70px; top: 58px; width: 120px; height: 28px; border: 2px solid var(--acc); border-radius: 5px; box-shadow: 0 0 0 3px var(--acc-soft)"></div>'
            '<span class="mono" style="position: absolute; left: 8px; bottom: 7px; font-size: 10px; padding: 2px 7px; border-radius: 5px; background: var(--scrim); color: #fff">backup match</span></div></div>')
    popups = ('<section class="card" style="padding: 18px; display: flex; flex-direction: column; gap: 12px"><span class="ttl" style="font-size: 17px">Popups and flagged steps</span>'
              '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Test</th><th>Step</th><th>What</th><th>Outcome</th></tr></thead><tbody>'
              '<tr><td>Owner_CRVD</td><td class="mono">96</td><td>If the feedback survey shows, close it</td><td><span class="tag tag-warn">appeared · closed</span></td></tr>'
              '<tr><td>ANZ</td><td class="mono">96</td><td>If the feedback survey shows, close it</td><td><span class="tag">did not appear</span></td></tr>'
              '<tr><td>Owner_CRVD</td><td class="mono">260</td><td>Click Purchase ' + '<span class="tag tag-warn">' + ic('bolt', 10) + ' side effects</span></td><td><span class="tag">not reached</span></td></tr>'
              '<tr><td>Owner_RVD</td><td class="mono">188</td><td>Click Purchase <span class="tag tag-warn">' + ic('bolt', 10) + ' side effects</span></td><td><span class="tag tag-pass">ran on UAT</span></td></tr>'
              '</tbody></table></div></section>')
    def trow(name, status, steps, dur, open_=False, detail=''):
        cls = {'FAILED': 'p-fail', 'PASSED': 'p-pass'}[status]
        return ('<div style="border-top: 1px solid var(--line)"><div style="display: grid; grid-template-columns: 22px 190px minmax(0, 1fr) 84px 60px; gap: 16px; align-items: center; padding: 14px 22px; %s">'
                '<span style="color: var(--tx3); display: inline-flex">%s</span><b>%s</b><span style="font-size: 12.5px; color: var(--tx2)">%s</span><span class="pill %s">%s</span><span class="mono" style="font-size: 12px; color: var(--tx3)">%s</span></div>%s</div>'
                % ('background: var(--fail-soft)' if status == 'FAILED' else '', ic('chevron' if open_ else 'chevr', 14, 2), name, steps, cls, status.title(), dur,
                   ('<div style="padding: 6px 22px 22px; background: var(--surface2); border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 14px">' + detail + '</div>') if open_ else ''))
    tests = ('<section class="card" style="overflow: hidden"><div style="padding: 16px 22px; display: flex; align-items: center; gap: 10px"><span class="ttl" style="font-size: 17px">Tests</span><span class="tag">9</span></div>'
             + trow('ANZ', 'FAILED', 'stopped at the Payment page gate · 211 of 240 steps', '6m 02s', True, gate)
             + trow('Owner_CRVD', 'FAILED', '2 failed steps · 228 of 287 run', '8m 41s', True, step)
             + trow('Owner_RVD', 'PASSED', '214 steps', '7m 12s') + trow('PostDeparture', 'PASSED', '77 steps · used POLICY_NO from Owner_CRVD', '3m 05s') + '</section>')
    body = (root_open(w, h, 'dark') + app_header('Results') + '<div style="flex-grow: 1; display: flex; min-height: 0">' + runs_side('0925-1412')
            + '<main style="flex-grow: 1; min-width: 0; padding: 36px 40px; display: flex; flex-direction: column; gap: 22px">'
            '<div style="display: flex; align-items: flex-end; gap: 14px"><div style="display: flex; flex-direction: column; gap: 4px"><span class="eyebrow">Results</span>'
            '<span class="disp" style="font-size: 30px; font-weight: 700">Run 0925-1412</span><span class="mono" style="font-size: 12.5px; color: var(--tx3)">Travelex Regression v9.1 · UAT · 25 Sep 14:12 · 41m 08s</span></div>'
            '<span style="flex-grow: 1"></span><span class="pill p-fail">2 failed</span><button class="btn btn-pri">' + ic('external', 15) + ' Open HTML report</button></div>'
            + tests + popups + '</main></div></div>')
    write('RunResults.dc.html', page('Results additions', body, w, h))


if __name__ == '__main__':
    new_run(); live_scenario(); results()
