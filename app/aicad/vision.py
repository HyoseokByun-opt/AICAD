"""Pixel work on drawings: view boxes, silhouettes and comparison images.

None of this needs the AI. The AI proposes where each view lies on the
sheet; the box is then snapped to the ink of the drawing, the filled
outline of the view is compared with the outline of the model seen from the
same side, and the pairs are composed into one image for the refinement
step.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def load_gray(path) -> np.ndarray:
    import cv2
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cannot read {path}")
    return img


def ink(gray: np.ndarray) -> np.ndarray:
    """Line work as a binary mask. A clean sheet takes a global (Otsu)
    threshold; a photographed or stained print, whose paper is not evenly lit,
    takes a local threshold against the surrounding paper instead."""
    import cv2
    _, m = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    frac = (m > 0).mean()
    small = cv2.resize(gray, (max(8, gray.shape[1] // 16), max(8, gray.shape[0] // 16)), interpolation=cv2.INTER_AREA)
    bg = cv2.medianBlur(small, 9 if min(small.shape) > 9 else 3)
    uneven = float(np.percentile(bg, 90) - np.percentile(bg, 10)) > 40
    if frac > 0.25 or uneven:
        blk = max(15, (min(gray.shape) // 40) | 1)
        m = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, blk, 18)
        # specks of paper texture are not lines
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    elif frac > 0.5:
        _, m = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
    return m


def zoom_crop(input_dir, page: dict, box, out, max_side=2048, pad=0.03):
    """A region of a page at the best resolution available.

    The page image is reduced for display; this crop comes from the original
    file (a re-render of the PDF page, or the full-resolution scan), so small
    dimension text on a large sheet becomes legible for the AI."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None
    W, H = page["w"], page["h"]
    x0, y0, x1, y1 = box
    px, py = (x1 - x0) * pad + 4, (y1 - y0) * pad + 4
    x0, y0, x1, y1 = max(0, x0 - px), max(0, y0 - py), min(W, x1 + px), min(H, y1 + py)
    o = page.get("orig") or {}
    src = Path(input_dir) / o["file"] if o.get("file") else None
    img = None
    try:
        if src is not None and src.exists() and "pdf_page" in o:
            import pypdfium2 as pdfium
            pw, ph = o["pt"]
            l, t, r, b = x0 / W * pw, y0 / H * ph, x1 / W * pw, y1 / H * ph
            scale = min(8.0, max(1.0, max_side / max(r - l, b - t)))
            pg = pdfium.PdfDocument(str(src))[o["pdf_page"]]
            img = pg.render(scale=scale, crop=(l, ph - b, pw - r, t), fill_color=(255, 255, 255, 255)).to_pil()
        elif src is not None and src.exists() and o.get("w"):
            im = Image.open(src)
            if o.get("frame"):
                im.seek(o["frame"])
            f = o["w"] / W
            img = im.crop((int(x0 * f), int(y0 * f), int(x1 * f), int(y1 * f)))
            if img.mode == "1":
                img = img.convert("L")
    except Exception:
        img = None
    if img is None:     # no original (DXF, old projects): the page image itself
        img = Image.open(Path(input_dir) / page["file"]).crop((int(x0), int(y0), int(x1), int(y1)))
    img = img.convert("RGB")
    if max(img.size) > max_side:
        s = max_side / max(img.size)
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=0.5)
    img.save(out)
    # page px per crop px, and the crop's origin on the page, to map points back
    return {"path": str(out), "origin": [x0, y0], "page_per_px": (x1 - x0) / img.width, "size": list(img.size)}


def norm_box_to_px(box, W, H):
    x0, y0, x1, y1 = [float(v) for v in box[:4]]
    if max(x0, y0, x1, y1) <= 1.0001:      # 0-1 fractions
        f = 1.0
    else:                                    # 0-1000 (the convention asked of the AI)
        f = 1000.0
    a = [x0 / f * W, y0 / f * H, x1 / f * W, y1 / f * H]
    return [min(a[0], a[2]), min(a[1], a[3]), max(a[0], a[2]), max(a[1], a[3])]


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def _outline(gray, lab, stats, i):
    """Box of component i as an outline: filled, opened to strip leaders and
    centre lines that touch it, at the centre of the stroke. Also returns
    the filled share of the box (low for dimension lines and text)."""
    import cv2
    cx, cy, cw, ch = (int(v) for v in stats[i][:4])
    k = max(3, int(0.02 * min(cw, ch))) | 1
    # a zero margin: erosion treats the image border as ink otherwise,
    # and a leader running along the border would survive the opening
    comp = cv2.copyMakeBorder((lab[cy:cy + ch, cx:cx + cw] == i).astype(np.uint8) * 255,
                              k, k, k, k, cv2.BORDER_CONSTANT, value=0)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fill = np.zeros_like(comp)
    cv2.drawContours(fill, cnts, -1, 255, thickness=-1)
    opened = cv2.morphologyEx(fill, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    ys, xs = np.nonzero(opened)
    filled = len(xs) / float(max(cw * ch, 1))
    if filled < 0.05:                      # open outline: no filled area
        bx = (0, 0, cw - 1, ch - 1)
    else:
        bx = (xs.min() - k, ys.min() - k, xs.max() - k, ys.max() - k)
    # the dilation thickened the lines by one pixel on each side; a drawn
    # line stands for the edge at its centre, so half the stroke width of
    # the outline comes off as well (width = 2 x area / contour length)
    raw = cv2.bitwise_and(ink(gray[cy:cy + ch, cx:cx + cw]), (lab[cy:cy + ch, cx:cx + cw] == i).astype(np.uint8) * 255)
    cl, _ = cv2.findContours(raw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    per = sum(cv2.arcLength(c, True) for c in cl)
    half = min(4.0, max(0.0, (2.0 * np.count_nonzero(raw) / per if per else 0.0) / 2.0 - 0.5))
    sh = 1 + half
    return [float(bx[0] + cx + sh), float(bx[1] + cy + sh), float(bx[2] + cx - sh), float(bx[3] + cy - sh)], filled


def snap_boxes(gray, boxes, expect=None):
    """Snap rough view boxes to the outlines of the objects drawn there.

    The AI's boxes may be offset or loose. Among the connected linework of
    the sheet, the component that overlaps a box best is taken as that
    view's outline (each component serves one view only). Dimension lines
    (separated from the outline by the usual gap) and text are not part of
    it. A box that overlaps no outline is matched by size instead when the
    expected size in pixels is known (`expect`: (w, h) per box, either may
    be None): the outline whose size agrees within 12 % and lies nearest is
    taken. Otherwise the box is kept as given.

    Returns (boxes, how) with how = "snap" | "size" | "ai" per box."""
    import cv2
    if not boxes:
        return [], []
    H, W = gray.shape
    m = cv2.dilate(ink(gray), np.ones((3, 3), np.uint8), iterations=1)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    pairs = []
    for bi, (x0, y0, x1, y1) in enumerate(boxes):
        bw, bh = max(x1 - x0, 2), max(y1 - y0, 2)
        for i in range(1, n):
            cx, cy, cw, ch, _a = stats[i]
            if max(cw, ch) < 0.3 * min(bw, bh) or cw * ch > 4 * bw * bh:
                continue   # specks, text, or the sheet border / title block
            j = _iou((cx, cy, cx + cw, cy + ch), (x0, y0, x1, y1))
            if j > 0.2:
                pairs.append((j, bi, i))
    pairs.sort(reverse=True)
    chosen, used = {}, set()
    for j, bi, i in pairs:
        if bi not in chosen and i not in used:
            chosen[bi] = i
            used.add(i)
    out, how = [], []
    for bi, box in enumerate(boxes):
        i = chosen.get(bi)
        if i is None:
            out.append([float(c) for c in box])
            how.append("ai")
        else:
            out.append(_outline(gray, lab, stats, i)[0])
            how.append("snap")
    # --- boxes that missed: match an outline of the expected size
    if expect:
        cand = None
        for bi in range(len(boxes)):
            if how[bi] != "ai" or not expect[bi] or all(e is None for e in expect[bi]):
                continue
            if cand is None:
                cand = []
                for i in range(1, n):
                    cx, cy, cw, ch, _a = stats[i]
                    if i in used or max(cw, ch) < 0.03 * min(W, H) or cw * ch > 0.3 * W * H:
                        continue
                    b, filled = _outline(gray, lab, stats, i)
                    if filled >= 0.15:
                        cand.append((i, b))
            ew, eh = expect[bi]
            bx0, by0, bx1, by1 = boxes[bi]
            best = None
            for i, b in cand:
                if i in used:
                    continue
                errs = []
                if ew:
                    errs.append(abs((b[2] - b[0]) / ew - 1))
                if eh:
                    errs.append(abs((b[3] - b[1]) / eh - 1))
                err = max(errs)
                if err > 0.12:
                    continue
                d = dist(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), ((bx0 + bx1) / 2, (by0 + by1) / 2))
                key = (round(err / 0.03), d)      # size first (in 3 % steps), then distance
                if best is None or key < best[0]:
                    best = (key, i, b)
            if best:
                used.add(best[1])
                out[bi], how[bi] = best[2], "size"
    return out, how


def snap_box(gray, box):
    return snap_boxes(gray, [box])[0][0]


def drawing_silhouette(gray, box):
    """Filled outline of one view of the drawing (bool mask cropped to it)."""
    import cv2
    H, W = gray.shape
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0 - 2), max(0, y0 - 2)
    x1, y1 = min(W, x1 + 2), min(H, y1 + 2)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    m = ink(gray[y0:y1, x0:x1])
    s = min(m.shape)
    k = max(3, int(s * 0.012)) | 1
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fill = np.zeros_like(m)
    area_min = 0.01 * m.shape[0] * m.shape[1]
    for c in cnts:
        if cv2.contourArea(c) >= area_min:
            cv2.drawContours(fill, [c], -1, 255, thickness=-1)
    k2 = max(3, int(s * 0.025)) | 1
    fill = cv2.morphologyEx(fill, cv2.MORPH_OPEN, np.ones((k2, k2), np.uint8))
    ys, xs = np.nonzero(fill)
    if len(xs) < 20:
        return None
    return fill[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0


def model_silhouette(path):
    """Outer outline of a model view, filled: through holes are closed as
    they are in the drawing outline, so the comparison is of the outer shape."""
    import cv2
    g = (load_gray(path) > 127).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(g, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fill = np.zeros_like(g)
    cv2.drawContours(fill, cnts, -1, 255, thickness=-1)
    ys, xs = np.nonzero(fill)
    if len(xs) < 4:
        return None
    return fill[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0


def _norm(mask, n=128):
    import cv2
    return cv2.resize(mask.astype(np.uint8) * 255, (n, n), interpolation=cv2.INTER_AREA) > 127


def compare(dmask, mmask):
    """Shape agreement of two outlines, each normalised to its own box.

    iou      overlap of the normalised outlines (1 = same shape)
    aspect   width/height of the drawing view and of the model view
    mirror   'h' or 'v' when a mirrored model outline fits clearly better"""
    if dmask is None or mmask is None:
        return None
    a, b = _norm(dmask), _norm(mmask)

    def iou(p, q):
        u = np.logical_or(p, q).sum()
        return float(np.logical_and(p, q).sum() / u) if u else 0.0

    base = iou(a, b)
    res = {"iou": round(base, 3),
           "aspect_drawing": round(dmask.shape[1] / dmask.shape[0], 4),
           "aspect_model": round(mmask.shape[1] / mmask.shape[0], 4)}
    res["aspect_error"] = round(abs(res["aspect_model"] / res["aspect_drawing"] - 1.0), 4)
    fh, fv = iou(a, b[:, ::-1]), iou(a, b[::-1, :])
    if max(fh, fv) > base + 0.08:
        res["mirror"] = "h" if fh >= fv else "v"
    return res


def crop_image(path, box, pad=10):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = box
    return im.crop((max(0, int(x0 - pad)), max(0, int(y0 - pad)),
                    min(im.width, int(x1 + pad)), min(im.height, int(y1 + pad))))


def compose_pairs(rows, path, height=300):
    """One image with a row per view: label | drawing | current model."""
    from PIL import Image, ImageDraw
    tiles = []
    for label, left, right in rows:
        def fit(im):
            if im is None:
                return Image.new("RGB", (height, height), "white")
            im = im.convert("RGB")
            s = height / im.height
            w = max(1, int(im.width * s))
            if w > height * 2.2:
                s = height * 2.2 / im.width
            return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
        tiles.append((label, fit(left), fit(right)))
    if not tiles:
        return None
    lw = max(t[1].width for t in tiles)
    rw = max(t[2].width for t in tiles)
    W = 110 + lw + 30 + rw + 20
    H = 40 + sum(max(t[1].height, t[2].height) + 24 for t in tiles)
    out = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(out)
    d.text((110, 10), "DRAWING", fill=(0, 0, 0))
    d.text((110 + lw + 30, 10), "CURRENT MODEL", fill=(0, 0, 0))
    y = 34
    for label, a, b in tiles:
        h = max(a.height, b.height)
        d.text((8, y + h // 2 - 6), label.upper(), fill=(0, 0, 0))
        out.paste(a, (110, y))
        out.paste(b, (110 + lw + 30, y))
        d.rectangle([108, y - 2, 110 + a.width + 1, y + a.height + 1], outline=(180, 180, 180))
        d.rectangle([110 + lw + 28, y - 2, 110 + lw + 30 + b.width + 1, y + b.height + 1], outline=(180, 180, 180))
        y += h + 24
    out.save(path)
    return path


def prepare_for_ai(path, out, long_side=2000):
    """The page as sent to the AI: long side limited, contrast stretched."""
    from PIL import Image, ImageOps
    im = Image.open(path).convert("RGB")
    if max(im.size) > long_side:
        s = long_side / max(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im = ImageOps.autocontrast(im, cutoff=0.5)
    im.save(out)
    return out


def dist(p, q):
    return math.hypot(q[0] - p[0], q[1] - p[1])
