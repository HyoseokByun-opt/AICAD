"""Input drawings: PDF, raster images and DXF become page images.

Every page is stored as a PNG next to the project together with the text
that could be read exactly from the file itself (vector PDFs and DXF): the
numbers of a drawing exported from a CAD system are then known to the last
digit and need not be read from pixels.

    page = {"file": "page_001.png", "w": 2400, "h": 1697, "source": "pump.pdf",
            "page": 1, "kind": "pdf-vector" | "raster" | "dxf",
            "texts": [{"t": "120", "box": [x0, y0, x1, y1]}]}   # box: 0-1000

DWG is a closed format; such files are refused with a request to save the
drawing as DXF or PDF.
"""
from __future__ import annotations

import math
from pathlib import Path

PAGE_LONG = 3200          # long side of a rendered PDF page, pixels
MAX_PAGES = 60
RASTER_MAX = 6000         # long side of a raster page as stored; the original is kept for zoomed reading
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
SUPPORTED = IMAGE_EXT | {".pdf", ".dxf"}


class IngestError(ValueError):
    pass


def ingest(src: Path, outdir: Path, stem: str) -> list[dict]:
    ext = src.suffix.lower()
    outdir.mkdir(parents=True, exist_ok=True)
    if ext == ".pdf":
        return _pdf(src, outdir, stem)
    if ext in IMAGE_EXT:
        return _image(src, outdir, stem)
    if ext == ".dxf":
        return _dxf(src, outdir, stem)
    if ext == ".dwg":
        raise IngestError("DWG is a closed format. Save the drawing as DXF or PDF and import that file.")
    raise IngestError(f"'{ext}' files are not supported. Use PDF, PNG, JPG, TIFF, BMP or DXF.")


# ------------------------------------------------------------------ PDF
def _pdf(src, outdir, stem):
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(str(src))
    except Exception as e:
        raise IngestError(f"The PDF could not be opened: {e}") from e
    pages = []
    for i in range(min(len(pdf), MAX_PAGES)):
        page = pdf[i]
        pw, ph = page.get_size()
        scale = PAGE_LONG / max(pw, ph)
        img = page.render(scale=scale, rotation=0, fill_color=(255, 255, 255, 255)).to_pil().convert("RGB")
        name = f"{stem}_p{i + 1:03d}.png"
        img.save(outdir / name)
        texts = []
        try:
            tp = page.get_textpage()
            n = tp.count_rects()
            for k in range(n):
                l, b, r, t = tp.get_rect(k)
                s = tp.get_text_bounded(l, b, r, t).strip()
                if not s:
                    continue
                texts.append({"t": s, "box": [round(l / pw * 1000), round((ph - t) / ph * 1000),
                                              round(r / pw * 1000), round((ph - b) / ph * 1000)]})
        except Exception:
            pass
        pages.append({"file": name, "w": img.width, "h": img.height, "source": src.name, "page": i + 1,
                      "kind": "pdf-vector" if texts else "raster", "texts": texts[:600],
                      "paper_mm": [round(pw * 25.4 / 72, 2), round(ph * 25.4 / 72, 2)],
                      "orig": {"file": src.name, "pdf_page": i, "pt": [pw, ph]}})
    if not pages:
        raise IngestError("The PDF has no pages.")
    return pages


# ------------------------------------------------------------------ images
def _image(src, outdir, stem):
    """Raster pages. Scans of large sheets (20 000 px and more, often 1-bit)
    are reduced with a box filter, which keeps thin lines as grey instead of
    dropping them; the original file stays in the project for zoomed reading."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None          # local drawings, not untrusted web images
    try:
        im = Image.open(src)
    except Exception as e:
        raise IngestError(f"The image could not be opened: {e}") from e
    pages = []
    n = getattr(im, "n_frames", 1)
    for i in range(min(n, MAX_PAGES)):
        try:
            im.seek(i)
        except EOFError:
            break
        W0, H0 = im.size
        fr = im
        if fr.mode == "1" or fr.mode.startswith("I;16") or fr.mode == "I":
            fr = fr.convert("L")
        elif fr.mode in ("RGBA", "LA", "P", "PA"):
            fr = fr.convert("RGBA")
            bg = Image.new("RGBA", fr.size, (255, 255, 255, 255))
            fr = Image.alpha_composite(bg, fr).convert("RGB")
        elif fr.mode not in ("L", "RGB"):
            fr = fr.convert("RGB")
        if max(fr.size) > RASTER_MAX:
            f = -(-max(fr.size) // RASTER_MAX)          # integer reduction factor
            fr = fr.reduce(f)
        fr = ImageOps.exif_transpose(fr)
        name = f"{stem}_p{i + 1:03d}.png"
        fr.save(outdir / name)
        pages.append({"file": name, "w": fr.width, "h": fr.height, "source": src.name, "page": i + 1,
                      "kind": "raster", "texts": [],
                      "orig": {"file": src.name, "frame": i, "w": W0, "h": H0}})
    return pages


# ------------------------------------------------------------------ DXF
def _font(size):
    from PIL import ImageFont
    for f in ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, max(6, int(size)))
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=max(6, int(size)))
    except TypeError:
        return ImageFont.load_default()


def _dxf(src, outdir, stem):
    import ezdxf
    from ezdxf import recover
    from ezdxf.disassemble import recursive_decompose, make_primitive
    from PIL import Image, ImageDraw
    try:
        doc, _aud = recover.readfile(str(src))
    except Exception as e:
        raise IngestError(f"The DXF could not be read: {e}") from e
    msp = doc.modelspace()
    polylines, texts, dims = [], [], []
    for e in msp:
        if e.dxftype() == "DIMENSION":
            try:
                m = e.get_measurement()
                val = m if isinstance(m, (int, float)) else math.hypot(m.x, m.y)
                p = e.dxf.text_midpoint if e.dxf.hasattr("text_midpoint") else e.dxf.defpoint
                dims.append((float(val), (p.x, p.y), e.dxf.get("text", "")))
            except Exception:
                pass
    for e in recursive_decompose(msp):
        t = e.dxftype()
        try:
            if t in ("TEXT", "ATTRIB", "MTEXT"):
                s = e.plain_text() if t == "MTEXT" else e.dxf.text
                ins = e.dxf.insert
                h = e.dxf.char_height if t == "MTEXT" else e.dxf.height
                rot = e.dxf.get("rotation", 0.0)
                if s and s.strip():
                    texts.append((s.strip(), (ins.x, ins.y), float(h or 2.5), float(rot or 0.0)))
                continue
            if t in ("POINT", "HATCH", "SOLID", "IMAGE", "WIPEOUT", "VIEWPORT"):
                continue
            prim = make_primitive(e)
            if prim.path is not None:
                for sp in prim.path.sub_paths():
                    pts = [(v.x, v.y) for v in sp.flattening(0.1)]
                    if len(pts) > 1:
                        polylines.append(pts)
            elif prim.mesh is not None:
                for face in prim.mesh.faces_as_vertices():
                    pts = [(v.x, v.y) for v in face]
                    polylines.append(pts + pts[:1])
        except Exception:
            continue
    xs = [p[0] for pl in polylines for p in pl] + [t[1][0] for t in texts]
    ys = [p[1] for pl in polylines for p in pl] + [t[1][1] for t in texts]
    if not xs:
        raise IngestError("The DXF model space has no drawable entities.")
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    margin = 40
    s = (PAGE_LONG - 2 * margin) / max(w, h)
    W, H = int(w * s + 2 * margin), int(h * s + 2 * margin)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def tr(x, y):
        return ((x - x0) * s + margin, (y1 - y) * s + margin)

    for pl in polylines:
        d.line([tr(*p) for p in pl], fill=(0, 0, 0), width=2)
    out_texts = []
    for s_, (x, y), hgt, rot in texts:
        px, py = tr(x, y)
        fs = max(8, hgt * s)
        f = _font(fs)
        if abs(rot) < 1:
            d.text((px, py - fs), s_, fill=(0, 0, 0), font=f)
            bw = d.textlength(s_, font=f)
            box = [px, py - fs, px + bw, py]
        else:
            tw = int(d.textlength(s_, font=f)) + 4
            tmp = Image.new("L", (tw, int(fs * 1.3) + 2), 0)
            ImageDraw.Draw(tmp).text((2, 0), s_, fill=255, font=f)
            tmp = tmp.rotate(rot, expand=True)
            img.paste((0, 0, 0), (int(px), int(py - tmp.height)), tmp)
            box = [px, py - tmp.height, px + tmp.width, py]
        out_texts.append({"t": s_, "box": [round(box[0] / W * 1000), round(box[1] / H * 1000),
                                           round(box[2] / W * 1000), round(box[3] / H * 1000)]})
    for val, (x, y), txt in dims:
        px, py = tr(x, y)
        out_texts.append({"t": f"{val:g}", "dim": round(val, 6), "box": [round(px / W * 1000) - 5, round(py / H * 1000) - 5,
                                                                         round(px / W * 1000) + 5, round(py / H * 1000) + 5]})
    name = f"{stem}_p001.png"
    img.save(outdir / name)
    units = {0: "", 1: "inch", 4: "mm", 5: "cm", 6: "m"}.get(doc.header.get("$INSUNITS", 0), "")
    return [{"file": name, "w": W, "h": H, "source": src.name, "page": 1, "kind": "dxf",
             "texts": out_texts[:800], "units": units,
             "dxf_scale": {"x0": x0, "y1": y1, "s": s, "margin": margin}}]
