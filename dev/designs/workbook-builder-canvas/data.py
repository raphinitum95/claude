"""Round-1 Travelex test (300 rows) reshaped to the round-2 decisions.

- API rows 182-189 and XML rows 292-298 move into their own tests (Q20); this test calls them (CALL_TEST) -> 287 steps.
- Step names become automatic sentences (Q38) with variable chips showing friendly labels (Q37); card data are secrets (Q42).
- Old fixed waits stay, with a hint (Q41). Row 254 is a legacy SNAGIT_SCREENSHOT, row 299 has a formula blnExecute (Q28).
- Rows 23-25 are disabled (blnExecute = N) (Q39). Purchase has side effects (Q13). Frames / tabs carry context tags (Q34).
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'round1_steps.json')))

LABELS = {
    'BASE_URL': 'Base URL', 'DESTINATION': 'Destination', 'DEPART_DAY': 'Departure day', 'RETURN_DAY': 'Return day', 'TRIP_DAYS': 'Trip length',
    'TRIP_COST': 'Trip cost', 'DEPOSIT_DATE': 'Deposit date', 'STATE': 'State', 'ZIP': 'Zip code', 'TRAVELER_COUNT': 'Traveler count',
    'PROMO_CODE': 'Promo code', 'DISCOUNT': 'Discount', 'PLAN': 'Plan', 'PRICE_BASIC': 'Basic price', 'PRICE_MAX': 'Max price',
    'FIRST_NAME': 'Traveler first name', 'LAST_NAME': 'Traveler last name', 'DOB': 'Date of birth', 'EMAIL': 'Traveler email',
    'PHONE': 'Traveler phone', 'PASSPORT': 'Passport no.', 'EMERG_NAME': 'Emergency contact', 'EMERG_PHONE': 'Emergency phone',
    'GENDER': 'Gender', 'STREET': 'Street', 'UNIT': 'Apt / unit', 'CITY': 'City', 'BEN_NAME': 'Beneficiary', 'BEN_REL': 'Relationship',
    'TEST_CARD': 'Test card', 'CARD_EXP': 'Card expiry', 'CARD_CVV': 'Card CVV', 'CARD_NAME': 'Name on card', 'BAD_ZIP': 'Invalid zip',
    'API_PREMIUM': 'Quoted premium', 'QUOTE_ID': 'Quote id', 'POLICY_NO': 'Policy number', 'POLICY_STATUS': 'Policy status',
    'RUN_ID': 'Run id', 'i': 'Traveler #', 'TAB': 'Tab key',
}
SECRETS = {'TEST_CARD', 'CARD_CVV'}
ENVVARS = {'BASE_URL'}


def label(tok):
    if tok in LABELS:
        return LABELS[tok]
    m = re.match(r'(BASIC|MAX)_(\w+)', tok)
    if m:
        return m.group(1).title() + ' ' + m.group(2).lower() + ' limit'
    m = re.match(r'DISCLOSURE_(\d+)', tok)
    if m:
        return 'Disclosure ' + m.group(1)
    return tok.replace('_', ' ').capitalize()


def parts(text):
    """Sentence -> [{t, v, secret, env, tok}] with {TOKENS} as variable chips."""
    out = []
    for i, seg in enumerate(re.split(r'\{([A-Za-z_0-9]+)\}', text)):
        if not seg:
            continue
        if i % 2:
            out.append({'t': ('•••• ' if seg in SECRETS else '') + label(seg), 'v': True, 'secret': seg in SECRETS, 'env': seg in ENVVARS, 'tok': seg})
        else:
            out.append({'t': seg, 'v': False, 'secret': False, 'env': False, 'tok': ''})
    return out


GROUP_OF = {'nav': 'nav', 'act': 'act', 'input': 'input', 'check': 'check', 'save': 'save', 'wait': 'wait', 'api': 'api', 'xml': 'xml'}


def sentence(r):
    m, t, val, exp, sv = r['m'], r['t'], r['val'], r['exp'], r['sv']
    how = 'contains' if r['opt'] == 'contains' else 'is'
    if m == 'OPEN': return 'Open ' + val
    if m == 'WAIT': return 'Wait %s s' % val
    if m == 'CLICK': return 'Click ' + t
    if m == 'SET': return 'Type %s into %s' % (val, t)
    if m == 'SELECT': return 'Choose %s in %s' % (val, t)
    if m == 'TICK': return 'Tick ' + t
    if m == 'SENDKEYS': return 'Press %s in %s' % (val, t)
    if m == 'EXIST': return 'Check %s shows' % t
    if m == 'NOT_EXIST': return 'Check %s is gone' % t
    if m == 'INNERTEXT' and sv: return 'Save %s text as %s' % (t, '{' + sv + '}')
    if m == 'INNERTEXT': return 'Check %s text %s %s' % (t, how, exp)
    if m == 'VALUE': return 'Check %s value is %s' % (t, exp)
    if m == 'SCREENSHOT': return 'Screenshot · ' + t
    if m == 'SET_VARIABLE': return 'Set %s to %s' % ('{' + t + '}', val)
    if m == 'SWITCHTOMAINWINDOW': return 'Back to the main window'
    if m == 'NAVIGATE': return 'Go back to the ' + t
    if m == 'QUIT': return 'Close the browser'
    return t


VERB = {'OPEN': ('Open', 'nav'), 'WAIT': ('Wait', 'wait'), 'CLICK': ('Click', 'act'), 'SET': ('Type', 'input'), 'SELECT': ('Choose', 'input'),
        'TICK': ('Tick', 'input'), 'SENDKEYS': ('Press', 'input'), 'EXIST': ('Shows', 'check'), 'NOT_EXIST': ('Gone', 'check'),
        'INNERTEXT': ('Text', 'check'), 'VALUE': ('Value', 'check'), 'SCREENSHOT': ('Shot', 'save'), 'SET_VARIABLE': ('Set', 'save'),
        'SWITCHTOWINDOW': ('Switch', 'nav'), 'SWITCHTOMAINWINDOW': ('Switch', 'nav'), 'NAVIGATE': ('Back', 'nav'), 'QUIT': ('Close', 'nav')}

GATE_WAITS = {38: 'Trip details', 81: 'Plans', 193: 'Traveler info', 231: 'Payment', 256: 'Review', 268: 'Confirmation'}


def build():
    rows = []
    old_blocks = D['blocks']

    def old_block(n):
        for b in old_blocks:
            if b['start'] < n <= b['end']:
                return b['i']

    for r in D['rows']:
        n = r['n']
        if 183 <= n <= 189 or 293 <= n <= 298:
            continue                                                  # moved into quotePrice#1 / policyRecord#1
        x = dict(old=n, blk=old_block(n), page=r['pg'], m=r['m'], fb=r['fb'], loc=r['loc'], val=r['val'], exp=r['exp'], sv=r['sv'],
                 opt=r['opt'], name=r['t'], ctx='', legacy='', disabled=False, side=False, failed=False, problem='', hint='', call='', xrow=0)
        if n == 182:
            x.update(m='CALL_TEST', call='quotePrice#1', page='Plans', val='', loc='')
            s = 'Run quotePrice#1 (API test), then carry on'
            verb, kind = 'Call', 'api'
        elif n == 292:
            x.update(m='CALL_TEST', call='policyRecord#1', page='Confirmation', val='', loc='')
            s = 'Run policyRecord#1 (XML test), then carry on'
            verb, kind = 'Call', 'xml'
        elif n == 233:
            x.update(m='SWITCHTOFRAME')
            s = 'Switch into the card frame'
            verb, kind = 'Frame', 'nav'
        elif n == 285:
            s = 'Switch to the new tab · Policy details'
            verb, kind = 'Switch', 'nav'
        elif n == 254:
            x.update(m='SNAGIT_SCREENSHOT', legacy='SNAGIT_SCREENSHOT used the SnagIt desktop app on the old Windows runner. The new runner skips it and takes a normal screenshot instead.')
            s = 'SNAGIT_SCREENSHOT · Payment filled'
            verb, kind = 'Legacy', 'legacy'
        elif n == 299:
            x.update(legacy='blnExecute is a formula here: =IF($D$13="PASSED","Y","N"). The builder keeps it byte-for-byte; edit it in the Excel grid.')
            s = sentence(r)
            verb, kind = 'Legacy', 'legacy'
        else:
            s = sentence(r)
            verb, kind = VERB.get(r['m'], (r['v'], GROUP_OF.get(r['g'], 'act')))
            if r['m'] == 'INNERTEXT' and r['sv']:
                verb, kind = 'Save', 'save'
        if r['m'] == 'WAIT':
            x['hint'] = ('The page gate for %s already waits for it.' % GATE_WAITS[n]) if n in GATE_WAITS else 'The engine already waits for the page to settle.'
        if 234 <= n <= 239:
            x['ctx'] = 'inside frame: card'
        if 286 <= n <= 289:
            x['ctx'] = 'Tab 2 · Policy details'
        if n in (23, 24, 25):
            x['disabled'] = True
        if n == 267:
            x['side'] = True
        if n in (211, 235):
            x['failed'] = True
        if n == 181:
            x['problem'] = 'red'
        x['sentence'] = s
        x['verb'] = verb
        x['kind'] = kind
        rows.append(x)

    for i, x in enumerate(rows):
        x['n'] = i + 1
        x['xrow'] = x['old'] + 1                                        # row 1 of the sheet is the header
        x['parts'] = parts(x['sentence'])

    blocks = []
    for b in old_blocks:
        mine = [x for x in rows if x['blk'] == b['i']]
        nb = dict(i=b['i'], title=b['title'], kind=b['kind'], page=b['page'], times=b['times'], returns=b['returns'], cond=b['cond'],
                  start=mine[0]['n'] - 1, end=mine[-1]['n'], lanes=[], gate='', gateState='', detour=False)
        for ln in b['lanes']:
            lr = [x for x in mine if ln['start'] < x['old'] <= ln['end']]
            nb['lanes'].append(dict(label=ln['label'], start=lr[0]['n'] - 1, end=lr[-1]['n']))
        blocks.append(nb)
    B = {b['i']: b for b in blocks}
    B[7].update(title='Calls quotePrice#1', kind='call', page='API test', returns='Plans', detour=True)
    B[15].update(detour=True)
    B[16].update(title='Calls policyRecord#1', kind='callxml', page='XML test', returns='Confirmation', detour=True)
    B[5].update(cond='{PROMO_CODE} is filled in')
    for i, pg in ((0, 'Home'), (3, 'Trip details'), (4, 'Travelers'), (5, 'Plans'), (9, 'Traveler info'), (11, 'Payment'), (12, 'Review'), (14, 'Confirmation'), (15, 'Policy details')):
        B[i].update(gate=pg, gateState='set')
    B[13].update(gate='Plans', gateState='suggest')
    B[10].update(gate='', gateState='')

    # problems per block (red / amber dots on the map)
    for x in rows:
        b = B[x['blk']]
        if x['problem'] == 'red' or x['failed']:
            b['dot'] = 'fail'
    B[13]['dot'] = B[13].get('dot') or 'warn'
    B[12]['dot'] = 'warn'                                                # side-effect step: blocked on PROD
    return rows, blocks


if __name__ == '__main__':
    rows, blocks = build()
    print(len(rows))
    for b in blocks:
        print(b['i'], b['title'], b['kind'], b['start'], b['end'], b['gate'], b.get('dot'))
    for x in rows:
        if x['n'] in (1, 34, 44, 176, 177, 182, 196, 211, 226, 227, 247, 260, 280, 281, 286, 287):
            print(x['n'], x['xrow'], x['verb'], x['sentence'], x['ctx'], x['legacy'][:20])
