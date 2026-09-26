"""Shared pieces for every round-2 Workbook Builder board: tokens (dark + light), components, icons, chrome."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')

P = json.load(open(os.path.join(HERE, 'app_icons.json')))
P.update({
    'grip': '<circle cx="9" cy="6" r="1.2"></circle><circle cx="15" cy="6" r="1.2"></circle><circle cx="9" cy="12" r="1.2"></circle><circle cx="15" cy="12" r="1.2"></circle><circle cx="9" cy="18" r="1.2"></circle><circle cx="15" cy="18" r="1.2"></circle>',
    'redo': '<path d="M23 4v6h-6"></path><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>',
    'braces': '<path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1M16 3h1a2 2 0 0 1 2 2v5a2 2 0 0 0 2 2 2 2 0 0 0-2 2v5a2 2 0 0 1-2 2h-1"></path>',
    'web': '<rect x="2" y="4" width="20" height="16" rx="2"></rect><path d="M2 9h20M6 6.5h.01M9 6.5h.01"></path>',
    'api': '<path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9a4.5 4.5 0 0 0 1 9z"></path>',
    'xml': '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"></path>',
    'layers': '<path d="M12 2l10 5-10 5L2 7z"></path><path d="M2 17l10 5 10-5M2 12l10 5 10-5"></path>',
    'table': '<rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="M3 10h18M9 4v16"></path>',
    'settings': '<circle cx="12" cy="12" r="3"></circle><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"></path>',
    'pencil': '<path d="M4 20h4L19 9l-4-4L4 16z"></path>',
    'flag': '<path d="M4 22V4a1 1 0 0 1 1-1h11l-2 4 2 4H5"></path>',
    'gate': '<path d="M4 21V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v16"></path><path d="M2 21h20M9 12l2 2 4-4"></path>',
    'call': '<path d="M5 12h11M12 7l5 5-5 5"></path><path d="M20 4v16"></path>',
    'window': '<rect x="3" y="3" width="18" height="18" rx="2"></rect><path d="M3 8h18M14 13h4v4"></path><path d="M18 13l-6 6"></path>',
    'frame': '<rect x="3" y="3" width="18" height="18" rx="2"></rect><rect x="7" y="7" width="10" height="10" rx="1" stroke-dasharray="2 2"></rect>',
    'repeat': '<path d="M17 1l4 4-4 4"></path><path d="M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4"></path><path d="M21 13v2a4 4 0 0 1-4 4H3"></path>',
    'branch': '<circle cx="6" cy="5" r="2"></circle><circle cx="6" cy="19" r="2"></circle><circle cx="18" cy="8" r="2"></circle><path d="M6 7v10M18 10c0 5-7 4-11 7"></path>',
    'rec': '<circle cx="12" cy="12" r="8"></circle><circle cx="12" cy="12" r="3.5" fill="currentColor"></circle>',
    'pointer': '<path d="M5 3l14 8-6 2-3 6z"></path>',
    'sparkle': '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"></path>',
    'history': '<path d="M3 3v5h5"></path><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"></path><path d="M12 7v5l4 2"></path>',
    'dot3': '<circle cx="5" cy="12" r="1.3"></circle><circle cx="12" cy="12" r="1.3"></circle><circle cx="19" cy="12" r="1.3"></circle>',
    'mail': '<rect x="2" y="4" width="20" height="16" rx="2"></rect><path d="M22 6l-10 7L2 6"></path>',
    'db': '<ellipse cx="12" cy="5" rx="8" ry="3"></ellipse><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"></path>',
    'queue': '<path d="M4 6h16M4 12h16M4 18h10"></path><path d="M18 16l3 2-3 2"></path>',
    'split': '<path d="M16 3h5v5M8 3H3v5M21 3l-7 7M3 3l7 7M12 22v-8"></path>',
    'merge': '<path d="M8 18l4-4 4 4M12 14V3"></path><path d="M4 21h16"></path>',
    'arrowr': '<path d="M5 12h14M13 6l6 6-6 6"></path>',
    'arrowl': '<path d="M19 12H5M11 6l-6 6 6 6"></path>',
    'chevr': '<path d="M9 6l6 6-6 6"></path>',
    'chevl': '<path d="M15 6l-6 6 6 6"></path>',
    'side': '<path d="M12 2l3 7h7l-5.5 4.5L18.5 21 12 16.5 5.5 21l2-7.5L2 9h7z"></path>',
    'bolt': '<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path>',
    'drag': '<path d="M5 9l-3 3 3 3M9 5l3-3 3 3M15 19l-3 3-3-3M19 9l3 3-3 3M2 12h20M12 2v20"></path>',
    'dup': '<rect x="8" y="8" width="13" height="13" rx="2"></rect><path d="M4 16V5a1 1 0 0 1 1-1h11"></path>',
    'eyeonly': '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>',
    'sync': '<path d="M4 12h16"></path><path d="M4 7v10M20 7v10"></path>',
    'excel': '<rect x="3" y="3" width="18" height="18" rx="2"></rect><path d="M8 8l8 8M16 8l-8 8"></path>',
})


def ic(name, size=16, sw=1.8, style=''):
    st = 'flex:none' + (';' + style if style else '')
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="%s" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="%s">%s</svg>') % (size, size, sw, st, P[name])


FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800'
         '&amp;family=Instrument+Sans:wght@400..700&amp;family=JetBrains+Mono:wght@400..700&amp;display=swap">')

# Tokens copied from src/regrunner/web/static/app.css, plus step-kind hues (light ones darkened for 4.5:1 on white).
CSS = r"""
body{margin:0;background:#090C12}
[data-theme="dark"]{--bg:#090C12;--rail:#0D1119;--surface:#121722;--surface2:#171E2C;--surface3:#1E2839;--line:#212B3D;--line2:#2F3B54;--tx:#E9EDF5;--tx2:#A6B0C5;--tx3:#8791A8;--tx4:#5A6784;--acc:#5CC8FF;--acc-tx:#06121C;--acc-soft:rgba(92,200,255,.12);--acc-line:rgba(92,200,255,.40);--pass:#43D69B;--pass-soft:rgba(67,214,155,.12);--pass-line:rgba(67,214,155,.38);--fail:#FF7062;--fail-soft:rgba(255,112,98,.13);--fail-line:rgba(255,112,98,.42);--warn:#F4B84A;--warn-soft:rgba(244,184,74,.12);--warn-line:rgba(244,184,74,.40);--pend:#5A6784;--pend-soft:rgba(90,103,132,.18);--track:#1A2334;--shadow:0 1px 0 rgba(255,255,255,.035) inset,0 14px 34px rgba(0,0,0,.34);--pop:0 24px 60px rgba(0,0,0,.5);--scrim:rgba(4,6,10,.72);--grid:rgba(150,175,220,.055);
--k-nav:#5CC8FF;--k-act:#DCE3F0;--k-input:#C3A6FF;--k-check:#43D69B;--k-save:#7FD8E6;--k-wait:#8791A8;--k-api:#F4B84A;--k-xml:#FF8FC7;--k-flow:#FFB38A;--k-legacy:#A6B0C5;--sel-bg:#13202E;color-scheme:dark}
[data-theme="light"]{--bg:#F2F0EA;--rail:#EAE7DF;--surface:#FFFFFF;--surface2:#F7F5F0;--surface3:#EDEAE1;--line:#E0DCD1;--line2:#C9C4B6;--tx:#161A23;--tx2:#4B5468;--tx3:#646D80;--tx4:#7D8596;--acc:#0A6FB0;--acc-tx:#FFFFFF;--acc-soft:rgba(10,111,176,.09);--acc-line:rgba(10,111,176,.38);--pass:#11704F;--pass-soft:rgba(17,112,79,.10);--pass-line:rgba(17,112,79,.36);--fail:#BE3427;--fail-soft:rgba(190,52,39,.09);--fail-line:rgba(190,52,39,.38);--warn:#8C5A00;--warn-soft:rgba(140,90,0,.10);--warn-line:rgba(140,90,0,.38);--pend:#8A93A6;--pend-soft:rgba(138,147,166,.16);--track:#E4E0D5;--shadow:0 1px 2px rgba(40,36,20,.06),0 10px 26px rgba(40,36,20,.07);--pop:0 24px 60px rgba(40,36,20,.22);--scrim:rgba(20,18,10,.5);--grid:rgba(60,50,20,.06);
--k-nav:#0A6FB0;--k-act:#3B4458;--k-input:#6B45C9;--k-check:#11704F;--k-save:#0F6E7E;--k-wait:#646D80;--k-api:#8C5A00;--k-xml:#B0337A;--k-flow:#A6461B;--k-legacy:#4B5468;--sel-bg:#E8F1F8;color-scheme:light}
.rr{font-family:'Instrument Sans','Helvetica Neue',Helvetica,sans-serif;font-size:14px;line-height:1.45;color:var(--tx);background:var(--bg);-webkit-font-smoothing:antialiased;overflow:hidden;position:relative}
.rr *,.rr *::before,.rr *::after{box-sizing:border-box}
.rr button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;text-align:left}
.rr input,.rr select,.rr textarea{font:inherit;color:inherit}
.rr a{color:var(--acc);text-decoration:none}
.rr a:hover{text-decoration:underline}
.rr :focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:6px}
.mono{font-family:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.disp{font-family:'Bricolage Grotesque','Helvetica Neue',sans-serif;letter-spacing:-.02em}
.lbl{font-size:11px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--tx3)}
.eyebrow{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:500;letter-spacing:.16em;text-transform:uppercase;color:var(--acc)}
.ttl{font-family:'Bricolage Grotesque',sans-serif;font-weight:650;font-size:19px;letter-spacing:-.01em;line-height:1.2}
.trunc{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.scroll::-webkit-scrollbar{width:10px;height:10px}.scroll::-webkit-scrollbar-thumb{background:var(--line2);border-radius:8px;border:2px solid var(--rail)}.scroll::-webkit-scrollbar-track{background:transparent}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;height:32px;padding:0 12px;border-radius:9px;border:1px solid var(--line2);background:var(--surface2);color:var(--tx);font-size:13px;font-weight:600;white-space:nowrap}
.btn:hover{background:var(--surface3);border-color:var(--tx3)}
.btn-pri{background:var(--acc);border-color:var(--acc);color:var(--acc-tx)}
.btn-pri:hover{background:var(--acc);border-color:var(--acc);filter:brightness(1.08)}
.btn-dng{color:var(--fail);border-color:var(--fail-line);background:var(--fail-soft)}
.btn-ghost{background:transparent;border-color:transparent;color:var(--tx2)}
.btn-ghost:hover{background:var(--surface2);border-color:transparent;color:var(--tx)}
.btn-sm{height:28px;padding:0 10px;font-size:12.5px;border-radius:8px}
.btn-lg{height:44px;padding:0 20px;font-size:14px;border-radius:11px}
.icon-btn{width:32px;height:32px;border-radius:9px;display:inline-grid;place-items:center;color:var(--tx2);border:1px solid var(--line2);background:var(--surface2)}
.icon-btn:hover{color:var(--tx);background:var(--surface3)}
.seg{display:flex;padding:3px;border-radius:10px;background:var(--bg);border:1px solid var(--line);gap:2px}
.seg button,.seg span{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;height:28px;padding:0 9px;border-radius:7px;font-weight:600;font-size:12.5px;color:var(--tx2);white-space:nowrap;text-align:center}
.seg .on{background:var(--surface3);color:var(--tx);box-shadow:0 0 0 1px var(--line2)}
.seg .on.uat{background:var(--acc-soft);color:var(--acc);box-shadow:0 0 0 1px var(--acc-line)}
.seg .on.qa{background:var(--warn-soft);color:var(--warn);box-shadow:0 0 0 1px var(--warn-line)}
.seg .on.prod{background:var(--fail-soft);color:var(--fail);box-shadow:0 0 0 1px var(--fail-line)}
.chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:999px;border:1px solid var(--line2);background:var(--surface2);color:var(--tx2);font-size:12px;white-space:nowrap}
.chip-acc{color:var(--acc);border-color:var(--acc-line);background:var(--acc-soft)}
.chip-warn{color:var(--warn);border-color:var(--warn-line);background:var(--warn-soft)}
.chip-fail{color:var(--fail);border-color:var(--fail-line);background:var(--fail-soft)}
.chip-pass{color:var(--pass);border-color:var(--pass-line);background:var(--pass-soft)}
.tag{display:inline-flex;align-items:center;gap:5px;height:20px;padding:0 7px;border-radius:6px;font:500 11px 'JetBrains Mono',monospace;color:var(--tx2);border:1px solid var(--line2);background:var(--surface2);white-space:nowrap}
.tag-acc{color:var(--acc);border-color:var(--acc-line);background:var(--acc-soft)}
.tag-warn{color:var(--warn);border-color:var(--warn-line);background:var(--warn-soft)}
.tag-fail{color:var(--fail);border-color:var(--fail-line);background:var(--fail-soft)}
.tag-pass{color:var(--pass);border-color:var(--pass-line);background:var(--pass-soft)}
.pill{display:inline-flex;align-items:center;gap:6px;height:22px;padding:0 9px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;border:1px solid transparent}
.p-run{color:var(--acc);background:var(--acc-soft);border-color:var(--acc-line)}
.p-pass{color:var(--pass);background:var(--pass-soft);border-color:var(--pass-line)}
.p-fail{color:var(--fail);background:var(--fail-soft);border-color:var(--fail-line)}
.p-warn{color:var(--warn);background:var(--warn-soft);border-color:var(--warn-line)}
.p-pend{color:var(--tx2);background:var(--pend-soft);border-color:var(--line2)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex:none;display:inline-block}
.badge{display:inline-flex;align-items:center;justify-content:center;height:20px;padding:0 7px;border-radius:5px;font:600 10.5px 'JetBrains Mono',monospace;letter-spacing:.02em;white-space:nowrap;color:var(--k);background:color-mix(in srgb,var(--k) 14%,transparent)}
.k-nav{--k:var(--k-nav)}.k-act{--k:var(--k-act)}.k-input{--k:var(--k-input)}.k-check{--k:var(--k-check)}.k-save{--k:var(--k-save)}.k-wait{--k:var(--k-wait)}.k-api{--k:var(--k-api)}.k-xml{--k:var(--k-xml)}.k-flow{--k:var(--k-flow)}.k-legacy{--k:var(--k-legacy)}
.var{display:inline-flex;align-items:center;gap:4px;height:21px;padding:0 7px;border-radius:6px;font-size:12px;font-weight:600;color:var(--k-input);background:color-mix(in srgb,var(--k-input) 13%,transparent);white-space:nowrap}
.var.secret{color:var(--tx2);background:var(--surface3)}
.var.env{color:var(--k-nav);background:color-mix(in srgb,var(--k-nav) 13%,transparent)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}
.scard{display:flex;align-items:center;gap:9px;width:100%;min-height:42px;padding:6px 12px 6px 6px;border-radius:9px;border:1px solid var(--line);background:var(--surface);font-size:13.5px}
.scard:hover{border-color:var(--line2)}
.rail-item{display:flex;align-items:center;gap:8px;width:100%;height:30px;padding:0 10px;border-radius:7px;font-size:13px;color:var(--tx2)}
.rail-item:hover{background:var(--surface);color:var(--tx)}
.rail-item.on{background:var(--surface2);color:var(--tx);box-shadow:inset 0 0 0 1px var(--line2)}
.field{display:flex;align-items:center;gap:8px;min-height:36px;padding:6px 10px;border-radius:8px;border:1px solid var(--line2);background:var(--bg);font-size:13px;width:100%}
.fld{height:36px;width:100%;border-radius:8px;border:1px solid var(--line2);background:var(--bg);padding:0 10px;font-size:13px;color:var(--tx)}
.kbd{font:500 10.5px 'JetBrains Mono',monospace;border:1px solid var(--line2);border-bottom-width:2px;border-radius:5px;padding:0 5px;background:var(--surface2);color:var(--tx2);white-space:nowrap}
.sw{flex:none;width:34px;height:20px;border-radius:20px;background:var(--line2);position:relative;display:inline-block}
.sw::after{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--tx)}
.sw.on{background:var(--acc)}.sw.on::after{left:16px;background:var(--acc-tx)}
.cbx{flex:none;width:16px;height:16px;border-radius:5px;border:1.5px solid var(--line2);background:var(--bg);display:inline-grid;place-items:center;color:var(--acc-tx)}
.cbx.on{background:var(--acc);border-color:var(--acc)}
.bn{display:flex;gap:10px;padding:11px 14px;border-radius:11px;border:1px solid var(--line2);background:var(--surface2);font-size:12.5px;line-height:1.5;color:var(--tx)}
.bn-warn{background:var(--warn-soft);border-color:var(--warn-line)}
.bn-fail{background:var(--fail-soft);border-color:var(--fail-line)}
.bn-acc{background:var(--acc-soft);border-color:var(--acc-line)}
.bn-pass{background:var(--pass-soft);border-color:var(--pass-line)}
.hr{height:1px;background:var(--line);flex:none}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.tbl th{text-align:left;font:600 10.5px 'Instrument Sans',sans-serif;letter-spacing:.09em;text-transform:uppercase;color:var(--tx3);padding:7px 10px;background:var(--surface2);border-bottom:1px solid var(--line);white-space:nowrap}
.tbl td{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:middle;white-space:nowrap}
.gcell{padding:0 9px;height:30px;display:flex;align-items:center;border-right:1px solid var(--line);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px;flex:none}
.shot{position:relative;border-radius:10px;overflow:hidden;border:1px solid var(--line2);background:repeating-linear-gradient(135deg,var(--surface) 0 10px,var(--surface2) 10px 20px)}
.pdot{width:8px;height:8px;border-radius:50%;flex:none;display:inline-block}
.scrim{position:absolute;inset:0;background:var(--scrim)}
.modal{position:relative;background:var(--surface);border:1px solid var(--line2);border-radius:16px;box-shadow:var(--pop);display:flex;flex-direction:column}
.menu{background:var(--surface);border:1px solid var(--line2);border-radius:12px;box-shadow:var(--pop)}
.mitem{display:flex;align-items:center;gap:9px;width:100%;height:34px;padding:0 10px;border-radius:8px;font-size:13px;color:var(--tx)}
.mitem:hover{background:var(--surface2)}
.mitem.on{background:var(--acc-soft);color:var(--acc)}
.site{font-family:Georgia,'Times New Roman',serif}
"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>@@TITLE@@</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
""" + FONTS + """
<style>""" + CSS + """</style>
</helmet>
"""

LOGO = ('<svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true" style="flex:none"><rect x="1" y="1" width="30" height="30" rx="9" '
        'style="fill:var(--acc-soft);stroke:var(--acc)" stroke-width="1.5"></rect><path d="M8 11h6M8 16h4M8 21h6" style="stroke:var(--acc)" stroke-width="1.6" '
        'stroke-linecap="round" opacity=".55"></path><path d="M15 17l3.6 3.6L25 12" style="stroke:var(--acc)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path></svg>')


def tabs(active):
    out = []
    for t in ('Run', 'Build', 'Results'):
        if t == active:
            out.append('<a href="#" aria-current="page" style="height: 30px; display: flex; align-items: center; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 600; background: var(--surface3); color: var(--tx); box-shadow: 0 0 0 1px var(--line2); text-decoration: none">%s</a>' % t)
        else:
            out.append('<a href="#" style="height: 30px; display: flex; align-items: center; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 600; color: var(--tx2); text-decoration: none">%s</a>' % t)
    return ('<nav aria-label="Sections" style="display: flex; gap: 2px; padding: 3px; border-radius: 11px; background: var(--surface); border: 1px solid var(--line)">'
            + ''.join(out) + '</nav>')


def header(active, middle='', right=''):
    return ('<header style="height: 60px; flex: none; display: flex; align-items: center; gap: 18px; padding: 0 18px 0 20px; border-bottom: 1px solid var(--line); background: var(--bg)">'
            '<div style="display: flex; align-items: center; gap: 10px">' + LOGO +
            '<span class="disp" style="font-size: 18px; font-weight: 700; letter-spacing: -.015em">QA Regression</span></div>'
            + tabs(active) +
            '<div style="display: flex; align-items: center; gap: 8px; min-width: 0; flex-grow: 1">' + middle + '</div>'
            + right + '</header>')


def root_open(w, h, theme='dark', extra=''):
    return ('<div class="rr" data-theme="%s" style="width: %dpx; height: %dpx; display: flex; flex-direction: column; %s">' % (theme, w, h, extra))


def page(title, body, w, h, script=None, props=None):
    pr = {'$preview': {'width': w, 'height': h}}
    if props:
        pr.update(props)
    js = script or 'class Component extends DCLogic {\n  renderVals() { return {}; }\n}\n'
    dp = json.dumps(pr, ensure_ascii=False).replace('&', '&amp;').replace("'", '&#39;')
    return HEAD.replace("@@TITLE@@", title) + body + '\n</x-dc>\n<script type="text/x-dc" data-dc-script data-props=\'' + dp + '\'>\n' + js + '</script>\n</body>\n</html>\n'


def write(name, html):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), 'w') as f:
        f.write(html)
    print('wrote', name, len(html))


# --- small builders ---------------------------------------------------------------------------------------------------
def var(label, token=None, secret=False, env=False):
    cls = 'var' + (' secret' if secret else '') + (' env' if env else '')
    t = (' title="{%s}"' % token) if token else ''
    icon = ic('lock', 11, 2.2) if secret else ic('braces', 11, 2.2)
    return '<span class="%s"%s>%s%s</span>' % (cls, t, icon, ('•••• ' + label) if secret else label)


def badge(kind, text):
    return '<span class="badge k-%s">%s</span>' % (kind, text)


def kbd(mac, win=None):
    return '<span class="kbd">%s</span>' % mac


def sw(on=True, label=None):
    return '<span class="sw%s"%s></span>' % (' on' if on else '', (' aria-label="%s"' % label) if label else '')


def cbx(on=False):
    return '<span class="cbx%s">%s</span>' % (' on' if on else '', ic('check', 11, 3) if on else '')


def rail_workbook(active_test='Owner_CRVD', extra_section=''):
    tests = [('web', 'Owner_CRVD', '287', 'fail'), ('api', 'quotePrice#1', '9', 'pass'), ('xml', 'policyRecord#1', '8', 'pass'),
             ('web', 'Owner_RVD', '214', 'pass'), ('web', 'Owner_AZ', '188', 'pass'), ('web', 'ANZ', '240', 'pass'),
             ('web', 'CW', '96', 'pend'), ('web', 'WM', '121', 'pass'), ('web', 'PostDeparture', '77', 'pass')]
    items = []
    for kind, name, n, st in tests:
        on = ' on' if name == active_test else ''
        col = {'pass': 'var(--pass)', 'fail': 'var(--fail)', 'pend': 'var(--pend)'}[st]
        items.append('<button class="rail-item%s"><span style="color: var(--tx3); display: inline-flex">%s</span><span class="trunc" style="flex-grow: 1">%s</span>'
                     '<span class="mono" style="font-size: 11px; color: var(--tx3)">%s</span><span class="pdot" style="background: %s" title="Last run"></span></button>'
                     % (on, ic(kind, 14), name, n, col))
    return ('<aside class="scroll" style="width: 236px; flex: none; border-right: 1px solid var(--line); background: var(--rail); display: flex; flex-direction: column; gap: 18px; padding: 14px 10px; overflow: auto">'
            '<a href="#" style="display: flex; flex-direction: column; gap: 6px; padding: 4px 6px; color: var(--tx); text-decoration: none">'
            '<span class="lbl" style="display: flex; align-items: center; gap: 6px">' + ic('chevl', 12, 2.4) + ' Workbook map</span>'
            '<span class="disp" style="font-size: 15px; font-weight: 700; line-height: 1.2">Travelex Regression v9.1</span>'
            '<span style="display: flex; gap: 6px"><span class="tag tag-acc">UAT</span><span class="tag">11 tests</span><span class="tag">52 variables</span></span></a>'
            '<div style="display: flex; flex-direction: column; gap: 2px"><div style="display: flex; align-items: center; justify-content: space-between; padding: 0 6px 4px">'
            '<span class="lbl">Tests</span><button class="btn btn-ghost btn-sm" style="height: 24px; padding: 0 6px">' + ic('plus', 13, 2.2) + ' New</button></div>'
            + ''.join(items) + '</div>'
            '<div style="display: flex; flex-direction: column; gap: 2px"><span class="lbl" style="padding: 0 6px 4px">Data</span>'
            '<button class="rail-item">' + ic('table', 14) + '<span style="flex-grow: 1">Params_1 · trip</span><span class="mono" style="font-size: 11px; color: var(--tx3)">8 rows</span></button>'
            '<button class="rail-item">' + ic('table', 14) + '<span style="flex-grow: 1">Params_2 · travelers</span><span class="mono" style="font-size: 11px; color: var(--tx3)">2 rows</span></button>'
            '<button class="rail-item">' + ic('braces', 14) + '<span style="flex-grow: 1">Variables</span><span class="mono" style="font-size: 11px; color: var(--tx3)">52</span></button>'
            '<button class="rail-item">' + ic('globe', 14) + '<span style="flex-grow: 1">Environments</span><span class="mono" style="font-size: 11px; color: var(--tx3)">3</span></button></div>'
            '<div style="display: flex; flex-direction: column; gap: 2px"><span class="lbl" style="padding: 0 6px 4px">Workbook</span>'
            '<button class="rail-item">' + ic('gate', 14) + '<span style="flex-grow: 1">Page fingerprints</span><span class="mono" style="font-size: 11px; color: var(--tx3)">9</span></button>'
            '<button class="rail-item">' + ic('layers', 14) + '<span style="flex-grow: 1">Templates</span><span class="mono" style="font-size: 11px; color: var(--tx3)">6</span></button>'
            '<button class="rail-item">' + ic('sync', 14) + '<span style="flex-grow: 1">Scenarios</span><span class="mono" style="font-size: 11px; color: var(--tx3)">1</span></button>'
            '<button class="rail-item">' + ic('history', 14) + '<span style="flex-grow: 1">History</span></button>'
            '<button class="rail-item">' + ic('settings', 14) + '<span style="flex-grow: 1">Settings (Global)</span></button></div>'
            + extra_section + '</aside>')
