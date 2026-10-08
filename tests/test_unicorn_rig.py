"""The unicorn mascot's SVG rig keeps the contract in src/regrunner/web/static/unicorn/docs/rig-spec.md (pure file checks, no browser)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

UNICORN = Path(__file__).resolve().parent.parent / "src" / "regrunner" / "web" / "static" / "unicorn"
SVG = UNICORN / "svg" / "unicorn-front-sitting.svg"
SVG_NS = "{http://www.w3.org/2000/svg}"

REQUIRED_IDS = [
    "body", "neck", "head", "ear-left", "ear-right", "horn", "eye-left", "eye-right", "eyelid-left", "eyelid-right",
    "brow-left", "brow-right", "cheek-left", "cheek-right", "mouth-neutral", "mouth-smile", "mouth-frown", "mouth-open",
    "mane-back", "mane-front", "tail", "front-leg-left", "front-leg-right", "hoof-left", "hoof-right", "chest-heart", "shadow",
]


def _tree() -> ET.Element:
    return ET.parse(SVG).getroot()


def _group_ids(root: ET.Element) -> list[str]:
    return [g.get("id") for g in root.iter(SVG_NS + "g") if g.get("id")]


def test_every_part_the_brief_names_is_its_own_group_with_a_unique_id() -> None:
    ids = _group_ids(_tree())
    assert len(ids) == len(set(ids)), "duplicate group id"
    locks = [i for i in ids if re.fullmatch(r"mane-lock-\d+", i)]
    assert 4 <= len(locks) <= 6, "the mane is 4 to 6 independent locks"
    missing = [i for i in REQUIRED_IDS if i not in ids]
    assert not missing, f"missing parts: {missing}"


def test_the_svg_has_no_scripts_animation_or_transform_attributes_on_parts() -> None:
    root = _tree()
    banned = {"script", "animate", "animateTransform", "animateMotion", "set", "foreignObject", "filter", "mask"}
    found = {el.tag.replace(SVG_NS, "") for el in root.iter()} & banned
    assert not found, f"phase 1 art must be plain shapes and gradients: {found}"
    for g in root.iter(SVG_NS + "g"):
        assert g.get("transform") is None, f"#{g.get('id')} has a transform attribute: CSS transforms would replace it"
    for el in root.iter():
        assert not any(k.startswith("on") for k in el.attrib), "no event-handler attributes"


def test_every_movable_part_has_a_documented_pivot_in_the_svg_css() -> None:
    css = "".join(el.text or "" for el in _tree().iter(SVG_NS + "style"))
    for part in ["head-rig", "neck", "horn", "ear-left", "ear-right", "tail", "body", "mane-front", "mane-back", "front-leg-left", "front-leg-right",
                 "hoof-left", "hoof-right", "eye-left", "eye-right", "eyelid-left", "eyelid-right", "brow-left", "brow-right", "chest-heart",
                 "mane-lock-1", "mane-lock-2", "mane-lock-3", "mane-lock-4", "mane-lock-5", "mane-lock-6", "shadow"]:
        assert re.search(r"#" + re.escape(part) + r"\b[^{]*\{[^}]*transform-origin:", css), f"no transform-origin for #{part}"


def test_by_default_only_the_neutral_mouth_and_open_eyes_are_visible() -> None:
    root = _tree()
    unicorn = next(g for g in root.iter(SVG_NS + "g") if g.get("id") == "unicorn")
    assert unicorn.get("data-eyes") == "open" and unicorn.get("data-mouth") == "neutral" and unicorn.get("data-fx") == "none"
    css = "".join(el.text or "" for el in root.iter(SVG_NS + "style"))
    for hidden in ["#unicorn .eye-closed", "#unicorn #mouth-smile", "#unicorn #mouth-frown", "#unicorn #mouth-open"]:
        assert hidden in css.split("{", 1)[0], f"{hidden} must be hidden by default"


def test_the_preview_page_is_up_to_date_and_loads_the_idle_and_mood_scripts() -> None:
    preview = (UNICORN / "preview.html").read_text(encoding="utf-8")
    svg = SVG.read_text(encoding="utf-8").split("?>", 1)[1].lstrip()
    assert svg in preview, "preview.html is stale: run tools/build_preview.py"
    for script in ("js/idle.js", "js/mood.js"):
        assert f'<script src="{script}"></script>' in preview and (UNICORN / script).is_file()


def test_every_visible_part_carries_its_own_shading_and_one_css_knob_scales_it() -> None:
    root = _tree()
    shaded = {}
    for g in root.iter(SVG_NS + "g"):
        if g.get("id"):
            shaded[g.get("id")] = sum(1 for el in g.iter() if "shade" in (el.get("class") or "").split())
    for part in ["body", "head", "ear-left", "ear-right", "tail", "mane-front", "front-leg-left", "front-leg-right", "hoof-left", "hoof-right",
                 "mane-lock-1", "mane-lock-2", "mane-lock-3", "mane-lock-4", "mane-lock-5", "mane-lock-6"]:
        assert shaded[part] >= 1, f"#{part} has no shade overlay"
    css = "".join(el.text or "" for el in root.iter(SVG_NS + "style"))
    assert "--shade-strength" in css and re.search(r"\.shade\s*\{[^}]*opacity:\s*var\(--shade-strength\)", css)


def test_cast_shadows_are_clipped_to_the_surface_they_fall_on_and_the_neck_sits_behind_the_body() -> None:
    root = _tree()
    defined = {el.get("id") for el in root.iter(SVG_NS + "clipPath")}
    used = {re.search(r"#([\w-]+)", el.get("clip-path")).group(1) for el in root.iter() if el.get("clip-path")}
    assert used and used <= defined, f"clip-path points at undefined ids: {used - defined}"
    ids = _group_ids(root)
    assert ids.index("neck") < ids.index("body"), "the neck must be drawn before the body, or its lower edge shows as a hard bib"
    assert ids.index("chest-heart") > ids.index("front-leg-right"), "the heart must be drawn after the legs"


def test_the_rig_stays_light_in_size_and_in_the_number_of_moving_groups() -> None:
    """Detail must come from gradients on shapes that already exist: a size and a group budget keep a later 'more detail' round honest."""
    assert SVG.stat().st_size < 60_000, "the SVG grew past 60 KB: add detail with gradients, not with more geometry"
    assert len(_group_ids(_tree())) <= 56, "more moving groups cost animation time; the rig has 52"
