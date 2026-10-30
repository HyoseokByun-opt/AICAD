"""AICAD modelling library: building blocks for plant structures, equipment
and machines, available to model code as `lib` (import aicad_lib as lib).

Everything is in millimetres, Z up, in global coordinates, so that a
component can be placed straight from the plan and elevation values of a
drawing. Each function returns a CadQuery Workplane holding one solid or a
compound of solids; large structures are compounds of members (no slow
boolean union of hundreds of members).

    units         ft(18, 10.5)  inch(3)  ftin("18'-10 1/2\\"")
    primitives    box  box_c  cyl  tube  cone  sphere  prism  extrude_on  revolve  plate
    steel         member  frame  profile  grating  handrail  ladder  stair
    piping        pipe  flange  nozzle  elbow
    vessels       vessel  dish
    machines      blade_row  bolt_holes  polar  linear
    assembly      compound  assemble
"""
from __future__ import annotations

import math
import re

import cadquery as cq

# =================================================================== units
INCH = 25.4


def inch(x):
    return float(x) * INCH


def ft(feet=0.0, inches=0.0):
    return (float(feet) * 12.0 + float(inches)) * INCH


from .units import _num, parse_length as _parse_length  # noqa: E402


def ftin(text) -> float:
    """Feet-and-inches (or any length) as written on a drawing, in mm:
    18'-10 1/2"  ->  5753.1    21'-0"  ->  6400.8    7 3/4"  ->  196.85    EL. 59'-6" -> 18135.6"""
    v = _parse_length(text, "ft-in")
    if v is None:
        raise ValueError(f"no length in '{text}'")
    return round(v, 3)


# =================================================================== vectors
_DIRS = {"x": (1, 0, 0), "+x": (1, 0, 0), "-x": (-1, 0, 0), "y": (0, 1, 0), "+y": (0, 1, 0), "-y": (0, -1, 0),
         "z": (0, 0, 1), "+z": (0, 0, 1), "-z": (0, 0, -1), "up": (0, 0, 1), "down": (0, 0, -1),
         "east": (1, 0, 0), "west": (-1, 0, 0), "north": (0, 1, 0), "south": (0, -1, 0)}


def _v(p):
    """A point or direction: (x, y, z), (x, y), a Vector, or a direction word ('up', '-x', 'north', ...)."""
    if isinstance(p, cq.Vector):
        return p
    if isinstance(p, str):
        if p.strip().lower() not in _DIRS:
            raise ValueError(f"unknown direction '{p}': give (x, y, z) or one of {', '.join(sorted(_DIRS))}")
        return cq.Vector(*_DIRS[p.strip().lower()])
    return cq.Vector(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)


def _frame(d):
    """Unit axes (x, y) of a section perpendicular to direction d; y is the
    'up' of the section: global Z for horizontal and sloped members, global Y
    for vertical ones."""
    d = d.normalized()
    up = cq.Vector(0, 0, 1) if abs(d.z) < 0.995 else cq.Vector(0, 1, 0)
    y = (up - d * up.dot(d)).normalized()
    x = y.cross(d).normalized()
    return x, y


def _wp(origin, d, roll=0.0):
    x, y = _frame(d)
    if roll:
        a = math.radians(roll)
        x, y = x * math.cos(a) + y * math.sin(a), y * math.cos(a) - x * math.sin(a)
    return cq.Workplane(cq.Plane(origin=origin, xDir=x, normal=d.normalized()))


# =================================================================== primitives
def box(x0, y0, z0, x1, y1, z1):
    """Axis-aligned box between two corners."""
    lx, ly, lz = abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)
    return cq.Workplane("XY").box(lx, ly, lz).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


def box_c(cx, cy, cz, lx, ly, lz):
    """Box by centre and size."""
    return cq.Workplane("XY").box(lx, ly, lz).translate((cx, cy, cz))


def cyl(p0, p1, d):
    """Solid cylinder of diameter d from point p0 to point p1."""
    a, b = _v(p0), _v(p1)
    return _wp(a, b - a).circle(d / 2).extrude((b - a).Length)


def tube(p0, p1, od, t):
    """Hollow cylinder (pipe) of outside diameter od and wall t."""
    a, b = _v(p0), _v(p1)
    w = _wp(a, b - a).circle(od / 2)
    if 0 < t < od / 2:
        w = w.circle(od / 2 - t)
    return w.extrude((b - a).Length)


def cone(p0, p1, d0, d1):
    """Truncated cone from diameter d0 at p0 to d1 at p1."""
    a, b = _v(p0), _v(p1)
    s = cq.Solid.makeCone(d0 / 2, max(d1 / 2, 1e-6), (b - a).Length, a, (b - a).normalized())
    return cq.Workplane().add(s)


def sphere(c, d):
    return cq.Workplane().add(cq.Solid.makeSphere(d / 2, _v(c), angleDegrees1=-90, angleDegrees2=90))


def prism(points_xy, z0, z1):
    """A plan outline (list of (x, y)) extruded from elevation z0 to z1:
    slabs, foundations, pedestals, walls in plan."""
    pts = [(float(x), float(y)) for x, y in points_xy]
    return cq.Workplane("XY", origin=(0, 0, min(z0, z1))).polyline(pts).close().extrude(abs(z1 - z0))


def extrude_on(plane, points, d0=None, d1=None, **kw):
    """An outline drawn in an elevation or section, extruded across it.
    plane 'XZ': points are (x, z), extruded from y=d0 to y=d1;
    plane 'YZ': points are (y, z), extruded from x=d0 to x=d1;
    plane 'XY': points are (x, y), extruded from z=d0 to z=d1.
    The limits may also be given by the name of the axis: y0=..., y1=... (or x0/x1, z0/z1)."""
    ax = {"XZ": "y", "YZ": "x", "XY": "z"}.get(plane.upper(), "y")
    d0 = kw.pop(ax + "0", d0)
    d1 = kw.pop(ax + "1", d1)
    if d0 is None or d1 is None or kw:
        raise TypeError(f"extrude_on('{plane}', points, {ax}0, {ax}1): give the two limits along {ax.upper()}"
                        + (f"; unknown arguments {sorted(kw)}" if kw else ""))
    pts = [(float(a), float(b)) for a, b in points]
    lo, hi = min(d0, d1), max(d0, d1)
    if plane.upper() == "XY":
        return prism(pts, lo, hi)
    if plane.upper() == "XZ":
        # Workplane XZ extrudes towards -Y: start at y = hi and extrude hi - lo
        return cq.Workplane("XZ", origin=(0, hi, 0)).polyline(pts).close().extrude(hi - lo)
    if plane.upper() == "YZ":
        return cq.Workplane("YZ", origin=(lo, 0, 0)).polyline(pts).close().extrude(hi - lo)
    raise ValueError("plane must be XY, XZ or YZ")


def revolve(profile_rz, origin=(0, 0, 0), axis="z", angle=360):
    """Axisymmetric solid from a half section: points (r, h) with r >= 0 the
    distance from the axis and h the position along it (turbines, pumps,
    vessels, shafts, casings drawn as half sections)."""
    pts = [(max(0.0, float(r)), float(h)) for r, h in profile_rz]
    s = cq.Workplane("XZ").polyline(pts).close().revolve(angle, (0, 0, 0), (0, 1, 0))
    o = _v(origin)
    ax = axis.lower() if isinstance(axis, str) else axis
    if ax == "x":
        s = s.rotate((0, 0, 0), (0, 1, 0), 90)
    elif ax == "y":
        s = s.rotate((0, 0, 0), (1, 0, 0), -90)
    return s.translate((o.x, o.y, o.z))


def plate(points_xy, t, z=0.0):
    """Horizontal plate of thickness t with its underside at elevation z."""
    return prism(points_xy, z, z + t)


# =================================================================== steel sections
# metric tables: h, b, tw, tf (mm)
_HEB = {100: (100, 100, 6, 10), 120: (120, 120, 6.5, 11), 140: (140, 140, 7, 12), 160: (160, 160, 8, 13),
        180: (180, 180, 8.5, 14), 200: (200, 200, 9, 15), 220: (220, 220, 9.5, 16), 240: (240, 240, 10, 17),
        260: (260, 260, 10, 17.5), 280: (280, 280, 10.5, 18), 300: (300, 300, 11, 19), 320: (320, 300, 11.5, 20.5),
        340: (340, 300, 12, 21.5), 360: (360, 300, 12.5, 22.5), 400: (400, 300, 13.5, 24), 450: (450, 300, 14, 26),
        500: (500, 300, 14.5, 28), 600: (600, 300, 15.5, 30)}
_HEA = {100: (96, 100, 5, 8), 120: (114, 120, 5, 8), 140: (133, 140, 5.5, 8.5), 160: (152, 160, 6, 9),
        180: (171, 180, 6, 9.5), 200: (190, 200, 6.5, 10), 220: (210, 220, 7, 11), 240: (230, 240, 7.5, 12),
        260: (250, 260, 7.5, 12.5), 280: (270, 280, 8, 13), 300: (290, 300, 8.5, 14), 400: (390, 300, 11, 19),
        500: (490, 300, 12, 23), 600: (590, 300, 13, 25)}
_IPE = {80: (80, 46, 3.8, 5.2), 100: (100, 55, 4.1, 5.7), 120: (120, 64, 4.4, 6.3), 140: (140, 73, 4.7, 6.9),
        160: (160, 82, 5, 7.4), 180: (180, 91, 5.3, 8), 200: (200, 100, 5.6, 8.5), 220: (220, 110, 5.9, 9.2),
        240: (240, 120, 6.2, 9.8), 270: (270, 135, 6.6, 10.2), 300: (300, 150, 7.1, 10.7), 330: (330, 160, 7.5, 11.5),
        360: (360, 170, 8, 12.7), 400: (400, 180, 8.6, 13.5), 450: (450, 190, 9.4, 14.6), 500: (500, 200, 10.2, 16),
        550: (550, 210, 11.1, 17.2), 600: (600, 220, 12, 19)}
_UPN = {80: (80, 45, 6, 8), 100: (100, 50, 6, 8.5), 120: (120, 55, 7, 9), 140: (140, 60, 7, 10), 160: (160, 65, 7.5, 10.5),
        180: (180, 70, 8, 11), 200: (200, 75, 8.5, 11.5), 220: (220, 80, 9, 12.5), 240: (240, 85, 9.5, 13),
        260: (260, 90, 10, 14), 280: (280, 95, 10, 15), 300: (300, 100, 10, 16), 400: (400, 110, 14, 18)}
# US wide flange (inches): d, bf, tw, tf
_W = {"W4X13": (4.16, 4.06, .28, .345), "W6X15": (5.99, 5.99, .23, .26), "W6X25": (6.38, 6.08, .32, .455),
      "W8X18": (8.14, 5.25, .23, .33), "W8X31": (8.0, 8.0, .285, .435), "W8X40": (8.25, 8.07, .36, .56),
      "W10X22": (10.17, 5.75, .24, .36), "W10X33": (9.73, 7.96, .29, .435), "W10X49": (10.0, 10.0, .34, .56),
      "W12X26": (12.22, 6.49, .23, .38), "W12X40": (11.94, 8.0, .295, .515), "W12X65": (12.12, 12.0, .39, .605),
      "W14X30": (13.84, 6.73, .27, .385), "W14X48": (13.79, 8.03, .34, .595), "W14X90": (14.02, 14.52, .44, .71),
      "W16X40": (16.01, 7.0, .305, .505), "W16X57": (16.43, 7.12, .43, .715), "W18X50": (17.99, 7.5, .355, .57),
      "W18X76": (18.21, 11.04, .425, .68), "W21X62": (20.99, 8.24, .4, .615), "W21X101": (21.36, 12.29, .5, .8),
      "W24X76": (23.92, 8.99, .44, .68), "W24X104": (24.06, 12.75, .5, .75), "W27X94": (26.92, 9.99, .49, .745),
      "W30X108": (29.83, 10.48, .545, .76), "W33X130": (33.09, 11.51, .58, .855), "W36X150": (35.85, 11.98, .625, .94)}


def profile(name: str) -> dict:
    """Section dimensions (mm) from a designation. Understood:
    H300x300x10x15, I400x200x8x13, HEB300, HEA300, IPE300, W14x30 (US),
    C200x80x7.5x11, UPN200, L100x100x10, L4x4x1/2 (inches), PIPE168.3x7.1 / CHS,
    SHS100x100x6, RHS200x100x6, BOX400x300x12, FB100x10, ROD50, PL300x20."""
    n = name.upper().replace(" ", "").replace("×", "X").replace("*", "X")
    nums = [float(_num(x)) for x in re.findall(r"\d+(?:\.\d+)?(?:-\d+/\d+)?|\d+/\d+", n)]
    k = re.match(r"[A-Z]+", n).group(0) if re.match(r"[A-Z]+", n) else ""
    if k in ("HEB", "HEA", "IPE", "UPN"):
        tab = {"HEB": _HEB, "HEA": _HEA, "IPE": _IPE, "UPN": _UPN}[k]
        key = min(tab, key=lambda s: abs(s - nums[0]))
        h, b, tw, tf = tab[key]
        return {"kind": "C" if k == "UPN" else "I", "h": h, "b": b, "tw": tw, "tf": tf}
    if k == "W":
        if n in _W:
            d, bf, tw, tf = _W[n]
        else:   # unlisted: proportions of the nominal depth (approximate)
            d = nums[0]
            bf, tw, tf = d * 0.55, max(0.23, d * 0.025), max(0.35, d * 0.04)
        return {"kind": "I", "h": d * INCH, "b": bf * INCH, "tw": tw * INCH, "tf": tf * INCH}
    if k in ("H", "I", "HW", "HM", "HN", "HP", "IB"):
        h, b = nums[0], nums[1] if len(nums) > 1 else nums[0]
        tw = nums[2] if len(nums) > 2 else max(5, h * 0.03)
        tf = nums[3] if len(nums) > 3 else max(7, h * 0.05)
        return {"kind": "I", "h": h, "b": b, "tw": tw, "tf": tf}
    if k in ("C", "U", "CH", "MC"):
        imperial = nums[0] < 20 and len(nums) <= 2
        if imperial:    # C12x20.7: depth in inches, proportions approximate
            d = nums[0] * INCH
            return {"kind": "C", "h": d, "b": d * 0.27, "tw": d * 0.03, "tf": d * 0.045}
        h, b = nums[0], nums[1] if len(nums) > 1 else nums[0] * 0.4
        tw = nums[2] if len(nums) > 2 else max(5, h * 0.035)
        tf = nums[3] if len(nums) > 3 else max(7, h * 0.055)
        return {"kind": "C", "h": h, "b": b, "tw": tw, "tf": tf}
    if k == "L":
        imperial = max(nums) < 12
        f = INCH if imperial else 1.0
        a = nums[0] * f
        b = (nums[1] if len(nums) > 2 else nums[0]) * f
        t = nums[-1] * f
        return {"kind": "L", "h": a, "b": b, "t": t}
    if k in ("PIPE", "CHS", "P", "TUBE", "OD"):
        od = nums[0]
        t = nums[1] if len(nums) > 1 else max(3, od * 0.06)
        return {"kind": "O", "d": od, "t": t}
    if k in ("SHS", "RHS", "BOX", "HSS", "SQ"):
        if len(nums) == 2:
            h = b = nums[0]
            t = nums[1]
        else:
            h, b = nums[0], nums[1] if len(nums) > 1 else nums[0]
            t = nums[2] if len(nums) > 2 else max(3, h * 0.05)
        return {"kind": "R", "h": h, "b": b, "t": t}
    if k in ("FB", "FL", "PL", "FLAT"):
        b, t = nums[0], nums[1] if len(nums) > 1 else 10
        return {"kind": "B", "h": min(b, t), "b": max(b, t)} if k == "PL" else {"kind": "B", "h": t, "b": b}
    if k in ("ROD", "RB", "BAR", "D"):
        return {"kind": "O", "d": nums[0], "t": 0}
    raise ValueError(f"unknown section designation '{name}'")


def _section(wp, p, align="center"):
    """Draw the section on a workplane (local x across, local y up)."""
    kind = p["kind"]
    h = p.get("h", p.get("d", 0))
    dy = {"center": 0.0, "top": -h / 2, "bottom": h / 2}.get(align, 0.0)
    if kind == "I":
        h, b, tw, tf = p["h"], p["b"], p["tw"], p["tf"]
        pts = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -h / 2 + tf), (tw / 2, -h / 2 + tf), (tw / 2, h / 2 - tf),
               (b / 2, h / 2 - tf), (b / 2, h / 2), (-b / 2, h / 2), (-b / 2, h / 2 - tf), (-tw / 2, h / 2 - tf),
               (-tw / 2, -h / 2 + tf), (-b / 2, -h / 2 + tf)]
    elif kind == "C":
        h, b, tw, tf = p["h"], p["b"], p["tw"], p["tf"]
        pts = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -h / 2 + tf), (-b / 2 + tw, -h / 2 + tf),
               (-b / 2 + tw, h / 2 - tf), (b / 2, h / 2 - tf), (b / 2, h / 2), (-b / 2, h / 2)]
    elif kind == "L":
        a, b, t = p["h"], p["b"], p["t"]
        pts = [(-b / 2, -a / 2), (b / 2, -a / 2), (b / 2, -a / 2 + t), (-b / 2 + t, -a / 2 + t), (-b / 2 + t, a / 2),
               (-b / 2, a / 2)]
    elif kind == "B":
        b, t = p["b"], p["h"]
        pts = [(-b / 2, -t / 2), (b / 2, -t / 2), (b / 2, t / 2), (-b / 2, t / 2)]
    elif kind == "O":
        w = wp.center(0, dy).circle(p["d"] / 2)
        if p.get("t") and 0 < p["t"] < p["d"] / 2:
            w = w.circle(p["d"] / 2 - p["t"])
        return w
    elif kind == "R":
        w = wp.center(0, dy).rect(p["b"], p["h"])
        if 0 < p["t"] < min(p["b"], p["h"]) / 2:
            w = w.rect(p["b"] - 2 * p["t"], p["h"] - 2 * p["t"])
        return w
    else:
        raise ValueError(kind)
    return wp.polyline([(x, y + dy) for x, y in pts]).close()


def member(section, p0, p1, roll=0.0, align="center"):
    """A steel member of the given section from p0 to p1 (beam, column,
    brace, chord). The web is vertical for horizontal and sloped members and
    the flanges face +/-Y for vertical members; roll turns the section about
    the member axis (degrees). align='top' puts the line p0-p1 on the top of
    the section (beams referenced to top of steel)."""
    a, b = _v(p0), _v(p1)
    d = b - a
    if d.Length < 1e-6:
        raise ValueError("member of zero length")
    p = profile(section) if isinstance(section, str) else section
    return _section(_wp(a, d, roll), p, align).extrude(d.Length)


def frame(nodes: dict, members: list, default_section=None):
    """A structure from node coordinates and a member list:
    nodes = {"A1": (0, 0, 0), "A1t": (0, 0, 6000), ...}
    members = [("A1", "A1t", "HEB300"), ("A1t", "B1t", "IPE400", 0, "top"), ...]
    (from, to, section[, roll[, align]]). Returns a compound of all members."""
    out = []
    for m in members:
        n0, n1 = m[0], m[1]
        sec = m[2] if len(m) > 2 and m[2] else default_section
        roll = m[3] if len(m) > 3 else 0.0
        align = m[4] if len(m) > 4 else "center"
        out.append(member(sec, nodes[n0], nodes[n1], roll, align).val())
    return cq.Workplane().add(cq.Compound.makeCompound(out))


def grating(x0, y0, x1, y1, z, t=30):
    """Floor grating / chequer plate panel, top surface at elevation z."""
    return box(x0, y0, z - t, x1, y1, z)


def handrail(points, h=1100, post_spacing=1500, d=42.7):
    """Handrail along a polyline at floor level: posts, top and mid rails."""
    pts = [_v(p) for p in points]
    parts = []
    for a, b in zip(pts[:-1], pts[1:]):
        L = (b - a).Length
        n = max(1, int(math.ceil(L / post_spacing)))
        for i in range(n + 1):
            q = a + (b - a) * (i / n)
            parts.append(cyl((q.x, q.y, q.z), (q.x, q.y, q.z + h), d).val())
        for zz in (h, h / 2):
            parts.append(cyl((a.x, a.y, a.z + zz), (b.x, b.y, b.z + zz), d).val())
    return cq.Workplane().add(cq.Compound.makeCompound(parts))


def ladder(base, top_z, width=450, rung_spacing=300, side="FB65x10", rung_d=22):
    """Vertical ladder with its centre at base (x, y, z) facing +Y, up to top_z."""
    x, y, z = base
    parts = [member(side, (x - width / 2, y, z), (x - width / 2, y, top_z)).val(),
             member(side, (x + width / 2, y, z), (x + width / 2, y, top_z)).val()]
    zz = z + rung_spacing
    while zz < top_z - 50:
        parts.append(cyl((x - width / 2, y, zz), (x + width / 2, y, zz), rung_d).val())
        zz += rung_spacing
    return cq.Workplane().add(cq.Compound.makeCompound(parts))


def stair(p0, p1, width=900, stringer="C200x75x8.5x11.5", tread_t=30):
    """Straight stair from p0 (bottom nosing line centre) to p1 (top), two
    stringers and treads at about 180 mm rise."""
    a, b = _v(p0), _v(p1)
    d = b - a
    run = cq.Vector(d.x, d.y, 0)
    if run.Length < 1:
        raise ValueError("a stair needs a horizontal run")
    side = cq.Vector(-run.y, run.x, 0).normalized() * (width / 2)
    parts = [member(stringer, a + side, b + side).val(), member(stringer, a - side, b - side).val()]
    n = max(2, int(round(abs(d.z) / 180)))
    for i in range(1, n):
        c = a + d * (i / n)
        # a tread: flat bar across the stair, 250 deep along the run, tread_t thick
        parts.append(member(f"FB250x{tread_t}", (c - side * 0.98).toTuple(), (c + side * 0.98).toTuple()).val())
    return cq.Workplane().add(cq.Compound.makeCompound(parts))


# =================================================================== piping and vessels
def pipe(points, od, t=None, bend=True):
    """A pipe through a list of points; joints get a sphere as a simplified
    elbow so the run stays closed."""
    pts = [_v(p) for p in points]
    parts = []
    for a, b in zip(pts[:-1], pts[1:]):
        if (b - a).Length > 1e-6:
            seg = tube(a.toTuple(), b.toTuple(), od, t) if t else cyl(a.toTuple(), b.toTuple(), od)
            parts.append(seg.val())
    if bend:
        for q in pts[1:-1]:
            parts.append(sphere(q.toTuple(), od).val())
    return cq.Workplane().add(cq.Compound.makeCompound(parts))


def flange(center, direction, od, t, bore=0.0, pcd=None, n_bolts=0, bolt_d=0.0):
    """A flange disc on an axis, its face at `center`, thickness along direction."""
    a = _v(center)
    d = _v(direction).normalized()
    wp = _wp(a, d).circle(od / 2)
    if bore:
        wp = wp.circle(bore / 2)
    f = wp.extrude(t)
    if pcd and n_bolts and bolt_d:
        f = f.cut(bolt_holes(center, direction, pcd, n_bolts, bolt_d, t))
    return f


def nozzle(base, direction, od, length, flange_od=None, flange_t=None, t=None):
    """A nozzle (pipe stub) from base along direction, with an optional flange at its end."""
    a = _v(base)
    d = _v(direction).normalized()
    e = a + d * length
    n = (tube(a.toTuple(), e.toTuple(), od, t) if t else cyl(a.toTuple(), e.toTuple(), od))
    if flange_od:
        ft_ = flange_t or max(15.0, od * 0.12)
        n = n.union(flange((e - d * ft_).toTuple(), d.toTuple(), flange_od, ft_, bore=(od - 2 * t) if t else 0))
    return n


def elbow(corner, d_in, d_out, od, bend_r=None):
    """A 90-degree style elbow is approximated by a sphere at the corner."""
    return sphere(corner, od)


def dish(center, d, h, direction=(0, 0, 1)):
    """An ellipsoidal or hemispherical head of diameter d and height h, its
    flat side at center, bulging along direction."""
    s = cq.Solid.makeSphere(1.0, angleDegrees1=0, angleDegrees2=90)
    s = s.transformGeometry(cq.Matrix([[d / 2, 0, 0, 0], [0, d / 2, 0, 0], [0, 0, h, 0]]))
    w = cq.Workplane().add(s)
    dd = _v(direction).normalized()
    z = cq.Vector(0, 0, 1)
    if (dd - z).Length > 1e-9:
        if (dd + z).Length < 1e-9:
            w = w.rotate((0, 0, 0), (1, 0, 0), 180)
        else:
            ax = z.cross(dd)
            ang = math.degrees(math.acos(max(-1.0, min(1.0, z.dot(dd)))))
            w = w.rotate((0, 0, 0), ax.toTuple(), ang)
    c = _v(center)
    return w.translate(c.toTuple())


def vessel(base, d, h, head="2:1", axis="z", top=True, bottom=True, t=None):
    """A cylindrical vessel: shell of diameter d and straight height h starting
    at `base` (centre of the bottom tangent line), heads '2:1' (ellipsoidal),
    'hemi', 'torispherical' (approx.), 'cone' or 'flat'. With a wall
    thickness t the vessel is hollow (needed for a shell analysis model);
    without it, it is a solid envelope."""
    body = _vessel_solid(base, d, h, head, axis, top, bottom)
    if t and 0 < t < d / 4:
        # hollow: the inner body is the same vessel, t smaller all round (the heads t lower)
        dv = _v({"z": (0, 0, 1), "x": (1, 0, 0), "y": (0, 1, 0)}[axis.lower()])
        hh = _head_height(head, d)
        b, hi = _v(base), h
        if hh <= 0:              # flat ends: the inner cavity stops t short of each closed end
            if bottom:
                b, hi = b + dv * t, hi - t
            if top:
                hi -= t
        inner = _vessel_solid(b.toTuple(), d - 2 * t, hi, head, axis, top, bottom, hh=max(hh - t, 0.0) if hh > 0 else 0.0)
        try:
            return body.cut(inner)
        except Exception:  # noqa: BLE001 - fall back to the solid envelope
            return body
    return body


def _head_height(head, d):
    return {"2:1": d / 4, "hemi": d / 2, "torispherical": d * 0.2, "cone": d * 0.4, "flat": 0}.get(head, d / 4)


def _vessel_solid(base, d, h, head, axis, top, bottom, hh=None):
    b = _v(base)
    dirs = {"z": (0, 0, 1), "x": (1, 0, 0), "y": (0, 1, 0)}
    dv = _v(dirs[axis.lower()])
    top_c = b + dv * h
    body = cyl(b.toTuple(), top_c.toTuple(), d)
    if hh is None:
        hh = _head_height(head, d)
    if hh > 0:
        if head == "cone":
            if top:
                body = body.union(cone(top_c.toTuple(), (top_c + dv * hh).toTuple(), d, d * 0.15))
            if bottom:
                body = body.union(cone(b.toTuple(), (b - dv * hh).toTuple(), d, d * 0.15))
        else:
            if top:
                body = body.union(dish(top_c.toTuple(), d, hh, dv.toTuple()))
            if bottom:
                body = body.union(dish(b.toTuple(), d, hh, (-dv).toTuple()))
    return body


# =================================================================== machines
def bolt_holes(center, direction, pcd, n, d, length, start_angle=0.0):
    """Cutting tools for n holes of diameter d on a bolt circle, to subtract with .cut()."""
    a = _v(center)
    dd = _v(direction).normalized()
    x, y = _frame(dd)
    tools = []
    for i in range(int(n)):
        ang = math.radians(start_angle + 360.0 * i / n)
        c = a + (x * math.cos(ang) + y * math.sin(ang)) * (pcd / 2) - dd * 0.01 * length
        tools.append(cyl(c.toTuple(), (c + dd * length * 1.02).toTuple(), d).val())
    return cq.Workplane().add(cq.Compound.makeCompound(tools))


def polar(shape, n, origin=(0, 0, 0), axis=(0, 0, 1), start_angle=0.0):
    """n copies of a shape rotated about an axis (as one compound)."""
    w = shape if isinstance(shape, cq.Workplane) else cq.Workplane().add(shape)
    base = w.val()
    o, ax = _v(origin), _v(axis)
    out = [base.rotate(o, o + ax, start_angle + 360.0 * i / n) for i in range(int(n))]
    return cq.Workplane().add(cq.Compound.makeCompound(out))


def linear(shape, n, step):
    """n copies of a shape, each moved by `step` (x, y, z) from the previous one."""
    w = shape if isinstance(shape, cq.Workplane) else cq.Workplane().add(shape)
    base = w.val()
    s = _v(step)
    return cq.Workplane().add(cq.Compound.makeCompound([base.translate(s * i) for i in range(int(n))]))


def _airfoil(chord, thick, n=24):
    """Symmetric 4-digit airfoil outline (chord along x, centred)."""
    pts_u, pts_l = [], []
    for i in range(n + 1):
        xc = (1 - math.cos(math.pi * i / n)) / 2
        yt = 5 * thick * (0.2969 * math.sqrt(xc) - 0.126 * xc - 0.3516 * xc ** 2 + 0.2843 * xc ** 3 - 0.1036 * xc ** 4)
        pts_u.append(((xc - 0.5) * chord, yt * chord))
        pts_l.append(((xc - 0.5) * chord, -yt * chord))
    pts = pts_u + pts_l[::-1][1:-1]
    # drop near-duplicate points at the trailing edge
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) > 1e-6 * chord:
            out.append(p)
    return out


def blade_row(origin, n, r_hub, r_tip, height, stagger=30.0, twist=0.0, thickness=0.12,
              axis="z", start_angle=0.0):
    """A row of n blades between radius r_hub and r_tip (turbine runner,
    guide vanes, pump impeller, fan): each blade an airfoil whose chord is
    set at `stagger` degrees to the axis so that the row spans `height`
    along the axis, twisted by `twist` degrees from hub to tip. The row
    starts at `origin` and extends along +axis. Simplified for layout models."""
    o = _v(origin)
    ang0 = math.radians(stagger)
    chord = height / max(math.cos(ang0), 0.2)
    prof = _airfoil(chord, thickness)
    span = r_tip - r_hub

    def section(ang):
        # (tangential, axial) coordinates of the airfoil turned by ang from the axis
        pts = [(x * math.sin(ang) + y * math.cos(ang), x * math.cos(ang) - y * math.sin(ang) + height / 2)
               for x, y in prof]
        return pts
    # blade along +X (radial); section in the YZ plane (y tangential, z axial)
    w = cq.Workplane("YZ", origin=(r_hub, 0, 0)).polyline(section(ang0)).close()
    w = w.workplane(offset=span).polyline(section(math.radians(stagger + twist))).close()
    blade = w.loft(ruled=True).val()
    blades = [blade.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), start_angle + 360.0 * i / n) for i in range(int(n))]
    c = cq.Compound.makeCompound(blades)
    ax = axis.lower() if isinstance(axis, str) else "z"
    if ax == "x":
        c = c.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 90)
    elif ax == "y":
        c = c.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), -90)
    return cq.Workplane().add(c.translate(o))


def _section_wire(center, d, sec, xdir=None):
    """A closed wire: ('circle', diameter) or ('rect', width, height) in the
    plane through `center` normal to d (width along the plane's x axis)."""
    c, n = _v(center), _v(d).normalized()
    x, y = _frame(n) if xdir is None else (_v(xdir).normalized(), n.cross(_v(xdir).normalized()).normalized())
    if sec[0] == "circle":
        return cq.Wire.makeCircle(sec[1] / 2, c, n)
    w, h = sec[1] / 2, sec[2] / 2
    pts = [c + x * sx * w + y * sy * h for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return cq.Wire.makePolygon(pts + pts[:1])


def transition(p0, sec0, p1, sec1):
    """A transition piece between two sections, lofted: draft tubes, duct
    pieces, hoppers, reducers. sec = ('circle', d) or ('rect', w, h); the
    sections lie normal to the line p0-p1."""
    a, b = _v(p0), _v(p1)
    d = b - a
    w0, w1 = _section_wire(a, d, sec0), _section_wire(b, d, sec1)
    return cq.Workplane().add(cq.Solid.makeLoft([w0, w1], True))


def spiral_case(origin, inlet_d, r_stay, axis="z", n=12, wrap=345.0, start_angle=0.0, inlet_length=None):
    """Spiral casing (volute) of a turbine or pump around an axis: circular
    sections whose area falls linearly from inlet_d at the inlet to almost
    nothing after `wrap` degrees, their inner edge on the stay-ring radius
    r_stay; a straight inlet pipe of length inlet_length (default inlet_d)."""
    o = _v(origin)
    wires = []
    for k in range(n + 1):
        th = math.radians(start_angle + wrap * k / n)
        dk = inlet_d * math.sqrt(max(1.0 - 0.9 * k / n, 0.05))
        rc = r_stay + dk / 2
        radial = cq.Vector(math.cos(th), math.sin(th), 0)
        tang = cq.Vector(-math.sin(th), math.cos(th), 0)
        wires.append(cq.Wire.makeCircle(dk / 2, radial * rc, tang))
    case = cq.Solid.makeLoft(wires, False)
    # straight inlet ending in the first section, coming from the -tangent side
    th0 = math.radians(start_angle)
    radial0 = cq.Vector(math.cos(th0), math.sin(th0), 0)
    tang0 = cq.Vector(-math.sin(th0), math.cos(th0), 0)
    c0 = radial0 * (r_stay + inlet_d / 2)
    L = inlet_length or inlet_d
    inlet = cq.Solid.makeCylinder(inlet_d / 2, L, c0 - tang0 * L, tang0)
    s = cq.Workplane().add(case).union(cq.Workplane().add(inlet))
    ax = axis.lower() if isinstance(axis, str) else "z"
    if ax == "x":
        s = s.rotate((0, 0, 0), (0, 1, 0), 90)
    elif ax == "y":
        s = s.rotate((0, 0, 0), (1, 0, 0), -90)
    return s.translate(o.toTuple())


# =================================================================== editing
# Features added by the user in the program (command line / feature tree).
# Faces and edges are found by the point the user clicked, not by an index,
# so a feature still finds its face when the model before it changes.

def _shape(t):
    if isinstance(t, cq.Workplane):
        vals = [v for v in t.vals() if isinstance(v, cq.Shape)]
        return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    return t


def _wp_of(s):
    return s if isinstance(s, cq.Workplane) else cq.Workplane().add(s)


def nearest_face(target, point):
    s = _shape(target)
    p = _v(point)
    return min(s.Faces(), key=lambda f: f.distance(cq.Vertex.makeVertex(p.x, p.y, p.z)))


def nearest_edges(target, points):
    s = _shape(target)
    out = []
    for q in points:
        p = _v(q)
        v = cq.Vertex.makeVertex(p.x, p.y, p.z)
        e = min(s.Edges(), key=lambda e: e.distance(v))
        if not any(e.isSame(o) for o in out):
            out.append(e)
    return out


def _tools(point, normal, make, count=1, pitch=(0, 0, 0)):
    p, n, st = _v(point), _v(normal).normalized(), _v(pitch)
    out = []
    for i in range(max(1, int(count))):
        out.append(make(p + st * i, n))
    return cq.Compound.makeCompound(out)


def f_hole(target, point, normal, d, depth=0.0, cbore_d=0.0, cbore_depth=0.0, count=1, pitch=(0, 0, 0)):
    """Hole of diameter d into the face at `point` (normal pointing out of the
    material); depth 0 = through all. Optional counterbore and a row of
    `count` holes, each `pitch` (x, y, z) from the previous one."""
    s = _shape(target)
    L = depth if depth and depth > 0 else s.BoundingBox().DiagonalLength * 2

    def make(c, n):
        tool = cq.Solid.makeCylinder(d / 2, L + 0.5, c + n * 0.5, -n)
        if cbore_d and cbore_depth:
            tool = tool.fuse(cq.Solid.makeCylinder(cbore_d / 2, cbore_depth + 0.5, c + n * 0.5, -n))
        return tool
    return _wp_of(s.cut(_tools(point, normal, make, count, pitch)))


def _profile_solid(c, n, shape, w, h, length, angle=0.0):
    x, y = _frame(n)
    if angle:
        a = math.radians(angle)
        x, y = x * math.cos(a) + y * math.sin(a), y * math.cos(a) - x * math.sin(a)
    wp = cq.Workplane(cq.Plane(origin=c, xDir=x, normal=n))
    if shape == "circle":
        wp = wp.circle(w / 2)
    elif shape == "slot":
        wp = wp.slot2D(max(w, h), min(w, h), 0 if w >= h else 90)
    else:
        wp = wp.rect(w, h)
    return wp.extrude(length).val()


def f_boss(target, point, normal, w, h=None, height=10.0, shape="rect", angle=0.0, count=1, pitch=(0, 0, 0)):
    """A rectangular, round or slotted boss (pad) on the face at `point`,
    `height` out along the face normal."""
    s = _shape(target)
    hh = w if h is None else h
    tool = _tools(point, normal, lambda c, n: _profile_solid(c - n * 0.01, n, shape, w, hh, height + 0.01, angle),
                  count, pitch)
    return _wp_of(s.fuse(tool).clean())


def f_pocket(target, point, normal, w, h=None, depth=10.0, shape="rect", angle=0.0, count=1, pitch=(0, 0, 0)):
    """A rectangular, round or slotted pocket into the face at `point`, `depth` deep."""
    s = _shape(target)
    hh = w if h is None else h
    tool = _tools(point, normal, lambda c, n: _profile_solid(c + n * 0.5, -n, shape, w, hh, depth + 0.5, angle),
                  count, pitch)
    return _wp_of(s.cut(tool))


def f_fillet(target, points, r):
    """Round the edges nearest to the clicked points."""
    s = _shape(target)
    return _wp_of(s.fillet(r, nearest_edges(s, points)))


def f_chamfer(target, points, d):
    """Bevel the edges nearest to the clicked points."""
    s = _shape(target)
    return _wp_of(s.chamfer(d, None, nearest_edges(s, points)))


def f_shell(target, point, t):
    """Hollow the body to wall thickness t, opening the face at `point`."""
    s = _shape(target)
    sol = s.Solids()[0] if s.Solids() else s
    # through the Workplane: the face on the stack, the solid found from its parent
    return cq.Workplane().add(sol).newObject([nearest_face(sol, point)]).shell(-abs(t))


def f_union(target, tool):
    return _wp_of(_shape(target).fuse(_shape(tool)).clean())


def f_cut(target, tool):
    return _wp_of(_shape(target).cut(_shape(tool)))


def f_move(target, dx=0.0, dy=0.0, dz=0.0):
    return _wp_of(_shape(target).translate(cq.Vector(dx, dy, dz)))


def f_rotate(target, origin=(0, 0, 0), axis=(0, 0, 1), angle=0.0):
    o = _v(origin)
    return _wp_of(_shape(target).rotate(o, o + _v(axis), angle))


def f_mirror(target, origin=(0, 0, 0), normal=(1, 0, 0), keep=True):
    """Mirror about a plane through `origin` with `normal`; keep=True joins
    the mirror image to the original (symmetric part), False replaces it."""
    s = _shape(target)
    m = s.mirror(cq.Vector(*_v(normal).toTuple()), cq.Vector(*_v(origin).toTuple()))
    return _wp_of(s.fuse(m).clean() if keep else m)


def f_array(target, count=2, step=(100, 0, 0)):
    """Copies of the body in a row, each `step` from the previous one (one compound)."""
    s = _shape(target)
    st = _v(step)
    return _wp_of(cq.Compound.makeCompound([s.translate(st * i) for i in range(max(1, int(count)))]))


# ---- assemblies: edit one component, add or remove one
def _child(assy, name):
    for ch in assy.children:
        if ch.name == name:
            return ch
        sub = _child(ch, name)
        if sub is not None:
            return sub
    return None


def edit_part(assy, name, fn):
    """Apply fn (shape in global coordinates -> new shape) to one component."""
    ch = _child(assy, name)
    if ch is None:
        raise ValueError(f"the assembly has no component '{name}'")
    shapes = [v for v in (ch.obj.vals() if isinstance(ch.obj, cq.Workplane) else [ch.obj]) if isinstance(v, cq.Shape)]
    obj = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    new = _shape(fn(_wp_of(obj.moved(ch.loc))))
    ch.obj = new.moved(ch.loc.inverse)
    return assy


def add_part(assy, name, shape, color="gray"):
    assy.add(_shape(shape), name=name, color=cq.Color(color) if isinstance(color, str) else None)
    return assy


def remove_part(assy, name):
    ch = _child(assy, name)
    if ch is None:
        raise ValueError(f"the assembly has no component '{name}'")
    if ch in assy.children:
        assy.remove(name)
        return assy
    for parent in [assy] + [c for c in assy.traverse()]:
        p = parent[1] if isinstance(parent, tuple) else parent
        if ch in getattr(p, "children", []):
            p.children.remove(ch)
            p.objects.pop(ch.name, None)
            break
    return assy


# =================================================================== assembly
def compound(*shapes):
    """Several solids or Workplanes as one compound (no boolean union)."""
    out = []
    for s in shapes:
        if isinstance(s, (list, tuple)):
            out += [x for t in s for x in (t.vals() if isinstance(t, cq.Workplane) else [t])]
        elif isinstance(s, cq.Workplane):
            out += [v for v in s.vals() if isinstance(v, cq.Shape)]
        elif isinstance(s, cq.Shape):
            out.append(s)
    return cq.Workplane().add(cq.Compound.makeCompound(out))


FAILED: list = []


def assemble(name, components):
    """Run component builders and collect them in an assembly. components =
    [(id, title, builder_function, colour), ...]. A builder that fails is
    reported (lib.FAILED) and left out; the rest of the assembly is kept."""
    assy = cq.Assembly(name=name)
    for comp in components:
        cid, title, fn = comp[0], comp[1], comp[2]
        color = comp[3] if len(comp) > 3 else None
        try:
            shp = fn()
            if isinstance(shp, cq.Assembly):
                shp = shp.toCompound()
            vals = shp.vals() if isinstance(shp, cq.Workplane) else [shp]
            vals = [v for v in vals if isinstance(v, cq.Shape)]
            if not vals:
                raise ValueError("the builder returned no shape")
            obj = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
            assy.add(obj, name=str(cid), color=cq.Color(color) if isinstance(color, str) else
                     (cq.Color(*color) if color else None))
        except Exception as e:  # noqa: BLE001 - reported, not fatal
            FAILED.append({"id": cid, "title": title, "error": f"{type(e).__name__}: {e}"})
    return assy
