"""Recording window (Q5/Q6/Q7/Q8/Q9/Q10/Q11/Q41/Q50/Q51/Q53): the real site in a controlled browser window + injected overlay."""
from common import *

W, H = 1440, 900
SITE_CSS = 'font-family: Georgia, \'Times New Roman\', serif; color: #1D2B36; background: #FFFFFF'


def window(url, content, w=1440, h=900, note='Controlled by QA Regression · Build'):
    return ('<div style="width: %dpx; height: %dpx; display: flex; flex-direction: column; background: #D9DDE3; font-family: \'Instrument Sans\', sans-serif">' % (w, h)
            + '<div style="height: 44px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 14px; background: #E8EBEF; border-bottom: 1px solid #C9CED6">'
            '<span style="display: flex; gap: 7px"><span class="pdot" style="width: 12px; height: 12px; background: #E0605A"></span><span class="pdot" style="width: 12px; height: 12px; background: #E1B94A"></span><span class="pdot" style="width: 12px; height: 12px; background: #5DBB63"></span></span>'
            '<span style="flex-grow: 1; height: 28px; border-radius: 8px; background: #FFFFFF; border: 1px solid #C9CED6; display: flex; align-items: center; gap: 8px; padding: 0 12px; font-size: 13px; color: #3A4452">'
            + ic('lock', 12, 2) + '<span class="mono" style="font-size: 12.5px">' + url + '</span></span></div>'
            '<div style="height: 30px; flex: none; display: flex; align-items: center; gap: 8px; padding: 0 14px; background: #FFF6D6; border-bottom: 1px solid #E8D48A; font-size: 12px; color: #5A4600">'
            + ic('info', 13, 2) + note + '</div>'
            '<div style="flex-grow: 1; position: relative; overflow: hidden; ' + SITE_CSS + '">' + content + '</div></div>')


def site_header(step_label):
    return ('<div style="height: 64px; display: flex; align-items: center; gap: 28px; padding: 0 48px; border-bottom: 1px solid #E3E7EC">'
            '<span style="width: 132px; height: 26px; border-radius: 4px; background: #E3E7EC; display: grid; place-items: center; font: 600 10px \'JetBrains Mono\', monospace; color: #6B7684">SITE LOGO</span>'
            '<span style="flex-grow: 1"></span>'
            + ''.join('<span style="font-size: 14px; color: %s">%s</span>' % ('#0D6E6E' if s == step_label else '#6B7684', s) for s in ('Trip', 'Travelers', 'Plans', 'Traveler info', 'Payment', 'Review'))
            + '</div>')


def plan_card(x, name, price, feats, hl=''):
    return ('<div style="position: absolute; left: %dpx; top: 150px; width: 250px; height: 380px; border: 1px solid #D5DBE2; border-radius: 10px; padding: 22px; display: flex; flex-direction: column; gap: 12px; background: #FFFFFF">' % x
            + '<span style="font-size: 22px; font-weight: 700">%s</span><span style="font-size: 30px" data-price="1">%s</span><span style="font-size: 12px; color: #6B7684">per trip, 2 travelers</span>' % (name, price)
            + ''.join('<span style="font-size: 13px; color: #3A4452">✓ %s</span>' % f for f in feats)
            + '<span style="flex-grow: 1"></span><span style="height: 42px; border-radius: 6px; background: #0D6E6E; color: #FFFFFF; display: grid; place-items: center; font: 600 14px \'Instrument Sans\', sans-serif; %s">Choose</span></div>' % hl)


def plans_page():
    return (site_header('Plans') + '<div style="position: relative; height: 760px">'
            '<span style="position: absolute; left: 48px; top: 34px; font-size: 34px">Choose your plan</span>'
            '<span style="position: absolute; left: 48px; top: 88px; font-size: 14px; color: #6B7684">Italy · 12–26 Jun · 2 travelers</span>'
            + plan_card(48, 'Basic', '$96.40', ['Trip cancellation $5,000', 'Medical $50,000', 'Baggage $500'])
            + plan_card(318, 'Plus', '$121.80', ['Trip cancellation $10,000', 'Medical $100,000', 'Baggage $1,000'])
            + plan_card(588, 'Max', '$148.20', ['Trip cancellation $20,000', 'Medical $250,000', 'Baggage $2,000'])
            + '<div style="position: absolute; left: 880px; top: 150px; width: 300px; border: 1px solid #D5DBE2; border-radius: 10px; padding: 20px; display: flex; flex-direction: column; gap: 10px; background: #F7F9FB">'
            '<span style="font-size: 17px; font-weight: 700">Your trip</span><span style="font-size: 13px; color: #3A4452">Destination: Italy</span><span style="font-size: 13px; color: #3A4452">Trip cost: $2,500</span>'
            '<span style="font-size: 13px; color: #3A4452">Promo: none</span><span style="height: 1px; background: #D5DBE2"></span><span style="font-size: 15px">Total <b>$96.40</b></span></div>'
            '</div>')


def pill(active='Pick', step='step 190 of 287', rec=True):
    items = ''.join('<button style="height: 30px; padding: 0 11px; border-radius: 8px; font-size: 12.5px; font-weight: 600; display: flex; align-items: center; gap: 6px; %s">%s</button>'
                    % ('background: var(--acc); color: var(--acc-tx)' if t == active else 'color: var(--tx)', t) for t in ('Pick', 'Check', 'Save', 'Wait until'))
    return ('<div data-theme="dark" class="rr" style="position: absolute; left: 50%; top: 14px; transform: translateX(-50%); display: flex; align-items: center; gap: 4px; padding: 5px 6px 5px 8px; border-radius: 14px; background: var(--surface2); border: 1px solid var(--line2); box-shadow: 0 14px 40px rgba(0,0,0,.35); overflow: visible; z-index: 10">'
            '<span style="color: var(--tx4); display: inline-flex; cursor: grab" title="Drag the pill">' + ic('grip', 14) + '</span>'
            '<button style="height: 30px; padding: 0 11px; border-radius: 8px; font-size: 12.5px; font-weight: 700; display: flex; align-items: center; gap: 7px; %s">'
            % ('background: var(--fail-soft); color: var(--fail); box-shadow: inset 0 0 0 1px var(--fail-line)' if rec else 'color: var(--tx2)')
            + '<span class="dot" style="width: 8px; height: 8px"></span>%s</button>' % ('Rec' if rec else 'Rec off')
            + '<span style="width: 1px; height: 20px; background: var(--line2); margin: 0 2px"></span>' + items
            + '<span style="width: 1px; height: 20px; background: var(--line2); margin: 0 2px"></span>'
            '<span class="mono" style="font-size: 11.5px; color: var(--tx2); padding: 0 8px">' + step + '</span>'
            '<button class="btn btn-sm btn-pri" style="height: 30px">Done</button></div>')


def outline(x, y, w, h, label, color='var(--acc)', num=None):
    tag = ('<span class="mono" style="position: absolute; left: -2px; top: -24px; height: 20px; padding: 0 7px; border-radius: 5px; background: %s; color: #06121C; font-size: 11px; display: flex; align-items: center; white-space: nowrap; font-weight: 600">%s</span>' % (color, label)) if label else ''
    n = ('<span class="mono" style="position: absolute; right: -11px; top: -11px; width: 22px; height: 22px; border-radius: 50%%; background: %s; color: #06121C; font-size: 12px; font-weight: 700; display: grid; place-items: center">%s</span>' % (color, num)) if num else ''
    return ('<div data-theme="dark" style="position: absolute; left: %dpx; top: %dpx; width: %dpx; height: %dpx; border: 2px solid %s; border-radius: 7px; box-shadow: 0 0 0 4px color-mix(in srgb, %s 22%%, transparent); pointer-events: none; z-index: 8">%s%s</div>'
            % (x, y, w, h, color, color, tag, n))


def popcard(x, y, w, inner):
    return ('<div data-theme="dark" class="rr" style="position: absolute; left: %dpx; top: %dpx; width: %dpx; border-radius: 14px; background: var(--surface); border: 1px solid var(--line2); box-shadow: 0 24px 60px rgba(0,0,0,.45); overflow: visible; z-index: 9; display: flex; flex-direction: column">' % (x, y, w)
            + inner + '</div>')


# content y offset: site area starts at 74px from window top (44 + 30)
Y0 = 74


def rec_pick():
    # Max card button: card at left 588, top 150+64(header) ; button bottom of card: y = 64+150+380-22-42 = 530
    btn = outline(588 + 22, 530, 206, 42, 'button “Choose” · card “Max”')
    card = popcard(840, 420, 330,
                   '<div style="padding: 12px 14px 10px; display: flex; flex-direction: column; gap: 3px; border-bottom: 1px solid var(--line)">'
                   '<span style="font-size: 13px; font-weight: 700">button “Choose” <span style="color: var(--tx3); font-weight: 500">inside card “Max”</span></span>'
                   '<span class="mono" style="font-size: 11px; color: var(--tx3)">text: Choose · enabled · 1 match</span></div>'
                   '<div style="padding: 6px; display: flex; flex-direction: column; gap: 1px">'
                   '<button class="mitem on">' + badge('act', 'Click') + '<span style="flex-grow: 1">Click it</span><span class="kbd">↵</span></button>'
                   '<button class="mitem">' + badge('check', 'Check') + '<span style="flex-grow: 1">Check it shows</span><span class="kbd">C</span></button>'
                   '<button class="mitem">' + badge('check', 'Check') + '<span style="flex-grow: 1">Check it is enabled</span></button>'
                   '<button class="mitem">' + badge('wait', 'Wait') + '<span style="flex-grow: 1">Wait until it shows</span><span class="kbd">W</span></button>'
                   '<button class="mitem">' + badge('save', 'Save') + '<span style="flex-grow: 1">Save its text as a variable</span><span class="kbd">S</span></button></div>'
                   '<div style="padding: 8px 10px 10px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px">'
                   '<div class="field">' + ic('search', 14) + '<span style="font-size: 12.5px; color: var(--tx3)">Search all 55 actions</span></div>'
                   '<div style="display: flex; flex-wrap: wrap; gap: 4px">' + ''.join('<span class="tag">%s</span>' % t for t in ('Do', 'Type', 'Check', 'Save', 'Wait', 'Window &amp; frames', 'Advanced')) + '</div>'
                   '<span style="display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--tx3)">' + ic('info', 12) + ' Adds step 190 in “Plans · pick {PLAN}” · <b style="color: var(--warn)">Choose</b> isn\'t a purchase, so no side-effect flag</span></div>')
    hover = outline(880, 64 + 150, 300, 180, '', 'rgba(92,200,255,.45)')
    return window('uat.travelex-insurance.test/quote/plans', plans_page() + btn + card + pill('Pick'))


def rec_check():
    price = outline(588 + 22, 64 + 150 + 22 + 30 + 12, 120, 40, 'text “$148.20” · card “Max”')
    groups = [('Text', [('Text is', True), ('Text contains', False)]), ('Shown or gone', [('It shows', False), ('It is gone', False)]),
              ('Control state', [('Field value', False), ('Ticked', False), ('Selected option', False), ('Enabled', False)]),
              ('Numbers & patterns', [('Greater than', False), ('Less than', False), ('Between', False), ('Matches pattern', False), ('Date format', False), ('Item count', False)])]
    g = ''.join('<div style="display: flex; flex-direction: column; gap: 5px"><span class="lbl">%s</span><div style="display: flex; flex-wrap: wrap; gap: 4px">%s</div></div>'
                % (t, ''.join('<button class="btn btn-sm %s" style="font-weight: 500%s">%s</button>' % ('btn-pri' if on else '', '; opacity: .45' if t == 'Control state' else '', n) for n, on in items))
                for t, items in groups)
    card = popcard(760, 150, 400,
                   '<div style="padding: 14px 16px 10px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--line)">' + ic('check', 16, 2.4, 'color: var(--pass)') +
                   '<span style="font-size: 15px; font-weight: 700">Check this</span><span style="font-size: 12px; color: var(--tx3)">text “$148.20” in card “Max”</span></div>'
                   '<div style="padding: 12px 16px; display: flex; flex-direction: column; gap: 12px">' + g +
                   '<span style="font-size: 11.5px; color: var(--tx3); margin-top: -4px">Control-state checks are greyed: this is plain text, not a field.</span>'
                   '<div style="display: flex; flex-direction: column; gap: 6px"><span class="lbl">Expected</span>'
                   '<div class="field"><span class="mono" style="font-size: 13px">$148.20</span><span style="font-size: 11.5px; color: var(--tx3)">from the live page</span><span style="flex-grow: 1"></span></div>'
                   '<div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx2)">' + ic('braces', 13) + ' Swap for a variable:'
                   '<button class="var">' + ic('braces', 11, 2.2) + 'Max price</button><span style="color: var(--tx3)">{PRICE_MAX} · row 1 = $148.20</span></div></div>'
                   '<div style="display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; background: var(--surface2); border: 1px solid var(--line)">'
                   + sw(False) + '<span style="font-size: 12.5px; flex-grow: 1">Also save it as a variable</span><span class="mono" style="font-size: 11.5px; color: var(--tx3)">MAX_PRICE_SHOWN</span></div></div>'
                   '<div style="padding: 10px 16px 14px; display: flex; gap: 8px; border-top: 1px solid var(--line)"><button class="btn btn-pri" style="flex-grow: 1">Add check · step 191</button><button class="btn">Cancel</button></div>')
    return window('uat.travelex-insurance.test/quote/plans', plans_page() + price + card + pill('Check', 'step 191 of 287'))


def rec_which():
    outs = ''.join(outline(x + 22, 530, 206, 42, '', 'var(--warn)', n) for n, x in (('1', 48), ('2', 318), ('3', 588)))
    card = popcard(860, 330, 360,
                   '<div style="padding: 14px 16px 10px; display: flex; flex-direction: column; gap: 4px; border-bottom: 1px solid var(--line)">'
                   '<span style="font-size: 15px; font-weight: 700">3 buttons match “Choose”. Which one?</span>'
                   '<span style="font-size: 12px; color: var(--tx3)">From “Click button…” in the action menu. Pick one here or click it on the page.</span></div>'
                   '<div style="padding: 6px; display: flex; flex-direction: column; gap: 2px">'
                   + ''.join('<button class="mitem%s"><span class="mono" style="width: 20px; height: 20px; border-radius: 50%%; background: var(--warn); color: #06121C; display: grid; place-items: center; font-size: 11px; font-weight: 700">%s</span><span style="flex-grow: 1">in card “%s”</span><span class="mono" style="font-size: 11px; color: var(--tx3)">%s</span></button>'
                             % (' on' if n == '3' else '', n, c, p) for n, c, p in (('1', 'Basic', '$96.40'), ('2', 'Plus', '$121.80'), ('3', 'Max', '$148.20')))
                   + '</div><div style="padding: 10px 14px 12px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px">'
                   '<button class="mitem" style="height: auto; padding: 8px 10px; align-items: flex-start; border: 1px dashed var(--line2)">' + ic('braces', 15, 1.8, 'color: var(--k-input); margin-top: 2px') +
                   '<span style="display: flex; flex-direction: column; gap: 2px"><b style="font-size: 13px">The one in the card for Plan</b><span style="font-size: 11.5px; color: var(--tx3)">Row 1 → Basic, row 2 → Max. The locator follows {PLAN}.</span></span></button>'
                   '<span class="mono" style="font-size: 11px; color: var(--tx3)">Builds: [data-plan=Max] » button “Choose” · 2 backups</span></div>')
    return window('uat.travelex-insurance.test/quote/plans', plans_page() + outs + card + pill('Pick', 'step 190 of 287'))


def traveler_page():
    fields = [('First name', 'Jane'), ('Last name', 'Doe'), ('Date of birth', ''), ('Email', ''), ('Account password', '••••••••')]
    f = ''.join('<div style="position: absolute; left: 48px; top: %dpx; display: flex; flex-direction: column; gap: 6px; width: 420px"><span style="font-size: 14px">%s</span>'
                '<span style="height: 42px; border: 1px solid %s; border-radius: 6px; padding: 0 12px; display: flex; align-items: center; font: 15px \'Instrument Sans\', sans-serif">%s</span></div>'
                % (150 + i * 84, n, '#0D6E6E' if n == 'First name' else '#C8D0D9', v) for i, (n, v) in enumerate(fields))
    return (site_header('Traveler info') + '<div style="position: relative; height: 760px">'
            '<span style="position: absolute; left: 48px; top: 34px; font-size: 34px">Traveler information</span>'
            '<span style="position: absolute; left: 48px; top: 88px; font-size: 14px; color: #6B7684">Traveler 1 of 2</span>' + f + '</div>')


def rec_variables():
    # left: site window 900 wide with typed prompt; right: builder inspector with the data-target step
    typed = popcard(490, 64 + 150 + 12, 330,
                    '<div style="padding: 12px 14px; display: flex; flex-direction: column; gap: 10px">'
                    '<span style="font-size: 13px"><b>You typed “Jane”.</b> <span style="color: var(--tx2)">Keep it as a variable so each data row can use its own name?</span></span>'
                    '<div class="field" style="min-height: 40px"><span class="var">' + ic('braces', 11, 2.2) + 'Traveler first name</span><span class="mono" style="font-size: 11px; color: var(--tx3)">{FIRST_NAME}</span>'
                    '<span style="flex-grow: 1"></span><span class="tag tag-pass">reused</span></div>'
                    '<span style="font-size: 11.5px; color: var(--tx3)">Params_2 row 1 already holds “Jane”, so the existing variable is reused.</span>'
                    '<div style="display: flex; gap: 6px"><button class="btn btn-sm btn-pri">Keep as variable</button><button class="btn btn-sm">Use fixed text</button><button class="btn btn-sm btn-ghost">Rename</button></div></div>')
    secret = popcard(490, 64 + 150 + 336 + 12, 330,
                     '<div style="padding: 10px 14px; display: flex; align-items: center; gap: 10px">' + ic('lock', 16, 2, 'color: var(--warn)') +
                     '<span style="font-size: 12.5px; color: var(--tx2)"><b style="color: var(--tx)">Password field → secret variable</b> UAT_PASSWORD. Stored in secrets.env for UAT only; shown as ••••.</span></div>')
    toasts = ('<div data-theme="dark" class="rr" style="position: absolute; left: 16px; bottom: 16px; width: 420px; display: flex; flex-direction: column; gap: 8px; background: transparent; overflow: visible">'
              '<div style="padding: 10px 12px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line2); box-shadow: var(--pop); display: flex; gap: 10px; font-size: 12.5px">'
              + ic('bolt', 15, 2, 'color: var(--k-input); margin-top: 2px') + '<span style="flex-grow: 1"><b>5 clicks became one step:</b> Pick date <span class="var">Departure date</span> in Departure date'
              '<span style="display: flex; gap: 6px; margin-top: 7px"><button class="btn btn-sm">Keep raw clicks</button></span></span></div>'
              '<div style="padding: 10px 12px; border-radius: 12px; background: var(--surface2); border: 1px solid var(--line2); box-shadow: var(--pop); display: flex; gap: 10px; font-size: 12.5px">'
              + ic('gate', 15, 2, 'color: var(--pass); margin-top: 2px') + '<span style="flex-grow: 1"><b>New page: /purchase/travelers.</b> Save it as “Traveler info page”? '
              '<span style="color: var(--tx2)">URL contains /purchase/travelers AND heading “Traveler information” shows.</span>'
              '<span style="display: flex; gap: 6px; margin-top: 7px"><button class="btn btn-sm btn-pri">Save fingerprint + add gate</button><button class="btn btn-sm">Edit</button><button class="btn btn-sm btn-ghost">Not now</button></span></span></div></div>')
    left = window('uat.travelex-insurance.test/purchase/travelers', traveler_page() + outline(48, 64 + 150 + 28, 420, 42, 'text field “First name”') + typed + secret + toasts
                  + pill('Pick', 'step 190 of 287'), w=900, h=900)
    words = [('button', 'tag'), ('“Choose”', 'btn btn-sm'), ('inside card', 'tag'), ('“Max”', 'btn btn-sm')]
    right = ('<div class="rr" data-theme="dark" style="width: 540px; height: 900px; display: flex; flex-direction: column; background: var(--rail); border-left: 1px solid var(--line)">'
             '<div style="padding: 14px 18px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 6px">'
             '<span class="lbl">Builder window · inspector</span>'
             '<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="font-size: 12px; color: var(--tx3)">Step 190</span>' + badge('act', 'Click') + '</div>'
             '<span class="disp" style="font-size: 19px; font-weight: 700">Click Choose in the <span class="var" style="font-family: \'Instrument Sans\', sans-serif; font-size: 13px; vertical-align: 2px">Plan</span> card</span></div>'
             '<div style="padding: 16px 18px; display: flex; flex-direction: column; gap: 16px">'
             '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">1 · In plain words</span>'
             '<div style="display: flex; flex-wrap: wrap; gap: 5px; align-items: center">' + ''.join('<button class="%s"%s>%s</button>' % (c, ' style="box-shadow: 0 0 0 2px var(--acc)"' if t == '“Max”' else '', t) for t, c in words) + '</div>'
             '<div class="menu" style="padding: 6px; width: 320px">'
             '<span class="lbl" style="display: block; padding: 4px 8px">Make “Max” a variable</span>'
             '<button class="mitem on">' + ic('braces', 14) + '<span style="flex-grow: 1">Plan <span class="mono" style="color: var(--tx3); font-size: 11px">{PLAN}</span></span><span class="tag">Params_1</span></button>'
             '<button class="mitem">' + ic('plus', 14) + '<span style="flex-grow: 1">New variable…</span></button></div></div>'
             '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">2 · Locator rebuilt for you</span>'
             '<div class="field mono" style="font-size: 12px; flex-direction: column; align-items: flex-start; gap: 4px"><span style="color: var(--tx3); text-decoration: line-through">[data-plan=Max] » button “Choose”</span>'
             '<span>[data-plan=<span class="var" style="font-family: \'Instrument Sans\', sans-serif">Plan</span>] » button “Choose”</span></div></div>'
             '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">3 · Re-checked on the live page</span>'
             '<div class="bn bn-pass">' + ic('check', 15, 2.4, 'color: var(--pass)') + '<span><b>1 match</b> with Row 1 (Plan = Basic): the Choose button in the Basic card. Row 2 (Max) also resolves to 1 match.</span></div></div>'
             '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Backups stored with the step</span>'
             '<div style="display: flex; flex-direction: column; gap: 4px" class="mono">'
             '<span class="tag" style="justify-content: flex-start">1 · test id plan-{PLAN}-choose</span><span class="tag" style="justify-content: flex-start">2 · card heading “{PLAN}” » button</span></div>'
             '<span style="font-size: 12px; color: var(--tx3)">If the main locator breaks, the step still fails; the backups only suggest a fix.</span></div></div></div>')
    return '<div style="width: 1440px; height: 900px; display: flex">' + left + right + '</div>'


if __name__ == '__main__':
    write('RecPick.dc.html', page('Recording · pick and act', rec_pick(), W, H))
    write('RecCheck.dc.html', page('Recording · check this', rec_check(), W, H))
    write('RecWhichOne.dc.html', page('Recording · which one?', rec_which(), W, H))
    write('RecVariables.dc.html', page('Recording · values become variables', rec_variables(), W, H))
