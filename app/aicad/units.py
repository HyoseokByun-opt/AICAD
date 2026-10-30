"""Lengths as written on drawings, converted to millimetres.

    parse_length("18'-10 1/2\\"")   -> 5753.1      feet and inches with a fraction
    parse_length("EL. 59'-6\\"")    -> 18135.6     an elevation
    parse_length("3/8\\"")          -> 9.525
    parse_length("Ø250")           -> 250.0       (default unit mm)
    parse_length("1.5 m")          -> 1500.0
    parse_length("12", "inch")     -> 304.8       a bare number in the drawing's unit
    scale_factor("3/8\\" = 1'-0\\"") -> 32.0        real length per paper length
"""
from __future__ import annotations

import re

INCH = 25.4
_FRAC = re.compile(r"(\d+)\s*/\s*(\d+)")
UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": INCH, "in": INCH, "ft": 12 * INCH, "ft-in": INCH}


def _num(s: str) -> float:
    """'10 1/2' -> 10.5, '3/8' -> 0.375, '7' -> 7."""
    s = s.strip().replace("-", " ")
    tot = 0.0
    for part in s.split():
        m = _FRAC.fullmatch(part)
        tot += float(m.group(1)) / float(m.group(2)) if m else float(part)
    return tot


def _clean(text) -> str:
    t = str(text).upper()
    t = t.replace("′", "'").replace("″", '"').replace("’", "'").replace("”", '"').replace("''", '"')
    t = re.sub(r"^\s*(EL\.?|ELEV\.?|T\.O\.S\.?|TOS|B\.O\.P\.?|C\.L\.|CL)\s*", "", t)
    t = t.replace("Ø", "").replace("Ø", "").replace("DIA.", "").replace("DIA", "")
    t = re.sub(r"^\s*[R]\s*(?=\d)", "", t)
    return t.strip()


def parse_length(text, default_unit: str = "mm"):
    """A length in mm, or None when the text holds no number."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) * UNIT_MM.get(default_unit, 1.0)
    t = _clean(text)
    sign = -1.0 if t.startswith("-") or t.startswith("(-") else 1.0
    # feet and inches: 18'-10 1/2"  18' 10"  21'-0"  168'-0"
    m = re.search(r"(\d+(?:\.\d+)?)\s*'\s*-?\s*(\d+(?:\.\d+)?(?:\s+\d+\s*/\s*\d+)?|\d+\s*/\s*\d+)?\s*\"?", t)
    if m and "'" in t:
        inches = _num(m.group(2)) if m.group(2) else 0.0
        return sign * (float(m.group(1)) * 12 + inches) * INCH
    m = re.search(r"(\d+(?:\.\d+)?(?:\s+\d+\s*/\s*\d+)?|\d+\s*/\s*\d+)\s*(\"|IN\b|INCH)", t)
    if m:
        return sign * _num(m.group(1)) * INCH
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(MM|CM|M)\b", t)
    if m:
        return sign * float(m.group(1).replace(",", ".")) * UNIT_MM[m.group(2).lower()]
    m = re.search(r"\d+\s*/\s*\d+|\d+(?:[.,]\d+)?", t)
    if not m:
        return None
    v = _num(m.group(0)) if "/" in m.group(0) else float(m.group(0).replace(",", "."))
    f = UNIT_MM.get(default_unit, 1.0)
    if default_unit == "ft-in":       # a bare number on a feet-inches drawing is inches
        f = INCH
    return sign * v * f


def scale_factor(text):
    """Real length per paper length from a scale note: '1:50' -> 50,
    '3/8" = 1\'-0"' -> 32, '1/4" = 1\'-0"' -> 48, 'HALF SIZE' -> 2."""
    if not text:
        return None
    t = str(text).upper()
    if "FULL" in t:
        return 1.0
    if "HALF" in t:
        return 2.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", t)
    if m and "=" not in t:
        a, b = float(m.group(1)), float(m.group(2))
        return b / a if a > 0 else None
    if "=" in t:
        left, right = t.split("=", 1)
        a, b = parse_length(left, "inch"), parse_length(right, "ft-in")
        if a and b:
            return b / a
    return None
