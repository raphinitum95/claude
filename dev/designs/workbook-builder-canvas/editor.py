"""Test editor (mix layout): block map + step cards + inspector + rail, with grid view, data drawer, problems, fix mode."""
import json
from common import *
from data import build

ROWS, BLOCKS = build()
BY_OLD = {x['old']: x['n'] for x in ROWS}

W, H = 1440, 1000
MAPX, MAPGAP, NODEW, NODEH = 16, 172, 150, 66
TOPY, LOWY = 30, 112


def map_geometry():
    nodes, x = [], MAPX
    for b in BLOCKS:
        y = LOWY if b['detour'] else TOPY
        nodes.append({'i': b['i'], 'x': x, 'y': y})
        x += MAPGAP
    width = x + 20
    paths = []
    for a, b in zip(nodes, nodes[1:]):
        x1, y1 = a['x'] + NODEW, a['y'] + NODEH / 2
        x2, y2 = b['x'], b['y'] + NODEH / 2
        if y1 == y2:
            paths.append('M%d,%d H%d' % (x1, y1, x2))
        else:
            mx = (x1 + x2) / 2
            paths.append('M%d,%d C%d,%d %d,%d %d,%d' % (x1, y1, mx, y1, mx, y2, x2, y2))
    svg = ('<svg width="%d" height="196" style="position: absolute; left: 0; top: 0" aria-hidden="true">'
           '<line x1="0" y1="%d" x2="%d" y2="%d" stroke="var(--acc-soft)" stroke-width="18"></line>' % (width, TOPY + NODEH / 2, width, TOPY + NODEH / 2)
           + ''.join('<path d="%s" fill="none" stroke="var(--line2)" stroke-width="2.5"></path>' % p for p in paths)
           + '<text x="%d" y="186" fill="var(--tx3)" font-size="11" font-family="Instrument Sans, sans-serif">↓ detours leave the site and come back</text>' % (nodes[7]['x'] - 4)
           + '</svg>')
    return nodes, width, svg


NODES, MAPW, MAPSVG = map_geometry()

# plain-words element descriptions (Q11) for web steps, derived from the locator
def describe(x):
    loc, name = x['loc'], x['name']
    if not loc:
        return []
    kind = 'element'
    if x['m'] in ('SET', 'VALUE') or 'input' in loc: kind = 'text field'
    if x['m'] == 'SELECT' or 'select' in loc: kind = 'dropdown'
    if x['m'] == 'TICK': kind = 'checkbox'
    if 'button' in loc: kind = 'button'
    if '//a' in loc or loc.startswith('//a'): kind = 'link'
    words = [{'t': kind, 'var': False, 'q': False}]
    nm = name.replace('{i}', '').strip()
    if 'data-plan' in loc:
        words += [{'t': '"Choose"', 'var': False, 'q': True}, {'t': 'inside card', 'var': False, 'q': False},
                  {'t': 'Plan' if '{PLAN}' in loc else '"Max"', 'var': '{PLAN}' in loc, 'q': '{PLAN}' not in loc}]
    else:
        words.append({'t': '"%s"' % nm.split(':')[0], 'var': False, 'q': True})
    if '{i}' in loc or x['blk'] == 9:
        words += [{'t': 'inside section', 'var': False, 'q': False}, {'t': 'Traveler #', 'var': True, 'q': False}]
    elif x['ctx'].startswith('inside frame'):
        words += [{'t': 'inside frame', 'var': False, 'q': False}, {'t': '"card"', 'var': False, 'q': True}]
    return words


def locator(x):
    loc = x['loc']
    if not loc:
        return ('', '', 0)
    if "data-qa='" in loc:
        v = loc.split("data-qa='")[1].split("'")[0]
        return ('Test id', 'data-qa = %s' % v, 2)
    if "@id='" in loc:
        v = loc.split("@id='")[1].split("'")[0]
        return ('Id', '#%s' % v, 2)
    if "label[text()='" in loc:
        v = loc.split("label[text()='")[1].split("'")[0]
        extra = '  within section[data-traveler={i}]' if x['blk'] == 9 else ''
        return ('Label', 'label "%s"%s' % (v, extra), 2)
    if "text()='" in loc:
        v = loc.split("text()='")[1].split("'")[0]
        tag = 'button' if 'button' in loc else ('link' if '//a' in loc else 'text')
        return ('Text', '%s "%s"' % (tag, v), 1)
    if "@name='" in loc:
        v = loc.split("@name='")[1].split("'")[0]
        return ('Attribute', 'name = %s' % v, 2)
    return ('XPath', loc, 0)


def card_data():
    out = []
    lastfail = BY_OLD[235]
    for x in ROWS:
        fb, lc, backups = locator(x)
        st = 'pass'
        if x['failed']: st = 'fail'
        elif x['n'] > lastfail: st = 'pend'
        if x['disabled']: st = 'off'
        out.append({
            'n': x['n'], 'xrow': x['xrow'], 'verb': x['verb'], 'kind': x['kind'], 'page': x['page'], 'ctx': x['ctx'], 'legacy': x['legacy'],
            'disabled': x['disabled'], 'side': x['side'], 'failed': x['failed'], 'problem': x['problem'], 'hint': x['hint'], 'call': x['call'],
            'parts': [dict(p, cls='var' + (' secret' if p['secret'] else '') + (' env' if p['env'] else '')) for p in x['parts']],
            'sentence': x['sentence'], 'm': x['m'], 'fb': fb, 'loc': lc, 'rawloc': x['loc'], 'backups': backups, 'val': x['val'], 'exp': x['exp'], 'sv': x['sv'],
            'opt': x['opt'], 'name': x['name'], 'desc': describe(x), 'last': st, 'blk': x['blk'],
        })
    return out


CARDS = card_data()

BLOCKS_JS = [{k: b[k] for k in ('i', 'title', 'kind', 'page', 'times', 'returns', 'cond', 'start', 'end', 'lanes', 'gate', 'gateState', 'detour')} | {'dot': b.get('dot', '')} for b in BLOCKS]

PARAMS1 = [
    [True, 1, 'NE · Basic', 'Italy', 'NE', 'Basic', '', '2500', '2'],
    [True, 2, 'NY · Max · promo', 'Japan', 'NY', 'Max', 'SPRING10', '4800', '2'],
    [True, 3, 'CA · Basic · solo', 'Mexico', 'CA', 'Basic', '', '1200', '1'],
    [True, 4, 'TX · Max · family', 'France', 'TX', 'Max', 'SPRING10', '6100', '3'],
    [True, 5, 'FL · Basic', 'Canada', 'FL', 'Basic', '', '900', '1'],
    [True, 6, 'WA · Max', 'United Kingdom', 'WA', 'Max', '', '3300', '2'],
    [False, 7, 'IL · Basic · promo', 'Spain', 'IL', 'Basic', 'SPRING10', '2100', '2'],
    [True, 8, 'GA · Max · family', 'Australia', 'GA', 'Max', '', '7400', '4'],
]
PARAMS2 = [
    [True, 1, 'Jane', 'Doe', '12/04/1986', 'jane.doe@example.com', 'Female', 'Alex Doe'],
    [True, 2, 'Omar', 'Haddad', '02/11/1979', 'omar.haddad@example.com', 'Male', 'Sara Haddad'],
]

PROBLEMS = [
    ('fail', 'Step 181', 'Uses Disclosure 35 {DISCLOSURE_35}, but no data column or earlier step sets it.', 'Add column to Params_1'),
    ('fail', 'Step 204', 'Choose Gender: the element was not found on the last run (25 Sep, UAT).', 'Fix in builder'),
    ('fail', 'Step 228', 'Card number: not found on the last run. A backup found 1 likely match.', 'Review suggestion'),
    ('warn', 'Step 260', 'Click Purchase has side effects. It will be blocked on PROD.', 'Show step'),
    ('warn', 'Block 14', 'Change plan returns to the Plans page but has no page gate.', 'Add gate: Plans page'),
    ('warn', 'Environments', 'PROD has no value for API_KEY. quotePrice#1 needs it.', 'Open environments'),
    ('warn', '15 steps', 'Fixed waits the engine already covers (page gates and settle).', 'Review waits'),
]


def T(s):
    return s


TEMPLATE = root_open(W, H, '{{theme}}') + header('Build',
    middle=('<span class="trunc" style="font-size: 13px; color: var(--tx3)">UAT_AEM_Travelex Regression_v9.1.xlsx</span>' + ic('chevr', 13, 2.2, 'color: var(--tx3)')
            + '<span class="disp" style="font-size: 17px; font-weight: 700">Owner_CRVD</span>'
            + '<button class="btn btn-ghost btn-sm" style="padding: 0 6px" aria-label="Rename test">' + ic('pencil', 13) + '</button>'),
    right=('<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--tx3)">' + ic('check', 13, 2.4, 'color: var(--pass)') + ' Draft autosaved 09:41</span>'
           '<button class="icon-btn" aria-label="Undo ({{mod}}Z)" title="Undo  {{mod}}Z">' + ic('undo', 15) + '</button>'
           '<button class="icon-btn" aria-label="Redo" title="Redo">' + ic('redo', 15) + '</button>'
           '<button class="btn btn-sm {{probBtnCls}}" onClick="{{toggleProblems}}">' + ic('warn', 14) + ' Problems 7</button>'
           '<button class="icon-btn" aria-label="History">' + ic('history', 15) + '</button>'
           '<button class="btn btn-pri">' + ic('download', 15, 2) + ' Save to Excel</button>'
           '<button class="icon-btn" aria-label="Switch between light and dark">' + ic('sun', 15) + '</button>'))

TEMPLATE += (
    '<div style="height: 52px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 16px; border-bottom: 1px solid var(--line); background: var(--rail)">'
    '<span class="chip" style="height: 28px">' + ic('web', 14) + ' Website test</span>'
    '<span class="mono" style="font-size: 12px; color: var(--tx3)">287 steps · 18 blocks</span>'
    '<span style="width: 1px; height: 22px; background: var(--line)"></span>'
    '<button class="chip" title="Variables this test reads that something else must provide">' + ic('arrowr', 13, 2) + ' Needs 14</button>'
    '<button class="chip" title="Variables this test sets for later tests">' + ic('arrowl', 13, 2) + ' Provides 4</button>'
    '<span style="flex-grow: 1"></span>'
    '<label style="display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--tx3)">Building with'
    '<button class="chip chip-acc" style="height: 30px">' + ic('table', 13) + ' {{buildingWith}} ' + ic('chevron', 13, 2) + '</button></label>'
    '<div class="seg" role="group" aria-label="View"><button class="{{segCards}}" onClick="{{showCards}}">' + ic('list', 14) + ' Cards</button>'
    '<button class="{{segGrid}}" onClick="{{showGrid}}">' + ic('grid', 14) + ' Excel grid</button></div>'
    '<button class="btn">' + ic('rec', 14, 2, 'color: var(--fail)') + ' Record</button>'
    '<button class="btn">' + ic('play', 13, 2) + ' Try it on UAT</button>'
    '</div>'
    '<div style="flex-grow: 1; display: flex; min-height: 0">'
    + rail_workbook() +
    # ---------------------------------------------------------------- main
    '<main style="flex-grow: 1; min-width: 0; display: flex; flex-direction: column; position: relative">'
    '<div style="flex: none; border-bottom: 1px solid var(--line); background: var(--rail)">'
    '<div style="display: flex; align-items: center; gap: 10px; padding: 10px 18px 0">'
    '<span class="lbl">Test map</span><span style="font-size: 12px; color: var(--tx3)">Blocks run left to right. Drag steps onto a block to move them.</span>'
    '<span style="flex-grow: 1"></span>'
    '<button class="btn btn-ghost btn-sm">' + ic('split', 13) + ' Split</button><button class="btn btn-ghost btn-sm">' + ic('merge', 13) + ' Merge</button>'
    '<button class="btn btn-ghost btn-sm">' + ic('plus', 13, 2.2) + ' Add block</button></div>'
    '<div class="scroll" style="overflow-x: auto; overflow-y: hidden"><div style="position: relative; width: ' + str(MAPW) + 'px; height: 196px">' + MAPSVG +
    '<sc-for list="{{map}}" as="m" hint-placeholder-count="8">'
    '<button onClick="{{m.pick}}" aria-label="{{m.title}}" style="position: absolute; left: {{m.x}}px; top: {{m.y}}px; width: ' + str(NODEW) + 'px; height: ' + str(NODEH) + 'px; border-radius: 11px; padding: 8px 10px; display: flex; flex-direction: column; justify-content: space-between; background: var(--surface); border: 1px solid var(--line2); {{m.style}}">'
    '<span style="display: flex; align-items: center; gap: 6px"><span class="badge {{m.kindCls}}" style="height: 17px; font-size: 9px; padding: 0 5px">{{m.kindLabel}}</span>'
    '<sc-if value="{{m.hasGate}}" hint-placeholder-val="{{false}}"><span style="color: var(--pass); display: inline-flex" title="Page gate">' + ic('gate', 12, 2) + '</span></sc-if>'
    '<span class="mono" style="font-size: 10px; color: var(--tx3)">{{m.count}}</span><span style="flex-grow: 1"></span>'
    '<sc-if value="{{m.hasDot}}" hint-placeholder-val="{{false}}"><span class="pdot" style="background: {{m.dotColor}}"></span></sc-if></span>'
    '<span class="trunc" style="font-size: 12.5px; font-weight: 600; width: 100%">{{m.title}}</span></button>'
    '</sc-for></div></div></div>'
    # session banner
    '<sc-if value="{{session}}" hint-placeholder-val="{{true}}">'
    '<div style="flex: none; display: flex; align-items: center; gap: 10px; padding: 8px 18px; border-bottom: 1px solid var(--acc-line); background: var(--acc-soft); font-size: 12.5px">'
    '<span class="dot" style="color: var(--acc); width: 8px; height: 8px"></span><b>Build session open on UAT</b>'
    '<span style="color: var(--tx2)">Replayed steps 1–{{sessionAt}} with Row 1 · the browser window is waiting at step {{sessionAt}}</span>'
    '<span style="flex-grow: 1"></span>'
    '<sc-if value="{{staleWarn}}" hint-placeholder-val="{{false}}"><span class="tag tag-warn">' + ic('warn', 12) + ' Steps 44–47 changed · replay from the start to be sure</span></sc-if>'
    '<button class="btn btn-sm">Run next 5</button><button class="btn btn-sm btn-ghost">Close session</button></div></sc-if>'
    # block header
    '<div style="flex: none; display: flex; align-items: center; gap: 12px; padding: 12px 18px 8px">'
    '<button class="icon-btn" onClick="{{prev}}" aria-label="Previous block">' + ic('chevl', 14, 2.2) + '</button>'
    '<div style="display: flex; flex-direction: column; gap: 2px; min-width: 0">'
    '<div style="display: flex; align-items: center; gap: 8px"><span class="badge {{cur.kindCls}}">{{cur.kindLabel}}</span><span class="disp trunc" style="font-size: 20px; font-weight: 700">{{cur.title}}</span>'
    '<button class="btn btn-ghost btn-sm" style="padding: 0 5px" aria-label="Rename block">' + ic('pencil', 12) + '</button></div>'
    '<span style="font-size: 12px; color: var(--tx3)">Block {{cur.pos}} of 18 · steps {{cur.range}} · {{cur.sub}}</span></div>'
    '<button class="icon-btn" onClick="{{next}}" aria-label="Next block">' + ic('chevr', 14, 2.2) + '</button>'
    '<span style="flex-grow: 1"></span>'
    '<div class="field" style="width: 220px; min-height: 32px; padding: 0 10px; color: var(--tx3)">' + ic('search', 14) + '<span style="flex-grow: 1; font-size: 12.5px">Find a step, element, variable</span><span class="kbd">/</span></div>'
    '<button class="btn" onClick="{{toggleMenu}}">' + ic('plus', 14, 2.2) + ' Add step ' + ic('chevron', 13, 2) + '</button></div>'
    # gate chip
    '<sc-if value="{{cur.gateSet}}" hint-placeholder-val="{{true}}"><div style="flex: none; padding: 0 18px 8px"><div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 10px; border: 1px solid var(--pass-line); background: var(--pass-soft); font-size: 12.5px">'
    '<span style="color: var(--pass); display: inline-flex">' + ic('gate', 16, 2) + '</span><b>Arrived at: {{cur.gate}} page</b>'
    '<span class="trunc" style="color: var(--tx2)">{{cur.gateRule}}</span><span style="flex-grow: 1"></span>'
    '<span class="tag tag-fail" title="A failed gate always stops the test">hard stop</span><button class="btn btn-ghost btn-sm">Edit fingerprint</button></div></div></sc-if>'
    '<sc-if value="{{cur.gateSuggest}}" hint-placeholder-val="{{false}}"><div style="flex: none; padding: 0 18px 8px"><div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 10px; border: 1px dashed var(--warn-line); font-size: 12.5px; color: var(--tx2)">'
    '<span style="color: var(--warn); display: inline-flex">' + ic('gate', 16, 2) + '</span>This block lands on the <b style="color: var(--tx)">{{cur.gate}}</b> page but doesn\'t check it arrived.'
    '<span style="flex-grow: 1"></span><button class="btn btn-sm">' + ic('plus', 13, 2.2) + ' Add gate: {{cur.gate}} page</button></div></div></sc-if>'
    # ---- cards
    '<sc-if value="{{isCards}}" hint-placeholder-val="{{true}}">'
    '<div class="scroll" style="flex-grow: 1; overflow: auto; padding: 0 18px 90px">'
    '<div style="display: flex; gap: 14px; align-items: flex-start">'
    '<sc-for list="{{lanes}}" as="ln" hint-placeholder-count="1">'
    '<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; {{ln.boxStyle}}">'
    '<sc-if value="{{ln.hasLabel}}" hint-placeholder-val="{{false}}"><div style="display: flex; align-items: center; gap: 8px; padding: 2px 2px 6px; font-size: 13px; font-weight: 600; color: var(--k-flow)">{{ln.label}}<span style="flex-grow: 1"></span><span class="mono" style="font-size: 11px; color: var(--tx3)">{{ln.count}}</span></div></sc-if>'
    '<sc-for list="{{ln.items}}" as="it" hint-placeholder-count="10">'
    '<div class="scard" style="{{it.cardStyle}}">'
    '<span style="color: var(--tx4); display: inline-flex; cursor: grab" title="Drag to reorder">' + ic('grip', 14) + '</span>'
    '<button onClick="{{it.toggle}}" aria-label="Select step {{it.n}}" style="display: inline-flex"><span class="cbx {{it.cbxCls}}">' + ic('check', 11, 3) + '</span></button>'
    '<button onClick="{{it.pick}}" style="flex-grow: 1; min-width: 0; display: flex; align-items: center; gap: 9px; min-height: 30px">'
    '<span class="mono" style="width: 28px; flex: none; font-size: 11px; color: var(--tx3); text-align: right">{{it.n}}</span>'
    '<span class="badge k-{{it.kind}}" style="width: 52px">{{it.verb}}</span>'
    '<span class="trunc" style="font-weight: 600; line-height: 22px; {{it.textStyle}}"><sc-for list="{{it.parts}}" as="p" hint-placeholder-count="2"><sc-if value="{{p.v}}" hint-placeholder-val="{{false}}"><span class="{{p.cls}}" style="vertical-align: 1px; margin: 0 1px">{{p.t}}</span></sc-if><sc-if value="{{p.plain}}" hint-placeholder-val="{{true}}">{{p.t}}</sc-if></sc-for></span>'
    '<sc-if value="{{it.hasCtx}}" hint-placeholder-val="{{false}}"><span class="tag">' + ic('frame', 11) + ' {{it.ctx}}</span></sc-if>'
    '<span style="flex-grow: 1"></span>'
    '<sc-if value="{{it.isHint}}" hint-placeholder-val="{{false}}"><span class="tag" title="{{it.hint}}">fixed wait</span></sc-if>'
    '<sc-if value="{{it.isLegacy}}" hint-placeholder-val="{{false}}"><span class="tag">' + ic('lock', 11) + ' legacy</span></sc-if>'
    '<sc-if value="{{it.side}}" hint-placeholder-val="{{false}}"><span class="tag tag-warn">' + ic('bolt', 11) + ' side effects</span></sc-if>'
    '<sc-if value="{{it.failed}}" hint-placeholder-val="{{false}}"><span class="tag tag-fail">failed on last run</span></sc-if>'
    '<sc-if value="{{it.disabled}}" hint-placeholder-val="{{false}}"><span class="tag">off</span></sc-if>'
    '<sc-if value="{{it.hasProblem}}" hint-placeholder-val="{{false}}"><span class="pdot" style="background: var(--fail)" title="Problem"></span></sc-if>'
    '<span style="font-size: 11.5px; color: var(--tx3); white-space: nowrap">{{it.page}}</span>'
    '<span class="pdot" style="width: 7px; height: 7px; background: {{it.lastColor}}" title="{{it.lastTitle}}"></span>'
    '</button></div>'
    '</sc-for>'
    '<button class="btn btn-ghost" style="justify-content: center; border: 1px dashed var(--line2); height: 36px; margin-top: 4px">' + ic('plus', 14, 2.2) + ' Add step here</button>'
    '</div></sc-for></div>'
    '<sc-if value="{{cur.hasReturn}}" hint-placeholder-val="{{false}}"><div style="margin-top: 14px; display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 10px; border: 1px dashed var(--line2); font-size: 13px; color: var(--tx2)">' + ic('arrowl', 14, 2) + ' Then carries on at <strong style="color: var(--tx)">{{cur.returns}}</strong>. Every value it saves ({{cur.saves}}) is available there.</div></sc-if>'
    '</div></sc-if>'
    # ---- grid
    '<sc-if value="{{isGrid}}" hint-placeholder-val="{{false}}">'
    '<div class="scroll" style="flex-grow: 1; overflow: auto; margin: 0 18px 90px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface)">'
    '<div style="width: 1560px">'
    '<div class="mono" style="display: flex; position: sticky; top: 0; background: var(--surface2); border-bottom: 1px solid var(--line); font-size: 10.5px; font-weight: 600; color: var(--tx3)">'
    + ''.join('<span class="gcell" style="width: %dpx">%s</span>' % (w, h) for w, h in ((34, ''), (46, 'ROW'), (64, 'blnExec'), (250, 'Step_Name'), (120, 'Method'), (110, 'Page'), (80, 'FindBy'), (280, 'FindBy_Value'), (150, 'Value'), (130, 'Expected_Value'), (52, 'Exact'), (70, 'Contains'), (110, 'Output_Value'), (68, 'BLOCK'))) +
    '</div>'
    '<sc-for list="{{grid}}" as="g" hint-placeholder-count="12">'
    '<div class="mono" style="display: flex; border-bottom: 1px solid var(--line); {{g.rowStyle}}">'
    '<button class="gcell" style="width: 34px; justify-content: center" onClick="{{g.toggle}}" aria-label="Select row {{g.xrow}}"><span class="cbx {{g.cbxCls}}">' + ic('check', 11, 3) + '</span></button>'
    '<span class="gcell" style="width: 46px; color: var(--tx3)">{{g.xrow}}</span><span class="gcell" style="width: 64px; {{g.blnStyle}}">{{g.bln}}</span>'
    '<button class="gcell" style="width: 250px; font-family: \'Instrument Sans\', sans-serif; font-size: 12.5px" onClick="{{g.pick}}">{{g.name}}</button>'
    '<span class="gcell" style="width: 120px; color: var(--acc)">{{g.m}}</span><span class="gcell" style="width: 110px">{{g.page}}</span><span class="gcell" style="width: 80px">{{g.fb}}</span>'
    '<span class="gcell" style="width: 280px; color: var(--tx2)">{{g.loc}}</span><span class="gcell" style="width: 150px; color: var(--k-input)">{{g.val}}</span>'
    '<span class="gcell" style="width: 130px; color: var(--k-check)">{{g.exp}}</span><span class="gcell" style="width: 52px">{{g.exact}}</span><span class="gcell" style="width: 70px">{{g.contains}}</span>'
    '<span class="gcell" style="width: 110px; color: var(--k-save)">{{g.sv}}</span><span class="gcell" style="width: 68px; color: var(--tx3)">{{g.block}}</span></div>'
    '</sc-for></div></div></sc-if>'
    # bulk bar
    '<sc-if value="{{hasMulti}}" hint-placeholder-val="{{false}}">'
    '<div style="position: absolute; left: 50%; bottom: {{bulkBottom}}px; transform: translateX(-50%); display: flex; align-items: center; gap: 6px; padding: 7px 8px 7px 14px; border-radius: 13px; background: var(--surface3); border: 1px solid var(--line2); box-shadow: var(--pop); white-space: nowrap; z-index: 5">'
    '<b style="font-size: 13px">{{multiCount}} selected</b><span style="width: 1px; height: 20px; background: var(--line2); margin: 0 4px"></span>'
    '<button class="btn btn-sm btn-ghost">On / off</button><button class="btn btn-sm btn-ghost">Timeout</button><button class="btn btn-sm btn-ghost">If it fails</button>'
    '<button class="btn btn-sm btn-ghost">Page</button><button class="btn btn-sm btn-ghost">Move to block</button>'
    '<span style="width: 1px; height: 20px; background: var(--line2); margin: 0 4px"></span>'
    '<button class="btn btn-sm btn-ghost" title="Duplicate">' + ic('dup', 13) + ' <span class="kbd">{{mod}}D</span></button>'
    '<button class="btn btn-sm btn-ghost">' + ic('layers', 13) + ' Save as template</button>'
    '<button class="btn btn-sm btn-ghost" style="color: var(--fail)">' + ic('trash', 13) + ' <span class="kbd">Del</span></button>'
    '<button class="icon-btn" style="width: 28px; height: 28px" onClick="{{clearMulti}}" aria-label="Clear selection">' + ic('x', 13, 2.2) + '</button></div></sc-if>'
    # add-step menu
    '<sc-if value="{{menu}}" hint-placeholder-val="{{false}}">'
    '<div class="menu" style="position: absolute; right: 18px; top: 322px; width: 330px; padding: 6px; z-index: 6">'
    '<div class="field" style="margin-bottom: 6px">' + ic('search', 14) + '<span style="color: var(--tx3); font-size: 12.5px">Search 55 actions…</span></div>'
    '<button class="mitem on">' + ic('rec', 15, 2) + '<span style="flex-grow: 1">Record from here in the browser</span></button>'
    '<button class="mitem">' + ic('target', 15) + '<span style="flex-grow: 1">Pick an element on the page</span></button>'
    '<div class="hr" style="margin: 5px 0"></div><span class="lbl" style="padding: 4px 10px; display: block">All actions</span>'
    '<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px">'
    + ''.join('<button class="mitem"><span class="badge k-%s" style="width: 20px; padding: 0"></span>%s</button>' % (k, t) for k, t in
              (('act', 'Do'), ('input', 'Type'), ('check', 'Check'), ('save', 'Save'), ('wait', 'Wait'), ('nav', 'Window &amp; frames'), ('flow', 'Flow'), ('legacy', 'Advanced'))) +
    '</div><div class="hr" style="margin: 5px 0"></div>'
    '<button class="mitem">' + ic('layers', 15) + '<span style="flex-grow: 1">Insert a template…</span></button>'
    '<button class="mitem">' + ic('call', 15) + '<span style="flex-grow: 1">Call another test…</span></button>'
    '<button class="mitem">' + ic('branch', 15) + '<span style="flex-grow: 1">If a variable…</span></button>'
    '<button class="mitem">' + ic('repeat', 15) + '<span style="flex-grow: 1">Repeat for each data row…</span></button>'
    '<button class="mitem">' + ic('x', 15) + '<span style="flex-grow: 1">If this popup shows, close it</span></button>'
    '<button class="mitem" disabled="" style="opacity: .55; cursor: default">' + ic('sparkle', 15) + '<span style="flex-grow: 1">Describe a step…</span><span class="tag">later</span></button>'
    '</div></sc-if>'
    # data drawer
    '<div style="flex: none; border-top: 1px solid var(--line); background: var(--rail); position: absolute; left: 0; right: 0; bottom: 0; z-index: 4">'
    '<button onClick="{{toggleDrawer}}" style="width: 100%; height: 38px; display: flex; align-items: center; gap: 10px; padding: 0 18px; font-size: 12.5px">'
    + ic('table', 14) + '<b>Data</b><span style="color: var(--tx3)">{{drawerLabel}}</span><span style="flex-grow: 1"></span>'
    '<span style="color: var(--tx3)">Building with</span><span class="tag tag-acc">{{buildingWith}}</span><span style="color: var(--tx3); display: inline-flex">{{drawerChevron}}</span></button>'
    '<sc-if value="{{drawer}}" hint-placeholder-val="{{false}}">'
    '<div style="padding: 0 18px 14px; display: flex; flex-direction: column; gap: 10px">'
    '<div style="display: flex; align-items: center; gap: 8px"><div class="seg" style="width: 380px"><span class="{{p1on}}">Params_1 · trip · 8</span><span class="{{p2on}}">Params_2 · travelers · 2</span></div>'
    '<span style="font-size: 12px; color: var(--tx3)">Rows are scenarios, columns are variables. Pick the row the browser and replays use.</span><span style="flex-grow: 1"></span>'
    '<button class="btn btn-sm">' + ic('plus', 13, 2.2) + ' Column</button><button class="btn btn-sm">' + ic('bolt', 13) + ' Value builder</button></div>'
    '<div class="scroll" style="max-height: 200px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; background: var(--surface)">'
    '<table class="tbl"><thead><tr><sc-for list="{{dheads}}" as="h" hint-placeholder-count="6"><th><span style="display: block">{{h.label}}</span><span class="mono" style="font-size: 10px; letter-spacing: 0; text-transform: none; color: var(--tx4)">{{h.tok}}</span></th></sc-for></tr></thead>'
    '<tbody><sc-for list="{{drows}}" as="r" hint-placeholder-count="4"><tr style="{{r.style}}">'
    '<td><span class="sw {{r.onCls}}"></span></td><td><button onClick="{{r.use}}" class="tag {{r.useCls}}">{{r.useLabel}}</button></td>'
    '<sc-for list="{{r.cells}}" as="c" hint-placeholder-count="6"><td class="{{c.cls}}" style="{{c.style}}">{{c.t}}</td></sc-for></tr></sc-for></tbody></table></div></div></sc-if></div>'
    '</main>'
    # ---------------------------------------------------------------- inspector / problems
    '<aside style="width: 372px; flex: none; border-left: 1px solid var(--line); background: var(--rail); display: flex; flex-direction: column; min-height: 0">'
    '<sc-if value="{{showProblems}}" hint-placeholder-val="{{false}}">'
    '<div style="padding: 16px 18px 12px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 8px"><span class="ttl">Problems</span><span class="tag">7</span><span style="flex-grow: 1"></span>'
    '<button class="icon-btn" onClick="{{toggleProblems}}" aria-label="Close problems">' + ic('x', 14, 2) + '</button></div>'
    '<div style="padding: 10px 18px 0; font-size: 12px; color: var(--tx3)">Checked live as you edit. Saving is never blocked.</div>'
    '<div class="scroll" style="flex-grow: 1; overflow: auto; padding: 12px 12px 16px; display: flex; flex-direction: column; gap: 6px">'
    '<sc-for list="{{problems}}" as="pb" hint-placeholder-count="5">'
    '<div style="display: flex; gap: 10px; padding: 11px 12px; border-radius: 11px; background: var(--surface); border: 1px solid var(--line)">'
    '<span class="pdot" style="margin-top: 5px; background: {{pb.color}}"></span><div style="display: flex; flex-direction: column; gap: 6px; min-width: 0">'
    '<span style="font-size: 12.5px"><b>{{pb.where}}</b> <span style="color: var(--tx2)">{{pb.text}}</span></span>'
    '<span><button class="btn btn-sm">{{pb.action}}</button></span></div></div></sc-for>'
    '<div class="bn" style="margin-top: 6px">' + ic('info', 15, 1.8, 'color: var(--tx3)') + '<span>Step 204 failed on the last run (25 Sep). This badge goes away by itself once a later run passes it.</span></div>'
    '</div></sc-if>'
    '<sc-if value="{{showInspector}}" hint-placeholder-val="{{true}}">'
    # fix-mode panel
    '<sc-if value="{{fix}}" hint-placeholder-val="{{false}}">'
    '<div style="padding: 12px 18px; border-bottom: 1px solid var(--fail-line); background: var(--fail-soft); display: flex; flex-direction: column; gap: 10px">'
    '<div style="display: flex; align-items: center; gap: 8px"><span class="pill p-fail">' + ic('x', 11, 3) + ' Failed</span><span style="font-size: 12px; color: var(--tx2)">Run 0925-1412 · UAT · Row 1 · opened from Results</span></div>'
    '<div class="shot" style="height: 118px"><div style="position: absolute; left: 14px; top: 14px; right: 14px; display: flex; flex-direction: column; gap: 7px">'
    '<span style="height: 8px; width: 40%; border-radius: 4px; background: var(--line2)"></span><span style="height: 26px; width: 70%; border-radius: 6px; border: 1px solid var(--line2); background: var(--surface)"></span>'
    '<span style="height: 26px; width: 70%; border-radius: 6px; border: 2px dashed var(--fail); background: var(--fail-soft)"></span></div>'
    '<span class="mono" style="position: absolute; left: 8px; bottom: 6px; font-size: 10px; padding: 1px 6px; border-radius: 5px; background: var(--scrim); color: #fff">failure screenshot · 14:12:09</span></div>'
    '<div class="mono" style="font-size: 11.5px; color: var(--fail); line-height: 1.5">Not found: label "Card number" inside frame "card" (waited 30 s)</div>'
    '<div style="display: flex; flex-direction: column; border-radius: 11px; background: var(--surface); border: 1px solid var(--line2); overflow: hidden">'
    '<div style="padding: 11px 12px; display: flex; flex-direction: column; gap: 7px">'
    '<span style="font-size: 12.5px"><b>A backup found 1 likely match</b> <span style="color: var(--tx2)">The field\'s label now reads "Card no."</span></span>'
    '<div class="mono" style="display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 3px 8px; font-size: 11.5px">'
    '<span style="color: var(--tx3)">old</span><span style="color: var(--fail); text-decoration: line-through; overflow-wrap: anywhere">label "Card number"</span>'
    '<span style="color: var(--tx3)">new</span><span style="color: var(--pass); overflow-wrap: anywhere">data-testid = card-number</span></div></div>'
    '<div style="padding: 10px 12px 12px; border-top: 1px solid var(--line); background: var(--surface2); display: flex; flex-direction: column; gap: 8px">'
    '<span class="lbl">Fix it</span>'
    '<button class="btn btn-pri" style="width: 100%; height: 36px">' + ic('check', 15, 2.4) + ' Accept new locator</button>'
    '<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px">'
    '<button class="btn" style="width: 100%; height: 36px; min-width: 0; padding: 0 8px">' + ic('target', 14) + ' Re-pick element</button>'
    '<button class="btn" style="width: 100%; height: 36px; min-width: 0; padding: 0 8px">' + ic('play', 12, 2) + ' Replay up to here</button></div></div></div></div></sc-if>'
    '<div style="padding: 14px 18px 12px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 7px">'
    '<div style="display: flex; align-items: center; gap: 8px"><span class="mono" style="font-size: 12px; color: var(--tx3)">Step {{sel.n}}</span><span class="badge k-{{sel.kind}}">{{sel.verb}}</span>'
    '<sc-if value="{{sel.side}}" hint-placeholder-val="{{false}}"><span class="tag tag-warn">' + ic('bolt', 11) + ' side effects</span></sc-if>'
    '<span style="flex-grow: 1"></span><span class="mono" style="font-size: 11px; color: var(--tx3)">Excel row {{sel.xrow}}</span></div>'
    '<div class="disp" style="font-size: 18px; font-weight: 700; line-height: 1.3"><sc-for list="{{sel.parts}}" as="p" hint-placeholder-count="2"><sc-if value="{{p.v}}" hint-placeholder-val="{{false}}"><span class="{{p.cls}}" style="font-family: \'Instrument Sans\', sans-serif; font-size: 13px; vertical-align: 2px; margin: 0 2px">{{p.t}}</span></sc-if><sc-if value="{{p.plain}}" hint-placeholder-val="{{true}}">{{p.t}}</sc-if></sc-for></div>'
    '<div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--tx3)"><span>Auto name</span><span>·</span><a href="#">Write my own</a><span style="flex-grow: 1"></span><span>{{sel.page}}</span></div></div>'
    '<div class="scroll" style="flex-grow: 1; overflow: auto; padding: 14px 18px 18px; display: flex; flex-direction: column; gap: 18px">'
    # legacy
    '<sc-if value="{{sel.isLegacy}}" hint-placeholder-val="{{false}}"><div class="bn">' + ic('lock', 15, 1.8, 'color: var(--tx3)') + '<span><b>Legacy row, kept exactly as it is.</b> {{sel.legacy}} You can move or delete it; edit it in the Excel grid.</span></div></sc-if>'
    # wait
    '<sc-if value="{{sel.isWait}}" hint-placeholder-val="{{false}}"><div class="bn">' + ic('clock', 15, 1.8, 'color: var(--tx3)') + '<span><b>Fixed wait from the old sheet.</b> {{sel.hint}} Safe to remove; the recorder never adds these.</span></div>'
    '<div style="display: flex; gap: 8px"><button class="btn btn-sm">Replace with “Wait until…”</button><button class="btn btn-sm btn-ghost">Remove</button></div></sc-if>'
    # call
    '<sc-if value="{{sel.isCall}}" hint-placeholder-val="{{false}}"><div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Runs this test, then carries on</span>'
    '<div class="field" style="min-height: 44px">' + ic('api', 16, 1.8, 'color: var(--k-api)') + '<b>{{sel.call}}</b><span style="flex-grow: 1"></span><a href="#">Open</a></div>'
    '<span style="font-size: 12px; color: var(--tx3)">It reads Plan, Traveler count and Quote request from this test, and gives back Quoted premium and Quote id.</span></div></sc-if>'
    # web element
    '<sc-if value="{{sel.isWeb}}" hint-placeholder-val="{{true}}"><div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">On which element</span>'
    '<div style="border: 1px solid var(--line2); border-radius: 10px; overflow: hidden; background: var(--surface)">'
    '<div class="shot" style="height: 84px; border: 0; border-radius: 0; border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: center">'
    '<span style="padding: 7px 14px; border-radius: 6px; border: 2px solid var(--acc); background: var(--acc-soft); font-size: 13px; box-shadow: 0 0 0 4px var(--acc-soft)">{{sel.name}}</span>'
    '<span class="mono" style="position: absolute; left: 8px; bottom: 5px; font-size: 10px; color: var(--tx3)">snapshot from the last run · 25 Sep</span></div>'
    '<div style="padding: 10px; display: flex; flex-direction: column; gap: 8px">'
    '<span style="font-size: 12px; color: var(--tx3)">In plain words (click a word to make it a variable)</span>'
    '<div style="display: flex; flex-wrap: wrap; gap: 5px"><sc-for list="{{sel.desc}}" as="w" hint-placeholder-count="3"><button class="{{w.cls}}">{{w.t}}</button></sc-for></div>'
    '<div style="display: flex; gap: 6px"><button class="btn btn-sm btn-pri" style="flex-grow: 1">' + ic('target', 13) + ' Pick on page</button><button class="btn btn-sm" style="flex-grow: 1">Highlight</button></div></div></div>'
    '<span style="font-size: 12px; color: var(--tx2); margin-top: 2px">Found by</span>'
    '<div class="field mono" style="font-size: 11.5px; color: var(--tx2); align-items: flex-start"><span class="tag">{{sel.fb}}</span><span style="word-break: break-all">{{sel.loc}}</span></div>'
    '<div style="display: flex; align-items: center; gap: 8px; font-size: 12px"><span style="color: var(--pass); display: inline-flex; align-items: center; gap: 5px">' + ic('check', 13, 2.4) + ' 1 match on the last run</span><span style="color: var(--tx3)">· {{sel.backups}} backups stored</span></div>'
    '<span style="font-size: 12px; color: var(--tx3)">Generated for you, never typed. The original XPath stays in the Excel grid.</span></div></sc-if>'
    # value
    '<sc-if value="{{sel.hasVal}}" hint-placeholder-val="{{true}}"><div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Value</span>'
    '<div class="field" style="flex-wrap: wrap"><sc-for list="{{sel.valParts}}" as="p" hint-placeholder-count="1"><sc-if value="{{p.v}}" hint-placeholder-val="{{true}}"><span class="{{p.cls}}">{{p.t}}</span></sc-if><sc-if value="{{p.plain}}" hint-placeholder-val="{{false}}"><span class="mono" style="font-size: 12px">{{p.t}}</span></sc-if></sc-for>'
    '<span style="flex-grow: 1"></span><button class="btn btn-ghost btn-sm" style="padding: 0 6px">' + ic('braces', 13) + ' Variable</button><button class="btn btn-ghost btn-sm" style="padding: 0 6px">' + ic('bolt', 13) + ' Builder</button></div>'
    '<span style="font-size: 12px; color: var(--tx3)">{{sel.valNote}}</span></div></sc-if>'
    # check
    '<sc-if value="{{sel.isCheck}}" hint-placeholder-val="{{false}}"><div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Check that</span>'
    '<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px">'
    '<sc-for list="{{sel.checks}}" as="c" hint-placeholder-count="9"><button class="btn btn-sm {{c.cls}}" style="justify-content: flex-start; padding: 0 8px; font-weight: 500">{{c.t}}</button></sc-for></div>'
    '<span style="font-size: 12px; color: var(--tx2); margin-top: 4px">Expected</span>'
    '<div class="field" style="flex-wrap: wrap"><sc-for list="{{sel.expParts}}" as="p" hint-placeholder-count="1"><sc-if value="{{p.v}}" hint-placeholder-val="{{true}}"><span class="{{p.cls}}">{{p.t}}</span></sc-if><sc-if value="{{p.plain}}" hint-placeholder-val="{{false}}"><span class="mono" style="font-size: 12px">{{p.t}}</span></sc-if></sc-for>'
    '<span style="flex-grow: 1"></span><button class="btn btn-ghost btn-sm" style="padding: 0 6px">' + ic('braces', 13) + ' Variable</button></div>'
    '<span style="font-size: 12px; color: var(--tx3)">{{sel.expNote}}</span></div></sc-if>'
    # save + fails + switches
    '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">Save the result as</span>'
    '<div class="field">' + ic('braces', 14, 1.8, 'color: var(--tx3)') + '<span style="font-size: 12.5px; color: {{sel.saveColor}}">{{sel.saveText}}</span></div></div>'
    '<div style="display: flex; flex-direction: column; gap: 8px"><span class="lbl">If this step fails</span>'
    '<div class="seg"><span class="on">Stop the test</span><span>Note it, keep going</span></div></div>'
    '<div style="display: flex; flex-direction: column; gap: 12px; padding-top: 14px; border-top: 1px solid var(--line)">'
    '<div style="display: flex; justify-content: space-between; align-items: center"><span style="font-size: 13px; color: var(--tx2)">Give up after</span><span class="mono" style="font-size: 12px">30 s</span></div>'
    '<div style="display: flex; justify-content: space-between; align-items: center"><span style="font-size: 13px; color: var(--tx2)">Run this step</span><span class="sw {{sel.onCls}}"></span></div>'
    '<div style="display: flex; justify-content: space-between; align-items: center; gap: 12px"><span style="font-size: 13px; color: var(--tx2)">Has side effects<span style="display: block; font-size: 11.5px; color: var(--tx3)">Replays ask first · always blocked on PROD</span></span><span class="sw {{sel.sideCls}}"></span></div></div>'
    '</div>'
    '<div style="padding: 10px 18px; border-top: 1px solid var(--line); display: flex; gap: 6px">'
    '<button class="btn btn-sm" style="flex-grow: 1">' + ic('play', 12, 2) + ' Run up to here <span class="kbd">R</span></button>'
    '<button class="btn btn-sm" style="flex-grow: 1">Run this step</button><button class="btn btn-sm">Next 5</button></div>'
    '</sc-if></aside>'
    '</div></div>')


SCRIPT = r"""
var C = %(cards)s;
var B = %(blocks)s;
var NODES = %(nodes)s;
var P1 = %(p1)s;
var P2 = %(p2)s;
var PROBS = %(probs)s;
var KIND = { page: ['PAGE', 'nav'], if: ['IF', 'flow'], loop: ['REPEAT', 'flow'], call: ['CALL', 'api'], callxml: ['CALL', 'xml'], window: ['TAB', 'save'] };
var CHECKS = ['Text is', 'Text contains', 'Shows', 'Is gone', 'Field value', 'Ticked', 'Selected', 'Enabled', 'Number > < =', 'Between', 'Matches pattern', 'Date format', 'Item count'];
var RULES = { 'Home': 'URL contains /travel-insurance and “Get a quote” form shows', 'Trip details': 'URL contains /quote/trip and heading “Trip details” shows',
  'Travelers': 'URL contains /quote/travelers and heading “Who is traveling?” shows', 'Plans': 'URL contains /quote/plans and heading “Choose your plan” shows',
  'Traveler info': 'URL contains /purchase/travelers and heading “Traveler information” shows', 'Payment': 'URL contains /purchase/payment and heading “Payment details” shows',
  'Review': 'URL contains /purchase/review and heading “Review your order” shows', 'Confirmation': 'URL contains /purchase/confirmation and “You’re covered” shows',
  'Policy details': 'New tab · URL contains /policy/ and heading “Policy details” shows' };
function blockOf(n) { for (var i = 0; i < B.length; i++) if (n > B[i].start && n <= B[i].end) return B[i]; return B[0]; }
function plainify(ps) { return ps.map(function (p) { return Object.assign({}, p, { plain: !p.v }); }); }
function tokParts(s) {
  if (!s) return [];
  var out = [], re = /\{([A-Za-z_0-9:]+)\}/g, last = 0, m;
  while ((m = re.exec(s))) { if (m.index > last) out.push({ t: s.slice(last, m.index), v: false, plain: true, cls: '' });
    var tk = m[1]; var sec = tk === 'TEST_CARD' || tk === 'CARD_CVV';
    out.push({ t: (sec ? '•••• ' : '') + tk, v: true, plain: false, cls: 'var' + (sec ? ' secret' : '') + (tk === 'BASE_URL' ? ' env' : '') }); last = re.lastIndex; }
  if (last < s.length) out.push({ t: s.slice(last), v: false, plain: true, cls: '' });
  return out;
}
class Component extends DCLogic {
  constructor(p) {
    super(p);
    this.state = { blk: p.startBlock != null ? p.startBlock : 9, sel: p.startStep != null ? p.startStep : 189, multi: (p.startMulti || '').split(',').filter(Boolean).map(Number),
      view: p.view || 'cards', drawer: !!p.drawer, problems: !!p.problems, menu: !!p.menu, row: 1 };
  }
  renderVals() {
    var s = this.state, self = this, props = this.props, b = B[s.blk];
    var mod = (props.platform || 'mac') === 'mac' ? '⌘' : 'Ctrl+';
    var go = function (i) { var bb = B[i]; self.setState({ blk: i, sel: (bb.lanes.length ? bb.lanes[0].start : bb.start) + 1, menu: false }); };
    var inMulti = function (n) { return s.multi.indexOf(n) >= 0; };
    var toggle = function (n) { return function () { var m = s.multi.slice(); var k = m.indexOf(n); if (k >= 0) m.splice(k, 1); else m.push(n); self.setState({ multi: m }); }; };
    var pick = function (n) { return function () { self.setState({ sel: n, menu: false }); }; };
    var map = NODES.map(function (m) {
      var bb = B[m.i], k = KIND[bb.kind];
      return { x: m.x, y: m.y, title: bb.title, count: (bb.end - bb.start) + (bb.times ? ' ×' + bb.times : ''), kindLabel: k[0], kindCls: 'k-' + k[1],
        hasGate: bb.gateState === 'set', hasDot: !!bb.dot, dotColor: bb.dot === 'fail' ? 'var(--fail)' : 'var(--warn)',
        style: m.i === s.blk ? 'border-color: var(--acc); background: var(--sel-bg); box-shadow: 0 0 0 3px var(--acc-soft)' : '', pick: function () { go(m.i); } };
    });
    var LC = { pass: 'var(--pass)', fail: 'var(--fail)', pend: 'var(--pend)', off: 'transparent' };
    var LT = { pass: 'Passed on the last run', fail: 'Failed on the last run', pend: 'Not reached on the last run', off: 'Turned off' };
    var mk = function (a, z) {
      var out = [];
      for (var n = a + 1; n <= z; n++) {
        var r = C[n - 1], selc = n === s.sel, mm = inMulti(n);
        out.push(Object.assign({}, r, { parts: plainify(r.parts), hasCtx: !!r.ctx, isHint: !!r.hint, isLegacy: !!r.legacy, hasProblem: r.problem === 'red',
          cbxCls: mm ? 'on' : '', lastColor: LC[r.last], lastTitle: LT[r.last], textStyle: r.disabled ? 'color: var(--tx3); text-decoration: line-through; text-decoration-color: var(--line2)' : '',
          cardStyle: (selc ? 'border-color: var(--acc); background: var(--sel-bg); box-shadow: 0 0 0 1px var(--acc-line);' : (mm ? 'border-color: var(--acc-line); background: var(--sel-bg);' : '')) + (r.disabled ? 'opacity: .6;' : '') + (r.legacy ? 'border-style: dashed;' : ''),
          pick: pick(n), toggle: toggle(n) }));
      }
      return out;
    };
    var box = 'padding: 12px; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--k-flow) 30%, transparent); background: color-mix(in srgb, var(--k-flow) 4%, transparent)';
    var lanes;
    if (b.kind === 'if') lanes = b.lanes.map(function (ln, j) { return { hasLabel: true, label: j ? 'Otherwise (no promo code)' : 'If Promo code is filled in', count: (ln.end - ln.start) + ' steps', items: mk(ln.start, ln.end), boxStyle: box }; });
    else if (b.kind === 'loop') lanes = [{ hasLabel: true, label: 'Repeats for each row of Params_2 · Jane Doe, Omar Haddad', count: '×' + b.times, items: mk(b.start, b.end), boxStyle: box }];
    else lanes = [{ hasLabel: false, items: mk(b.start, b.end), boxStyle: '' }];
    var grid = [];
    for (var n = b.start + 1; n <= b.end; n++) {
      var r = C[n - 1], mm = inMulti(n);
      grid.push({ xrow: r.xrow, bln: r.disabled ? 'N' : (r.legacy && r.n === 286 ? '=IF($D$13…' : 'Y'), blnStyle: r.disabled ? 'color: var(--fail)' : '', name: r.sentence.replace(/\{([A-Z_0-9]+)\}/g, '{$1}'),
        m: r.m, page: r.page, fb: r.rawloc ? 'XPATH' : '', loc: r.rawloc, val: r.val, exp: r.exp, exact: r.opt === 'exact' ? 'Y' : '', contains: r.opt === 'contains' ? 'Y' : '', sv: r.sv,
        block: 'B' + (s.blk + 1), cbxCls: mm ? 'on' : '', rowStyle: (n === s.sel ? 'background: var(--sel-bg);' : (mm ? 'background: var(--acc-soft);' : '')) + (r.disabled ? 'opacity: .55' : ''),
        toggle: toggle(n), pick: pick(n) });
    }
    var k = KIND[b.kind];
    var saves = []; for (var q = b.start + 1; q <= b.end; q++) if (C[q - 1].sv) saves.push(C[q - 1].sv);
    if (b.kind === 'call') saves = ['API_PREMIUM', 'QUOTE_ID'];
    if (b.kind === 'callxml') saves = ['POLICY_STATUS'];
    var r = C[s.sel - 1];
    var isCheck = r.kind === 'check';
    var vtok = (r.val.match(/\{([A-Z_0-9]+)\}/) || [])[1];
    var inLoop = B[r.blk] && B[r.blk].kind === 'loop';
    var row1 = { DESTINATION: 'Italy', STATE: 'NE', PLAN: 'Basic', TRIP_COST: '2500', FIRST_NAME: 'Jane', LAST_NAME: 'Doe', EMAIL: 'jane.doe@example.com', GENDER: 'Female', ZIP: '68102', PROMO_CODE: '(empty in row 1)' };
    var desc = (r.desc || []).map(function (w) { return { t: w.t, cls: w.var ? 'var' : (w.q ? 'btn btn-sm' : 'tag') }; });
    var chk = r.m === 'EXIST' ? 'Shows' : r.m === 'NOT_EXIST' ? 'Is gone' : r.m === 'VALUE' ? 'Field value' : (r.opt === 'contains' ? 'Text contains' : 'Text is');
    var sel = Object.assign({}, r, { parts: plainify(r.parts), isLegacy: !!r.legacy, isWait: r.m === 'WAIT', isCall: r.m === 'CALL_TEST',
      isWeb: !!r.rawloc && !r.legacy, hasVal: !!r.val && r.m !== 'WAIT' && !r.legacy, valParts: tokParts(r.val),
      valNote: vtok ? (vtok === 'BASE_URL' ? 'Base URL comes from the environment table: UAT = https://uat.travelex-insurance.test' : (vtok === 'TEST_CARD' || vtok === 'CARD_CVV') ? 'Secret. Stored in secrets.env per environment, never in the workbook.' : (inLoop ? vtok + ' comes from Params_2, one value per traveler row. Row 1: ' + (row1[vtok] || '…') : vtok + ' comes from Params_1, column ' + vtok + '. Row 1: ' + (row1[vtok] || '…'))) : 'Fixed text: the same every run.',
      isCheck: isCheck, checks: CHECKS.map(function (c) { return { t: c, cls: c === chk ? 'btn-pri' : '' }; }), expParts: tokParts(r.exp || (r.m === 'EXIST' ? '' : '')),
      expNote: r.m === 'EXIST' || r.m === 'NOT_EXIST' ? 'No expected value needed.' : 'Prefilled from the live page when you picked it. Swap in a variable any time.',
      saveText: r.sv ? r.sv : 'Not saved', saveColor: r.sv ? 'var(--k-save)' : 'var(--tx3)', desc: desc, onCls: r.disabled ? '' : 'on', sideCls: r.side ? 'on' : '' });
    var dh, dr;
    var useP2 = b.kind === 'loop' || b.i === 10;
    if (useP2) {
      dh = [['On', ''], ['', ''], ['Traveler first name', 'FIRST_NAME'], ['Traveler last name', 'LAST_NAME'], ['Date of birth', 'DOB'], ['Traveler email', 'EMAIL'], ['Gender', 'GENDER'], ['Emergency contact', 'EMERG_NAME']];
      dr = P2;
    } else {
      dh = [['On', ''], ['', ''], ['Scenario', ''], ['Destination', 'DESTINATION'], ['State', 'STATE'], ['Plan', 'PLAN'], ['Promo code', 'PROMO_CODE'], ['Trip cost', 'TRIP_COST'], ['Traveler count', 'TRAVELER_COUNT']];
      dr = P1;
    }
    var drows = dr.map(function (row) {
      var use = row[1] === s.row;
      return { onCls: row[0] ? 'on' : '', style: (use ? 'background: var(--acc-soft);' : '') + (row[0] ? '' : 'opacity: .55'), useCls: use ? 'tag-acc' : '', useLabel: use ? '● Row ' + row[1] : 'Row ' + row[1],
        use: function () { self.setState({ row: row[1] }); },
        cells: row.slice(2).map(function (c, j) { return { t: c === '' ? '—' : c, cls: j === 0 && !useP2 ? '' : 'mono', style: c === '' ? 'color: var(--tx4)' : '' }; }) };
    });
    var bw = useP2 ? ('Row ' + s.row + ' · ' + (s.row === 1 ? 'Jane Doe' : 'Omar Haddad')) : ('Row ' + s.row + ' · ' + (P1[s.row - 1] ? P1[s.row - 1][2] : ''));
    return {
      theme: props.theme || 'dark', mod: mod, map: map, lanes: lanes, grid: grid, sel: sel,
      isCards: s.view === 'cards', isGrid: s.view === 'grid', segCards: s.view === 'cards' ? 'on' : '', segGrid: s.view === 'grid' ? 'on' : '',
      showCards: function () { self.setState({ view: 'cards' }); }, showGrid: function () { self.setState({ view: 'grid' }); },
      hasMulti: s.multi.length >= 2, multiCount: s.multi.length, clearMulti: function () { self.setState({ multi: [] }); }, bulkBottom: s.drawer ? 300 : 56,
      drawer: s.drawer, toggleDrawer: function () { self.setState({ drawer: !s.drawer }); }, drawerChevron: s.drawer ? '▾' : '▴',
      drawerLabel: useP2 ? 'Params_2 · travelers · 2 rows' : 'Params_1 · trip · 8 rows', p1on: useP2 ? '' : 'on', p2on: useP2 ? 'on' : '',
      dheads: dh.map(function (h) { return { label: h[0], tok: h[1] }; }), drows: drows, buildingWith: bw,
      showProblems: s.problems, showInspector: !s.problems, toggleProblems: function () { self.setState({ problems: !s.problems }); },
      probBtnCls: s.problems ? 'chip-fail' : 'btn-dng',
      problems: PROBS.map(function (p) { return { color: p[0] === 'fail' ? 'var(--fail)' : 'var(--warn)', where: p[1], text: p[2], action: p[3] }; }),
      menu: s.menu, toggleMenu: function () { self.setState({ menu: !s.menu }); },
      fix: !!props.fix, session: props.session !== false, sessionAt: props.sessionAt || 188, staleWarn: !!props.staleWarn,
      cur: { title: b.title, kindLabel: k[0], kindCls: 'k-' + k[1], pos: s.blk + 1, range: (b.start + 1) + '–' + b.end,
        sub: b.kind === 'if' ? 'two paths on a variable, then they meet again' : b.kind === 'loop' ? 'repeats ×' + b.times + ', once per data row' : b.kind === 'page' ? 'on the ' + b.page + ' page' : b.kind === 'window' ? 'a new tab, then back' : 'a detour to another test',
        gateSet: b.gateState === 'set', gateSuggest: b.gateState === 'suggest', gate: b.gate, gateRule: RULES[b.gate] || '',
        hasReturn: !!b.returns, returns: b.returns + (b.kind === 'window' ? ' (main window)' : ''), saves: saves.join(', ') || 'none' },
      prev: function () { go(Math.max(0, s.blk - 1)); }, next: function () { go(Math.min(B.length - 1, s.blk + 1)); }
    };
  }
}
"""


def script():
    nodes = NODES
    subs = {
        'cards': json.dumps(CARDS, ensure_ascii=False, separators=(',', ':')),
        'blocks': json.dumps(BLOCKS_JS, ensure_ascii=False, separators=(',', ':')),
        'nodes': json.dumps(nodes), 'p1': json.dumps(PARAMS1), 'p2': json.dumps(PARAMS2),
        'probs': json.dumps(PROBLEMS, ensure_ascii=False),
    }
    out = SCRIPT
    for k, v in subs.items():
        out = out.replace('%(' + k + ')s', v)
    return out


PROPS_BASE = {
    'theme': {'editor': 'enum', 'options': ['dark', 'light'], 'default': 'dark'},
    'platform': {'editor': 'enum', 'options': ['mac', 'windows'], 'default': 'mac', 'section': 'Shortcuts'},
}


def board(name, title, **defaults):
    props = json.loads(json.dumps(PROPS_BASE))
    for k, v in defaults.items():
        if k in props:
            props[k]['default'] = v
        else:
            props[k] = {'editor': None, 'default': v}
    # constructor reads this.props; pass defaults via renderVals fallback: the DC runtime applies defaults
    js = script()
    # bake defaults in case the runtime does not seed props from data-props defaults
    js = js.replace('super(p);', 'super(p); p = Object.assign(%s, p || {});' % json.dumps(defaults), 1)
    js = js.replace("theme: props.theme || 'dark'", "theme: props.theme || %s" % json.dumps(defaults.get('theme', 'dark')))
    js = js.replace("var s = this.state, self = this, props = this.props", "var s = this.state, self = this, props = Object.assign(%s, this.props || {})" % json.dumps(defaults))
    write(name, page(title, TEMPLATE, W, H, js, props))


if __name__ == '__main__':
    board('Editor.dc.html', 'Test editor', theme='dark', startBlock=9, startStep=BY_OLD[196], session=True, sessionAt=BY_OLD[195])
    board('EditorLight.dc.html', 'Test editor · light', theme='light', startBlock=12, startStep=BY_OLD[267], session=False)
    board('EditorIf.dc.html', 'IF block, check step, problems', theme='dark', startBlock=5, startStep=BY_OLD[87], problems=True, session=False, menu=False)
    board('EditorFix.dc.html', 'Fix in builder', theme='dark', startBlock=11, startStep=BY_OLD[235], fix=True, session=True, sessionAt=BY_OLD[234], staleWarn=True)
    board('EditorGrid.dc.html', 'Excel grid, bulk edit, data drawer', theme='dark', startBlock=1, startStep=BY_OLD[14], view='grid', drawer=True,
          startMulti=','.join(str(BY_OLD[n]) for n in (22, 23, 24, 25)), session=False)
    board('EditorMenu.dc.html', 'Add step menu', theme='dark', startBlock=3, startStep=BY_OLD[53], menu=True, session=False)
