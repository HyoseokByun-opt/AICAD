"""The part specification read from a drawing, and missing sizes from ratio.

The AI returns a specification (views, dimensions, features, estimates);
this module turns it into the table of values the model is built from.
Every value carries its provenance:

    drawing      written on the drawing (read by the AI or exact from a vector file)
    ratio        measured on the sheet and scaled by a known dimension
    user         entered or calibrated by the user
    description  stated in the written request
    assumed      neither written nor measurable; a reasonable default

Scale (mm per pixel) comes from, in this order: a calibration by the user,
the exact scale of a DXF, the known overall dimensions against the view
boxes (median over views), or the drawing scale of the title block applied
to the paper size of a PDF.
"""
from __future__ import annotations

import json
import re
import statistics

from .cadexec import VIEW_AXES
from . import vision

ORTHO = set(VIEW_AXES)


# ------------------------------------------------------------------ JSON
def parse_json(text: str):
    """The first JSON object in an AI answer, tolerating code fences,
    comments and trailing commas."""
    if not text:
        raise ValueError("empty answer")
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in the answer")
    depth, end, ins, esc = 0, None, False, False
    for i in range(start, len(t)):
        c = t[i]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
            continue
        if c == '"':
            ins = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    s = t[start:end] if end else t[start:]
    try:
        return json.loads(s)
    except ValueError:
        pass
    s2 = re.sub(r"//[^\n]*", "", s)
    s2 = re.sub(r",\s*([}\]])", r"\1", s2)
    if end is None:  # cut off: close what is open
        s2 = s2.rstrip().rstrip(",")
        s2 += "]" * max(0, s2.count("[") - s2.count("]"))
        s2 += "}" * max(0, s2.count("{") - s2.count("}"))
    return json.loads(s2)


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def normalize(spec: dict) -> dict:
    """Coerce the AI's answer into the expected shape (missing keys filled)."""
    s = dict(spec or {})
    s.setdefault("part_name", "part")
    s["part_name"] = re.sub(r"[^\w\- ]+", "", str(s.get("part_name") or "part"))[:60] or "part"
    s.setdefault("summary", "")
    s["units"] = "inch" if str(s.get("units", "mm")).lower().startswith("in") else "mm"
    ov = s.get("overall") or {}
    s["overall"] = {a: _num(ov.get(a)) for a in ("x", "y", "z")}
    views = []
    for i, v in enumerate(s.get("views") or []):
        if not isinstance(v, dict):
            continue
        t = str(v.get("type", "other")).lower().split()[0] if v.get("type") else "other"
        t = {"side": "right", "plan": "top", "elevation": "front", "back": "rear"}.get(t, t)
        box = v.get("box") or v.get("bbox")
        if isinstance(box, (list, tuple)) and len(box) >= 4 and all(_num(b) is not None for b in box[:4]):
            box = [_num(b) for b in box[:4]]
        else:
            box = None
        views.append({"id": str(v.get("id") or f"V{i + 1}"), "type": t, "box": box, "label": v.get("label", ""),
                      "fixed": bool(v.get("fixed"))})
    s["views"] = views
    dims = []
    for i, d in enumerate(s.get("dimensions") or []):
        if not isinstance(d, dict):
            continue
        val = _num(d.get("value"))
        if val is None:
            continue
        ax = str(d.get("axis") or "").lower()
        dims.append({"id": str(d.get("id") or f"D{i + 1}"), "name": _ident(d.get("name") or f"d{i + 1}"),
                     "value": val, "type": str(d.get("type") or "length").lower(),
                     "axis": ax if ax in ("x", "y", "z") else None, "view": d.get("view"),
                     "text": str(d.get("text") or ""), "describes": str(d.get("describes") or "")})
    s["dimensions"] = dims
    ests = []
    for i, e in enumerate(s.get("estimates") or []):
        if not isinstance(e, dict):
            continue
        p1, p2 = e.get("p1"), e.get("p2")
        ok = all(isinstance(p, (list, tuple)) and len(p) >= 2 and _num(p[0]) is not None and _num(p[1]) is not None
                 for p in (p1, p2))
        ax = str(e.get("axis") or "").lower()
        ests.append({"id": str(e.get("id") or f"E{i + 1}"), "name": _ident(e.get("name") or f"e{i + 1}"),
                     "describes": str(e.get("describes") or ""), "view": e.get("view"),
                     "p1": [_num(p1[0]), _num(p1[1])] if ok else None,
                     "p2": [_num(p2[0]), _num(p2[1])] if ok else None,
                     "axis": ax if ax in ("x", "y", "z") else None,
                     "guess": _num(e.get("guess"))})
    s["estimates"] = ests
    s["features"] = [f for f in (s.get("features") or []) if isinstance(f, dict)]
    s["notes"] = [str(n) for n in (s.get("notes") or [])][:30]
    s["questions"] = [str(q) for q in (s.get("questions") or [])][:10]
    return s


def _ident(name) -> str:
    n = re.sub(r"\W+", "_", str(name).strip().lower()).strip("_") or "value"
    return ("v_" + n) if n[0].isdigit() else n[:40]


# ------------------------------------------------------------------ scale
def _title_scale(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", str(text or ""))
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    return b / a if a > 0 and b > 0 else None   # real mm per paper mm


def resolve(spec: dict, page: dict | None, page_path=None, calib: dict | None = None) -> dict:
    """Values to build from, with provenance, plus the scale that was used."""
    s = normalize(spec)
    unit_f = 25.4 if s["units"] == "inch" else 1.0
    out = {"units": "mm", "unit_factor": unit_f, "views": [], "values": [], "warnings": [],
           "scale": {"mm_per_px": None, "source": None, "candidates": []}}
    W = (page or {}).get("w") or 1
    H = (page or {}).get("h") or 1
    gray = None
    if page_path is not None:
        try:
            gray = vision.load_gray(page_path)
        except Exception:
            gray = None

    ov = {a: (s["overall"][a] * unit_f if s["overall"][a] else None) for a in "xyz"}
    # overall extents also appear as dimensions along an axis
    for d in s["dimensions"]:
        if d["axis"] and d["type"] == "length" and "overall" in (d["name"] + d["describes"]).lower():
            if ov[d["axis"]] is None:
                ov[d["axis"]] = d["value"] * unit_f

    # --- views: boxes in pixels, snapped to the ink (boxes set by the user stay)
    vlist = [v for v in s["views"] if v["box"]]
    pxb = [vision.norm_box_to_px(v["box"], W, H) for v in vlist]
    free = [i for i, v in enumerate(vlist) if not v.get("fixed")]
    snapped = list(pxb)
    how = ["user" if v.get("fixed") else "ai" for v in vlist]
    if gray is not None and free:
        sb, hw = vision.snap_boxes(gray, [pxb[i] for i in free])
        for i, b, h in zip(free, sb, hw):
            snapped[i], how[i] = b, h
        # a box that lies on no outline: look for the outline of the size the
        # other views predict (front and top share the width, front and side
        # the height, at the scale found so far)
        miss = [i for i in free if how[i] == "ai" and VIEW_AXES.get(vlist[i]["type"])]
        c, meas = [], {"x": [], "y": [], "z": []}
        for i, v in enumerate(vlist):
            ax = VIEW_AXES.get(v["type"])
            if ax and how[i] in ("snap", "user"):
                for k, a in enumerate(ax):
                    size = snapped[i][2 + k] - snapped[i][k]
                    if size > 20:
                        meas[a].append(size)
                        if ov[a]:
                            c.append(ov[a] / size)
        if miss and (c or any(meas.values())):
            sc = statistics.median(c) if c else None

            def expected(axes):
                # an axis already measured in another view has the same length
                # in pixels here (projection alignment); only otherwise the
                # written size at the scale found so far is used
                e = [statistics.median(meas[a]) if meas[a] else None for a in axes]
                if all(x is None for x in e) and sc:
                    e = [ov[a] / sc if ov[a] else None for a in axes]
                return tuple(e)
            exp = [expected(VIEW_AXES[vlist[i]["type"]]) if i in miss else None for i in free]
            sb, hw = vision.snap_boxes(gray, [snapped[i] for i in free], expect=exp)
            for i, b, h in zip(free, sb, hw):
                if how[i] == "ai" and h == "size":
                    snapped[i], how[i] = b, "size"
                    out["warnings"].append(
                        f"View {vlist[i]['id']} ({vlist[i]['type']}): the box given by the AI lies on no outline; "
                        "the outline of the expected size nearby was used. Check it on the Drawing tab.")
    for v, bpx, sb, h in zip(vlist, pxb, snapped, how):
        rv = {"id": v["id"], "type": v["type"], "label": v["label"], "box_ai": [round(float(c), 1) for c in bpx],
              "box": [round(float(c), 1) for c in sb], "axes": VIEW_AXES.get(v["type"]), "fixed": bool(v.get("fixed")),
              "how": h}
        rv["size_px"] = [round(rv["box"][2] - rv["box"][0], 1), round(rv["box"][3] - rv["box"][1], 1)]
        out["views"].append(rv)

    # --- scale candidates
    cands = []
    if calib and calib.get("mm_per_px"):
        out["scale"].update(mm_per_px=float(calib["mm_per_px"]), source="user calibration")
    elif page and page.get("kind") == "dxf" and page.get("dxf_scale"):
        f = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}.get(page.get("units") or "mm", 1.0)
        out["scale"].update(mm_per_px=f / page["dxf_scale"]["s"], source="DXF model space (1:1)")
    per_view = {}
    for rv in out["views"]:
        if not rv["axes"]:
            continue
        for k, a in enumerate(rv["axes"]):
            if ov[a] and rv["size_px"][k] > 20:
                c = ov[a] / rv["size_px"][k]
                cands.append(c)
                per_view.setdefault(rv["id"], []).append(c)
                out["scale"]["candidates"].append({"view": rv["id"], "axis": a, "mm_per_px": round(c, 6)})
    if out["scale"]["mm_per_px"] is None and cands:
        out["scale"].update(mm_per_px=statistics.median(cands), source="overall dimensions vs. view size")
        if len(cands) > 1:
            spread = (max(cands) - min(cands)) / statistics.median(cands)
            out["scale"]["spread"] = round(spread, 4)
            if spread > 0.08:
                out["warnings"].append(
                    f"The views give scales that differ by {spread * 100:.0f} %: the drawing may not be to scale, "
                    "a view box may be off, or a dimension was misread. Check the views on the Drawing tab.")
    if out["scale"]["mm_per_px"] is None and page and page.get("paper_mm"):
        k = _title_scale(s.get("drawing_scale"))
        if k:
            out["scale"].update(mm_per_px=page["paper_mm"][0] / W * k,
                                source=f"title block scale {s.get('drawing_scale')} on the PDF paper size")
    mmpx = out["scale"]["mm_per_px"]

    def view_scale(vid):
        c = per_view.get(vid)
        if c and out["scale"]["source"] == "overall dimensions vs. view size":
            return statistics.median(c)
        return mmpx

    values = []

    def add(name, value, source, ref, describes, unit="mm"):
        values.append({"name": name, "value": round(float(value), 4), "unit": unit, "source": source,
                       "ref": ref, "describes": describes})

    # --- overall extents
    for a in "xyz":
        if ov[a]:
            add(f"overall_{a}", ov[a], "drawing", "dimension", f"overall size along {a.upper()}")
            continue
        best = None
        for rv in out["views"]:
            if rv["axes"] and a in rv["axes"]:
                k = rv["axes"].index(a)
                sc = view_scale(rv["id"])
                if sc and (best is None or rv["size_px"][k] > best[0]):
                    best = (rv["size_px"][k], rv["size_px"][k] * sc, rv["id"])
        if best:
            add(f"overall_{a}", best[1], "ratio", f"view {best[2]}", f"overall size along {a.upper()} measured on the sheet")
    # --- written dimensions
    for d in s["dimensions"]:
        unit = "deg" if d["type"] == "angle" else ("count" if d["type"] == "count" else "mm")
        f = unit_f if unit == "mm" else 1.0
        add(d["name"], d["value"] * f, "drawing", d["id"] + (f" '{d['text']}'" if d["text"] else ""), d["describes"], unit)
    # --- sizes measured on the sheet
    vid_map = {rv["id"]: rv for rv in out["views"]}
    for e in s["estimates"]:
        rv = vid_map.get(str(e["view"])) if e["view"] is not None else None
        sc = view_scale(rv["id"]) if rv else mmpx
        if e["p1"] and e["p2"] and sc:
            p1 = [e["p1"][0] / 1000 * W, e["p1"][1] / 1000 * H]
            p2 = [e["p2"][0] / 1000 * W, e["p2"][1] / 1000 * H]
            dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
            L = vision.dist(p1, p2)
            if rv and rv["axes"] and e["axis"] in rv["axes"]:
                L = dx if rv["axes"].index(e["axis"]) == 0 else dy
            add(e["name"], L * sc, "ratio", e["id"] + (f" in {rv['id']}" if rv else ""), e["describes"])
            values[-1]["p1"], values[-1]["p2"] = [round(c, 1) for c in p1], [round(c, 1) for c in p2]
        elif e.get("guess"):
            add(e["name"], e["guess"] * unit_f, "assumed", e["id"], e["describes"] + " (AI estimate, no scale)")
    # --- cross-check written overall sizes against the sheet
    if mmpx:
        for a in "xyz":
            if not ov[a]:
                continue
            for rv in out["views"]:
                if rv["axes"] and a in rv["axes"]:
                    k = rv["axes"].index(a)
                    meas = rv["size_px"][k] * mmpx
                    if meas > 0 and abs(meas / ov[a] - 1) > 0.12:
                        out["warnings"].append(
                            f"View {rv['id']} ({rv['type']}) measures {meas:.1f} mm along {a.upper()} at the common scale, "
                            f"but the drawing states {ov[a]:g} mm.")
    if not mmpx and s["views"]:
        out["warnings"].append("No scale could be found (no overall dimension, calibration or title-block scale): "
                               "sizes that are not written on the drawing are assumed. Use Calibrate on the Drawing tab.")
    out["values"] = values
    out["overall"] = {a: next((v["value"] for v in values if v["name"] == f"overall_{a}"), None) for a in "xyz"}
    out["spec"] = s
    return out


def values_table(resolved: dict) -> str:
    """The values as a plain table for the prompt."""
    rows = ["name | value | unit | source | meaning", "--- | --- | --- | --- | ---"]
    for v in resolved.get("values", []):
        rows.append(f"{v['name']} | {v['value']:g} | {v['unit']} | {v['source']} | {v['describes']}")
    return "\n".join(rows)
