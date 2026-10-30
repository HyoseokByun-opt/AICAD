"""Graphic scale bars, measured instead of guessed.

A model's pixel coordinates are not precise enough to measure a scale bar
(a factor of nine was observed). Here the bar is found by image analysis
near the place the AI pointed at - a scale bar is one connected, long and
flat piece of line work - and its length in pixels is measured exactly.
The AI is then shown the bar outlined in red, enlarged, and asks only for
the length the whole bar stands for. With two bars (feet and metres) the
two scales are cross-checked.
"""
from __future__ import annotations

import numpy as np

from . import vision


def find_bars(crop_path):
    """Long, flat connected line work in an image: candidate scale bars as
    (x0, y0, x1, y1) in image pixels, longest first."""
    import cv2
    g = vision.load_gray(crop_path)
    m = cv2.dilate(vision.ink(g), np.ones((3, 3), np.uint8), iterations=1)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    H, W = g.shape
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w >= 0.08 * W and w >= 4 * h and h >= 3 and a >= 0.02 * w * h:
            comp = lab[y:y + h, x:x + w] == i
            # a scale bar has several vertical strokes (ticks, box edges) across its
            # height; a dimension line has at most its two ends
            cov = comp.mean(axis=0) >= 0.6
            strokes = int(np.count_nonzero(np.diff(cov.astype(np.int8)) == 1) + (1 if cov[0] else 0))
            if strokes >= 2:
                out.append([int(x) + 1, int(y), int(x + w) - 1, int(y + h), strokes])
    # a faint print breaks a bar into pieces: join pieces on the same height
    # that nearly touch
    out.sort(key=lambda b: b[0])
    merged = []
    for b in out:
        for m in merged:
            ov = min(m[3], b[3]) - max(m[1], b[1])
            gap = b[0] - m[2]
            if ov >= 0.5 * min(m[3] - m[1], b[3] - b[1]) and -5 <= gap <= max(12, 0.04 * W):
                m[2], m[1], m[3], m[4] = max(m[2], b[2]), min(m[1], b[1]), max(m[3], b[3]), m[4] + b[4]
                break
        else:
            merged.append(list(b))
    bars = [tuple(m[:4]) for m in merged if m[4] >= 3 and (m[2] - m[0]) >= 4 * (m[3] - m[1])]
    bars.sort(key=lambda b: -(b[2] - b[0]))
    return bars


def _mark(src, dst, box):
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    pad = 6
    d.rectangle([box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad], outline=(230, 0, 0), width=4)
    im.save(dst)
    return dst


ASK = ("The image shows a graphic scale bar of an engineering drawing; the bar in question is outlined in red. "
       "Read its labels and answer with ONE JSON object: {\"length\": the length the WHOLE outlined bar stands for, "
       "from its left end to its right end (labels 0 1 2 3 4 5 10 -> 10; 10 0 10 20 30 -> 40), \"unit\": \"ft\", \"m\", "
       "\"mm\" or \"in\", \"labels\": the labels as written}.")


def refine(job, ask_fn, input_dir, page, workdir, p1, p2, ai_length_mm=None, tag="bar"):
    """Measure a scale bar near the AI's points p1, p2 (page pixels).
    Returns {p1, p2, length_mm, mm_per_px, how} or None."""
    from . import units
    from .spec import parse_json
    W, H = page["w"], page["h"]
    workdir.mkdir(parents=True, exist_ok=True)
    L0 = max(vision.dist(p1, p2), 0.02 * W)
    cx, cy = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    # the AI's points can be off by several bar lengths: look in a wide area,
    # and wider still when nothing bar-like is found
    for grow in (1.0, 2.2):
        hx, hy = max(1.6 * L0, 0.10 * W) * grow, max(1.0 * L0, 0.07 * H) * grow
        region = [max(0, cx - hx), max(0, cy - hy), min(W, cx + hx), min(H, cy + hy)]
        # at least the page's own resolution, so thin bar lines stay connected
        side = int(min(4000, max(1600, max(region[2] - region[0], region[3] - region[1]) / 0.7)))
        crop = vision.zoom_crop(input_dir, page, region, workdir / f"{tag}_region.png", max_side=side, pad=0)
        bars = find_bars(crop["path"])
        if bars:
            break
    if not bars:
        return None
    k = crop["page_per_px"]
    oy = (cy - crop["origin"][1]) / k
    best = min(bars[:4], key=lambda b: abs((b[1] + b[3]) / 2 - oy) - 0.15 * (b[2] - b[0]))
    cw = crop["size"][0]
    if best[0] <= 3 or best[2] >= cw - 4:
        # the bar runs out of the area: look again around the bar itself
        bx0, bx1 = crop["origin"][0] + best[0] * k, crop["origin"][0] + best[2] * k
        by = crop["origin"][1] + (best[1] + best[3]) / 2 * k
        span = max(bx1 - bx0, 0.05 * W)
        region = [max(0, bx0 - 1.5 * span), max(0, by - 0.6 * span), min(W, bx1 + 1.5 * span), min(H, by + 0.6 * span)]
        side = int(min(4000, max(1600, (region[2] - region[0]) / 0.7)))
        crop = vision.zoom_crop(input_dir, page, region, workdir / f"{tag}_region.png", max_side=side, pad=0)
        again = find_bars(crop["path"])
        if again:
            k = crop["page_per_px"]
            ty = (by - crop["origin"][1]) / k
            best = min(again[:4], key=lambda b: abs((b[1] + b[3]) / 2 - ty) - 0.15 * (b[2] - b[0]))
    q1 = [crop["origin"][0] + best[0] * k, crop["origin"][1] + (best[1] + best[3]) / 2 * k]
    q2 = [crop["origin"][0] + best[2] * k, q1[1]]
    px = vision.dist(q1, q2)
    length = None
    how = "measured bar, length from the AI's survey"
    if ask_fn is not None:
        try:
            marked = _mark(crop["path"], workdir / f"{tag}_marked.png", best)
            from .llm import image_part
            raw = parse_json(ask_fn(job, [{"role": "user", "content": [{"type": "text", "text": ASK}, image_part(marked)]}],
                                    "repair", 600))
            u = str(raw.get("unit") or "").lower()
            sym = {"ft": "'", "feet": "'", "in": '"', "inch": '"'}.get(u, " " + u)
            length = units.parse_length(f"{raw.get('length')}{sym}", "mm")
            how = "measured bar, length read from its labels"
        except Exception:
            length = None
    if not length:
        length = ai_length_mm
    if not length or px < 10:
        return None
    return {"p1": [round(c, 1) for c in q1], "p2": [round(c, 1) for c in q2], "length_mm": float(length),
            "mm_per_px": float(length) / px, "how": how}
