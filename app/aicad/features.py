"""CAD operations of the user, kept as parametric feature blocks in the script.

An operation done in the program (hole, pocket, fillet, move ...) is
appended to the model script as a block whose first line holds its
parameters:

    # === FEATURE 3: {"op": "hole", "point": [40, 50, 20], "normal": [0, 0, 1], "d": 10} ===
    result = lib.f_hole(result, (40, 50, 20), (0, 0, 1), 10, 0)
    # === END FEATURE 3 ===

The feature tree is read back from these blocks; editing a feature
rewrites its block from the parameters, suppressing comments its code out,
deleting removes it. Faces and edges are referred to by the clicked point,
so a feature keeps its place when what comes before it changes.
"""
from __future__ import annotations

import json
import re

HEAD = re.compile(r"^# === FEATURE (\d+)( \(suppressed\))?: (\{.*\}) ===\s*$")
END = re.compile(r"^# === END FEATURE (\d+) ===\s*$")

OPS = {
    "hole": "Hole", "pocket": "Pocket", "boss": "Pad", "fillet": "Fillet", "chamfer": "Chamfer", "shell": "Shell",
    "box": "Box", "cylinder": "Cylinder", "move": "Move", "rotate": "Rotate", "mirror": "Mirror",
    "array": "Array", "delete": "Delete component",
}


def model_mode(code: str) -> str:
    return "assembly" if re.search(r"^assembly\s*=", code, re.M) else "result"


def parse(code: str) -> list[dict]:
    out = []
    lines = code.splitlines()
    i = 0
    while i < len(lines):
        m = HEAD.match(lines[i])
        if m:
            n = int(m.group(1))
            try:
                spec = json.loads(m.group(3))
            except ValueError:
                spec = {"op": "?"}
            j = i + 1
            while j < len(lines) and not END.match(lines[j]):
                j += 1
            out.append({"n": n, "suppressed": bool(m.group(2)), "spec": spec, "text": describe(spec),
                        "start": i + 1, "end": j + 1})
            i = j
        i += 1
    return out


def _f(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        r = round(float(v), 4)
        return str(int(r)) if r == int(r) else repr(r)
    if isinstance(v, list):
        return "[" + ", ".join(_f(x) for x in v) + "]"
    if isinstance(v, tuple):
        return "(" + ", ".join(_f(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    return repr(v)


def _expr(spec: dict, t: str) -> str:
    """The new shape from the shape `t`."""
    op = spec["op"]
    g = lambda k, d=None: spec.get(k, d)
    pat = ""
    if int(g("count", 1) or 1) > 1:
        pat = f", count={int(g('count'))}, pitch={_f(g('pitch', [0, 0, 0]))}"
    if op == "hole":
        cb = f", cbore_d={_f(g('cbore_d'))}, cbore_depth={_f(g('cbore_depth'))}" if g("cbore_d") else ""
        return f"lib.f_hole({t}, {_f(g('point'))}, {_f(g('normal'))}, {_f(g('d', 10))}, {_f(g('depth', 0))}{cb}{pat})"
    if op in ("pocket", "boss"):
        fn = "f_pocket" if op == "pocket" else "f_boss"
        size = "depth" if op == "pocket" else "height"
        return (f"lib.{fn}({t}, {_f(g('point'))}, {_f(g('normal'))}, {_f(g('w', 20))}, {_f(g('h', g('w', 20)))}, "
                f"{size}={_f(g(size, 10))}, shape={g('shape', 'rect')!r}, angle={_f(g('angle', 0))}{pat})")
    if op in ("fillet", "chamfer"):
        fn = "f_fillet" if op == "fillet" else "f_chamfer"
        return f"lib.{fn}({t}, {_f([tuple(p) for p in g('points', [])])}, {_f(g('r', g('d', 2)))})"
    if op == "shell":
        return f"lib.f_shell({t}, {_f(g('point'))}, {_f(g('t', 3))})"
    if op == "move":
        return f"lib.f_move({t}, {_f(g('dx', 0))}, {_f(g('dy', 0))}, {_f(g('dz', 0))})"
    if op == "rotate":
        return f"lib.f_rotate({t}, {_f(g('origin', [0, 0, 0]))}, {_f(g('axis', [0, 0, 1]))}, {_f(g('angle', 90))})"
    if op == "mirror":
        return f"lib.f_mirror({t}, {_f(g('origin', [0, 0, 0]))}, {_f(g('normal', [1, 0, 0]))}, keep={_f(bool(g('keep', True)))})"
    if op == "array":
        return f"lib.f_array({t}, {int(g('count', 2))}, {_f(g('step', [100, 0, 0]))})"
    if op in ("box", "cylinder"):
        tool = _tool(spec)
        mode = g("mode", "add")
        if mode == "cut":
            return f"lib.f_cut({t}, {tool})"
        if mode == "new":
            return f"lib.compound({t}, {tool})"
        return f"lib.f_union({t}, {tool})"
    raise ValueError(f"unknown operation '{op}'")


def _tool(spec):
    g = spec.get
    if spec["op"] == "box":
        c = g("center", [0, 0, 0])
        return f"lib.box_c({_f(c[0])}, {_f(c[1])}, {_f(c[2])}, {_f(g('lx', 50))}, {_f(g('ly', 50))}, {_f(g('lz', 50))})"
    p0 = g("base", [0, 0, 0])
    n = g("axis", [0, 0, 1])
    h = float(g("height", 50))
    p1 = [p0[i] + n[i] * h for i in range(3)]
    return f"lib.cyl({_f(p0)}, {_f(p1)}, {_f(g('d', 50))})"


def gen(spec: dict, mode: str) -> list[str]:
    """Code lines of a feature for a script that ends in `result` or `assembly`."""
    part = spec.get("part")
    if mode == "assembly":
        if spec["op"] == "delete":
            return [f"assembly = lib.remove_part(assembly, {part!r})"]
        if spec["op"] in ("box", "cylinder") and spec.get("mode") == "new":
            return [f"assembly = lib.add_part(assembly, {spec.get('name') or 'new_part'!r}, {_tool(spec)}, "
                    f"{spec.get('color', 'gray')!r})"]
        if not part:
            raise ValueError("choose the component to change (click one of its faces)")
        return [f"assembly = lib.edit_part(assembly, {part!r}, lambda s: {_expr(spec, 's')})"]
    if spec["op"] == "delete":
        raise ValueError("a single part has no components to delete")
    return [f"result = {_expr(spec, 'result')}"]


def _block(n, spec, mode, suppressed=False):
    body = gen(spec, mode)
    if suppressed:
        body = ["# " + ln for ln in body]
    head = f"# === FEATURE {n}{' (suppressed)' if suppressed else ''}: {json.dumps(spec, separators=(', ', ': '))} ==="
    return [head] + body + [f"# === END FEATURE {n} ==="]


def add(code: str, spec: dict) -> str:
    feats = parse(code)
    n = 1 + max([f["n"] for f in feats] or [0])
    lines = code.rstrip("\n").splitlines()
    if not feats:
        lines += ["", "# " + "=" * 30 + " features added in AICAD " + "=" * 30]
    lines += _block(n, spec, model_mode(code))
    return "\n".join(lines) + "\n"


def _replace(code: str, n: int, new_lines):
    feats = {f["n"]: f for f in parse(code)}
    if n not in feats:
        raise ValueError(f"feature {n} not found")
    f = feats[n]
    lines = code.splitlines()
    lines[f["start"] - 1:f["end"]] = new_lines
    return "\n".join(lines) + "\n"


def edit(code: str, n: int, spec: dict) -> str:
    f = next(x for x in parse(code) if x["n"] == n)
    return _replace(code, n, _block(n, spec, model_mode(code), f["suppressed"]))


def suppress(code: str, n: int, on: bool) -> str:
    f = next(x for x in parse(code) if x["n"] == n)
    return _replace(code, n, _block(n, f["spec"], model_mode(code), on))


def delete(code: str, n: int) -> str:
    return _replace(code, n, [])


def describe(spec: dict) -> str:
    op = spec.get("op", "?")
    g = spec.get
    name = OPS.get(op, op)
    if op == "hole":
        s = f"Ø{g('d')} " + ("through" if not g("depth") else f"depth {g('depth')}")
        if g("cbore_d"):
            s += f", c'bore Ø{g('cbore_d')}"
    elif op in ("pocket", "boss"):
        dims = f"Ø{g('w')}" if g("shape") == "circle" else f"{g('w')} x {g('h', g('w'))}"
        s = f"{dims}, {'depth' if op == 'pocket' else 'height'} {g('depth' if op == 'pocket' else 'height')}"
    elif op in ("fillet", "chamfer"):
        s = f"{'R' if op == 'fillet' else 'C'}{g('r', g('d'))} on {len(g('points') or [])} edge(s)"
    elif op == "shell":
        s = f"wall {g('t')}"
    elif op == "move":
        s = f"by ({g('dx', 0)}, {g('dy', 0)}, {g('dz', 0)})"
    elif op == "rotate":
        s = f"{g('angle')}° about {g('axis')}"
    elif op == "mirror":
        s = "symmetric" if g("keep", True) else "mirror image"
    elif op == "array":
        s = f"{g('count')} x {g('step')}"
    elif op == "box":
        s = f"{g('lx')} x {g('ly')} x {g('lz')} ({g('mode', 'add')})"
    elif op == "cylinder":
        s = f"Ø{g('d')} x {g('height')} ({g('mode', 'add')})"
    else:
        s = ""
    if int(g("count", 1) or 1) > 1 and op in ("hole", "pocket", "boss"):
        s += f", {g('count')} in a row"
    if g("part"):
        s += f" · {g('part')}"
    return f"{name} {s}".strip()
