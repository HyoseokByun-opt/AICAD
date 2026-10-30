"""Analysis model: beams and shells derived from the solid model.

Structures are often analysed with beam and shell elements instead of
solid elements. The solids of a model are idealised the way an analyst
would do it by hand:

- a straight solid of constant cross-section that is long compared with its
  section (pipe, tube, rod, rolled section, bar) becomes a BEAM: its centre
  line, with the section measured on its end face (area, second moments,
  torsion constant, and the standard shape when it is one: rod, pipe,
  rectangle, box, I);
- a round solid made only of cylinders and tori (a pipe run with bends)
  becomes a chain of straight and curved beam segments;
- a thin wall - two faces at a small, constant distance (plate, sheet,
  vessel shell, dished head, duct) - becomes a SHELL: the mid-surface with
  the thickness;
- a ball at a pipe joint is dropped; everything else stays a SOLID, to be
  meshed with solid elements.

Beam ends that stop at the side of another member (a beam ending at the
face of a column) are connected to that member's centre line.

Written files: STEP with the centre lines, the mid-surfaces and the remaining
solids, named per component; an input deck in the keyword format of
CalculiX (nodes, B31 beam and S3 shell elements, sections, material); a
section table (CSV); JSON for the 3D view. Runs in the CAD worker process.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import cadquery as cq
import numpy as np

SLENDER = 4.0          # length / section size from which a straight member is a beam
THIN = 0.2             # wall thickness / sqrt(face area) below which two faces form a shell
ANG = 1e-3             # tolerance on directions (dot products)


# ---------------------------------------------------------------- geometry helpers
def _vec(v):
    return np.array([v.x, v.y, v.z], dtype=float) if hasattr(v, "x") else np.asarray(v, dtype=float)


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _gp(p):
    from OCP.gp import gp_Pnt
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def _obb(shape):
    from OCP.Bnd import Bnd_OBB
    from OCP.BRepBndLib import BRepBndLib
    o = Bnd_OBB()
    BRepBndLib.AddOBB_s(shape.wrapped, o, True, True, False)
    axes = [(o.XHSize(), o.XDirection()), (o.YHSize(), o.YDirection()), (o.ZHSize(), o.ZDirection())]
    axes.sort(key=lambda a: -a[0])
    return [(2 * h, _unit([d.X(), d.Y(), d.Z()])) for h, d in axes]


def _surface(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    return BRepAdaptor_Surface(face.wrapped)


def _cyl(face):
    c = _surface(face).Cylinder()
    ax = c.Axis()
    loc, d = ax.Location(), ax.Direction()
    return np.array([loc.X(), loc.Y(), loc.Z()]), _unit([d.X(), d.Y(), d.Z()]), c.Radius()


def _torus(face):
    t = _surface(face).Torus()
    ax = t.Axis()
    loc, d = ax.Location(), ax.Direction()
    return np.array([loc.X(), loc.Y(), loc.Z()]), _unit([d.X(), d.Y(), d.Z()]), t.MajorRadius(), t.MinorRadius()


def _normal(face, at=None):
    return _unit(_vec(face.normalAt(cq.Vector(*at)) if at is not None else face.normalAt()))


def _circle_centres(face):
    """Centres and radii of the circular edges of a face."""
    out = []
    for e in face.Edges():
        if e.geomType() == "CIRCLE":
            out.append((_vec(e.arcCenter()), e.radius()))
    return out


def _dist_point_face(p, face):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    v = BRepBuilderAPI_MakeVertex(_gp(p)).Vertex()
    d = BRepExtrema_DistShapeShape(v, face.wrapped)
    if not d.IsDone() or d.NbSolution() == 0:
        return None, None
    q = d.PointOnShape2(1)
    return d.Value(), np.array([q.X(), q.Y(), q.Z()])


def _samples(face, n=9):
    """Points inside a face: centroids of the largest triangles of its tessellation."""
    try:
        verts, tris = face.tessellate(1.0, 0.5)
    except Exception:  # noqa: BLE001
        return [_vec(face.Center())]
    pts = [_vec(v) for v in verts]
    cand = []
    for a, b, c in tris:
        pa, pb, pc = pts[a], pts[b], pts[c]
        cand.append((np.linalg.norm(np.cross(pb - pa, pc - pa)), (pa + pb + pc) / 3))
    cand.sort(key=lambda x: -x[0])
    out = []
    for _, c in cand[:n]:
        # a triangle centre lies off a curved surface (by the chord sag): take its foot on the face
        d, q = _dist_point_face(c, face)
        out.append(q if q is not None else c)
    return out or [_vec(face.Center())]


# ---------------------------------------------------------------- sections
def _section_props(face, axis):
    """Area, centroid, principal second moments and axes of a planar end face
    whose normal is `axis`, the torsion constant (exact for round sections,
    estimated otherwise) and the standard shape when it is one."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, g)
    A = g.Mass()
    c = g.CentreOfMass()
    cen = np.array([c.X(), c.Y(), c.Z()])
    M = g.MatrixOfInertia()
    M = np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])
    d = _unit(axis)
    e1 = _unit(np.cross(d, [0, 0, 1] if abs(d[2]) < 0.9 else [1, 0, 0]))
    e2 = np.cross(d, e1)
    # second moments about the in-plane axes: I_e1 = e1.M.e1 = integral (r.e2)^2 dA
    I = np.array([[e1 @ M @ e1, -(e1 @ M @ e2)], [-(e2 @ M @ e1), e2 @ M @ e2]])
    w, v = np.linalg.eigh(I)
    order = np.argsort(-w)
    w, v = w[order], v[:, order]
    a1 = _unit(v[0, 0] * e1 + v[1, 0] * e2)          # principal axis of the larger moment
    a2 = np.cross(d, a1)
    I11, I22 = float(w[0]), float(w[1])
    Ip = I11 + I22
    wires = face.Wires()
    outer = face.outerWire()
    inner = [wi for wi in wires if not wi.isSame(outer)]
    perim = sum(wi.Length() for wi in wires)
    sec = {"A": A, "I11": I11, "I22": I22, "J": None, "dir1": a1.tolist(), "dir2": a2.tolist(), "shape": "general"}
    circ = [e for e in face.Edges() if e.geomType() == "CIRCLE"]
    lines = [e for e in face.Edges() if e.geomType() == "LINE"]
    edges = face.Edges()

    def local(p):
        q = _vec(p) - cen
        return float(q @ a1), float(q @ a2)

    if circ and len(circ) == len(edges) and not inner and len({round(e.radius(), 3) for e in circ}) == 1:
        sec.update(shape="rod", r=circ[0].radius(), J=Ip)
    elif len(circ) == len(edges) and len(inner) == 1 and len({round(e.radius(), 3) for e in circ}) == 2:
        ro = max(e.radius() for e in circ)
        ri = min(e.radius() for e in circ)
        sec.update(shape="pipe", r=ro, t=ro - ri, J=Ip)
    elif len(lines) == len(edges):
        ov = [local(v.Center()) for v in outer.Vertices()]
        xs, ys = sorted({round(x, 3) for x, _ in ov}), sorted({round(y, 3) for _, y in ov})
        a, b = xs[-1] - xs[0], ys[-1] - ys[0]
        if len(ov) == 4 and len(xs) == 2 and len(ys) == 2 and not inner:
            sec.update(shape="rect", a=a, b=b)
            s, l_ = min(a, b), max(a, b)
            sec["J"] = l_ * s ** 3 * (1 / 3 - 0.21 * s / l_ * (1 - s ** 4 / (12 * l_ ** 4)))
        elif len(ov) == 4 and len(inner) == 1 and len(inner[0].Vertices()) == 4:
            iv = [local(v.Center()) for v in inner[0].Vertices()]
            ixs, iys = sorted({round(x, 3) for x, _ in iv}), sorted({round(y, 3) for _, y in iv})
            if len(ixs) == 2 and len(iys) == 2:
                t1, t3 = iys[0] - ys[0], ys[-1] - iys[-1]          # walls normal to axis 2
                t2, t4 = xs[-1] - ixs[-1], ixs[0] - xs[0]          # walls normal to axis 1
                sec.update(shape="box", a=a, b=b, t=[t1, t2, t3, t4])
                tm = (t1 + t2 + t3 + t4) / 4
                Am = (a - tm) * (b - tm)
                sec["J"] = 4 * Am ** 2 / (2 * ((a - tm) + (b - tm)) / tm)
        elif len(ov) == 12 and len(xs) == 4 and len(ys) == 4 and not inner:
            # I or H section, web along axis 2 or axis 1
            if abs((xs[1] - xs[0]) - (xs[3] - xs[2])) < 1e-3 * a and abs((ys[1] - ys[0]) - (ys[3] - ys[2])) < 1e-3 * b:
                h, bf = (b, a) if (xs[2] - xs[1]) < (ys[2] - ys[1]) else (a, b)
                if h == b:
                    tw, tf = xs[2] - xs[1], ys[1] - ys[0]
                else:
                    tw, tf = ys[2] - ys[1], xs[1] - xs[0]
                sec.update(shape="I", h=h, b=bf, tw=tw, tf=tf)
                sec["J"] = (2 * bf * tf ** 3 + (h - 2 * tf) * tw ** 3) / 3
    if sec["J"] is None:
        # St Venant's estimate for compact sections, thin-wall estimate for open thin sections
        j_sv = A ** 4 / (40 * Ip) if Ip > 0 else 0.0
        if inner:
            tm = A / max(perim / 2, 1e-9)
            Am = A / 2 + sum(abs(_wire_area(wi)) for wi in inner)
            j_thin = 4 * Am ** 2 * tm / max(perim / 2, 1e-9)
        else:
            tm = 2 * A / max(perim, 1e-9)
            j_thin = A * tm ** 2 / 3
        sec["J"] = min(j_sv, j_thin) if j_thin > 0 else j_sv
        sec["J_estimated"] = True
    return sec, cen


def _wire_area(wire):
    try:
        return cq.Face.makeFromWires(wire).Area()
    except Exception:  # noqa: BLE001
        return 0.0


def section_text(s):
    sh = s.get("shape")
    if sh == "rod":
        return f"rod d{2 * s['r']:.4g}"
    if sh == "pipe":
        return f"pipe {2 * s['r']:.4g}x{s['t']:.3g}"
    if sh == "rect":
        return f"rect {s['a']:.4g}x{s['b']:.4g}"
    if sh == "box":
        return f"box {s['a']:.4g}x{s['b']:.4g}x{min(s['t']):.3g}"
    if sh == "I":
        return f"I {s['h']:.4g}x{s['b']:.4g}x{s['tw']:.3g}x{s['tf']:.3g}"
    return f"general A{s['A']:.4g}"


# ---------------------------------------------------------------- classification
def _as_round(solid):
    """A pipe, rod or pipe run: only cylinders and tori besides planar end
    faces, with one outer radius. Returns beam segments or None."""
    faces = solid.Faces()
    rounds = [f for f in faces if f.geomType() in ("CYLINDER", "TORUS")]
    caps = [f for f in faces if f.geomType() == "PLANE"]
    if not rounds or len(rounds) + len(caps) != len(faces) or len(caps) > 2 * 2:
        return None
    radii = []
    for f in rounds:
        radii.append(_cyl(f)[2] if f.geomType() == "CYLINDER" else _torus(f)[3])
    ro = max(radii)
    inner = sorted({round(r, 4) for r in radii if r < ro * 0.999})
    if len(inner) > 1:
        return None
    ri = inner[0] if inner else 0.0
    segs = []
    for f in rounds:
        if f.geomType() == "CYLINDER":
            p, d, r = _cyl(f)
            if r < ro * 0.999:
                continue
            ends = [c for c, rr in _circle_centres(f) if abs(rr - ro) < 1e-3 * ro]
            if len(ends) < 2:
                # a full cylinder face whose ends are not circles: project its bounding points on the axis
                bb = f.BoundingBox()
                cs = [np.array([x, y, z]) for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)]
                s = [float((c - p) @ d) for c in cs]
                ends = [p + d * min(s), p + d * max(s)]
            ends = sorted(ends, key=lambda c: float((c - p) @ d))
            segs.append(("line", ends[0], ends[-1], None))
        else:
            c0, ax, R, r = _torus(f)
            if r < ro * 0.999:
                continue
            ends = [c for c, rr in _circle_centres(f) if abs(rr - ro) < 1e-3 * ro]
            if len(ends) < 2:
                return None
            segs.append(("arc", ends[0], ends[-1], (c0, ax, R)))
    if not segs:
        return None
    # merge the halves of faces split by a seam (same segment twice)
    uniq = []
    for s in segs:
        if not any(s[0] == u[0] and ((np.allclose(s[1], u[1], atol=1e-3) and np.allclose(s[2], u[2], atol=1e-3)) or
                                     (np.allclose(s[1], u[2], atol=1e-3) and np.allclose(s[2], u[1], atol=1e-3)))
                   for u in uniq):
            uniq.append(s)
    length = sum(np.linalg.norm(s[2] - s[1]) if s[0] == "line" else _arc_len(s) for s in uniq)
    if length < SLENDER * 2 * ro:
        return None
    A = math.pi * (ro ** 2 - ri ** 2)
    Ip = math.pi / 2 * (ro ** 4 - ri ** 4)
    sec = {"A": A, "I11": Ip / 2, "I22": Ip / 2, "J": Ip, "shape": "pipe" if ri > 0 else "rod", "r": ro}
    if ri > 0:
        sec["t"] = ro - ri
    return [(s, sec) for s in uniq]


def _arc_len(seg):
    _, a, b, (c0, ax, R) = seg
    va, vb = a - c0, b - c0
    va, vb = va - ax * (va @ ax), vb - ax * (vb @ ax)
    ang = math.atan2(float(np.cross(va, vb) @ ax), float(va @ vb))
    return abs(ang) * R


def _arc_points(seg, step_deg=15.0):
    _, a, b, (c0, ax, R) = seg
    oa = a - c0
    h_a = float(oa @ ax)
    va = oa - ax * h_a
    vb = (b - c0) - ax * float((b - c0) @ ax)
    ang = math.atan2(float(np.cross(va, vb) @ ax), float(va @ vb))
    n = max(2, int(math.ceil(abs(math.degrees(ang)) / step_deg)))
    u = _unit(va)
    w = np.cross(ax, u)
    rad = np.linalg.norm(va)
    return [c0 + ax * h_a + rad * (math.cos(ang * k / n) * u + math.sin(ang * k / n) * w) for k in range(n + 1)]


def _as_prism(solid):
    """A straight member of constant cross-section (rolled section, bar, box):
    every face is an end face normal to the axis or a side face parallel to
    it (at least 90 % of the side area). Returns (p0, p1, section) or None."""
    dims = _obb(solid)
    L, d0 = dims[0]
    size = max(dims[1][0], dims[2][0])
    if size <= 0 or L < SLENDER * size:
        return None
    faces = solid.Faces()
    planes = [f for f in faces if f.geomType() == "PLANE"]
    # the axis: the normal of the planar face most nearly parallel to the box axis
    caps_n = [(abs(float(_normal(f) @ d0)), f) for f in planes]
    caps_n = [x for x in caps_n if x[0] > 0.98]
    if len(caps_n) < 2:
        return None
    d = _normal(max(caps_n, key=lambda x: x[0])[1])
    if d @ d0 < 0:
        d = -d
    caps, side, other = [], 0.0, 0.0
    for f in faces:
        t = f.geomType()
        a = f.Area()
        if t == "PLANE":
            n = _normal(f)
            if abs(n @ d) > 1 - ANG:
                caps.append(f)
                continue
            if abs(n @ d) < ANG:
                side += a
                continue
        elif t == "CYLINDER" and abs(_cyl(f)[1] @ d) > 1 - ANG:
            side += a
            continue
        other += a
    if side <= 0 or other > 0.1 * (side + other):
        return None
    pos = [(float(_vec(f.Center()) @ d), f) for f in caps]
    lo, hi = min(p for p, _ in pos), max(p for p, _ in pos)
    if hi - lo < SLENDER * size * 0.9:
        return None
    c_lo = max((f for p, f in pos if abs(p - lo) < 1e-3 * L), key=lambda f: f.Area())
    sec, cen = _section_props(c_lo, d)
    return cen, cen + d * (hi - lo), sec


def _thin_pairs(solid):
    """Thin walls: pairs of faces at a constant distance t, small against the
    face size, with opposite normals. Returns [(face, t)] for one face of
    each pair, and the fraction of the area they cover."""
    faces = sorted(solid.Faces(), key=lambda f: -f.Area())
    total = sum(f.Area() for f in faces)
    used, out = set(), []
    for i, fa in enumerate(faces):
        if i in used or fa.Area() < 1e-3 * total:
            continue
        pts = _samples(fa, 7)
        na = [_normal(fa, p) for p in pts]
        bb_a = fa.BoundingBox()
        for j, fb in enumerate(faces):
            if j == i or j in used:
                continue
            bb_b = fb.BoundingBox()
            gap = max(bb_a.xmin - bb_b.xmax, bb_b.xmin - bb_a.xmax, bb_a.ymin - bb_b.ymax, bb_b.ymin - bb_a.ymax,
                      bb_a.zmin - bb_b.zmax, bb_b.zmin - bb_a.zmax)
            if gap > math.sqrt(fa.Area()) * THIN:
                continue
            ds, ok = [], True
            for p, n in zip(pts, na):
                dist, q = _dist_point_face(p, fb)
                if dist is None or dist < 1e-6:
                    ok = False
                    break
                if abs(float(_unit(q - p) @ n) + 1) > 0.05 or float(_normal(fb, q) @ n) > -0.95:
                    ok = False
                    break
                ds.append(dist)
            if not ok or not ds:
                continue
            t = float(np.mean(ds))
            if max(ds) - min(ds) > 0.05 * t + 1e-6 or t > THIN * math.sqrt(fa.Area()):
                continue
            used.update((i, j))
            out.append((fa, t))
            break
    cover = sum(2 * f.Area() for f, _ in out) / max(total, 1e-9)
    return out, cover


def _mid_surface(face, t):
    """The face moved half the thickness into the solid (against its outward normal)."""
    if face.geomType() == "PLANE":
        n = _normal(face)
        return face.translate(cq.Vector(*(-n * t / 2)))
    from OCP.BRepOffset import BRepOffset_MakeSimpleOffset
    for sign in (-1.0, 1.0):
        try:
            so = BRepOffset_MakeSimpleOffset(face.wrapped, sign * t / 2)
            so.Perform()
            if not so.IsDone():
                continue
            mid = cq.Shape.cast(so.GetResultShape())
            fs = [mid] if mid.ShapeType() == "Face" else mid.Faces()
            if not fs:
                continue
            m = fs[0]
            p = _samples(m, 1)[0]
            dist, q = _dist_point_face(p, face)
            if dist is not None and float((p - q) @ _normal(face, q)) < 0:
                return m
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("offset of a curved face failed")


def classify(parts, pipes="beam"):
    """parts: [{"name", "shape"}]. Returns the idealised items."""
    beams, shells, solids, notes = [], [], [], []
    balls = []
    for p in parts:
        comp = p.get("name") or "body"
        shp = p["shape"]
        sols = shp.Solids() if hasattr(shp, "Solids") else []
        for k, s in enumerate(sols):
            tag = f"{comp}#{k + 1}"
            fs = s.Faces()
            if len(fs) == 1 and fs[0].geomType() == "SPHERE":
                balls.append((comp, tag, _vec(s.Center()), s))
                continue
            if pipes == "beam":
                r = _as_round(s)
                if r:
                    for (kind, a, b, arc), sec in r:
                        pts = [a, b] if kind == "line" else _arc_points((kind, a, b, arc))
                        beams.append({"comp": comp, "tag": tag, "pts": [q.tolist() for q in pts], "section": sec})
                    continue
            pr = _as_prism(s)
            if pr and not (pipes == "shell" and pr[2]["shape"] == "pipe"):
                p0, p1, sec = pr
                beams.append({"comp": comp, "tag": tag, "pts": [p0.tolist(), p1.tolist()], "section": sec})
                continue
            pairs, cover = _thin_pairs(s)
            if pairs and cover > 0.8:
                for f, t in pairs:
                    try:
                        mid = _mid_surface(f, t)
                    except Exception as e:  # noqa: BLE001
                        notes.append(f"{tag}: mid-surface failed ({e})")
                        continue
                    shells.append({"comp": comp, "tag": tag, "t": t, "face": mid})
                continue
            solids.append({"comp": comp, "tag": tag, "shape": s})
    # balls at pipe joints are dropped; others stay solids
    ends = [np.array(q) for b in beams for q in (b["pts"][0], b["pts"][-1])]
    for comp, tag, c, s in balls:
        r = (s.BoundingBox().xlen) / 2
        if any(np.linalg.norm(c - e) < 0.25 * r for e in ends):
            notes.append(f"{tag}: ball at a pipe joint left out (the pipes meet at its centre)")
        else:
            solids.append({"comp": comp, "tag": tag, "shape": s})
    return beams, shells, solids, notes


# ---------------------------------------------------------------- connections and mesh
def _closest_on_segment(p, a, b):
    ab = b - a
    L2 = float(ab @ ab)
    if L2 < 1e-12:
        return a, 0.0
    s = max(0.0, min(1.0, float((p - a) @ ab) / L2))
    return a + ab * s, s


def _section_size(sec):
    """The larger outside dimension of a section (estimated for general sections)."""
    if sec.get("shape") in ("rod", "pipe"):
        return 2 * sec["r"]
    if sec.get("shape") in ("rect", "box"):
        return max(sec["a"], sec["b"])
    if sec.get("shape") == "I":
        return max(sec["h"], sec["b"])
    # radius of gyration of the stronger axis, times about 2.5 for typical sections
    return 2.5 * 2 * math.sqrt(max(sec["I11"], 1e-9) / max(sec["A"], 1e-9))


def connect(beams):
    """Beam ends that stop at another member (within half the two section
    sizes of its centre line, not parallel to it) are moved onto that centre
    line; the other member gets a node there. Returns the number of
    connections made."""
    n = 0
    lines = []          # (beam index, segment index, a, b)
    for i, b in enumerate(beams):
        for k in range(len(b["pts"]) - 1):
            lines.append((i, k, np.array(b["pts"][k]), np.array(b["pts"][k + 1])))
    for i, b in enumerate(beams):
        for end in (0, -1):
            p = np.array(b["pts"][end])
            q = np.array(b["pts"][1 if end == 0 else -2])
            dirb = _unit(p - q)
            best = None
            for j, k, a, c in lines:
                if j == i:
                    continue
                x, s = _closest_on_segment(p, a, c)
                dist = float(np.linalg.norm(x - p))
                tol = (_section_size(b["section"]) + _section_size(beams[j]["section"])) / 2
                if dist < 1e-6:
                    best = None
                    break
                if dist <= tol and abs(float(dirb @ _unit(c - a))) < 0.95 and (best is None or dist < best[0]):
                    best = (dist, x)
            if best:
                b["pts"][end] = best[1].tolist()
                n += 1
    return n


class Mesh:
    def __init__(self, tol):
        self.tol = tol
        self.nodes = []
        self.grid = {}

    def node(self, p):
        key = tuple(int(round(c / self.tol)) for c in p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for idx in self.grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                        if np.linalg.norm(self.nodes[idx] - p) <= self.tol:
                            return idx + 1
        self.nodes.append(np.asarray(p, dtype=float))
        self.grid.setdefault(key, []).append(len(self.nodes) - 1)
        return len(self.nodes)


def _beam_points(beams, esize):
    """Every beam polyline split at the nodes of other beams on it and into
    pieces of about esize."""
    allp = [np.array(q) for b in beams for q in (b["pts"][0], b["pts"][-1])]
    out = []
    for b in beams:
        pts = [np.array(q) for q in b["pts"]]
        seq = []
        for a, c in zip(pts[:-1], pts[1:]):
            L = float(np.linalg.norm(c - a))
            ss = {0.0, 1.0}
            for p in allp:
                x, s = _closest_on_segment(p, a, c)
                if 1e-6 < s < 1 - 1e-6 and np.linalg.norm(x - p) < 1e-3:
                    ss.add(s)
            ss = sorted(ss)
            for s0, s1 in zip(ss[:-1], ss[1:]):
                m = max(1, int(math.ceil((s1 - s0) * L / esize)))
                for k in range(m):
                    seq.append(a + (c - a) * (s0 + (s1 - s0) * k / m))
        seq.append(pts[-1])
        out.append(seq)
    return out


def _shell_tris(face, esize, fixed=()):
    """Triangles on a mid-surface of about esize: planar faces get boundary
    points every esize and an interior grid, triangulated (Delaunay) and
    clipped to the face; curved faces use the tessellation. `fixed` points
    (beam ends lying on the face) become nodes of the mesh, so the beams and
    the shell share them."""
    import cv2
    if face.geomType() != "PLANE":
        # a coarser triangulation left by the sampling would be reused: clear it first
        from OCP.BRepTools import BRepTools
        BRepTools.Clean_s(face.wrapped)
        verts, tris = face.tessellate(max(esize / 50, 0.05), 0.15)
        return [_vec(v) for v in verts], [tuple(t) for t in tris]
    n = _normal(face)
    o = _vec(face.Center())
    e1 = _unit(np.cross(n, [0, 0, 1] if abs(n[2]) < 0.9 else [1, 0, 0]))
    e2 = np.cross(n, e1)
    pts3 = []
    for w in face.Wires():
        for e in w.Edges():
            L = e.Length()
            m = max(1, int(math.ceil(L / esize)))
            for k in range(m):
                pts3.append(_vec(e.positionAt(k / m)))
    bb = face.BoundingBox()
    span = max(bb.xlen, bb.ylen, bb.zlen)
    from OCP.TopAbs import TopAbs_IN as TopAbs_IN_
    uv = [((p - o) @ e1, (p - o) @ e2) for p in pts3]
    us, vs = [u for u, _ in uv], [v for _, v in uv]
    gu = np.arange(min(us) + esize, max(us), esize)
    gv = np.arange(min(vs) + esize, max(vs), esize)
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.BRepClass import BRepClass_FaceClassifier as _FC
    for p in fixed:
        p = np.asarray(p, dtype=float)
        if abs(float((p - o) @ n)) < 1e-3 * max(esize, 1.0) and _FC(face.wrapped, _gp(p), 1e-6 * span).State() == TopAbs_IN_:
            pts3.append(p)
            uv.append(((p - o) @ e1, (p - o) @ e2))
    bnd = np.array(uv)
    for u in gu:
        for v in gv:
            # interior points on a grid, not closer than half a size to the boundary points
            if np.min(np.hypot(bnd[:, 0] - u, bnd[:, 1] - v)) <= 0.5 * esize:
                continue
            p = o + e1 * u + e2 * v
            if BRepClass_FaceClassifier(face.wrapped, _gp(p), 1e-6 * span).State() == TopAbs_IN:
                pts3.append(p)
                uv.append((u, v))
    # Delaunay in the plane of the face
    us = [u for u, _ in uv]
    vs = [v for _, v in uv]
    x0, y0 = min(us) - 1, min(vs) - 1
    w_, h_ = max(us) - x0 + 2, max(vs) - y0 + 2
    sub = cv2.Subdiv2D((0, 0, int(math.ceil(w_)) + 2, int(math.ceil(h_)) + 2))
    # the triangulation returns its vertices in single precision: they are found
    # again by position within a small tolerance (points are about esize apart)
    cell = max(esize / 4, 1e-3)
    grid, tol = {}, min(esize / 10, 1.0)

    def find(x, y):
        cx, cy = int(x // cell), int(y // cell)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for k, (px, py) in grid.get((gx, gy), ()):
                    if abs(px - x) <= tol and abs(py - y) <= tol:
                        return k
        return None

    for k, (u, v) in enumerate(uv):
        x, y = u - x0, v - y0
        if find(x, y) is not None:
            continue
        grid.setdefault((int(x // cell), int(y // cell)), []).append((k, (x, y)))
        sub.insert((float(x), float(y)))
    tris = []
    for t in sub.getTriangleList():
        ks = []
        for j in range(3):
            k = find(float(t[2 * j]), float(t[2 * j + 1]))
            if k is None:
                break
            ks.append(k)
        if len(ks) != 3:
            continue
        c = (pts3[ks[0]] + pts3[ks[1]] + pts3[ks[2]]) / 3
        if BRepClass_FaceClassifier(face.wrapped, _gp(c), 1e-6 * span).State() != TopAbs_IN:
            continue
        a, b, cc = pts3[ks[0]], pts3[ks[1]], pts3[ks[2]]
        if float(np.cross(b - a, cc - a) @ n) < 0:
            ks = [ks[0], ks[2], ks[1]]
        tris.append(tuple(ks))
    return pts3, tris


# ---------------------------------------------------------------- outputs
def build(parts, outdir: Path, name: str, esize: float = 0.0, pipes: str = "beam", join: bool = True,
          density: float = 7.85, E: float = 210000.0, nu: float = 0.3) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    beams, shells, solids, notes = classify(parts, pipes)
    if not beams and not shells:
        return {"ok": False, "error": "No member, pipe or thin wall was found; the model is solid only "
                "(blocks, castings, machines). Export it as STEP for a solid mesh.",
                "solids": len(solids)}
    comp = cq.Compound.makeCompound([p["shape"] for p in parts])
    bb = comp.BoundingBox()
    size = max(bb.xlen, bb.ylen, bb.zlen, 1.0)
    if not esize or esize <= 0:
        esize = size / 60
    joined = connect(beams) if join and beams else 0
    mesh = Mesh(max(1e-3, size * 1e-6))
    elem_b, elem_s = [], []           # (eid, set, nodes)
    sets, eid = {}, 0
    rows = []
    # beams: one element set per beam (its own section and orientation)
    for k, (b, seq) in enumerate(zip(beams, _beam_points(beams, esize))):
        es = f"B{k + 1}"
        sets[es] = ("beam", b)
        for a, c in zip(seq[:-1], seq[1:]):
            if np.linalg.norm(c - a) < 1e-9:
                continue
            eid += 1
            elem_b.append((eid, es, (mesh.node(a), mesh.node(c))))
        L = sum(float(np.linalg.norm(np.array(q1) - np.array(q0))) for q0, q1 in zip(b["pts"][:-1], b["pts"][1:]))
        s = b["section"]
        rows.append({"set": es, "component": b["comp"], "solid": b["tag"], "kind": "beam", "section": section_text(s),
                     "length_mm": round(L, 2), "area_mm2": round(s["A"], 3), "I11_mm4": round(s["I11"], 1),
                     "I22_mm4": round(s["I22"], 1), "J_mm4": round(s["J"], 1) if s.get("J") else "",
                     "J_note": "estimated" if s.get("J_estimated") else "", "thickness_mm": "",
                     "mass_kg": round(density * 1e-6 * s["A"] * L, 3)})
    # shells: one element set per mid-surface; beam ends on a mid-surface become shell nodes
    beam_ends = [np.array(q) for b in beams for q in (b["pts"][0], b["pts"][-1])]
    for k, sh in enumerate(shells):
        es = f"S{k + 1}"
        sets[es] = ("shell", sh)
        try:
            pts, tris = _shell_tris(sh["face"], esize, fixed=beam_ends)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{sh['tag']}: shell mesh failed ({e}); only the surface is in the STEP file")
            continue
        ids = [mesh.node(p) for p in pts]
        for t in tris:
            if len({ids[t[0]], ids[t[1]], ids[t[2]]}) < 3:
                continue
            eid += 1
            elem_s.append((eid, es, (ids[t[0]], ids[t[1]], ids[t[2]])))
        A = sh["face"].Area()
        rows.append({"set": es, "component": sh["comp"], "solid": sh["tag"], "kind": "shell", "section": "",
                     "length_mm": "", "area_mm2": round(A, 1), "I11_mm4": "", "I22_mm4": "", "J_mm4": "", "J_note": "",
                     "thickness_mm": round(sh["t"], 3), "mass_kg": round(density * 1e-6 * A * sh["t"], 3)})
    base = outdir / name
    # ---- STEP: centre lines, mid-surfaces, remaining solids per component
    assy = cq.Assembly(name=f"{name}_analysis")
    by_comp = {}
    for b in beams:
        pts = [cq.Vector(*q) for q in b["pts"]]
        by_comp.setdefault((b["comp"], "beams"), []).append(cq.Wire.makePolygon(pts))
    for sh in shells:
        by_comp.setdefault((sh["comp"], "shells"), []).append(sh["face"])
    for so in solids:
        by_comp.setdefault((so["comp"], "solids"), []).append(so["shape"])
    colours = {"beams": (0.10, 0.35, 0.80), "shells": (0.85, 0.45, 0.10), "solids": (0.6, 0.6, 0.6)}
    for (cname, kind), shapes in by_comp.items():
        assy.add(cq.Compound.makeCompound(shapes), name=f"{cname}_{kind}", color=cq.Color(*colours[kind]))
    assy.export(str(base.with_suffix(".step")), "STEP")
    # ---- input deck
    rho = density * 1e-9           # t/mm3
    L = [f"** AICAD analysis model of {name}", "** units: mm, N, t, s (stress in MPa)",
         f"** {len(beams)} beams, {len(shells)} shell surfaces, {len(solids)} solids not idealised (see the STEP file)",
         "*HEADING", f"{name} - beams and shells", "*NODE"]
    L += [f"{i + 1}, {p[0]:.6g}, {p[1]:.6g}, {p[2]:.6g}" for i, p in enumerate(mesh.nodes)]
    for es in sets:
        kind = sets[es][0]
        els = [e for e in (elem_b if kind == "beam" else elem_s) if e[1] == es]
        if not els:
            continue
        L.append(f"*ELEMENT, TYPE={'B31' if kind == 'beam' else 'S3'}, ELSET={es}")
        L += [f"{e[0]}, " + ", ".join(str(n) for n in e[2]) for e in els]
    L += ["*MATERIAL, NAME=STEEL", "*ELASTIC", f"{E:.6g}, {nu:.3g}", "*DENSITY", f"{rho:.4g}"]
    general = 0
    for es, (kind, it) in sets.items():
        if kind == "shell":
            L += [f"*SHELL SECTION, ELSET={es}, MATERIAL=STEEL", f"{it['t']:.6g}"]
            continue
        s = it["section"]
        d1 = s.get("dir1") or _unit(np.cross(_unit(np.array(it["pts"][-1]) - np.array(it["pts"][0])),
                                             [0, 0, 1] if abs(_unit(np.array(it["pts"][-1]) - np.array(it["pts"][0]))[2]) < 0.9
                                             else [1, 0, 0])).tolist()
        ori = f"{d1[0]:.6g}, {d1[1]:.6g}, {d1[2]:.6g}"
        sh = s.get("shape")
        if sh == "rod":
            L += [f"*BEAM SECTION, ELSET={es}, MATERIAL=STEEL, SECTION=CIRC", f"{s['r']:.6g}", ori]
        elif sh == "pipe":
            L += [f"*BEAM SECTION, ELSET={es}, MATERIAL=STEEL, SECTION=PIPE", f"{s['r']:.6g}, {s['t']:.6g}", ori]
        elif sh == "rect":
            L += [f"*BEAM SECTION, ELSET={es}, MATERIAL=STEEL, SECTION=RECT", f"{s['a']:.6g}, {s['b']:.6g}", ori]
        elif sh == "box":
            t = s["t"]
            L += [f"*BEAM SECTION, ELSET={es}, MATERIAL=STEEL, SECTION=BOX",
                  f"{s['a']:.6g}, {s['b']:.6g}, {t[0]:.6g}, {t[1]:.6g}, {t[2]:.6g}, {t[3]:.6g}", ori]
        else:
            general += 1
            G = E / (2 * (1 + nu))
            L += [f"** {section_text(s)}: general section (area, second moments, torsion constant)",
                  f"*BEAM GENERAL SECTION, ELSET={es}, SECTION=GENERAL, DENSITY={rho:.4g}",
                  f"{s['A']:.6g}, {s['I11']:.6g}, 0., {s['I22']:.6g}, {s['J']:.6g}", ori, f"{E:.6g}, {G:.6g}"]
    if solids:
        L.append("** solids not idealised (mesh them with solid elements from the STEP file):")
        L += [f"**   {so['tag']}" for so in solids[:200]]
    L += ["**", "** add supports, loads and an analysis step, for example:",
          "** *STEP", "** *FREQUENCY", "** 10", "** *END STEP"]
    base.with_suffix(".inp").write_text("\n".join(L) + "\n", encoding="utf-8")
    # ---- section table
    with open(base.with_name(base.name + "_sections.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["set"])
        w.writeheader()
        w.writerows(rows)
    # ---- view data
    view = {"beams": [{"set": f"B{k + 1}", "comp": b["comp"], "pts": b["pts"], "section": section_text(b["section"])}
                      for k, b in enumerate(beams)],
            "shells": [], "nodes": len(mesh.nodes), "elements": eid}
    for k, sh in enumerate(shells):
        try:
            verts, tris = sh["face"].tessellate(max(size / 2000, 0.05), 0.3)
            view["shells"].append({"set": f"S{k + 1}", "comp": sh["comp"], "t": sh["t"],
                                   "v": [round(c, 3) for v in verts for c in (v.x, v.y, v.z)],
                                   "i": [i for t in tris for i in t]})
        except Exception:  # noqa: BLE001
            pass
    summary = {"ok": True, "beams": len(beams), "shells": len(shells), "solids": len(solids),
               "nodes": len(mesh.nodes), "beam_elements": len(elem_b), "shell_elements": len(elem_s),
               "joined": joined, "general_sections": general, "esize": round(esize, 3), "notes": notes[:50],
               "solid_list": [s["tag"] for s in solids][:100],
               "files": [base.with_suffix(".step").name, base.with_suffix(".inp").name, base.name + "_sections.csv"]}
    view["summary"] = summary
    (outdir / f"{name}_view.json").write_text(json.dumps(view), encoding="utf-8")
    summary["files"].append(f"{name}_view.json")
    return summary
