"""Large objects: multi-sheet drawing sets, plant structures, machines.

A single prompt cannot hold a twelve-sheet plant set, and a single script for
hundreds of members fails as a whole when one line is wrong. This pipeline
therefore works in steps that each fit the model and fail on their own:

    survey      every sheet at overview resolution: title, views, tables, scale bars
    read        every main view zoomed from the original file: dimensions,
                levels, grid lines, labels, members (lengths converted to mm)
    scale       mm per sheet pixel for each view, from its scale bar or from
                the dimensions read in it (written value / measured length)
    plan        the object broken into 5-30 components with global bounding boxes
    components  one script per component, built and corrected on its own;
                a component that still fails becomes a marked placeholder box
    assemble    one script with a builder function per component -> one
                version: STEP assembly with named, coloured components

Everything is stored under <project>/assembly/ so that a component can be
redone later without reading the drawings again.
"""
from __future__ import annotations

import json
import math
import re
import statistics

from . import prompts, prompts_asm as PA, spec as specmod, units, vision
from .cadexec import worker
from .jobs import Stopped
from .paths import load_settings
from .pipeline import _user, ai_image, ask, build_version, ensure_engine
from .project import Project

MAX_VIEWS_PER_SHEET = 8
MAX_VIEWS = 30
COLORS = ["gray50", "steelblue", "orange", "lightgray", "darkgreen", "gold", "brown", "teal", "red", "blue"]


# ------------------------------------------------------------------ helpers
def _ask_json(job, msgs, stage, max_tokens=8000):
    text = ask(job, msgs, stage, max_tokens=max_tokens, temperature=0.2)
    try:
        return specmod.parse_json(text)
    except ValueError as e:
        job.log(f"The answer was not valid JSON ({e}); asking again.", "warn")
        msgs = msgs + [{"role": "assistant", "content": text[-6000:]},
                       {"role": "user", "content": "That was not one valid JSON object. Return only the JSON object."}]
        return specmod.parse_json(ask(job, msgs, "repair", max_tokens=max_tokens, temperature=0.1))


def _pt(p, W, H):
    try:
        return [float(p[0]) / 1000 * W, float(p[1]) / 1000 * H]
    except (TypeError, ValueError, IndexError):
        return None


def _crop_pt(p, crop):
    """A point in 0-1000 crop coordinates -> page pixels."""
    try:
        x = float(p[0]) / 1000 * crop["size"][0] * crop["page_per_px"] + crop["origin"][0]
        y = float(p[1]) / 1000 * crop["size"][1] * crop["page_per_px"] + crop["origin"][1]
        return [round(x, 1), round(y, 1)]
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def _length_of(text, unit):
    """The length a dimension text stands for: the total after '=' when the
    text is a chain such as '8 PANELS @ 21'-0" = 168'-0"'."""
    t = str(text or "")
    if "=" in t:
        t = t.split("=")[-1]
    return units.parse_length(t, unit)


def _ident(s, used):
    base = re.sub(r"\W+", "_", str(s or "c")).strip("_").lower() or "c"
    if base[0].isdigit():
        base = "c_" + base
    n, k = base[:30], 2
    while n in used:
        n = f"{base[:26]}_{k}"
        k += 1
    used.add(n)
    return n


# ------------------------------------------------------------------ survey
def survey_page(job, p: Project, idx: int) -> dict:
    page, path = p.page(idx)
    W, H = page["w"], page["h"]
    label = f"S{idx + 1} ({page['source']} p{page['page']})"
    from .pipeline import _texts_hint
    raw = _ask_json(job, [{"role": "system", "content": PA.SURVEY_SYSTEM},
                          _user(PA.survey_user(label, _texts_hint(page)), [ai_image(p, path)])], "read", 6000)
    sh = raw.get("sheet") or {}
    unit = str(raw.get("units") or "mm").lower()
    unit = "ft-in" if ("ft" in unit or "'" in unit) else ("inch" if unit.startswith("in") else ("m" if unit == "m" else "mm"))
    sheet = {"page": idx, "id": f"S{idx + 1}", "file": page["file"], "title": str(sh.get("title") or ""),
             "number": str(sh.get("number") or ""), "kind": str(sh.get("kind") or ""), "units": unit,
             "scale_text": raw.get("scale_text"), "summary": str(raw.get("summary") or ""),
             "objects": [str(o) for o in _as_list(raw.get("objects"))][:20], "views": [], "scale_bars": [], "tables": []}
    boxes, views = [], []
    for k, v in enumerate(raw.get("views") or []):
        if not isinstance(v, dict) or not isinstance(v.get("box"), (list, tuple)) or len(v["box"]) < 4:
            continue
        try:
            b = vision.norm_box_to_px([float(c) for c in v["box"][:4]], W, H)
        except (TypeError, ValueError):
            continue
        if (b[2] - b[0]) < 0.02 * W or (b[3] - b[1]) < 0.02 * H:
            continue
        views.append({"id": f"{sheet['id']}{str(v.get('id') or f'V{k + 1}').upper()}", "type": str(v.get("type") or "other").lower(),
                      "label": str(v.get("label") or ""), "level_or_cut": str(v.get("level_or_cut") or ""),
                      "scale_text": v.get("scale_text"), "box_ai": b})
        boxes.append(b)
    try:
        gray = vision.load_gray(path)
        snapped, how = vision.snap_boxes(gray, boxes)
    except Exception:
        snapped, how = boxes, ["ai"] * len(boxes)
    for v, b, h in zip(views, snapped, how):
        v["box"], v["how"] = [round(c, 1) for c in b], h
        sheet["views"].append(v)
    for sb in raw.get("scale_bars") or []:
        if not isinstance(sb, dict):
            continue
        p1, p2 = _pt(sb.get("p1") or [], W, H), _pt(sb.get("p2") or [], W, H)
        L = units.parse_length(f"{sb.get('length')} {sb.get('unit', '')}".replace(" ft", "'").replace(" in", '"'),
                               "mm")
        if p1 and p2 and L and vision.dist(p1, p2) > 10:
            bar = {"p1": p1, "p2": p2, "length_mm": L, "view": sb.get("view"),
                   "mm_per_px": L / vision.dist(p1, p2), "how": "AI points (not measured)"}
            try:     # measure the bar itself; the AI's points are only a hint
                from . import scalebar
                r = scalebar.refine(job, ask, p.dir / "input", page, p.dir / "assembly" / "crops", p1, p2, L,
                                    tag=f"{sheet['id']}_bar{len(sheet['scale_bars']) + 1}")
                if r:
                    bar.update(r)
            except Exception as e:
                job.log(f"  scale bar could not be measured ({e}); the AI's points are used.", "warn")
            sheet["scale_bars"].append(bar)
    for t in raw.get("tables") or []:
        if isinstance(t, dict) and isinstance(t.get("box"), (list, tuple)) and len(t["box"]) >= 4:
            try:
                sheet["tables"].append({"kind": str(t.get("kind") or ""),
                                        "box": vision.norm_box_to_px([float(c) for c in t["box"][:4]], W, H)})
            except (TypeError, ValueError):
                pass
    job.log(f"{sheet['id']} '{sheet['title'][:60]}': {len(sheet['views'])} views, "
            f"{len(sheet['scale_bars'])} scale bars, units {unit}.")
    return sheet


# ------------------------------------------------------------------ read views
MAX_TILES = 6
TILE_FACTOR = 2.5     # at most this many original pixels per crop pixel before a view is tiled


def _tiles(page, box, side):
    """Overlapping tiles of a view so that small text stays legible: a view
    drawn large on a 20 000 px scan would otherwise be reduced several times."""
    f = (page.get("orig") or {}).get("w", page["w"]) / page["w"]
    w, h = (box[2] - box[0]) * f, (box[3] - box[1]) * f
    nx = max(1, math.ceil(w / (side * TILE_FACTOR)))
    ny = max(1, math.ceil(h / (side * TILE_FACTOR)))
    while nx * ny > MAX_TILES:
        if nx >= ny:
            nx -= 1
        else:
            ny -= 1
    if nx * ny == 1:
        return [list(box)]
    tw, th = (box[2] - box[0]) / nx, (box[3] - box[1]) / ny
    ov = 0.08
    out = []
    for j in range(ny):
        for i in range(nx):
            out.append([box[0] + max(0, i - ov) * tw, box[1] + max(0, j - ov) * th,
                        box[0] + min(nx, i + 1 + ov) * tw, box[1] + min(ny, j + 1 + ov) * th])
    return out


def read_view(job, p: Project, sheet: dict, view: dict) -> dict:
    page, path = p.page(sheet["page"])
    eng_cpu = False
    try:
        from . import llm
        eng_cpu = llm.engine().engine_kind == "cpu"
    except Exception:
        pass
    side = 1024 if eng_cpu else 1800
    out = p.dir / "assembly" / "crops" / f"{view['id']}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # the whole view (also shown to the component step), then tiles when it is large
    crop = vision.zoom_crop(p.dir / "input", page, view["box"], out, max_side=side)
    tiles = _tiles(page, view["box"], side)
    raws = []
    if len(tiles) == 1:
        raws.append((crop, _ask_json(job, [{"role": "system", "content": PA.READ_VIEW_SYSTEM},
                                           _user(PA.read_view_user(view, sheet, sheet["units"]), [out])], "read", 8000)))
    else:
        job.log(f"  {view['id']}: large view, read in {len(tiles)} tiles.")
        for k, tb in enumerate(tiles):
            job.check()
            tp = out.with_name(f"{view['id']}_t{k + 1}.png")
            tc = vision.zoom_crop(p.dir / "input", page, tb, tp, max_side=side, pad=0)
            note = f" This is tile {k + 1} of {len(tiles)} of the view; report only what is in this tile."
            try:
                raws.append((tc, _ask_json(job, [{"role": "system", "content": PA.READ_VIEW_SYSTEM},
                                                 _user(PA.read_view_user(view, sheet, sheet["units"]) + note, [tp])],
                                           "read", 8000)))
            except ValueError as e:
                job.log(f"  {view['id']} tile {k + 1}: unreadable answer ({e}).", "warn")
    unit = sheet["units"]
    rd = {"view": view["id"], "crop": crop, "tiles": len(tiles), "dimensions": [], "levels": [], "grid": [],
          "labels": [], "members": [], "shapes": " ".join(str(r.get("shapes") or "") for _, r in raws)[:1500],
          "notes": [str(n) for _, r in raws for n in _as_list(r.get("notes"))][:30]}
    for crop, raw in raws:
        _merge_reading(rd, crop, raw, unit)
    job.log(f"  {view['id']} ({view['type']}): {len(rd['dimensions'])} dimensions, {len(rd['levels'])} levels, "
            f"{len(rd['labels'])} labels, {len(rd['members'])} members.")
    return rd


def _as_list(v):
    """A list answer that the AI may also give as one string (or leave out)."""
    if not v:
        return []
    return v if isinstance(v, list) else [v]


SCALE_NOTE = re.compile(r"=|\bscale\b|\bNTS\b", re.I)


def _near(a, b, tol=25.0):
    return a and b and abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _merge_reading(rd, crop, raw, unit):
    """Add one (tile) answer to a reading; items repeated in the overlap of
    two tiles (same text at nearly the same place) are kept once."""
    def seen(key, text, pt):
        return any(x.get("text", x.get("mark")) == text and _near(x.get("at") or x.get("p1"), pt) for x in rd[key])

    for d in raw.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        L = _length_of(d.get("text"), unit)
        p1, p2 = _crop_pt(d.get("p1") or [], crop), _crop_pt(d.get("p2") or [], crop)
        t = str(d.get("text") or "")
        if seen("dimensions", t, p1):
            continue
        if SCALE_NOTE.search(t):          # a scale note such as 3/8" = 1'-0" is not a size of the object
            if t not in rd["notes"]:
                rd["notes"].append(t)
            continue
        rd["dimensions"].append({"text": t, "mm": round(L, 2) if L else None,
                                 "describes": str(d.get("describes") or ""), "axis": d.get("axis"), "p1": p1, "p2": p2})
    for lv in raw.get("levels") or []:
        if isinstance(lv, dict):
            L = units.parse_length(lv.get("text"), unit)
            at = _crop_pt(lv.get("at") or [], crop)
            if seen("levels", str(lv.get("text") or ""), at):
                continue
            rd["levels"].append({"text": str(lv.get("text") or ""), "mm": round(L, 1) if L is not None else None,
                                 "at": at, "describes": str(lv.get("describes") or "")})
    for key in ("grid", "labels"):
        for g in raw.get(key) or []:
            if isinstance(g, dict):
                t, at = str(g.get("label") or g.get("text") or ""), _crop_pt(g.get("at") or [], crop)
                if not seen(key, t, at):
                    rd[key].append({"text": t, "at": at, "dir": g.get("dir")})
    for m in raw.get("members") or []:
        if isinstance(m, dict):
            p1 = _crop_pt(m.get("p1") or [], crop)
            if any(x["mark"] == str(m.get("mark") or "") and _near(x.get("p1"), p1) for x in rd["members"]):
                continue
            rd["members"].append({"mark": str(m.get("mark") or ""), "section": str(m.get("section") or ""),
                                  "p1": p1, "p2": _crop_pt(m.get("p2") or [], crop)})


def _box_dist(pt, box):
    dx = max(box[0] - pt[0], 0, pt[0] - box[2])
    dy = max(box[1] - pt[1], 0, pt[1] - box[3])
    return math.hypot(dx, dy)


def _bar_scale(sheet, view, bars, readings):
    """The scale of a view from the bars drawn with it. Bars that agree
    (feet and metres within 10 %) give their median; when they disagree, a
    bar measured on the sheet beats one placed by the AI, and the dimensions
    read in the view decide between the rest."""
    vals = [b["mm_per_px"] for b in bars]
    if max(vals) / min(vals) <= 1.10:
        return statistics.median(vals), "graphic scale bar"
    measured = [b for b in bars if str(b.get("how", "")).startswith("measured")]
    if measured and (len(measured) == 1 or max(b["mm_per_px"] for b in measured) / min(b["mm_per_px"] for b in measured) <= 1.10):
        return statistics.median(b["mm_per_px"] for b in measured), "graphic scale bar (measured)"
    cand = measured or bars
    sc, _ = view_scale(sheet, view, readings.get(view["id"]) if readings else None, None, bars=False)
    if sc:
        b = min(cand, key=lambda b: abs(math.log(b["mm_per_px"] / sc)))
        return b["mm_per_px"], f"graphic scale bar (of {len(bars)} that disagree, the one closest to the dimensions)"
    b = max(cand, key=lambda b: vision.dist(b["p1"], b["p2"]))
    return b["mm_per_px"], f"graphic scale bar (the longest of {len(bars)} that disagree)"


def sheet_scales(sheet: dict, readings: dict, calib=None) -> dict:
    """mm per page pixel of every view of a sheet, with its source.

    A measured scale bar serves the view it is drawn with (the nearest one);
    a view without a bar takes the scale of its own dimensions, or else the
    ratio of its scale note to that of a view with a bar (a sheet with a
    3/8" = 1'-0" section and a 1/16" = 1'-0" key plan has two scales)."""
    from . import units as U
    out = {}
    views = sheet.get("views") or []
    if calib and calib.get("mm_per_px"):
        return {v["id"]: (calib["mm_per_px"], "user calibration") for v in views}
    bars = [b for b in (sheet.get("scale_bars") or []) if b.get("mm_per_px")]
    owner = {}
    for b in bars:
        c = ((b["p1"][0] + b["p2"][0]) / 2, (b["p1"][1] + b["p2"][1]) / 2)
        if views:
            v = min(views, key=lambda v: _box_dist(c, v["box"]))
            owner.setdefault(v["id"], []).append(b)
    for v in views:
        if owner.get(v["id"]):
            out[v["id"]] = _bar_scale(sheet, v, owner[v["id"]], readings)
    sheet_f = U.scale_factor(sheet.get("scale_text") or "")
    for v in views:
        if v["id"] in out:
            continue
        fv = U.scale_factor(v.get("scale_text") or "")
        # 1. a scale note of its own that differs from a view with a bar: the ratio
        if fv:
            for w in views:
                fw = U.scale_factor(w.get("scale_text") or sheet.get("scale_text") or "")
                if w["id"] in out and fw and abs(fv / fw - 1) > 0.01:
                    out[v["id"]] = (out[w["id"]][0] * fv / fw, f"scale note {v['scale_text']} against {w['id']}")
                    break
        # 2. the measured bar of the sheet (a measured bar beats the AI's points)
        if v["id"] not in out and bars and (not fv or not sheet_f or abs(fv / sheet_f - 1) <= 0.01 or len(views) == 1):
            c = ((v["box"][0] + v["box"][2]) / 2, (v["box"][1] + v["box"][3]) / 2)
            b = min(bars, key=lambda b: vision.dist(((b["p1"][0] + b["p2"][0]) / 2, (b["p1"][1] + b["p2"][1]) / 2), c))
            out[v["id"]] = (b["mm_per_px"], "graphic scale bar of the sheet")
        # 3. the dimensions read in the view: the scale, or a check of the bar
        sc, src = view_scale(sheet, v, readings.get(v["id"]), None, bars=False)
        if v["id"] not in out:
            out[v["id"]] = (sc, src) if sc else (None, None)
        elif sc and abs(sc / out[v["id"]][0] - 1) > 0.15:
            out[v["id"]] = (out[v["id"]][0], out[v["id"]][1] +
                            f" (the dimensions read in the view suggest {sc:.4g} mm/px; the bar is used)")
    return out


def view_scale(sheet: dict, view: dict, reading: dict | None, calib=None, bars=True):
    """mm per page pixel of a view and where it comes from."""
    if calib and calib.get("mm_per_px"):
        return calib["mm_per_px"], "user calibration"
    if bars and sheet.get("scale_bars"):
        sc = sheet_scales(sheet, {view["id"]: reading} if reading else {}).get(view["id"])
        if sc and sc[0]:
            return sc
    cands = []
    for d in (reading or {}).get("dimensions", []):
        if d.get("mm") and d.get("p1") and d.get("p2"):
            dx, dy = abs(d["p2"][0] - d["p1"][0]), abs(d["p2"][1] - d["p1"][1])
            L = dx if d.get("axis") == "h" else dy if d.get("axis") == "v" else math.hypot(dx, dy)
            if L > 15:
                cands.append(d["mm"] / L)
    if len(cands) >= 2:
        med = statistics.median(cands)
        good = [c for c in cands if abs(c / med - 1) < 0.15]       # misread dimensions drop out
        if len(good) >= 2:
            return statistics.median(good), f"{len(good)} dimensions read in the view"
    if len(cands) == 1:
        return cands[0], "one dimension read in the view"
    return None, None


# ------------------------------------------------------------------ digest, contact sheet
LEGEND = re.compile(r"^\s*([A-Z]|\d{1,2})\s*[.):-]?\s+([A-Za-z].{2,})$")


def _placed_labels(labels):
    """Labels in the order they help the plan, each at the place of the part it names.

    A legend entry ("A PILOT EXCITER", "13 FRANCIS TURBINE") sits in the legend
    table; the part itself is where its callout ("A", "13") is drawn. Such
    entries take the position of their callout. Names come first, callouts
    that were not matched and single letters last; a legend entry without a
    callout keeps no position."""
    legend = {}
    for lb in labels:
        m = LEGEND.match(lb["text"])
        if m:
            legend.setdefault(m.group(1), []).append(lb)
    used, out = set(), []
    for key, entries in legend.items():
        calls = [c for c in labels if c["text"].strip() == key and c.get("at")
                 and not any(_near(c["at"], e.get("at"), 120.0) for e in entries)]
        for e in entries:
            used.add(id(e))
            name = LEGEND.match(e["text"]).group(2).strip()
            if calls:
                for c in calls:
                    used.add(id(c))
                    out.append({"text": f"{name} [{key}]", "at": c["at"]})
            else:
                out.append({"text": f"{name} [{key}]", "at": None})
    rest = [lb for lb in labels if id(lb) not in used]
    rest.sort(key=lambda lb: len(lb["text"].strip()) < 3)
    names = [lb for lb in rest if len(lb["text"].strip()) >= 3]
    return names + [o for o in out if o["at"]] + [o for o in out if not o["at"]] + \
        [lb for lb in rest if len(lb["text"].strip()) < 3]


def digest(sheets, readings, scales) -> str:
    L = []
    for sh in sheets:
        L.append(f"## Sheet {sh['id']}: {sh['title']} ({sh['kind']}) units {sh['units']}"
                 + (f", scale note {sh['scale_text']}" if sh.get("scale_text") else ""))
        if sh.get("summary"):
            L.append(sh["summary"])
        for v in sh["views"]:
            sc, src = scales.get(v["id"], (None, None))
            # without a scale, sizes and positions are given in sheet pixels (f = 1): a size stated in words fixes them
            f, unit = (sc, "mm") if sc else (1.0, "px")
            size = f", view {(v['box'][2] - v['box'][0]) * f:.0f} x {(v['box'][3] - v['box'][1]) * f:.0f} {unit}"
            L.append(f"### View {v['id']} {v['type']} '{v['label']}'" + (f" [{v['level_or_cut']}]" if v.get("level_or_cut") else "")
                     + (f" scale {sc:.4g} mm/px ({src}){size}" if sc else f" (no scale; sizes in sheet pixels){size}"))
            rd = readings.get(v["id"])
            if not rd:
                continue
            if rd["dimensions"]:
                L.append("dims: " + "; ".join(f"{d['text']}={d['mm']:.0f}mm {d['describes']}" if d.get("mm") else
                                              f"{d['text']} {d['describes']}" for d in rd["dimensions"][:40]))
            if rd["levels"]:
                L.append("levels: " + "; ".join(f"{lv['text']}={lv['mm']:.0f}mm {lv['describes']}" if lv.get("mm") is not None
                                                else lv["text"] for lv in rd["levels"][:20]))
            if rd["members"]:
                ms = []
                for m in rd["members"][:40]:
                    ln = ""
                    if sc and m.get("p1") and m.get("p2"):
                        ln = f" {vision.dist(m['p1'], m['p2']) * sc:.0f}mm"
                    ms.append(f"{m['mark']} {m['section']}{ln}".strip())
                L.append("members: " + "; ".join(ms))
            if rd["labels"]:
                lbs = _placed_labels(rd["labels"])[:60]
                b = v["box"]
                L.append(f"labels at (x, u) {unit} - x from the left edge of the view, u up from its bottom edge: " + "; ".join(
                    f"{lb['text']} ({(lb['at'][0] - b[0]) * f:.0f}, {(b[3] - lb['at'][1]) * f:.0f})"
                    if lb.get("at") else lb["text"] for lb in lbs))
            if rd["shapes"]:
                L.append("shapes: " + rd["shapes"][:600])
            if rd["notes"]:
                L.append("notes: " + " | ".join(rd["notes"][:8])[:600])
    text = "\n".join(L)
    return text[:24000]


def contact_sheet(p: Project, sheets, out):
    from PIL import Image, ImageDraw
    thumbs = []
    for sh in sheets:
        im = Image.open(p.dir / "input" / sh["file"]).convert("RGB")
        im.thumbnail((900, 900))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 26], fill=(255, 255, 255))
        d.text((6, 6), f"{sh['id']}: {sh['title'][:70]}", fill=(200, 0, 0))
        for v in sh["views"]:
            f = im.width / Image.open(p.dir / "input" / sh["file"]).width
            b = [c * f for c in v["box"]]
            d.rectangle(b, outline=(0, 90, 220), width=2)
            d.text((b[0] + 3, b[1] + 3), v["id"], fill=(0, 90, 220))
        thumbs.append(im)
    cols = 2 if len(thumbs) > 1 else 1
    rows = math.ceil(len(thumbs) / cols)
    cw = max(t.width for t in thumbs)
    ch = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * cw + (cols - 1) * 10, rows * ch + (rows - 1) * 10), "white")
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * (cw + 10), (i // cols) * (ch + 10)))
    sheet.thumbnail((2000, 2000))
    sheet.save(out)
    return out


# ------------------------------------------------------------------ plan
def make_plan(job, p: Project, sheets, readings, scales, extra) -> dict:
    cs = contact_sheet(p, sheets, p.dir / "assembly" / "contact.png")
    raw = _ask_json(job, [{"role": "system", "content": PA.PLAN_SYSTEM},
                          _user(PA.plan_user(digest(sheets, readings, scales), extra), [cs])], "code", 12000)
    used = set()
    comps = []
    names = set()
    for k, c in enumerate(raw.get("components") or []):
        if not isinstance(c, dict):
            continue
        # the same part listed twice (by name) is modelled once
        words = re.sub(r"[^a-z0-9]+", " ", str(c.get("name") or c.get("id") or "").lower()).split()
        key = " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words)
        if key and key in names:
            job.log(f"  plan: '{c.get('name')}' is listed twice; modelled once.", "warn")
            continue
        names.add(key)
        try:
            mn = [float(x) for x in (c.get("min") or [])[:3]]
            mx = [float(x) for x in (c.get("max") or [])[:3]]
            if len(mn) < 3 or len(mx) < 3:
                raise ValueError
            mn, mx = [min(a, b) for a, b in zip(mn, mx)], [max(a, b) for a, b in zip(mn, mx)]
        except (TypeError, ValueError):
            mn, mx = None, None
        comps.append({"id": _ident(c.get("id") or c.get("name"), used), "name": str(c.get("name") or f"Component {k + 1}"),
                      "kind": str(c.get("kind") or "other"), "views": [str(v).upper() for v in _as_list(c.get("views"))],
                      "min": mn, "max": mx, "description": str(c.get("description") or ""),
                      "color": str(c.get("color") or COLORS[k % len(COLORS)])})
    plan = {"name": re.sub(r"[^\w\- ]+", "", str(raw.get("name") or p.data.get("name") or "assembly"))[:60],
            "datum": str(raw.get("datum") or ""), "overall": raw.get("overall") or {},
            "components": comps[:40], "notes": [str(n) for n in _as_list(raw.get("notes"))][:20]}
    p.write_json("assembly/plan.json", plan)
    job.log(f"Plan: '{plan['name']}', {len(comps)} components. Datum: {plan['datum'][:120]}", "ok")
    return plan


# ------------------------------------------------------------------ components
def _readings_for(comp, readings, scales):
    L = []
    for vid in comp.get("views") or []:
        rd = readings.get(vid)
        if not rd:
            continue
        sc, src = scales.get(vid, (None, None))
        L.append(f"View {vid}" + (f" (scale {sc:.4g} mm/px)" if sc else ""))
        L += [f"  {d['text']} = {d['mm']:.0f} mm: {d['describes']}" if d.get("mm") else f"  {d['text']}: {d['describes']}"
              for d in rd["dimensions"][:40]]
        L += [f"  level {lv['text']} = {lv['mm']:.0f} mm: {lv['describes']}" for lv in rd["levels"][:20] if lv.get("mm") is not None]
        for m in rd["members"][:40]:
            ln = f" length {vision.dist(m['p1'], m['p2']) * sc:.0f} mm" if sc and m.get("p1") and m.get("p2") else ""
            L.append(f"  member {m['mark']} {m['section']}{ln}")
        if rd["shapes"]:
            L.append("  shapes: " + rd["shapes"][:500])
    return "\n".join(L)[:9000] or "(no readings for this component; use the plan description)"


def write_component(job, p: Project, plan, comp, readings, scales, extra, instruction=""):
    imgs = []
    for vid in (comp.get("views") or [])[:2]:
        f = p.dir / "assembly" / "crops" / f"{vid}.png"
        if f.exists():
            imgs.append(f)
    body = PA.component_user(comp, plan, _readings_for(comp, readings, scales), extra)
    if instruction:
        body += "\n\nChange requested by the user for this component:\n" + instruction
    msgs = [{"role": "system", "content": PA.COMPONENT_SYSTEM + "\n\n" + PA.COMPONENT_RULES}, _user(body, imgs)]
    return prompts.extract_code(ask(job, msgs, "code", max_tokens=10000, temperature=0.5))


def build_component(job, p: Project, comp, code):
    d = p.dir / "assembly" / "components" / comp["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.py").write_text(code, encoding="utf-8")
    n = len(list(d.glob("attempt_*.py"))) + 1        # every attempt is kept for the record
    (d / f"attempt_{n}.py").write_text(code, encoding="utf-8")
    r = worker().build(code, d, views=["iso"], hlr=False, step=False, png=False, stop_event=job.stop)
    if r.get("stopped"):
        raise Stopped()
    if not r.get("ok"):
        (d / f"attempt_{n}.error.txt").write_text(f"line {r.get('line')}: {r.get('error')}\n", encoding="utf-8")
    return r


ENVELOPE_FIX = 0.5      # a component further off its planned box than this (fraction of its size) is corrected once
ENVELOPE_REJECT = 1.0   # ... and replaced by its planned box when it is still this far off (or further)


def envelope_check(comp, r):
    if not r.get("ok") or not comp.get("min") or not comp.get("max"):
        return None
    bb = r["metrics"]["bbox"]
    pmn, pmx = comp["min"], comp["max"]
    size = [max(pmx[i] - pmn[i], 1.0) for i in range(3)]
    off = max(max(abs(bb[i] - pmn[i]), abs(bb[i + 3] - pmx[i])) / max(size) for i in range(3))
    return round(off, 3)


def do_component(job, p: Project, plan, comp, readings, scales, extra, instruction=""):
    tries = min(3, int(load_settings().get("repair_attempts", 4)))
    code = write_component(job, p, plan, comp, readings, scales, extra, instruction)
    r = build_component(job, p, comp, code)
    k = 0
    while (not r.get("ok") or r.get("lint")) and k < tries:
        k += 1
        job.log(f"  {comp['id']}: build failed ({(r.get('error') or '; '.join(r.get('lint', [])))[:160]}); correcting ({k}/{tries}).", "warn")
        msgs = [{"role": "system", "content": PA.COMPONENT_SYSTEM + "\n\n" + PA.COMPONENT_RULES},
                {"role": "user", "content": prompts.repair_user(code, r)}]
        new = prompts.extract_code(ask(job, msgs, "repair", max_tokens=8000, temperature=0.4))
        r2 = build_component(job, p, comp, new)
        if r2.get("ok") or not r.get("ok"):
            code, r = new, r2
    # built, but far from its place in the plan: one round to move and size it into the planned box
    off = envelope_check(comp, r)
    if off is not None and off > ENVELOPE_FIX and k < tries:
        k += 1
        bb = r["metrics"]["bbox"]
        job.log(f"  {comp['id']}: built {off * 100:.0f} % off its planned box; correcting the placement.", "warn")
        msgs = [{"role": "system", "content": PA.COMPONENT_SYSTEM + "\n\n" + PA.COMPONENT_RULES},
                {"role": "user", "content": PA.envelope_user(code, comp, bb)}]
        new = prompts.extract_code(ask(job, msgs, "repair", max_tokens=8000, temperature=0.4))
        r2 = build_component(job, p, comp, new)
        off2 = envelope_check(comp, r2)
        if r2.get("ok") and not r2.get("lint") and off2 is not None and off2 < off:
            code, r = new, r2
    st = {"ok": bool(r.get("ok")), "error": r.get("error"), "metrics": r.get("metrics"),
          "envelope_offset": envelope_check(comp, r), "attempts": k + 1}
    if st["ok"] and st["envelope_offset"] is not None and st["envelope_offset"] >= ENVELOPE_REJECT:
        # still far outside its place (a 28 m manifold on a 4 m engine): it would distort the whole
        # assembly; the planned box stands in, the script is kept for Redo
        m = r["metrics"]
        st.update(ok=False, built=True, error=f"built {st['envelope_offset'] * 100:.0f} % outside its planned box "
                                               f"({m['size'][0]:.0f} x {m['size'][1]:.0f} x {m['size'][2]:.0f} mm)")
        job.log(f"  {comp['id']} {comp['name']}: {st['error']}; a placeholder box is used (Redo to try again).", "error")
        return code, st
    if st["ok"]:
        m = r["metrics"]
        job.log(f"  {comp['id']} {comp['name']}: {m['size'][0]:.0f} x {m['size'][1]:.0f} x {m['size'][2]:.0f} mm, "
                f"{m['solids']} solids" + (f", off its planned box by {st['envelope_offset'] * 100:.0f} %"
                                          if st["envelope_offset"] and st["envelope_offset"] > 0.15 else ""), "ok")
    else:
        job.log(f"  {comp['id']} {comp['name']}: could not be built; a placeholder box is used.", "error")
    return code, st


# ------------------------------------------------------------------ the combined script
def combined_script(plan, codes: dict, status: dict) -> str:
    out = ["import cadquery as cq", "import math", "import aicad_lib as lib", "",
           f"# {plan['name']} - assembly of {len(plan['components'])} components", f"# Datum: {plan.get('datum', '')}", ""]
    entries = []
    for c in plan["components"]:
        cid = c["id"]
        code = codes.get(cid) or ""
        ok = status.get(cid, {}).get("ok")
        out.append(f"# {'=' * 66} {c['name']}")
        out.append(f"def build_{cid}():")
        if ok and code:
            body = [ln for ln in code.splitlines()
                    if not re.match(r"\s*(import\s+(cadquery|math|aicad_lib)|from\s+cadquery)\b", ln)]
            body = [ln.replace("# --- PARAMETERS", f"# --- PARAMETERS {cid}") for ln in body]
            out += ["    " + ln if ln.strip() else "" for ln in body]
            if not re.search(r"^\s*result\s*=", code, re.M) and re.search(r"^\s*assembly\s*=", code, re.M):
                out.append("    result = assembly")
            out.append("    return result")
        else:
            mn, mx = c.get("min") or [0, 0, 0], c.get("max") or [100, 100, 100]
            out.append(f"    # PLACEHOLDER: the component could not be modelled; its planned bounding box is shown")
            out.append(f"    return lib.box({mn[0]:.1f}, {mn[1]:.1f}, {mn[2]:.1f}, {mx[0]:.1f}, {mx[1]:.1f}, {mx[2]:.1f})")
        out.append("")
        color = c.get("color") if ok else "red"
        entries.append(f"    ({cid!r}, {c['name']!r}, build_{cid}, {color!r}),")
    out.append("COMPONENTS = [")
    out += entries
    out.append("]")
    out.append(f"assembly = lib.assemble({plan['name']!r}, COMPONENTS)")
    return "\n".join(out) + "\n"


def assemble_version(job, p: Project, plan, codes, status, note):
    code = combined_script(plan, codes, status)
    p.write_json("assembly/status.json", status)
    job.set("Building the assembly", 0.9)
    vid, r = build_version(job, p, code, "ai-assembly", note)
    return vid, r


# ------------------------------------------------------------------ jobs
def _load(p: Project):
    sheets = p.read_json("assembly/sheets.json") or []
    readings = p.read_json("assembly/readings.json") or {}
    scales = {k: tuple(v) for k, v in (p.read_json("assembly/scales.json") or {}).items()}
    return sheets, readings, scales


def job_generate_assembly(job, pid: str, text: str = "", pages=None, reread=True):
    p = Project(pid)
    if not p.data.get("pages"):
        raise RuntimeError("Import the drawing sheets first.")
    p.data["mode"] = "assembly"
    p.data["request"] = text
    p.save()
    ensure_engine(job, need_vision=True)
    idxs = list(range(len(p.data["pages"]))) if not pages else [int(i) for i in pages]
    sheets, readings, scales = _load(p)
    if reread or not sheets:
        # ---- survey
        sheets = []
        for n, i in enumerate(idxs):
            job.check()
            job.set(f"Surveying sheet {n + 1} of {len(idxs)}", 0.02 + 0.13 * n / max(len(idxs), 1))
            sheets.append(survey_page(job, p, i))
            p.write_json("assembly/sheets.json", sheets)
        # ---- read views (largest first, capped)
        todo = []
        for sh in sheets:
            vs = sorted(sh["views"], key=lambda v: -(v["box"][2] - v["box"][0]) * (v["box"][3] - v["box"][1]))
            todo += [(sh, v) for v in vs[:MAX_VIEWS_PER_SHEET] if v["type"] not in ("isometric",)]
        todo = todo[:MAX_VIEWS]
        readings = {}
        for n, (sh, v) in enumerate(todo):
            job.check()
            job.set(f"Reading view {n + 1} of {len(todo)} ({v['id']})", 0.15 + 0.3 * n / max(len(todo), 1))
            try:
                readings[v["id"]] = read_view(job, p, sh, v)
            except Exception as e:  # one unreadable view does not stop the set
                job.log(f"  {v['id']}: could not be read ({e}).", "warn")
            p.write_json("assembly/readings.json", readings)
        # ---- scales
        scales = {}
        calib = p.data.get("calib") or {}
        for sh in sheets:
            for vid, (sc, src) in sheet_scales(sh, readings, calib.get(sh["file"])).items():
                scales[vid] = (sc, src)
                if sc:
                    job.log(f"  scale {vid}: {sc:.4g} mm/px from the {src}.")
        p.write_json("assembly/scales.json", {k: list(v) for k, v in scales.items()})
    job.check()
    job.set("Planning the components", 0.47)
    plan = make_plan(job, p, sheets, readings, scales, text)
    if not plan["components"]:
        raise RuntimeError("The plan has no components; see the AI output.")
    codes, status = {}, {}
    nC = len(plan["components"])
    for n, comp in enumerate(plan["components"]):
        job.check()
        job.set(f"Modelling component {n + 1} of {nC}: {comp['name']}", 0.5 + 0.38 * n / nC)
        try:
            codes[comp["id"]], status[comp["id"]] = do_component(job, p, plan, comp, readings, scales, text)
        except Stopped:
            raise
        except Exception as e:
            status[comp["id"]] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            job.log(f"  {comp['id']}: {e}", "error")
        p.write_json("assembly/codes.json", codes)
        p.write_json("assembly/status.json", status)
    vid, r = assemble_version(job, p, plan, codes, status, f"assembly of {nC} components")
    p.data["current"] = vid
    p.save()
    nok = sum(1 for s in status.values() if s.get("ok"))
    job.result.update(version=vid, ok=bool(r.get("ok")))
    job.log(f"Finished: {vid}, {nok} of {nC} components modelled"
            + (f", {nC - nok} shown as red placeholder boxes" if nok < nC else "") + ".", "ok" if r.get("ok") else "error")


def job_component(job, pid: str, cid: str, instruction: str = ""):
    """Redo one component (optionally with an instruction) and rebuild the assembly."""
    p = Project(pid)
    plan = p.read_json("assembly/plan.json")
    if not plan:
        raise RuntimeError("This project has no assembly plan.")
    comp = next((c for c in plan["components"] if c["id"] == cid), None)
    if not comp:
        raise RuntimeError(f"Unknown component {cid}.")
    ensure_engine(job, need_vision=True)
    sheets, readings, scales = _load(p)
    codes = p.read_json("assembly/codes.json") or {}
    status = p.read_json("assembly/status.json") or {}
    job.set(f"Modelling {comp['name']} again", 0.2)
    codes[cid], status[cid] = do_component(job, p, plan, comp, readings, scales, p.data.get("request", ""), instruction)
    p.write_json("assembly/codes.json", codes)
    vid, r = assemble_version(job, p, plan, codes, status, f"{comp['name']} redone" + (f": {instruction[:60]}" if instruction else ""))
    p.data["current"] = vid
    p.save()
    job.result.update(version=vid, ok=bool(r.get("ok")))


def job_replan(job, pid: str, text: str = ""):
    """Plan and model again from the stored readings (after the user corrected them)."""
    job_generate_assembly(job, pid, text, reread=False)
