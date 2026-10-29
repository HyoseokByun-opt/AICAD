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
    """Numbers in the PARAMETERS block, or top-level numeric constants when
    the block is missing."""
    lines = code.splitlines()
    out = []
    start = next((i for i, l in enumerate(lines) if BEGIN.match(l) and not END.match(l)), None)
    if start is not None:
        for i in range(start + 1, len(lines)):
            if END.match(lines[i]):
                break
            m = LINE.match(lines[i])
            if m and not m.group("ind"):
                desc, src = _source(m.group("cmt"))
                v = m.group("val")
                out.append({"name": m.group("name"), "value": float(v), "int": _is_int(v),
                            "desc": desc, "source": src, "line": i + 1})
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
            out.append({"name": node.targets[0].id, "value": float(node.value.value),
                        "int": isinstance(node.value.value, int), "desc": desc, "source": src,
                        "line": node.lineno})
    return out


def _is_int(s: str) -> bool:
    return re.fullmatch(r"[-+]?\d+", s) is not None


def _fmt(v: float, as_int: bool) -> str:
    if as_int:
        return str(int(round(v)))
    s = f"{v:.6f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def update(code: str, values: dict, mark_user: bool = True) -> str:
    """Write new values into the parameter lines; the comment is kept and the
    provenance becomes [user] for every value that changed."""
    params = {p["name"]: p for p in parse(code)}
    lines = code.splitlines()
    for name, val in values.items():
        p = params.get(name)
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
        new = f"{name} = {_fmt(v, p['int'])}"
        lines[p["line"] - 1] = new + (" " * max(1, 22 - len(new)) + "# " + cmt if cmt else "")
    return "\n".join(lines) + ("\n" if code.endswith("\n") else "")
