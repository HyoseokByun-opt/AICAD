"""Model code execution on the OpenCASCADE kernel, in a worker process.

The model code (CadQuery, written by the AI or by the user) runs in a
separate process, so a kernel crash or an endless loop cannot take the
program down: the worker is restarted and the error is reported like any
other build error. One build writes everything a version needs:

    model.step      the deliverable (AP214 by default)
    mesh.json       triangles per face and edge polylines for the 3D viewer
    views.json      hidden-line projections (front, top, right, ...) in mm
    view_<v>.png    the same projections as line drawings (for the AI)
    sil_<v>.png     filled silhouettes (for the drawing comparison)
    build.json      the summary returned to the caller
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import multiprocessing as mp
import os
import threading
import time
import traceback
from pathlib import Path

# --------------------------------------------------------------- code check
ALLOWED_ROOTS = {"cadquery", "math", "numpy", "typing", "itertools", "functools",
                 "collections", "dataclasses", "OCP"}
BLOCKED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "globals",
                 "locals", "vars", "breakpoint", "help", "exit", "quit", "getattr",
                 "setattr", "delattr"}
SAFE_BUILTINS = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
    "frozenset", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max",
    "min", "next", "pow", "print", "range", "repr", "reversed", "round", "set", "slice",
    "sorted", "str", "sum", "tuple", "zip", "hasattr", "callable", "format", "hash", "id",
    "object", "property", "staticmethod", "classmethod", "super", "type", "complex",
    "ArithmeticError", "AssertionError", "AttributeError", "Exception", "IndexError",
    "KeyError", "NameError", "NotImplementedError", "RuntimeError", "StopIteration",
    "TypeError", "ValueError", "ZeroDivisionError", "True", "False", "None",
]


def check_code(code: str) -> list[str]:
    """Static check before running: syntax, imports and obviously unsafe calls.

    The model code only needs CadQuery and arithmetic; anything that reaches
    files, processes or the network is refused with the line number."""
    try:
        tree = ast.parse(code, filename="model.py")
    except SyntaxError as e:
        return [f"SyntaxError: {e.msg} (line {e.lineno})"]
    errs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_ROOTS:
                    errs.append(f"line {node.lineno}: importing '{a.name}' is not allowed (only cadquery, math, numpy)")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if node.level or mod not in ALLOWED_ROOTS:
                errs.append(f"line {node.lineno}: importing from '{node.module}' is not allowed (only cadquery, math, numpy)")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            errs.append(f"line {node.lineno}: '{node.func.id}()' is not allowed in model code")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            errs.append(f"line {node.lineno}: access to '{node.attr}' is not allowed in model code")
    return errs


RESULT_METHODS = {"cut", "union", "intersect", "hole", "cboreHole", "cskHole", "cutThruAll", "cutBlind",
                  "extrude", "revolve", "fillet", "chamfer", "shell", "translate", "rotate", "mirror", "loft",
                  "sweep", "twistExtrude", "split", "moved", "located", "fuse", "clean"}


def lint(code: str) -> list[str]:
    """Mistakes that build without error but lose geometry: a CadQuery
    operation whose result is thrown away (CadQuery returns a new object)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr in RESULT_METHODS:
                out.append(f"line {node.lineno}: the result of .{f.attr}() is discarded - CadQuery returns a new "
                           f"object, so assign it (for example body = body.{f.attr}(...)); as written this "
                           "operation has no effect on the model")
    return out


# --------------------------------------------------------------- views
# view name -> (direction towards the viewer, screen right); screen up = dir x right
VIEWS = {
    "front": ((0, -1, 0), (1, 0, 0)),
    "rear": ((0, 1, 0), (-1, 0, 0)),
    "top": ((0, 0, 1), (1, 0, 0)),
    "bottom": ((0, 0, -1), (1, 0, 0)),
    "right": ((1, 0, 0), (0, 1, 0)),
    "left": ((-1, 0, 0), (0, -1, 0)),
    "iso": ((1 / math.sqrt(3), -1 / math.sqrt(3), 1 / math.sqrt(3)), (1 / math.sqrt(2), 1 / math.sqrt(2), 0)),
}
# which model axis runs along the screen (horizontal, vertical) of a view
VIEW_AXES = {"front": ("x", "z"), "rear": ("x", "z"), "top": ("x", "y"), "bottom": ("x", "y"),
             "right": ("y", "z"), "left": ("y", "z")}


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def view_frame(name):
    n, r = VIEWS[name]
    return n, r, _cross(n, r)


MESH_QUALITY = {"coarse": (0.004, 0.5), "standard": (0.0015, 0.3), "fine": (0.0005, 0.15)}
DEFAULT_COLOR = (0.70, 0.75, 0.80)


# =============================================================== worker side
CSS_COLORS = {
    "grey": (0.5, 0.5, 0.5), "darkgray": (0.66, 0.66, 0.66), "darkgrey": (0.66, 0.66, 0.66),
    "dimgray": (0.41, 0.41, 0.41), "dimgrey": (0.41, 0.41, 0.41), "lightgrey": (0.83, 0.83, 0.83),
    "silver": (0.75, 0.75, 0.75), "gainsboro": (0.86, 0.86, 0.86), "slategray": (0.44, 0.5, 0.56),
    "navy": (0.0, 0.0, 0.5), "copper": (0.72, 0.45, 0.2), "bronze": (0.8, 0.5, 0.2),
    "steel": (0.6, 0.64, 0.68), "stainless": (0.78, 0.8, 0.82), "aluminium": (0.85, 0.86, 0.88),
    "aluminum": (0.85, 0.86, 0.88), "brass": (0.71, 0.65, 0.26), "olive": (0.5, 0.5, 0.0),
    "maroon": (0.5, 0.0, 0.0), "skyblue": (0.53, 0.81, 0.92), "darkblue": (0.0, 0.0, 0.55),
    "darkred": (0.55, 0.0, 0.0), "lime": (0.0, 1.0, 0.0), "charcoal": (0.21, 0.27, 0.31),
}


def _w_import():
    global cq
    import cadquery as cq  # noqa: F401  (warm the kernel once per worker)

    # model code often names CSS colours the kernel does not know ("darkgray");
    # an unknown name becomes a neutral grey instead of a failed build
    orig = cq.Color.__init__

    def _color_init(self, *args, **kwargs):
        if len(args) == 1 and isinstance(args[0], str):
            try:
                return orig(self, *args, **kwargs)
            except ValueError:
                key = args[0].lower().replace(" ", "").replace("_", "").replace("-", "")
                return orig(self, *CSS_COLORS.get(key, DEFAULT_COLOR))
        return orig(self, *args, **kwargs)

    cq.Color.__init__ = _color_init


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED_ROOTS:
        raise ImportError(f"importing '{name}' is not allowed in model code")
    return __import__(name, globals, locals, fromlist, level)


def _exec(code: str):
    import builtins
    import numpy as np
    b = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
    b["__import__"] = _safe_import
    b["__build_class__"] = builtins.__build_class__
    shown = []

    def show_object(obj, name=None, options=None, **kw):
        color = None
        if isinstance(options, dict) and options.get("color") is not None:
            color = options.get("color")
        shown.append((obj, name, color))

    ns = {"__builtins__": b, "__name__": "__aicad__", "cq": cq, "math": math, "np": np,
          "show_object": show_object, "debug": lambda *a, **k: None}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(code, "model.py", "exec"), ns)
    return ns, shown, out.getvalue()


def _color_tuple(c):
    if c is None:
        return None
    try:
        if isinstance(c, cq.Color):
            t = c.toTuple()
            return tuple(float(x) for x in t[:3])
        if isinstance(c, str):
            t = cq.Color(c).toTuple()
            return tuple(float(x) for x in t[:3])
        if isinstance(c, (tuple, list)) and len(c) >= 3:
            v = [float(x) for x in c[:3]]
            if max(v) > 1.0:
                v = [x / 255.0 for x in v]
            return tuple(v)
    except Exception:
        return None
    return None


def _shapes_of(obj):
    if isinstance(obj, cq.Workplane):
        return [v for v in obj.vals() if isinstance(v, cq.Shape)]
    if isinstance(obj, cq.Sketch):
        return []
    if isinstance(obj, cq.Shape):
        return [obj]
    if isinstance(obj, (list, tuple)):
        out = []
        for o in obj:
            out += _shapes_of(o)
        return out
    return []


def _flatten_assembly(assy, loc=None, prefix=""):
    loc = loc * assy.loc if loc is not None else assy.loc
    name = assy.name
    parts = []
    if assy.obj is not None:
        shapes = _shapes_of(assy.obj)
        if shapes:
            shp = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
            parts.append({"name": name, "shape": shp.moved(loc), "color": _color_tuple(assy.color)})
    for ch in assy.children:
        sub = _flatten_assembly(ch, loc, prefix)
        for p in sub:
            if p["color"] is None:
                p["color"] = _color_tuple(assy.color)
        parts += sub
    return parts


def _collect(ns, shown):
    """Find what the code built: an assembly, `result`, show_object() calls,
    or the last CadQuery object it defined."""
    for key in ("assembly", "assy"):
        a = ns.get(key)
        if isinstance(a, cq.Assembly):
            return _flatten_assembly(a), a
    res = ns.get("result")
    if isinstance(res, cq.Assembly):
        return _flatten_assembly(res), res
    if res is None and shown:
        parts = []
        for i, (obj, name, color) in enumerate(shown):
            if isinstance(obj, cq.Assembly):
                return _flatten_assembly(obj), obj
            shapes = _shapes_of(obj)
            if shapes:
                shp = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
                parts.append({"name": name or f"Body {i + 1}", "shape": shp, "color": _color_tuple(color)})
        return parts, None
    if res is None:
        for k in reversed(list(ns.keys())):
            v = ns[k]
            if isinstance(v, cq.Assembly):
                return _flatten_assembly(v), v
            if isinstance(v, (cq.Workplane, cq.Shape)) and not k.startswith("_") and _shapes_of(v):
                res = v
                break
    shapes = _shapes_of(res)
    if not shapes:
        return [], None
    shp = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    return [{"name": ns.get("PART_NAME") or "Body", "shape": shp, "color": None}], None


def _user_line(tb_exc, code):
    line = None
    for fr in traceback.extract_tb(tb_exc.__traceback__):
        if fr.filename == "model.py":
            line = fr.lineno
    if line is None and isinstance(tb_exc, SyntaxError):
        line = tb_exc.lineno
    text = ""
    if line:
        lines = code.splitlines()
        if 0 < line <= len(lines):
            text = lines[line - 1].strip()
    return line, text


def _face_info(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    info = {"t": face.geomType(), "a": round(face.Area(), 4)}
    try:
        s = BRepAdaptor_Surface(face.wrapped)
        t = info["t"]
        if t == "CYLINDER":
            c = s.Cylinder()
            ax = c.Axis()
            info["r"] = round(c.Radius(), 5)
            info["c"] = [round(ax.Location().X(), 4), round(ax.Location().Y(), 4), round(ax.Location().Z(), 4)]
            info["d"] = [round(ax.Direction().X(), 5), round(ax.Direction().Y(), 5), round(ax.Direction().Z(), 5)]
        elif t == "PLANE":
            n = face.normalAt()
            info["d"] = [round(n.x, 5), round(n.y, 5), round(n.z, 5)]
        elif t == "SPHERE":
            info["r"] = round(s.Sphere().Radius(), 5)
        elif t == "CONE":
            cone = s.Cone()
            info["ang"] = round(math.degrees(cone.SemiAngle()), 4)
            info["r"] = round(cone.RefRadius(), 5)
        elif t == "TORUS":
            tor = s.Torus()
            info["r"] = round(tor.MajorRadius(), 5)
            info["r2"] = round(tor.MinorRadius(), 5)
    except Exception:
        pass
    return info


def _discretize(e, defl, ang=0.12):
    """Points along an edge: chord error below defl and at most ang radians
    per segment, so small holes stay round on large models."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_TangentialDeflection
    crv = BRepAdaptor_Curve(e.wrapped)
    pts = GCPnts_TangentialDeflection(crv, crv.FirstParameter(), crv.LastParameter(), ang, defl, 2)
    return [pts.Value(i) for i in range(1, pts.NbPoints() + 1)]


def _mesh_part(shape, lin, ang):
    """Triangles per face (one shared mesh, so faces meet without cracks) and
    edge polylines."""
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    BRepMesh_IncrementalMesh(shape.wrapped, lin, False, ang, True)
    pos, idx, faces = [], [], []
    nv = 0
    for face in shape.Faces():
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face.wrapped, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        nn = tri.NbNodes()
        for i in range(1, nn + 1):
            p = tri.Node(i).Transformed(trsf)
            pos += (p.X(), p.Y(), p.Z())
        rev = face.wrapped.Orientation() == TopAbs_REVERSED
        start = len(idx) // 3
        nt = tri.NbTriangles()
        for i in range(1, nt + 1):
            a, b, c = tri.Triangle(i).Get()
            if rev:
                b, c = c, b
            idx += (nv + a - 1, nv + b - 1, nv + c - 1)
        nv += nn
        fi = _face_info(face)
        fi["s"], fi["k"] = start, nt
        faces.append(fi)
    edges = []
    for e in shape.Edges():
        try:
            if e.geomType() == "LINE":
                a, b = e.startPoint(), e.endPoint()
                edges.append([a.x, a.y, a.z, b.x, b.y, b.z])
                continue
            pts = _discretize(e, lin)
            if len(pts) > 1:
                pl = []
                for p in pts:
                    pl += (p.X(), p.Y(), p.Z())
                edges.append(pl)
        except Exception:
            continue
    return np.asarray(pos, dtype=float).reshape(-1, 3), np.asarray(idx, dtype=np.int64).reshape(-1, 3), faces, edges


def _hlr(shape, view, defl):
    """Hidden-line projection of a shape: lists of 2D polylines (mm)."""
    from OCP.BRepLib import BRepLib
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    n, r, _ = view_frame(view)
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*n), gp_Dir(*r))))
    algo.Update()
    algo.Hide()
    h = HLRBRep_HLRToShape(algo)
    groups = {"v": [h.VCompound(), h.Rg1LineVCompound(), h.OutLineVCompound()],
              "h": [h.HCompound(), h.OutLineHCompound()]}
    out = {"v": [], "h": []}
    for key, comps in groups.items():
        for c in comps:
            if c.IsNull():
                continue
            BRepLib.BuildCurves3d_s(c, 1e-6)
            for e in cq.Shape(c).Edges():
                try:
                    pts = _discretize(e, defl)
                    if len(pts) < 2:
                        continue
                    pl = []
                    for p in pts:
                        pl += (round(p.X(), 4), round(p.Y(), 4))
                    out[key].append(pl)
                except Exception:
                    continue
    return out


def _bounds2d(polys):
    xs, ys = [], []
    for key in ("v", "h"):
        for pl in polys.get(key, []):
            xs += pl[0::2]
            ys += pl[1::2]
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _draw_view_png(polys, path, size=640, margin=24):
    from PIL import Image, ImageDraw
    b = _bounds2d(polys)
    if b is None:
        return
    w, h = max(b[2] - b[0], 1e-9), max(b[3] - b[1], 1e-9)
    s = (size - 2 * margin) / max(w, h)
    W, H = int(w * s + 2 * margin), int(h * s + 2 * margin)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)

    def tr(pl):
        return [((pl[i] - b[0]) * s + margin, (b[3] - pl[i + 1]) * s + margin) for i in range(0, len(pl), 2)]

    for pl in polys.get("h", []):
        pts = tr(pl)
        # dashed hidden lines
        for i in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            L = math.hypot(x1 - x0, y1 - y0)
            nseg = max(1, int(L / 6))
            for k in range(0, nseg, 2):
                t0, t1 = k / nseg, min(1, (k + 1) / nseg)
                d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], fill=140, width=1)
    for pl in polys.get("v", []):
        d.line(tr(pl), fill=0, width=2)
    img.save(path)


def _silhouette(points, tris, view, path, size=256):
    """Filled outline of the model seen along a view (all triangles projected)."""
    import numpy as np
    from PIL import Image, ImageDraw
    _, r, u = view_frame(view)
    P = np.asarray(points)
    X = P @ np.asarray(r)
    Y = P @ np.asarray(u)
    x0, x1, y0, y1 = X.min(), X.max(), Y.min(), Y.max()
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    s = (size - 4) / max(w, h)
    W, H = max(4, int(round(w * s)) + 4), max(4, int(round(h * s)) + 4)
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    px = (X - x0) * s + 2
    py = (y1 - Y) * s + 2
    for a, b, c in tris:
        d.polygon([(px[a], py[a]), (px[b], py[b]), (px[c], py[c])], fill=255)
    img.save(path)
    return [float(w), float(h)]


def _step_schema(schema):
    try:
        from OCP.Interface import Interface_Static
        val = {"AP203": "AP203", "AP214": "AP214IS", "AP242": "AP242DIS"}.get(schema, "AP214IS")
        Interface_Static.SetCVal_s("write.step.schema", val)
    except Exception:
        pass


def _export_step(parts, assy, path, name, schema):
    _step_schema(schema)
    if assy is not None:
        assy.export(str(path), "STEP")
        return
    if len(parts) == 1:
        a = cq.Assembly(parts[0]["shape"], name=name or parts[0]["name"] or "part",
                        color=cq.Color(*parts[0]["color"]) if parts[0]["color"] else None)
    else:
        a = cq.Assembly(name=name or "assembly")
        for i, p in enumerate(parts):
            a.add(p["shape"], name=p["name"] or f"body_{i + 1}",
                  color=cq.Color(*p["color"]) if p["color"] else None)
    a.export(str(path), "STEP")


def _fmt_exc(e):
    return f"{type(e).__name__}: {e}".strip()


def _build(req):
    import numpy as np
    t0 = time.time()
    code = req["code"]
    out = Path(req["outdir"])
    out.mkdir(parents=True, exist_ok=True)
    res = {"ok": False, "log": "", "warnings": [], "lint": lint(code)}
    errs = check_code(code)
    if errs:
        res["error"] = "; ".join(errs)
        m = [int(s.split()[1].rstrip(":")) for s in errs if s.startswith("line ")]
        res["line"] = m[0] if m else None
        return res
    try:
        ns, shown, log = _exec(code)
        res["log"] = log[-4000:]
    except BaseException as e:  # noqa: BLE001 - every failure is reported to the AI
        line, text = _user_line(e, code)
        res.update(error=_fmt_exc(e), line=line, line_text=text,
                   trace="".join(traceback.format_exception(type(e), e, e.__traceback__))[-3000:])
        return res
    try:
        parts, assy = _collect(ns, shown)
    except Exception as e:
        res["error"] = "The result could not be read: " + _fmt_exc(e)
        return res
    if not parts:
        res["error"] = ("The code ran but produced no shape. Assign the final solid to a variable "
                        "named `result` (or an assembly to `assembly`).")
        return res

    # ---------------------------------------------------- checks and metrics
    nsol, vol, area = 0, 0.0, 0.0
    for p in parts:
        shp = p["shape"]
        try:
            if not shp.isValid():
                fixed = shp.fix()
                if fixed.isValid():
                    p["shape"] = shp = fixed
                    res["warnings"].append(f"{p['name']}: the shape was repaired by the kernel (shape fix).")
                else:
                    res["warnings"].append(f"{p['name']}: the kernel reports the shape as invalid.")
        except Exception:
            pass
        sols = shp.Solids()
        nsol += len(sols)
        try:
            vol += sum(s.Volume() for s in sols)
            area += shp.Area()
        except Exception:
            pass
        p["n_solids"] = len(sols)
        if assy is None and len(sols) > 1:
            res["warnings"].append(f"{p['name']} consists of {len(sols)} separate solids; "
                                   "a single part is normally one connected solid.")
    if nsol == 0:
        res["error"] = ("The result contains no solid (only faces, wires or a sketch). "
                        "Extrude, revolve or loft the profile into a solid.")
        return res
    comp = cq.Compound.makeCompound([p["shape"] for p in parts])
    bb = comp.BoundingBox()
    bbox = [bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax]
    diag = max(bb.DiagonalLength, 1e-6)
    res["metrics"] = {
        "bbox": [round(v, 4) for v in bbox],
        "size": [round(bb.xlen, 4), round(bb.ylen, 4), round(bb.zlen, 4)],
        "volume": round(vol, 3), "area": round(area, 3), "solids": nsol,
        "faces": len(comp.Faces()), "edges": len(comp.Edges()), "parts": len(parts),
        "assembly": assy is not None,
    }
    if vol <= 0:
        res["warnings"].append("The total volume is zero or negative: a face orientation is probably reversed.")

    # ---------------------------------------------------- STEP
    if req.get("step", True):
        try:
            _export_step(parts, assy, out / "model.step", req.get("name"), req.get("schema", "AP214"))
        except Exception as e:
            res["warnings"].append("STEP export failed: " + _fmt_exc(e))

    # ---------------------------------------------------- mesh
    fl, ang = MESH_QUALITY.get(req.get("quality", "standard"), MESH_QUALITY["standard"])
    lin = max(diag * fl, 1e-3)
    mesh_parts, allp, allt = [], [], []
    off = 0
    for i, p in enumerate(parts):
        P, T, faces, edges = _mesh_part(p["shape"], lin, ang)
        mesh_parts.append({
            "name": p["name"] or f"Body {i + 1}",
            "color": list(p["color"] or DEFAULT_COLOR),
            "pos": [round(v, 4) for v in P.reshape(-1).tolist()],
            "idx": T.reshape(-1).tolist(),
            "faces": faces,
            "edges": [[round(v, 4) for v in e] for e in edges],
            "solids": p.get("n_solids", 0),
        })
        allp.append(P)
        allt.append(T + off)
        off += len(P)
    (out / "mesh.json").write_text(json.dumps({"parts": mesh_parts, "bbox": res["metrics"]["bbox"]}, separators=(",", ":")))
    res["metrics"]["triangles"] = int(sum(len(t) for t in allt))
    P = np.vstack(allp) if allp else np.zeros((0, 3))
    T = np.vstack(allt) if allt else np.zeros((0, 3), dtype=np.int64)

    # ---------------------------------------------------- projections
    views = req.get("views") or ["front", "top", "right", "iso"]
    vj = {}
    big = res["metrics"]["faces"] > int(req.get("hlr_face_limit", 3000))
    for v in views:
        if v not in VIEWS:
            continue
        entry = {}
        try:
            if req.get("hlr", True) and not big:
                polys = _hlr(comp, v, max(diag * 0.001, 1e-3))
                entry = {"v": polys["v"], "h": polys["h"], "bounds": _bounds2d(polys)}
                if req.get("png", True):
                    _draw_view_png(polys, out / f"view_{v}.png")
        except Exception as e:
            res["warnings"].append(f"Projection '{v}' failed: {_fmt_exc(e)}")
        if v != "iso" and len(T):
            try:
                entry["sil_size"] = _silhouette(P, T, v, out / f"sil_{v}.png")
            except Exception as e:
                res["warnings"].append(f"Silhouette '{v}' failed: {_fmt_exc(e)}")
        vj[v] = entry
    if big:
        res["warnings"].append("Hidden-line views were skipped for this large model (more faces than the limit).")
    (out / "views.json").write_text(json.dumps(vj, separators=(",", ":")))
    res["ok"] = True
    res["seconds"] = round(time.time() - t0, 2)
    (out / "build.json").write_text(json.dumps(res, indent=1))
    return res


def _export(req):
    """Re-run a version's code and write one more file format."""
    code = Path(req["code_file"]).read_text(encoding="utf-8")
    ns, shown, _ = _exec(code)
    parts, assy = _collect(ns, shown)
    if not parts:
        return {"ok": False, "error": "The code produced no shape."}
    fmt, path = req["format"], Path(req["path"])
    tol = float(req.get("tolerance", 0.05))
    comp = cq.Compound.makeCompound([p["shape"] for p in parts])
    if fmt == "step":
        _export_step(parts, assy, path, req.get("name"), req.get("schema", "AP214"))
    elif fmt == "stl":
        cq.exporters.export(comp, str(path), "STL", tolerance=tol, angularTolerance=0.1)
    elif fmt == "brep":
        cq.exporters.export(comp, str(path), "BREP")
    elif fmt == "glb":
        a = assy
        if a is None:
            a = cq.Assembly(name=req.get("name") or "part")
            for i, p in enumerate(parts):
                a.add(p["shape"], name=p["name"] or f"body_{i + 1}",
                      color=cq.Color(*(p["color"] or DEFAULT_COLOR)))
        a.export(str(path), "GLTF", tolerance=tol, angularTolerance=0.1)
    elif fmt == "dxf":
        _export_drawing_dxf(comp, path, req.get("name") or "part", req.get("projection", "third-angle"))
    else:
        return {"ok": False, "error": f"Unknown format {fmt}"}
    return {"ok": True, "path": str(path)}


def _export_drawing_dxf(comp, path, name, projection):
    """A 2D drawing of the model: front, top and right views in third-angle
    (or first-angle) layout, hidden lines dashed, overall dimensions."""
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.layers.add("VISIBLE", color=7, lineweight=50)
    doc.layers.add("HIDDEN", color=8, linetype="DASHED", lineweight=25)
    doc.layers.add("DIM", color=1)
    msp = doc.modelspace()
    bb = comp.BoundingBox()
    gap = max(bb.xlen, bb.ylen, bb.zlen) * 0.35 + 10
    diag = max(bb.DiagonalLength, 1e-6)
    # anchor (lower-left of each view's box) in sheet coordinates
    fx, fy = 0.0, 0.0
    if projection == "first-angle":
        place = {"front": (fx, fy), "top": (fx, fy - gap - bb.ylen), "right": (fx - gap - bb.ylen, fy)}
    else:
        place = {"front": (fx, fy), "top": (fx, fy + bb.zlen + gap), "right": (fx + bb.xlen + gap, fy)}
    for v, (ax, ay) in place.items():
        polys = _hlr(comp, v, max(diag * 0.001, 1e-3))
        b = _bounds2d(polys)
        if b is None:
            continue
        dx, dy = ax - b[0], ay - b[1]
        for key, layer in (("h", "HIDDEN"), ("v", "VISIBLE")):
            for pl in polys[key]:
                pts = [(pl[i] + dx, pl[i + 1] + dy) for i in range(0, len(pl), 2)]
                if len(pts) == 2:
                    msp.add_line(pts[0], pts[1], dxfattribs={"layer": layer})
                else:
                    msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
        w, h = b[2] - b[0], b[3] - b[1]
        off = max(w, h) * 0.12 + 5
        try:
            msp.add_linear_dim(base=(ax, ay - off), p1=(ax, ay), p2=(ax + w, ay),
                               dxfattribs={"layer": "DIM"}).render()
            msp.add_linear_dim(base=(ax - off, ay), p1=(ax, ay), p2=(ax, ay + h), angle=90,
                               dxfattribs={"layer": "DIM"}).render()
        except Exception:
            pass
        msp.add_text(v.upper() + " VIEW", height=max(diag * 0.02, 2.5),
                     dxfattribs={"layer": "DIM"}).set_placement((ax, ay + h + off * 0.4))
    msp.add_text(name, height=max(diag * 0.03, 3.5)).set_placement((0, -gap * 1.2))
    doc.saveas(str(path))


def _worker_main(conn):
    try:
        _w_import()
    except Exception as e:  # pragma: no cover - only if the install is broken
        conn.send({"ok": False, "error": "CadQuery could not be imported: " + _fmt_exc(e)})
        return
    while True:
        try:
            req = conn.recv()
        except (EOFError, OSError):
            return
        op = req.get("op")
        try:
            if op == "build":
                r = _build(req)
            elif op == "export":
                r = _export(req)
            elif op == "ping":
                r = {"ok": True, "pid": os.getpid()}
            elif op == "quit":
                return
            else:
                r = {"ok": False, "error": f"unknown op {op}"}
        except BaseException as e:  # noqa: BLE001
            r = {"ok": False, "error": _fmt_exc(e),
                 "trace": "".join(traceback.format_exception(type(e), e, e.__traceback__))[-3000:]}
        try:
            conn.send(r)
        except (OSError, ValueError, TypeError):
            conn.send({"ok": False, "error": "The worker result could not be sent."})


# =============================================================== parent side
class CadWorker:
    """One modelling process, restarted after a crash, a timeout or Stop."""

    def __init__(self):
        self._proc = None
        self._conn = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._proc is not None and self._proc.is_alive():
            return
        ctx = mp.get_context("spawn")
        a, b = ctx.Pipe()
        self._proc = ctx.Process(target=_worker_main, args=(b,), daemon=True, name="aicad-cad")
        self._proc.start()
        self._conn = a

    def warm(self):
        threading.Thread(target=lambda: self.call({"op": "ping"}, timeout=120), daemon=True).start()

    def kill(self):
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.kill()
                p.join(5)
            except Exception:
                pass

    def call(self, req: dict, timeout: float = 120, stop=None) -> dict:
        with self._lock:
            self._ensure()
            try:
                self._conn.send(req)
            except (OSError, ValueError):
                self.kill()
                self._ensure()
                self._conn.send(req)
            t0 = time.time()
            while True:
                if self._conn.poll(0.15):
                    try:
                        return self._conn.recv()
                    except (EOFError, OSError):
                        self.kill()
                        return {"ok": False, "error": "The modelling process ended unexpectedly."}
                if not self._proc.is_alive():
                    self._proc = None
                    return {"ok": False, "error": ("The modelling kernel crashed while running the code. "
                                                   "This usually means an operation on impossible geometry "
                                                   "(for example a fillet larger than the edge allows).")}
                if stop is not None and stop.is_set():
                    self.kill()
                    return {"ok": False, "error": "Stopped.", "stopped": True}
                if time.time() - t0 > timeout:
                    self.kill()
                    return {"ok": False, "error": f"The model code did not finish within {int(timeout)} s and was stopped."}

    def build(self, code, outdir, timeout=180, stop_event=None, **kw):
        req = {"op": "build", "code": code, "outdir": str(outdir)}
        req.update(kw)
        return self.call(req, timeout=timeout, stop=stop_event)

    def export(self, code_file, fmt, path, **kw):
        req = {"op": "export", "code_file": str(code_file), "format": fmt, "path": str(path)}
        req.update(kw)
        return self.call(req, timeout=300)


_WORKER = None


def worker() -> CadWorker:
    global _WORKER
    if _WORKER is None:
        _WORKER = CadWorker()
    return _WORKER
