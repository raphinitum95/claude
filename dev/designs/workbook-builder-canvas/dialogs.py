"""Setup screens and dialogs (screen group 5)."""
from common import *

BW, BH = 1280, 820


def ghost():
    """A dimmed hint of the editor behind the dialog."""
    return ('<div style="position: absolute; inset: 0; display: flex; flex-direction: column" aria-hidden="true">'
            '<div style="height: 60px; border-bottom: 1px solid var(--line); background: var(--bg)"></div>'
            '<div style="flex-grow: 1; display: flex"><div style="width: 236px; background: var(--rail); border-right: 1px solid var(--line)"></div>'
            '<div style="flex-grow: 1; padding: 30px; display: flex; flex-direction: column; gap: 8px">'
            + ''.join('<div style="height: 40px; border-radius: 9px; background: var(--surface); border: 1px solid var(--line)"></div>' for _ in range(12))
            + '</div><div style="width: 372px; background: var(--rail); border-left: 1px solid var(--line)"></div></div></div><div class="scrim"></div>')


def dialog(title, sub, inner, footer, w=720, tone='', icon_name=None):
    border = {'fail': 'border-color: var(--fail-line)', 'warn': 'border-color: var(--warn-line)'}.get(tone, '')
    ico = ''
    if icon_name:
        col = {'fail': 'var(--fail)', 'warn': 'var(--warn)', '': 'var(--acc)'}[tone]
        ico = '<span style="width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; flex: none; color: %s; background: color-mix(in srgb, %s 14%%, transparent)">%s</span>' % (col, col, ic(icon_name, 19, 2))
    return ('<div class="modal" role="dialog" aria-label="%s" style="width: %dpx; max-height: 760px; %s">' % (title, w, border)
            + '<div style="padding: 20px 22px 14px; display: flex; gap: 14px; align-items: flex-start">' + ico
            + '<div style="display: flex; flex-direction: column; gap: 4px; min-width: 0; flex-grow: 1"><span class="ttl">%s</span><span style="font-size: 13px; color: var(--tx2)">%s</span></div>' % (title, sub)
            + '<button class="icon-btn" aria-label="Close" style="border-color: transparent; background: transparent">' + ic('x', 16, 2) + '</button></div>'
            + '<div class="scroll" style="padding: 4px 22px 18px; overflow: auto; display: flex; flex-direction: column; gap: 16px">' + inner + '</div>'
            + '<div style="padding: 14px 22px; border-top: 1px solid var(--line); display: flex; align-items: center; gap: 8px">' + footer + '</div></div>')


def board(name, title, dlg, extra='', theme='dark'):
    body = (root_open(BW, BH, theme) + ghost() + '<div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center">' + dlg + '</div>' + extra + '</div>')
    write(name, page(title, body, BW, BH))


def lbl(t):
    return '<span class="lbl">%s</span>' % t


def new_workbook():
    envs = ''.join('<tr><td><span class="field" style="min-height: 30px; padding: 0 8px; width: 90px"><b>%s</b></span></td><td><span class="field mono" style="min-height: 30px; font-size: 12px">%s</span></td><td style="text-align: center">%s</td></tr>'
                   % (e, d, cbx(p)) for e, d, p in (('QA', 'qa.qantas-insurance.test', False), ('UAT', 'uat.qantas-insurance.test', False), ('PROD', 'www.qantas-insurance.com', True)))
    inner = (
        '<div style="display: flex; flex-direction: column; gap: 6px">' + lbl('Name') +
        '<input class="fld" value="Qantas Regression" aria-label="Workbook name">'
        '<span class="mono" style="font-size: 12px; color: var(--tx3)">Saved as workbooks/Qantas Regression.xlsx</span></div>'
        '<div style="display: flex; flex-direction: column; gap: 6px"><div style="display: flex; align-items: center; gap: 8px">' + lbl('Environments and their domain') +
        '<span style="flex-grow: 1"></span><button class="btn btn-ghost btn-sm">' + ic('plus', 13, 2.2) + ' Environment</button></div>'
        '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Environment</th><th>DOMAIN (required)</th><th style="text-align: center">Production</th></tr></thead><tbody>'
        + envs + '</tbody></table></div>'
        '<span style="font-size: 12px; color: var(--tx3)">Production keeps the typed confirmation and always blocks steps with side effects.</span></div>'
        '<div style="display: flex; flex-direction: column; gap: 8px">' + lbl('Start from') +
        '<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px">'
        '<button class="card" style="padding: 12px; display: flex; flex-direction: column; gap: 4px; box-shadow: none"><b style="font-size: 13px">Empty</b><span style="font-size: 12px; color: var(--tx3)">No tests yet</span></button>'
        '<button class="card" style="padding: 12px; display: flex; flex-direction: column; gap: 4px; box-shadow: 0 0 0 2px var(--acc); border-color: var(--acc)"><b style="font-size: 13px">Copy a workbook</b><span style="font-size: 12px; color: var(--tx3)">Travelex Regression v9.1 ▾</span></button>'
        '<button class="card" style="padding: 12px; display: flex; flex-direction: column; gap: 4px; box-shadow: none"><b style="font-size: 13px">Templates</b><span style="font-size: 12px; color: var(--tx3)">Pick sections to start with</span></button></div>'
        '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Copying opens <b>What changes?</b> next, so you can swap the Travelex domain, names and common values in one go.</span></div></div>')
    footer = '<span style="font-size: 12px; color: var(--tx3)">Lands on an empty workbook map with New test and Record a test.</span><span style="flex-grow: 1"></span><button class="btn">Cancel</button><button class="btn btn-pri">Create workbook</button>'
    board('DlgNewWorkbook.dc.html', 'New workbook', dialog('New workbook', 'One screen, then you are building.', inner, footer, 700, icon_name='plus'))


def env_table():
    rows = [('DOMAIN', 'Domain', True, ['qa.travelex-insurance.test', 'uat.travelex-insurance.test', 'www.travelex-insurance.com'], ''),
            ('BASE_URL', 'Base URL', True, ['https://{DOMAIN}', 'https://{DOMAIN}', 'https://{DOMAIN}'], ''),
            ('API_KEY', 'API key', True, ['secret · ••••', 'secret · ••••', None], 'secret'),
            ('PAYMENT_GATEWAY', 'Payment gateway', False, ['sandbox', 'sandbox', 'live'], ''),
            ('SUPPORT_EMAIL', 'Support inbox', False, ['qa-inbox@example.com', 'uat-inbox@example.com', 'support@example.com'], ''),
            ('PROMO_CODE', 'Promo code', False, ['SPRING10', 'SPRING10', 'SPRING10'], 'same')]
    head = ('<tr><th style="width: 200px">Variable</th>'
            + ''.join('<th><span style="display: flex; align-items: center; gap: 6px">%s%s<button style="display: inline-flex; color: var(--tx3)" aria-label="Rename %s">%s</button></span></th>'
                      % (e, ' <span class="tag tag-fail" style="height: 17px; font-size: 9.5px">production</span>' if e == 'PROD' else '', e, ic('pencil', 11)) for e in ('QA', 'UAT', 'PROD'))
            + '<th style="width: 60px"><button class="btn btn-ghost btn-sm" style="padding: 0 6px">' + ic('plus', 13, 2.2) + '</button></th></tr>')
    body = ''
    for tok, label, req, vals, kind in rows:
        cells = ''
        for v in vals:
            if v is None:
                cells += '<td><span class="field" style="min-height: 30px; border-color: var(--fail); background: var(--fail-soft); color: var(--fail); font-size: 12px">' + ic('warn', 13) + ' missing, required</span></td>'
            else:
                cells += '<td><span class="field mono" style="min-height: 30px; font-size: 11.5px; %s">%s</span></td>' % ('color: var(--tx3)' if kind else '', v)
        body += ('<tr><td><div style="display: flex; flex-direction: column"><span style="font-weight: 600">%s%s</span><span class="mono" style="font-size: 10.5px; color: var(--tx3)">{%s}</span></div></td>%s<td></td></tr>'
                 % (label, ' <span style="color: var(--fail)">*</span>' if req else '', tok, cells))
    inner = ('<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>'
             '<div style="display: flex; gap: 10px">'
             '<div class="bn" style="flex: 1">' + ic('lock', 15, 1.8, 'color: var(--tx3)') + '<span>Secret values live in <span class="mono">secrets.env</span>, one per environment. The workbook only stores {SECRET:API_KEY}.</span></div>'
             '<div class="bn" style="flex: 1">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Promo code is the same everywhere. Keep it as normal data, or keep it here to make it environment-specific.</span></div></div>'
             '<div class="bn bn-fail">' + ic('warn', 15, 1.8, 'color: var(--fail)') + '<span><b>PROD can’t run yet:</b> API key has no value for PROD. quotePrice#1 needs it.</span></div>')
    footer = '<button class="btn btn-sm">' + ic('plus', 13, 2.2) + ' Variable</button><span style="flex-grow: 1"></span><span style="font-size: 12px; color: var(--tx3)">The run settings pick the environment; these fill in.</span><button class="btn btn-pri">Done</button>'
    board('DlgEnvironments.dc.html', 'Environment variables', dialog('Environment variables', 'The test stays the same everywhere. Only these change per environment.', inner, footer, 1040, icon_name='globe'))


def template_insert():
    maps = [('FIRST_NAME', 'Traveler first name', 'FIRST_NAME', 'same name', 'pass'), ('LAST_NAME', 'Traveler last name', 'LAST_NAME', 'same name', 'pass'),
            ('DATE_OF_BIRTH', 'Date of birth', 'DOB', 'close match: DOB', 'warn'), ('EMAIL_ADDR', 'Email', 'EMAIL', 'close match: EMAIL', 'warn'),
            ('EMERGENCY_PHONE', 'Emergency phone', None, 'no match', 'fail')]
    rows = ''
    for tvar, lab, mine, how, st in maps:
        target = ('<span class="field" style="min-height: 30px">' + var(lab if mine else lab, mine) + '<span class="mono" style="font-size: 11px; color: var(--tx3)">{%s}</span><span style="flex-grow: 1"></span>' % mine + ic('chevron', 12, 2) + '</span>') if mine else \
                 ('<span class="field" style="min-height: 30px; border-color: var(--acc); color: var(--acc)">' + ic('plus', 13, 2.2) + ' Create new column in Params_2 <span class="mono" style="font-size: 11px">EMERG_PHONE</span></span>')
        rows += ('<tr><td class="mono">{%s}</td><td style="width: 30px; color: var(--tx3)">%s</td><td style="width: 360px">%s</td><td><span class="tag tag-%s">%s</span></td></tr>'
                 % (tvar, ic('arrowr', 14), target, {'pass': 'pass', 'warn': 'warn', 'fail': 'acc'}[st], how))
    inner = ('<div class="card" style="padding: 12px 14px; display: flex; align-items: center; gap: 12px; box-shadow: none">' + ic('layers', 18, 1.8, 'color: var(--acc)') +
             '<div style="display: flex; flex-direction: column"><b>Traveler form</b><span style="font-size: 12px; color: var(--tx3)">12 steps · from templates.xlsx next to the workbooks · used in 20 tests</span></div><span style="flex-grow: 1"></span>'
             '<span style="font-size: 12.5px; color: var(--tx2)">Inserts at step 190 in <b>For each traveler</b></span></div>'
             '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Template uses</th><th></th><th>In this workbook</th><th>Why</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
             '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Inserting copies the steps. Later edits to the template don’t change this test, and edits here don’t change the template.</span></div>')
    footer = '<span style="font-size: 12px; color: var(--tx3)">2 need a quick look · 1 new column</span><span style="flex-grow: 1"></span><button class="btn">Cancel</button><button class="btn btn-pri">Insert 12 steps</button>'
    board('DlgTemplate.dc.html', 'Insert template', dialog('Insert a template', 'Match its variables to yours.', inner, footer, 860, icon_name='layers'))


def duplicate():
    changes = [('Domain', 'uat.travelex-insurance.test', 'uat.qantas-insurance.test', True), ('Environment', 'UAT', 'UAT', False), ('Workbook name', 'Travelex Regression v9.1', 'Qantas Regression', True),
               ('“Italy”', '14 uses', 'Japan', True), ('“Basic”', '9 uses · Plan', 'Essentials', True), ('“jane.doe@example.com”', '4 uses', '', False)]
    rows = ''.join('<div style="display: grid; grid-template-columns: 24px 200px 1fr 1fr; gap: 10px; align-items: center">%s<b style="font-size: 12.5px">%s</b>'
                   '<span class="mono trunc" style="font-size: 11.5px; color: var(--tx3)">%s</span><span class="field mono" style="min-height: 30px; font-size: 12px; %s">%s</span></div>'
                   % (cbx(on), k, a, '' if b else 'color: var(--tx4)', b or 'keep') for k, a, b, on in changes)
    hits = [('Owner_CRVD', '1', 'Value', '{BASE_URL}/travel-insurance', '{BASE_URL}/travel-insurance', False), ('Owner_CRVD', '26', 'Expected_Value', 'Travel insurance made simple', '—', False),
            ('Params_1', 'row 1', 'DESTINATION', 'Italy', 'Japan', True), ('Params_1', 'row 7', 'DESTINATION', 'Italy', 'Japan', True), ('Owner_RVD', '41', 'Expected_Value', 'Italy · 12–26 Jun', 'Japan · 12–26 Jun', True),
            ('ANZ', '38', 'Value', 'Italy', 'Japan', True), ('Global', 'B4', 'Environment', 'uat.travelex-insurance.test', 'uat.qantas-insurance.test', True)]
    hrows = ''.join('<tr style="%s"><td>%s</td><td>%s</td><td class="mono">%s</td><td class="mono" style="color: var(--tx3)">%s</td><td class="mono"><span style="color: var(--fail); text-decoration: line-through">%s</span> → <span style="color: var(--pass)">%s</span></td></tr>'
                    % ('' if on else 'opacity: .5', cbx(on), t, s, c, a, b) for t, s, c, a, b, on in hits[2:])
    inner = ('<div style="display: flex; gap: 10px; align-items: center"><span class="field" style="min-height: 34px; width: 280px"><b>Travelex Regression v9.1</b></span>' + ic('arrowr', 16) +
             '<input class="fld" value="Qantas Regression" aria-label="New name" style="width: 280px"><span class="tag">workbook</span></div>'
             '<div style="display: flex; flex-direction: column; gap: 8px">' + lbl('What changes? (optional)') + rows + '</div>'
             '<div style="display: flex; flex-direction: column; gap: 8px"><div style="display: flex; align-items: center; gap: 8px">' + lbl('Find and replace across the workbook') + '<span style="flex-grow: 1"></span><span class="tag">5 of 5 hits selected</span></div>'
             '<div style="display: flex; gap: 8px"><span class="field" style="min-height: 32px">' + ic('search', 13) + '<span class="mono" style="font-size: 12px">Italy</span></span>'
             '<span class="field" style="min-height: 32px">' + ic('arrowr', 13) + '<span class="mono" style="font-size: 12px">Japan</span></span><span class="seg" style="width: 280px"><span class="on">Whole value</span><span>Part of a value</span></span></div>'
             '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th></th><th>Where</th><th>Step / row</th><th>Column</th><th>Change</th></tr></thead><tbody>' + hrows + '</tbody></table></div></div>')
    footer = '<span style="font-size: 12px; color: var(--tx3)">Nothing is written until you duplicate. Undo covers it all.</span><span style="flex-grow: 1"></span><button class="btn">Skip, just duplicate</button><button class="btn btn-pri">Duplicate with 5 changes</button>'
    board('DlgDuplicate.dc.html', 'Duplicate · what changes?', dialog('Duplicate workbook', 'Copy, then change what differs.', inner, footer, 1060, icon_name='dup'))


def run_blocked():
    inner = ('<div class="bn bn-fail" style="font-size: 13px">' + ic('warn', 16, 2, 'color: var(--fail)') + '<span><b>DOMAIN has no value for PROD.</b> Every step that opens the site uses it, so nothing would reach the right place.</span></div>'
             '<div style="display: flex; flex-direction: column; gap: 6px">' + lbl('Fix it here') +
             '<div style="display: flex; gap: 8px; align-items: center"><span class="field" style="min-height: 36px; width: 170px"><b>DOMAIN</b><span class="tag tag-fail">PROD</span></span>'
             '<input class="fld mono" placeholder="www.example.com" aria-label="DOMAIN for PROD" style="flex-grow: 1; border-color: var(--fail)"><button class="btn">Save</button></div>'
             '<a href="DlgEnvironments.dc.html" style="font-size: 12.5px; font-weight: 600">Open all environment variables</a></div>'
             '<div class="bn">' + ic('shield', 15, 1.8, 'color: var(--tx3)') + '<span>PROD is marked production. Once DOMAIN is set, you’ll still type PROD to confirm, and Click Purchase (side effects) stays blocked.</span></div>')
    footer = '<span style="flex-grow: 1"></span><button class="btn">Switch to UAT</button><button class="btn btn-pri" disabled="" style="opacity: .45">Try it on PROD</button>'
    board('DlgRunBlocked.dc.html', 'Run blocked · missing DOMAIN', dialog('Can’t start on PROD', 'A required environment variable is missing.', inner, footer, 620, 'fail', 'warn'))


def fingerprint():
    part = lambda n, title, val, extra: ('<div class="card" style="padding: 14px; display: flex; flex-direction: column; gap: 10px; box-shadow: none">'
                                         '<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="width: 22px; height: 22px; border-radius: 7px; display: grid; place-items: center; background: var(--acc-soft); color: var(--acc); font-size: 11px; font-weight: 700">%s</span><b>%s</b><span style="flex-grow: 1"></span>'
                                         '<span style="display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--pass)">%s matches the live page</span></div>%s%s</div>' % (n, title, ic('check', 13, 2.4), val, extra))
    url = ('<div style="display: flex; gap: 8px"><span class="seg" style="width: 210px"><span class="on">contains</span><span>is</span><span>pattern</span></span>'
           '<span class="field mono" style="min-height: 34px; font-size: 12.5px">/purchase/payment</span></div>'
           '<span class="mono" style="font-size: 11px; color: var(--tx3)">live: https://uat.travelex-insurance.test/purchase/payment?session=…</span>')
    land = ('<div style="display: flex; gap: 8px; align-items: center"><span class="tag">heading</span><span class="field" style="min-height: 34px">“Payment details”</span>'
            '<button class="btn btn-sm">' + ic('target', 13) + ' Re-pick</button></div>'
            '<span style="font-size: 12px; color: var(--tx3)">Picked on the page. Anything unique to this page works: a heading, a form, a step marker.</span>')
    inner = ('<div style="display: flex; gap: 10px; align-items: center"><span class="field" style="min-height: 36px; width: 300px">' + ic('gate', 15, 2, 'color: var(--pass)') + '<b>Payment page</b></span>'
             '<span style="font-size: 12.5px; color: var(--tx3)">Defined once for the workbook · used by 6 gates in 5 tests</span></div>'
             + part('1', 'The address', url, '') + '<div style="text-align: center; font: 700 12px \'JetBrains Mono\', monospace; color: var(--tx3)">AND</div>' + part('2', 'A landmark on the page', land, '')
             + '<div class="bn bn-fail">' + ic('gate', 15, 2, 'color: var(--fail)') + '<span><b>A failed gate always stops the test,</b> even with Ignore_not_existing_object = Y. The result says which part was missing.</span></div>')
    footer = '<button class="btn btn-sm">' + ic('play', 12, 2) + ' Check on the live page</button><span style="flex-grow: 1"></span><button class="btn">Cancel</button><button class="btn btn-pri">Save fingerprint</button>'
    board('DlgFingerprint.dc.html', 'Page fingerprint', dialog('Page fingerprint', 'How every test knows it really arrived.', inner, footer, 680, icon_name='gate'))


def run_for_real():
    inner = ('<div class="card" style="padding: 12px 14px; display: flex; align-items: center; gap: 10px; box-shadow: none; border-color: var(--warn-line)">'
             '<span class="mono" style="font-size: 12px; color: var(--tx3)">Step 260</span>' + badge('act', 'Click') + '<b style="flex-grow: 1">Click Purchase</b><span class="tag tag-warn">' + ic('bolt', 11) + ' side effects</span></div>'
             '<span style="font-size: 13px; color: var(--tx2)">You’re replaying up to step 266 on <b style="color: var(--tx)">UAT</b> with Row 1. This click places a real order on UAT and may email the traveler.</span>'
             '<div class="bn">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Full runs are not affected by this question. On PROD this step is always blocked.</span></div>'
             '<label style="display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--tx2)">' + cbx(False) + ' Don’t ask again for this build session</label>')
    footer = '<button class="btn">Stop before it</button><span style="flex-grow: 1"></span><button class="btn">Skip it, carry on</button><button class="btn btn-dng">Run it for real</button>'
    board('DlgRunForReal.dc.html', 'Run it for real?', dialog('Run it for real?', 'This step has real consequences.', inner, footer, 580, 'warn', 'bolt'))


def file_changed():
    diffs = [('Owner_CRVD', '45', 'Click Next month arrow', 'Value', '', '', 'theirs', 'Only in Excel'),
             ('Owner_CRVD', '204', 'Choose Gender', 'FindBy_Value', "//select[@name='gender{i}']", "//select[@id='gender-{i}']", 'both', 'Changed in both'),
             ('Owner_CRVD', '58', 'Check Zip error is gone', 'Timeout', '', '10', 'theirs', 'Only in Excel'),
             ('Params_1', 'row 3', 'DESTINATION', '', 'Mexico', 'Cancún, Mexico', 'mine', 'Only in your draft')]
    rows = ''
    for t, r, name, col, a, b, who, why in diffs:
        pick = ('<span class="seg" style="width: 190px"><span class="%s">Excel’s</span><span class="%s">Mine</span></span>' % ('on' if who != 'mine' else '', 'on' if who == 'mine' else ''))
        rows += ('<tr><td>%s · <span class="mono">%s</span></td><td>%s</td><td class="mono" style="color: var(--tx3)">%s</td><td><span class="tag %s">%s</span></td><td>%s</td></tr>'
                 % (t, r, name, col, 'tag-warn' if who == 'both' else '', why, pick))
    inner = ('<div class="bn bn-warn">' + ic('warn', 16, 2, 'color: var(--warn)') + '<span><b>UAT_AEM_Travelex Regression_v9.1.xlsx changed on disk</b> at 09:52 (saved in Excel). Your draft has 6 unsaved edits.</span></div>'
             '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Where</th><th>Step</th><th>Column</th><th>What happened</th><th>Keep</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
             '<span style="font-size: 12px; color: var(--tx3)">3 more of your edits don’t touch anything Excel changed; they are kept.</span>')
    footer = '<button class="btn">Reload from disk</button><button class="btn btn-ghost">Keep mine, overwrite</button><span style="flex-grow: 1"></span><button class="btn btn-pri">Merge 4 changes</button>'
    lock = ('<div data-theme="dark" class="rr" style="position: absolute; right: 22px; bottom: 22px; width: 360px; padding: 12px 14px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--warn-line); box-shadow: var(--pop); display: flex; gap: 10px; font-size: 12.5px; overflow: visible">'
            + ic('lock', 16, 2, 'color: var(--warn); margin-top: 1px') + '<span><b>Close it in Excel to save.</b> Excel has the workbook open. Saving waits and finishes by itself once it’s closed.<span style="display: block; margin-top: 6px; color: var(--tx3)">Another state of the same screen</span></span></div>')
    board('DlgFileChanged.dc.html', 'File changed on disk', dialog('The workbook changed in Excel', 'Reload, or merge step by step.', inner, footer, 980, 'warn', 'refresh'), lock)


def history():
    saves = [('Today 09:41', 'Draft (autosaved)', 'current', True), ('Today 09:12', 'Save to Excel · backup kept', '6 steps changed', False), ('Yesterday 17:05', 'Save to Excel', '22 steps · template inserted', False),
             ('Yesterday 11:30', 'Save to Excel', 'renamed DEST → DESTINATION (31 uses)', False), ('24 Sep 16:02', 'Opened from Excel', 'original file', False)]
    left = ''.join('<button class="rail-item%s" style="height: auto; padding: 8px 10px; flex-direction: column; align-items: flex-start; gap: 1px"><b style="font-size: 12.5px; color: var(--tx)">%s</b><span style="font-size: 12px">%s</span><span class="mono" style="font-size: 10.5px; color: var(--tx3)">%s</span></button>'
                   % (' on' if i == 1 else '', a, b, c) for i, (a, b, c, _) in enumerate(saves))
    diffs = [('Owner_CRVD', '44', 'Click Day {DEPART_DAY}', 'Pick date {DEPART_DATE} in Departure date', 'changed'), ('Owner_CRVD', '45–48', '4 raw calendar clicks', '—', 'removed'),
             ('Owner_CRVD', '228', 'label “Card number”', 'data-testid = card-number', 'changed'), ('Owner_CRVD', '262', '—', 'Arrived at: Confirmation page', 'added'),
             ('Params_2', 'row 2', 'omar@example.com', 'omar.haddad@example.com', 'changed')]
    drows = ''.join('<tr><td>%s · <span class="mono">%s</span></td><td><span class="tag %s">%s</span></td><td class="mono" style="color: var(--fail); white-space: normal">%s</td><td class="mono" style="color: var(--pass); white-space: normal">%s</td></tr>'
                    % (t, n, {'changed': 'tag-acc', 'removed': 'tag-fail', 'added': 'tag-pass'}[k], k, a, b) for t, n, a, b, k in diffs)
    inner = ('<div style="display: flex; gap: 16px; min-height: 420px"><div style="width: 250px; flex: none; display: flex; flex-direction: column; gap: 3px">' + left + '</div>'
             '<div style="flex-grow: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px"><div style="display: flex; align-items: center; gap: 8px"><b>Today 09:12 → now</b><span style="flex-grow: 1"></span><span class="mono" style="font-size: 11px; color: var(--tx3)">backups/UAT_AEM_Travelex Regression_v9.1.2026-09-26_0912.xlsx</span></div>'
             '<div style="border: 1px solid var(--line); border-radius: 10px; overflow: hidden"><table class="tbl"><thead><tr><th>Step</th><th></th><th>Before</th><th>After</th></tr></thead><tbody>' + drows + '</tbody></table></div></div></div>')
    footer = '<span style="font-size: 12px; color: var(--tx3)">Restoring makes a new draft; nothing is lost.</span><span style="flex-grow: 1"></span><button class="btn">Close</button><button class="btn btn-pri">Restore this save</button>'
    board('DlgHistory.dc.html', 'History', dialog('History', 'Every save to Excel keeps a timestamped backup.', inner, footer, 1080, icon_name='history'))


if __name__ == '__main__':
    new_workbook(); env_table(); template_insert(); duplicate(); run_blocked(); fingerprint(); run_for_real(); file_changed(); history()
