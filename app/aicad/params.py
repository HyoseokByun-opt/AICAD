"""The PARAMETERS block at the top of a model script.

Model code keeps every dimension as a named number between two marker
comments, with the provenance in square brackets:

    # --- PARAMETERS (mm) ---
    length = 200.0      # overall length [drawing]
    rib_t = 8.0         # rib thickness [ratio]
    # --- END PARAMETERS ---

The inspector shows them as a table; a changed value is written back into
the same line and the model is rebuilt without the AI.
"""
from __future__ import annotations

import ast
import re

BEGIN = re.compile(r"^\s*#\s*-+\s*PARAMETERS", re.I)
END = re.compile(r"^\s*#\s*-+\s*END\s+PARAMETERS", re.I)
LINE = re.compile(r"^(?P<ind>\s*)(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<val>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:#\s*(?P<cmt>.*))?$")
SOURCES = ("drawing", "ratio", "assumed", "user", "standard", "description")


def _source(comment: str) -> tuple[str, str]:
    m = re.search(r"\[(\w+)\]\s*$", comment or "")
    if m and m.group(1).lower() in SOURCES:
        return comment[: m.start()].strip(), m.group(1).lower()
    return (comment or "").strip(), ""


def parse(code: str) -> list[dict]:
    """Numbers in the PARAMETERS block(s), or top-level numeric constants when
    there is no block. An assembly has one block per component, inside the
    component's builder function and named after it ("# --- PARAMETERS c3 (mm)");
    its parameters carry the component as `group` and are keyed "c3.name"."""
    lines = code.splitlines()
    out = []
    i = 0
    found = False
    while i < len(lines):
        l = lines[i]
        if BEGIN.match(l) and not END.match(l):
            found = True
            ind = len(l) - len(l.lstrip())
            m = re.search(r"PARAMETERS\s+([A-Za-z_]\w*)", l)
            group = m.group(1) if m and m.group(1).lower() not in ("mm",) else ""
            i += 1
            while i < len(lines) and not END.match(lines[i]):
                mm = LINE.match(lines[i])
                if mm and len(mm.group("ind")) == ind:
                    desc, src = _source(mm.group("cmt"))
                    v = mm.group("val")
                    name = mm.group("name")
                    out.append({"name": name, "key": f"{group}.{name}" if group else name, "group": group,
                                "value": float(v), "int": _is_int(v), "desc": desc, "source": src, "line": i + 1})
                i += 1
        i += 1
    if found:
        return out
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)) \
                and not isinstance(node.value.value, bool):
            m = LINE.match(lines[node.lineno - 1])
            desc, src = _source(m.group("cmt") if m else "")
            name = node.targets[0].id
            out.append({"name": name, "key": name, "group": "", "value": float(node.value.value),
                        "int": isinstance(node.value.value, int), "desc": desc, "source": src, "line": node.lineno})
    return out


def _is_int(s: str) -> bool:
    return re.fullmatch(r"[-+]?\d+", s) is not None


def _fmt(v: float, as_int: bool) -> str:
    if as_int:
        return str(int(round(v)))
    s = f"{v:.6f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def update(code: str, values: dict, mark_user: bool = True) -> str:
    """Write new values into the parameter lines (keys as returned by parse);
    the comment is kept and the provenance becomes [user] for every value
    that changed."""
    params = {p["key"]: p for p in parse(code)}
    lines = code.splitlines()
    for key, val in values.items():
        p = params.get(key)
        if p is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if abs(v - p["value"]) < 1e-12:
            continue
        m = LINE.match(lines[p["line"] - 1])
        if not m:
            continue
        desc, src = _source(m.group("cmt"))
        if mark_user:
            src = "user"
        cmt = (desc + (f" [{src}]" if src else "")).strip()
        new = f"{m.group('ind')}{p['name']} = {_fmt(v, p['int'])}"
        lines[p["line"] - 1] = new + (" " * max(1, 22 + len(m.group('ind')) - len(new)) + "# " + cmt if cmt else "")
    return "\n".join(lines) + ("\n" if code.endswith("\n") else "")
