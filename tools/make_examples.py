"""Build the example drawings in examples/ from reference CadQuery models.

Each example has a reference model (examples/<id>/reference.py). Its
hidden-line views are laid out on an A3 sheet in third-angle projection
with dimensions, a border and a title block, and written as PNG (raster),
PDF (vector, with real text) or DXF (model space 1:1 with DIMENSION
entities). Text-only examples carry a description instead of a drawing.
The reference model is the ground truth for tests/eval_examples.py.

    python tools/make_examples.py
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
EX = ROOT / "examples"

PAPER = (420.0, 297.0)      # A3 landscape, mm
PX_PER_MM = 6.0             # PNG resolution
SCALES = [1, 2, 2.5, 5, 10, 20, 25, 50]

# ===================================================================== models
BASE_PLATE = '''import cadquery as cq

# --- PARAMETERS (mm) ---
length = 240.0          # overall length [drawing]
width = 160.0           # overall width [drawing]
thickness = 16.0        # plate thickness [drawing]
corner_r = 10.0         # corner radius [drawing]
hole_d = 18.0           # mounting hole diameter [drawing]
hole_px = 180.0         # hole spacing along X [drawing]
hole_py = 100.0         # hole spacing along Y [drawing]
bore_d = 60.0           # central bore [drawing]
# --- END PARAMETERS ---

result = (cq.Workplane("XY").box(length, width, thickness, centered=(True, True, False))
          .edges("|Z").fillet(corner_r)
          .faces(">Z").workplane().rarray(hole_px, hole_py, 2, 2).hole(hole_d)
          .faces(">Z").workplane().hole(bore_d))
'''

FLANGE = '''import cadquery as cq
import math

# --- PARAMETERS (mm) ---
od = 250.0              # flange outer diameter [drawing]
t = 24.0                # flange thickness [drawing]
hub_d = 140.0           # hub diameter [drawing]
hub_h = 50.0            # hub height above the flange [drawing]
bore = 90.0             # bore diameter [drawing]
pcd = 205.0             # bolt circle diameter [drawing]
bolt_d = 22.0           # bolt hole diameter [drawing]
n = 8                   # number of bolt holes [drawing]
# --- END PARAMETERS ---

prof = [(bore / 2, 0), (od / 2, 0), (od / 2, t), (hub_d / 2, t), (hub_d / 2, t + hub_h), (bore / 2, t + hub_h)]
body = cq.Workplane("XZ").polyline(prof).close().revolve(360, (0, 0, 0), (0, 1, 0))
pts = [(pcd / 2 * math.cos(2 * math.pi * (i + 0.5) / n), pcd / 2 * math.sin(2 * math.pi * (i + 0.5) / n)) for i in range(n)]
result = body.cut(cq.Workplane("XY").pushPoints(pts).circle(bolt_d / 2).extrude(t))
'''

BRACKET = '''import cadquery as cq

# --- PARAMETERS (mm) ---
leg_x = 100.0           # horizontal leg length [drawing]
leg_z = 80.0            # vertical leg height [drawing]
width = 60.0            # bracket width [drawing]
t = 10.0                # wall thickness (not dimensioned on the drawing) [ratio]
hole_d = 11.0           # hole diameter [drawing]
hole_x = 65.0           # hole position on the base from the back face [drawing]
hole_z = 50.0           # hole height on the upright [drawing]
hole_s = 30.0           # hole spacing across the width [drawing]
# --- END PARAMETERS ---

prof = [(0, 0), (leg_x, 0), (leg_x, t), (t, t), (t, leg_z), (0, leg_z)]
body = cq.Workplane("XZ").polyline(prof).close().extrude(-width / 2, both=True)
body = body.edges("|Y").edges(cq.selectors.NearestToPointSelector((t, 0, t))).fillet(8)
base_holes = cq.Workplane("XY").pushPoints([(hole_x, -hole_s / 2), (hole_x, hole_s / 2)]).circle(hole_d / 2).extrude(t)
up_holes = cq.Workplane("YZ").pushPoints([(-hole_s / 2, hole_z), (hole_s / 2, hole_z)]).circle(hole_d / 2).extrude(t)
result = body.cut(base_holes).cut(up_holes)
'''

SKID = '''import cadquery as cq

# --- PARAMETERS (mm) ---
frame_l = 1400.0        # base frame length [drawing]
frame_w = 700.0         # base frame width [drawing]
frame_h = 120.0         # base frame height [drawing]
flange_t = 12.0         # channel flange / top plate thickness [assumed]
motor_d = 300.0         # motor body diameter [drawing]
motor_l = 520.0         # motor body length [drawing]
motor_x = -310.0        # motor centre along X [drawing]
ped_h = 70.0            # motor pedestal height [drawing]
pump_l = 380.0          # pump casing length [drawing]
pump_w = 300.0          # pump casing width [drawing]
pump_h = 340.0          # pump casing height [drawing]
pump_x = 390.0          # pump centre along X [drawing]
anchor_d = 24.0         # anchor bolt holes [drawing]
# --- END PARAMETERS ---

axis_z = frame_h + ped_h + motor_d / 2
frame = (cq.Workplane("XY").box(frame_l, frame_w, frame_h, centered=(True, True, False))
         .faces(">Z").workplane().rect(frame_l - 2 * flange_t, frame_w - 2 * flange_t).cutBlind(-(frame_h - flange_t))
         .faces("<Z").workplane().rect(frame_l - 100, frame_w - 100, forConstruction=True).vertices().hole(anchor_d))
ped = cq.Workplane("XY", origin=(motor_x, 0, frame_h)).rect(motor_l * 0.8, motor_d * 0.8).extrude(ped_h)
motor = cq.Workplane("YZ", origin=(motor_x - motor_l / 2, 0, axis_z)).circle(motor_d / 2).extrude(motor_l)
pump = cq.Workplane("XY", origin=(pump_x, 0, frame_h)).rect(pump_l, pump_w).extrude(pump_h)
shaft = cq.Workplane("YZ", origin=(motor_x + motor_l / 2, 0, axis_z)).circle(30).extrude(pump_x - pump_l / 2 - motor_x - motor_l / 2)

assembly = cq.Assembly(name="pump_skid")
assembly.add(frame, name="base_frame", color=cq.Color("gray50"))
assembly.add(ped, name="motor_pedestal", color=cq.Color("gray50"))
assembly.add(motor, name="motor", color=cq.Color("steelblue"))
assembly.add(pump, name="pump", color=cq.Color("orange"))
assembly.add(shaft, name="coupling", color=cq.Color("lightgray"))
'''

VESSEL = '''import cadquery as cq
import math

# --- PARAMETERS (mm) ---
shell_d = 800.0         # shell outside diameter [description]
shell_h = 1500.0        # straight shell height [description]
head_h = 200.0          # 2:1 ellipsoidal head height = D/4 [description]
leg_s = 100.0           # square leg size [description]
leg_l = 400.0           # leg length below the bottom head [description]
top_nz_d = 114.3        # top nozzle OD, 100A [description]
top_nz_h = 150.0        # top nozzle height above the head [description]
side_nz_d = 60.5        # side nozzle OD, 50A [description]
side_nz_z = 300.0       # side nozzle height above the bottom tangent line [description]
side_nz_r = 600.0       # side nozzle projection from the vessel axis [description]
# --- END PARAMETERS ---

z0 = leg_l + head_h                                  # bottom tangent line
r = shell_d / 2
shell = cq.Workplane("XY", origin=(0, 0, z0)).circle(r).extrude(shell_h)
head = cq.Solid.makeSphere(1.0, angleDegrees1=0, angleDegrees2=90)
top = cq.Workplane().add(head.scale(1.0)).val().transformGeometry(cq.Matrix([[r, 0, 0, 0], [0, r, 0, 0], [0, 0, head_h, z0 + shell_h]]))
bot = cq.Workplane().add(head).val().transformGeometry(cq.Matrix([[r, 0, 0, 0], [0, r, 0, 0], [0, 0, -head_h, z0]]))
body = shell.union(cq.Workplane().add(top)).union(cq.Workplane().add(bot))
legs = cq.Workplane("XY").polarArray(r - leg_s / 2, 45, 360, 4).rect(leg_s, leg_s).extrude(z0 + 50)
nz_top = cq.Workplane("XY", origin=(0, 0, z0 + shell_h + head_h - 20)).circle(top_nz_d / 2).extrude(top_nz_h + 20)
nz_side = cq.Workplane("YZ", origin=(0, 0, z0 + side_nz_z)).circle(side_nz_d / 2).extrude(side_nz_r)
result = body.union(legs).union(nz_top).union(nz_side)
'''

SHAFT = '''import cadquery as cq

# --- PARAMETERS (mm) ---
d1 = 40.0               # first journal diameter [description]
l1 = 60.0               # first journal length [description]
d2 = 50.0               # middle section diameter [description]
l2 = 150.0              # middle section length [description]
d3 = 45.0               # third section diameter [description]
l3 = 40.0               # third section length [description]
d4 = 35.0               # end section diameter [description]
l4 = 70.0               # end section length [description]
chamfer = 1.0           # end chamfers [description]
key_w = 10.0            # keyway width [description]
key_t = 5.0             # keyway depth [description]
key_l = 50.0            # keyway length [description]
# --- END PARAMETERS ---

prof = [(0, 0), (0, d1 / 2), (l1, d1 / 2), (l1, d2 / 2), (l1 + l2, d2 / 2), (l1 + l2, d3 / 2),
        (l1 + l2 + l3, d3 / 2), (l1 + l2 + l3, d4 / 2), (l1 + l2 + l3 + l4, d4 / 2), (l1 + l2 + l3 + l4, 0)]
shaft = cq.Workplane("XY").polyline(prof).close().revolve(360, (0, 0, 0), (1, 0, 0))
shaft = shaft.faces("<X or >X").chamfer(chamfer)
key = (cq.Workplane("XY", origin=(l1 + l2 / 2, 0, d2 / 2 - key_t)).slot2D(key_l, key_w).extrude(key_t + 1))
result = shaft.cut(key)
'''

EXAMPLES = [
    {"id": "base_plate", "title": "Base plate", "fmt": "png", "code": BASE_PLATE, "name": "BASE PLATE",
     "description": "Raster drawing (PNG), third-angle, scale 1:2: plate with corner radii, four holes and a central bore.",
     "views": ["top", "front", "right"],
     "dims": [
         ("top", "h", -120, 120, "above", 1, None), ("top", "h", -90, 90, "above", 0, None),
         ("top", "v", -80, 80, "left", 0, None), ("top", "v", -50, 50, "right", 0, None),
         ("top", "dia", (90, 50), 9, "4x Ø18"), ("top", "dia", (0, 0), 30, "Ø60"),
         ("top", "rad", (120 - 2.93, -80 + 2.93), 0, "R10 (4x)", -45),
         ("front", "v", 0, 16, "right", 0, None)]},
    {"id": "pipe_flange", "title": "Pipe flange", "fmt": "pdf", "code": FLANGE, "name": "FLANGE DN80",
     "description": "Vector PDF, third-angle, scale 1:2: hub flange with a bolt circle of 8 holes.",
     "views": ["top", "front"],
     "dims": [
         ("front", "h", -125, 125, "below", 0, "Ø250"), ("front", "h", -70, 70, "above", 0, "Ø140"),
         ("front", "v", 0, 24, "left", 0, None), ("front", "v", 0, 74, "right", 0, None),
         ("top", "dia", (0, 0), 45, "Ø90"), ("top", "pcd", (0, 0), 102.5, "PCD 205"),
         ("top", "dia", (102.5 * math.cos(math.pi / 8), 102.5 * math.sin(math.pi / 8)), 11, "8x Ø22 EQ. SP.")]},
    {"id": "l_bracket", "title": "L bracket (one size missing)", "fmt": "png", "code": BRACKET, "name": "L BRACKET",
     "description": "Raster drawing, third-angle, 1:1. The wall thickness is not dimensioned: it has to be measured on the sheet.",
     "probe": ("front", (0, 50), (10, 50), 10.0),
     "views": ["top", "front", "right"],
     "dims": [
         ("front", "h", 0, 100, "below", 0, None), ("front", "v", 0, 80, "left", 0, None),
         ("top", "v", -30, 30, "left", 0, None), ("top", "v", -15, 15, "right", 0, None),
         ("top", "h", 0, 65, "above", 0, None), ("top", "dia", (65, 15), 5.5, "4x Ø11"),
         ("right", "v", 0, 50, "right", 0, None)]},
    {"id": "pump_skid", "title": "Pump skid (DXF assembly)", "fmt": "dxf", "code": SKID, "name": "PUMP SKID",
     "description": "DXF in model space 1:1 with dimension entities: base frame, motor, pump and coupling as an assembly.",
     "views": ["top", "front"],
     "dims": [
         ("front", "h", -700, 700, "below", 0, None), ("front", "v", 0, 120, "left", 0, None),
         ("front", "v", 0, 490, "right", 0, None), ("front", "h", -570, -50, "above", 1, None),
         ("front", "h", 200, 580, "above", 0, None), ("front", "v", 0, 460, "right", 1, None),
         ("top", "v", -350, 350, "left", 0, None), ("top", "v", -150, 150, "right", 0, None),
         ("top", "h", -310, 390, "above", 0, None)]},
    {"id": "vessel", "title": "Vertical vessel (description)", "fmt": "text", "code": VESSEL, "name": "VESSEL",
     "description": "Text only: a vertical tank with ellipsoidal heads, four legs and two nozzles.",
     "text": ("Vertical storage tank. Cylindrical shell 800 mm outside diameter and 1500 mm straight height, with "
              "2:1 semi-ellipsoidal heads at the top and bottom. It stands on four legs of 100 x 100 mm square "
              "section, equally spaced at 45 degrees, reaching 400 mm below the bottom of the lower head. One 100A "
              "nozzle (OD 114.3 mm) on the centre of the top head, 150 mm high. One 50A side nozzle (OD 60.5 mm) "
              "300 mm above the bottom tangent line, pointing along +X and ending 600 mm from the vessel axis.")},
    {"id": "stepped_shaft", "title": "Stepped shaft (description)", "fmt": "text", "code": SHAFT, "name": "SHAFT",
     "description": "Text only: a turned shaft with four diameters, chamfers and a keyway.",
     "text": ("Stepped shaft along the X axis, starting at x = 0: diameter 40 mm for 60 mm, then diameter 50 mm for "
              "150 mm, then diameter 45 mm for 40 mm, then diameter 35 mm for 70 mm. 1 mm chamfers on both end "
              "faces. A keyway 10 mm wide, 5 mm deep and 50 mm long, centred on the 50 mm section, on top (+Z).")},
]


# ===================================================================== sheet
class Sheet:
    """Lines and texts in paper millimetres (origin lower-left)."""

    def __init__(self):
        self.lines = []   # (x0, y0, x1, y1, style) style: thick | thin | hidden | center
        self.texts = []   # (x, y, text, size, anchor, angle)
        self.arrows = []  # (x, y, angle) filled arrow heads

    def line(self, a, b, style="thin"):
        self.lines.append((a[0], a[1], b[0], b[1], style))

    def text(self, x, y, s, size=3.5, anchor="mm", angle=0):
        self.texts.append((x, y, s, size, anchor, angle))

    def arrow(self, tip, toward):
        ang = math.atan2(toward[1] - tip[1], toward[0] - tip[0])
        self.arrows.append((tip[0], tip[1], ang))

    # ---------------------------------------------------------- outputs
    def png(self, path):
        from PIL import Image, ImageDraw, ImageFont
        W, H = int(PAPER[0] * PX_PER_MM), int(PAPER[1] * PX_PER_MM)
        img = Image.new("L", (W, H), 255)
        d = ImageDraw.Draw(img)
        T = lambda x, y: (x * PX_PER_MM, (PAPER[1] - y) * PX_PER_MM)
        width = {"thick": 4, "thin": 2, "hidden": 2, "center": 1}
        for x0, y0, x1, y1, st in self.lines:
            a, b = T(x0, y0), T(x1, y1)
            if st in ("hidden", "center"):
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                pat = [12, 7] if st == "hidden" else [30, 6, 5, 6]
                pos, k = 0.0, 0
                while pos < L:
                    seg = pat[k % len(pat)]
                    if k % 2 == 0:
                        t0, t1 = pos / L, min(1.0, (pos + seg) / L)
                        d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                                (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=0, width=width[st])
                    pos += seg
                    k += 1
            else:
                d.line([a, b], fill=0, width=width[st])
        for x, y, ang in self.arrows:
            tip = T(x, y)
            L, Wd = 3.0 * PX_PER_MM, 0.9 * PX_PER_MM
            ca, sa = math.cos(-ang), math.sin(-ang)
            p1 = (tip[0] + L * ca - Wd * sa, tip[1] + L * sa + Wd * ca)
            p2 = (tip[0] + L * ca + Wd * sa, tip[1] + L * sa - Wd * ca)
            d.polygon([tip, p1, p2], fill=0)
        for x, y, s, size, anchor, angle in self.texts:
            f = ImageFont.truetype("arial.ttf", int(size * PX_PER_MM * 1.25))
            px, py = T(x, y)
            if angle == 0:
                d.text((px, py), s, fill=0, font=f, anchor=anchor)
            else:
                tw = int(d.textlength(s, font=f)) + 8
                th = int(size * PX_PER_MM * 1.8)
                tmp = Image.new("L", (tw, th), 0)
                ImageDraw.Draw(tmp).text((tw / 2, th / 2), s, fill=255, font=f, anchor="mm")
                tmp = tmp.rotate(angle, expand=True)
                img.paste(0, (int(px - tmp.width / 2), int(py - tmp.height / 2)), tmp)
        img.save(path)

    def pdf(self, path):
        k = 72 / 25.4
        W, H = PAPER[0] * k, PAPER[1] * k
        out = []
        lw = {"thick": 0.7, "thin": 0.35, "hidden": 0.35, "center": 0.25}
        dash = {"thick": "[] 0 d", "thin": "[] 0 d", "hidden": "[3 2] 0 d", "center": "[8 2 1.5 2] 0 d"}
        for x0, y0, x1, y1, st in self.lines:
            out.append(f"{lw[st] * k:.2f} w {dash[st]} {x0 * k:.2f} {y0 * k:.2f} m {x1 * k:.2f} {y1 * k:.2f} l S")
        out.append("[] 0 d")
        for x, y, ang in self.arrows:
            L, Wd = 3.0, 0.9
            ca, sa = math.cos(ang), math.sin(ang)
            p1 = (x + L * ca - Wd * sa, y + L * sa + Wd * ca)
            p2 = (x + L * ca + Wd * sa, y + L * sa - Wd * ca)
            out.append(f"{x * k:.2f} {y * k:.2f} m {p1[0] * k:.2f} {p1[1] * k:.2f} l {p2[0] * k:.2f} {p2[1] * k:.2f} l f")

        def enc(s):
            b = s.encode("cp1252", "replace")
            r = ""
            for c in b:
                ch = chr(c)
                if ch in "()\\":
                    r += "\\" + ch
                elif c > 126:
                    r += "\\%03o" % c
                else:
                    r += ch
            return r
        for x, y, s, size, anchor, angle in self.texts:
            fs = size * 1.25 * k
            w = len(s) * fs * 0.55
            dx = {"l": 0, "m": -w / 2, "r": -w}[anchor[0]]
            dy = {"t": -fs * 0.75, "m": -fs * 0.35, "b": 0, "s": 0}[anchor[1]]
            if angle == 0:
                out.append(f"BT /F1 {fs:.2f} Tf 1 0 0 1 {x * k + dx:.2f} {y * k + dy:.2f} Tm ({enc(s)}) Tj ET")
            else:
                c, s_ = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                ox, oy = x * k + c * dx - s_ * dy, y * k + s_ * dx + c * dy
                out.append(f"BT /F1 {fs:.2f} Tf {c:.4f} {s_:.4f} {-s_:.4f} {c:.4f} {ox:.2f} {oy:.2f} Tm ({enc(s)}) Tj ET")
        stream = ("\n".join(out)).encode("latin-1")
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.2f} {H:.2f}] /Contents 4 0 R "
                f"/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
        data = b"%PDF-1.4\n"
        offs = []
        for i, o in enumerate(objs):
            offs.append(len(data))
            data += f"{i + 1} 0 obj\n".encode() + o + b"\nendobj\n"
        xref = len(data)
        data += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for o in offs:
            data += f"{o:010d} 00000 n \n".encode()
        data += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        Path(path).write_bytes(data)


# ===================================================================== layout
def layout(views_json, order, scale_guess=None):
    """Positions (paper mm) of the views in third-angle projection."""
    b = {v: views_json[v]["bounds"] for v in order}
    size = {v: (b[v][2] - b[v][0], b[v][3] - b[v][1]) for v in order}
    fw, fh = size["front"]
    tw, th = size.get("top", (0, 0))
    rw, rh = size.get("right", (0, 0))
    avail_w, avail_h = PAPER[0] - 40, PAPER[1] - 70
    for s in SCALES:
        gap = 45
        W = (fw + (rw if "right" in order else 0)) / s + (gap if "right" in order else 0)
        H = (fh + (th if "top" in order else 0)) / s + (gap if "top" in order else 0)
        if W <= avail_w and H <= avail_h:
            break
    x0 = 20 + (avail_w - W) / 2 + 10
    y0 = 52 + (avail_h - H) / 2
    pos = {"front": (x0, y0)}
    if "top" in order:
        pos["top"] = (x0, y0 + fh / s + gap)
    if "right" in order:
        pos["right"] = (x0 + fw / s + gap, y0)
    return s, pos, b


def norm_pt(pos, vb, s, u, v):
    """View coordinates (mm) -> sheet coordinates 0-1000 (y down)."""
    X, Y = pos[0] + (u - vb[0]) / s, pos[1] + (v - vb[1]) / s
    return [round(X / PAPER[0] * 1000, 2), round((PAPER[1] - Y) / PAPER[1] * 1000, 2)]


def norm_box(pos, vb, s):
    a, c = norm_pt(pos, vb, s, vb[0], vb[3]), norm_pt(pos, vb, s, vb[2], vb[1])
    return [a[0], a[1], c[0], c[1]]


def draw_views(sh, views_json, s, pos, b):
    for v, (px, py) in pos.items():
        vb = b[v]
        T = lambda u, w: (px + (u - vb[0]) / s, py + (w - vb[1]) / s)
        for pl in views_json[v]["h"]:
            for i in range(0, len(pl) - 2, 2):
                sh.line(T(pl[i], pl[i + 1]), T(pl[i + 2], pl[i + 3]), "hidden")
        for pl in views_json[v]["v"]:
            for i in range(0, len(pl) - 2, 2):
                sh.line(T(pl[i], pl[i + 1]), T(pl[i + 2], pl[i + 3]), "thick")


def draw_dim(sh, d, s, pos, b):
    v = d[0]
    vb = b[v]
    px, py = pos[v]
    T = lambda u, w: (px + (u - vb[0]) / s, py + (w - vb[1]) / s)
    kind = d[1]
    if kind in ("h", "v"):
        _, _, a, c, side, row, txt = d
        val = abs(c - a)
        txt = txt or f"{val:g}"
        off = 10 + 9 * row
        if kind == "h":
            ya = {"above": vb[3], "below": vb[1]}[side]
            p1, p2 = T(a, ya), T(c, ya)
            yy = p1[1] + (off if side == "above" else -off)
            sh.line((p1[0], p1[1] + (1.5 if side == "above" else -1.5)), (p1[0], yy + (2 if side == "above" else -2)))
            sh.line((p2[0], p2[1] + (1.5 if side == "above" else -1.5)), (p2[0], yy + (2 if side == "above" else -2)))
            sh.line((p1[0], yy), (p2[0], yy))
            sh.arrow((p1[0], yy), (p2[0], yy))
            sh.arrow((p2[0], yy), (p1[0], yy))
            sh.text((p1[0] + p2[0]) / 2, yy + 1.2, txt, anchor="mb")
        else:
            xa = {"left": vb[0], "right": vb[2]}[side]
            p1, p2 = T(xa, a), T(xa, c)
            xx = p1[0] + (off if side == "right" else -off)
            sgn = 1 if side == "right" else -1
            sh.line((p1[0] + 1.5 * sgn, p1[1]), (xx + 2 * sgn, p1[1]))
            sh.line((p2[0] + 1.5 * sgn, p2[1]), (xx + 2 * sgn, p2[1]))
            sh.line((xx, p1[1]), (xx, p2[1]))
            sh.arrow((xx, p1[1]), (xx, p2[1]))
            sh.arrow((xx, p2[1]), (xx, p1[1]))
            sh.text(xx - 1.5, (p1[1] + p2[1]) / 2, txt, anchor="mb", angle=90)
    elif kind in ("dia", "rad", "pcd"):
        _, _, c, r, txt = d[:5]
        cx, cy = T(*c)
        rr = r / s
        ang = math.radians(d[5] if len(d) > 5 else 45)
        tip = (cx + rr * math.cos(ang), cy + rr * math.sin(ang))
        if kind == "pcd":
            sh.lines.append((cx - rr - 3, cy, cx + rr + 3, cy, "center"))
            sh.lines.append((cx, cy - rr - 3, cx, cy + rr + 3, "center"))
            n = 72
            for i in range(n):
                a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
                sh.lines.append((cx + rr * math.cos(a0), cy + rr * math.sin(a0), cx + rr * math.cos(a1), cy + rr * math.sin(a1), "center"))
            ang = math.radians(150)
            tip = (cx + rr * math.cos(ang), cy + rr * math.sin(ang))
            elbow = (tip[0] - 14, tip[1] + 14)
            sh.line(tip, elbow); sh.arrow(tip, elbow)
            sh.line(elbow, (elbow[0] - 22, elbow[1]))
            sh.text(elbow[0] - 22, elbow[1] + 1.2, txt, anchor="lb")
            return
        elbow = (tip[0] + 16 * math.sqrt(2) * math.cos(ang), tip[1] + 16 * math.sqrt(2) * math.sin(ang))
        sh.line(tip, elbow); sh.arrow(tip, elbow)
        sh.line(elbow, (elbow[0] + 26, elbow[1]))
        sh.text(elbow[0] + 1, elbow[1] + 1.2, txt, anchor="lb")


def frame_and_title(sh, name, scale, ex_id):
    W, H = PAPER
    for a, b in (((10, 10), (W - 10, 10)), ((W - 10, 10), (W - 10, H - 10)), ((W - 10, H - 10), (10, H - 10)), ((10, H - 10), (10, 10))):
        sh.line(a, b, "thick")
    x0, y0, x1, y1 = W - 190, 10, W - 10, 42
    for a, b in (((x0, y0), (x0, y1)), ((x0, y1), (x1, y1)), ((x0, 26), (x1, 26)), ((x0 + 110, y0), (x0 + 110, 26)), ((x0 + 145, y0), (x0 + 145, 26))):
        sh.line(a, b)
    sh.text(x0 + 4, 34, name, size=5, anchor="lm")
    sh.text(x0 + 4, 18, "AICAD EXAMPLE  " + ex_id.upper().replace("_", "-"), size=2.5, anchor="lm")
    sh.text(x0 + 113, 21, "SCALE", size=2, anchor="lm")
    sh.text(x0 + 113, 14.5, f"1:{scale:g}", size=3.5, anchor="lm")
    sh.text(x0 + 148, 21, "UNIT", size=2, anchor="lm")
    sh.text(x0 + 148, 14.5, "mm", size=3.5, anchor="lm")
    # third-angle symbol
    cx, cy = x0 - 30, 26
    sh.line((cx - 14, cy - 4), (cx - 4, cy - 6.5)); sh.line((cx - 4, cy - 6.5), (cx - 4, cy + 6.5))
    sh.line((cx - 4, cy + 6.5), (cx - 14, cy + 4)); sh.line((cx - 14, cy + 4), (cx - 14, cy - 4))
    n = 40
    for r in (6.5, 3):
        for i in range(n):
            a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            sh.line((cx + 8 + r * math.cos(a0), cy + r * math.sin(a0)), (cx + 8 + r * math.cos(a1), cy + r * math.sin(a1)))
    sh.text(cx - 4, cy - 11, "THIRD ANGLE PROJECTION", size=1.8, anchor="mm")
    sh.text(20, 16, "GENERAL TOLERANCE ISO 2768-m.  ALL DIMENSIONS IN mm.", size=2.2, anchor="lm")


# ===================================================================== DXF
def write_dxf(path, views_json, order, dims, name):
    """Model space 1:1: the views at real size, real DIMENSION entities."""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.units = 4  # mm
    doc.header["$INSUNITS"] = 4
    doc.layers.add("VISIBLE", color=7)
    doc.layers.add("HIDDEN", color=8, linetype="DASHED")
    doc.layers.add("DIM", color=1)
    msp = doc.modelspace()
    b = {v: views_json[v]["bounds"] for v in order}
    gap = 400.0
    pos = {"front": (0.0, 0.0)}
    if "top" in order:
        pos["top"] = (0.0, (b["front"][3] - b["front"][1]) + gap)
    if "right" in order:
        pos["right"] = ((b["front"][2] - b["front"][0]) + gap, 0.0)
    for v, (px, py) in pos.items():
        vb = b[v]
        T = lambda u, w: (px + u - vb[0], py + w - vb[1])
        for key, layer in (("h", "HIDDEN"), ("v", "VISIBLE")):
            for pl in views_json[v][key]:
                pts = [T(pl[i], pl[i + 1]) for i in range(0, len(pl), 2)]
                msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
    for d in dims:
        v = d[0]
        vb = b[v]
        px, py = pos[v]
        T = lambda u, w: (px + u - vb[0], py + w - vb[1])
        if d[1] == "h":
            _, _, a, c, side, row, txt = d
            ya = vb[3] if side == "above" else vb[1]
            off = (90 + 80 * row) * (1 if side == "above" else -1)
            p1, p2 = T(a, ya), T(c, ya)
            dim = msp.add_linear_dim(base=(p1[0], p1[1] + off), p1=p1, p2=p2, dimstyle="EZDXF",
                                     override={"dimtxt": 25, "dimasz": 18, "dimlfac": 1.0, "dimdec": 0, "dimexo": 8, "dimexe": 10}, dxfattribs={"layer": "DIM"})
            dim.render()
        elif d[1] == "v":
            _, _, a, c, side, row, txt = d
            xa = vb[2] if side == "right" else vb[0]
            off = (90 + 80 * row) * (1 if side == "right" else -1)
            p1, p2 = T(xa, a), T(xa, c)
            dim = msp.add_linear_dim(base=(p1[0] + off, p1[1]), p1=p1, p2=p2, angle=90, dimstyle="EZDXF",
                                     override={"dimtxt": 25, "dimasz": 18, "dimlfac": 1.0, "dimdec": 0, "dimexo": 8, "dimexe": 10}, dxfattribs={"layer": "DIM"})
            dim.render()
    fx = b["front"][2] - b["front"][0]
    msp.add_text(name + "   (all dimensions in mm, model space 1:1)", height=30,
                 dxfattribs={"layer": "DIM"}).set_placement((0, -320))
    msp.add_text("FRONT VIEW", height=22, dxfattribs={"layer": "DIM"}).set_placement((fx / 2 - 100, -200))
    if "top" in pos:
        msp.add_text("TOP VIEW", height=22, dxfattribs={"layer": "DIM"}).set_placement(
            (fx / 2 - 80, pos["top"][1] + (b["top"][3] - b["top"][1]) + 200))
    doc.saveas(path)


# ===================================================================== main
def main():
    from aicad.cadexec import worker
    EX.mkdir(exist_ok=True)
    index = []
    w = worker()
    for ex in EXAMPLES:
        d = EX / ex["id"]
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        (d / "reference.py").write_text(ex["code"], encoding="utf-8")
        build = d / "_build"
        r = w.build(ex["code"], build, name=ex["id"], views=["front", "top", "right", "iso"])
        if not r.get("ok"):
            raise SystemExit(f"{ex['id']}: reference does not build: {r.get('error')} line {r.get('line')}")
        vj = json.loads((build / "views.json").read_text())
        shutil.copyfile(build / "view_iso.png", d / "thumb.png")
        entry = {"id": ex["id"], "title": ex["title"], "description": ex["description"],
                 "reference": f"{ex['id']}/reference.py", "thumb": f"{ex['id']}/thumb.png",
                 "truth": {"size": r["metrics"]["size"], "volume": r["metrics"]["volume"],
                           "solids": r["metrics"]["solids"], "parts": r["metrics"]["parts"]}}
        if ex["fmt"] == "text":
            entry["text"] = ex["text"]
        else:
            order = ex["views"]
            if ex["fmt"] == "dxf":
                f = d / f"{ex['id']}.dxf"
                write_dxf(f, vj, order, ex["dims"], ex["name"])
            else:
                s, pos, b = layout(vj, order)
                sh = Sheet()
                draw_views(sh, vj, s, pos, b)
                for dm in ex["dims"]:
                    draw_dim(sh, dm, s, pos, b)
                frame_and_title(sh, ex["name"], s, ex["id"])
                entry["truth"].update(scale=s, mm_per_px=s / PX_PER_MM if ex["fmt"] == "png" else None,
                                      views=[{"type": v, "box": norm_box(pos[v], b[v], s)} for v in order])
                if ex.get("probe"):
                    pv, (u0, v0), (u1, v1), val = ex["probe"]
                    entry["truth"]["probe"] = {"view": pv, "value": val,
                                               "p1": norm_pt(pos[pv], b[pv], s, u0, v0),
                                               "p2": norm_pt(pos[pv], b[pv], s, u1, v1)}
                f = d / f"{ex['id']}.{ex['fmt']}"
                (sh.png if ex["fmt"] == "png" else sh.pdf)(f)
                if ex["fmt"] == "pdf":
                    sh.png(d / "preview.png")
            entry["drawing"] = f"{ex['id']}/{f.name}"
        shutil.rmtree(build, ignore_errors=True)
        index.append(entry)
        print(f"{ex['id']:15s} {ex['fmt']:5s} size {r['metrics']['size']}  volume {r['metrics']['volume']:.0f}")
    index += hard_examples(w)
    (EX / "examples.json").write_text(json.dumps(index, indent=1), encoding="utf-8")


# ===================================================================== real drawings
HAER = ("Historic American Engineering Record (HAER), National Park Service; Library of Congress, Prints & "
        "Photographs Division. Public domain (no known restrictions), via Wikimedia Commons.")
HARD = [
    {"id": "turbine_unit", "title": "Turbine and generator unit, 1925 (hard)",
     "description": "Real drawing, HAER AL-47-A (Wilson Dam): half section of a 35,000 hp Francis turbine and "
                    "generator. No dimensions at all - sizes only from the graphic scale bars; two scales on one sheet.",
     "files": [("wilson_turbine/turbine_generator_unit.tif", "turbine_generator_unit.tif", None)], "reference": True,
     "text": "Model the turbine and generator unit as a layout model: generator, exciter, shaft, Francis runner, "
             "wicket gates and stay vanes, spiral distributor, draft tube and the surrounding concrete."},
    {"id": "steel_truss", "title": "Steel deck truss, erection plan (hard)",
     "description": "Real drawing, HAER FL-12 (Apalachicola River Bridge): photograph of a 1934 erection plan - two "
                    "Warren trusses, top and bottom laterals, sway frames; feet-and-inch dimensions, member marks.",
     "files": [("steel_truss/truss_span1.tif", "truss_span1.jpg", 88)], "reference": True, "text": ""},
    {"id": "turbine_building", "title": "Turbine building, three sheets (hard)",
     "description": "Real drawing set, HAER CT-185-C (Haddam Neck plant): turbine support outline, machine location "
                    "sections and the operating floor plan; 21,600 x 13,000 px scans, feet-and-inch dimensions.",
     "files": [("turbine_building/turbine_support_outline.tif", "turbine_support_outline.tif", None),
               ("turbine_building/machine_sections_s10.tif", "machine_sections_s10.tif", None),
               ("turbine_building/plan_operating_floor_s9.tif", "plan_operating_floor_s9.tif", None)],
     "reference": False, "text": "Layout model of the turbine-generator support (pedestal), the machines on it and "
                                 "the operating floor."},
]


def hard_examples(w):
    """Real drawings (public domain) copied from downloads/hard when present;
    an existing copy in examples/ is kept otherwise."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    src_root = ROOT / "downloads" / "hard"
    out = []
    for ex in HARD:
        d = EX / ex["id"]
        d.mkdir(parents=True, exist_ok=True)
        names = []
        for src, name, jpeg_q in ex["files"]:
            dst = d / name
            s = src_root / src
            if s.exists() and not dst.exists():
                if jpeg_q:
                    Image.open(s).convert("L").save(dst, quality=jpeg_q, optimize=True)
                else:
                    shutil.copyfile(s, dst)
            if dst.exists():
                names.append(f"{ex['id']}/{name}")
        if not names:
            print(f"{ex['id']:15s} skipped (drawing not found)")
            continue
        (d / "SOURCE.txt").write_text(HAER + "\n", encoding="utf-8")
        entry = {"id": ex["id"], "title": ex["title"], "description": ex["description"], "drawing": names[0],
                 "drawings": names, "text": ex["text"], "hard": True, "mode": "assembly", "source": HAER}
        ref = d / "reference.py"
        if ex["reference"] and ref.exists():
            build = d / "_build"
            r = w.build(ref.read_text(encoding="utf-8"), build, name=ex["id"], views=["iso"], timeout=900)
            if not r.get("ok"):
                raise SystemExit(f"{ex['id']}: reference does not build: {r.get('error')}")
            shutil.copyfile(build / "view_iso.png", d / "thumb.png")
            shutil.rmtree(build, ignore_errors=True)
            entry.update(reference=f"{ex['id']}/reference.py", thumb=f"{ex['id']}/thumb.png",
                         truth={"size": r["metrics"]["size"], "volume": r["metrics"]["volume"],
                                "solids": r["metrics"]["solids"], "parts": r["metrics"]["parts"]})
        else:
            im = Image.open(EX / names[0])
            im.thumbnail((640, 640))
            im.convert("L").save(d / "thumb.png")
            entry["thumb"] = f"{ex['id']}/thumb.png"
        out.append(entry)
        print(f"{ex['id']:15s} real  {len(names)} sheet(s)" + (f", reference {entry['truth']['size']}" if "truth" in entry else ""))
    return out


if __name__ == "__main__":
    main()
