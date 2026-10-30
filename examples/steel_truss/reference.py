import cadquery as cq
import math
import aicad_lib as lib

# Apalachicola River Bridge, span 1 - steel deck truss (layout model).
# From the erection plan: 8 panels @ 21'-0" = 168'-0", trusses 18'-0" apart,
# depth 17'-6" at U0-L0 rising to 25'-10" at U8-L8. Member sections are not
# given on this sheet; typical riveted sections are assumed.
# Datum: centre of the fixed-end pin L0 on the bridge axis, x along the span, z up.


def build_truss(y):
    # --- PARAMETERS truss (mm) ---
    panel = 6400.8          # panel length, 8 panels @ 21'-0" [drawing]
    n_panels = 8            # number of panels [drawing]
    h0 = 5334.0             # depth at U0-L0, 17'-6" [drawing]
    h8 = 7874.0             # depth at U8-L8, 25'-10" [drawing]
    # --- END PARAMETERS ---
    nodes = {}
    for i in range(n_panels + 1):
        nodes["L%d" % i] = (i * panel, y, 0.0)
        nodes["U%d" % i] = (i * panel, y, h0 + (h8 - h0) * i / n_panels)
    members = []
    for i in range(n_panels):
        members.append(("L%d" % i, "L%d" % (i + 1), "H400x300x14x22"))
        members.append(("U%d" % i, "U%d" % (i + 1), "H400x300x14x22"))
        a, b = ("U%d" % i, "L%d" % (i + 1)) if i % 2 == 0 else ("L%d" % i, "U%d" % (i + 1))
        members.append((a, b, "H250x250x9x14"))
    for i in range(n_panels + 1):
        members.append(("L%d" % i, "U%d" % i, "H300x300x10x15"))
    return lib.frame(nodes, members)


def build_truss_south():
    # --- PARAMETERS truss_south (mm) ---
    half = 2743.2           # half of 18'-0" between trusses [drawing]
    # --- END PARAMETERS ---
    return build_truss(-half)


def build_truss_north():
    # --- PARAMETERS truss_north (mm) ---
    half = 2743.2           # half of 18'-0" between trusses [drawing]
    # --- END PARAMETERS ---
    return build_truss(half)


def laterals(top):
    panel, n, half, h0, h8 = 6400.8, 8, 2743.2, 5334.0, 7874.0
    z = (lambda i: h0 + (h8 - h0) * i / n) if top else (lambda i: 0.0)
    parts = [lib.member("L6x4x1/2", (i * panel, -half, z(i)), (i * panel, half, z(i))) for i in range(n + 1)]
    for i in range(n):
        parts.append(lib.member("L5x3x3/8", (i * panel, -half, z(i)), ((i + 1) * panel, half, z(i + 1))))
        parts.append(lib.member("L5x3x3/8", (i * panel, half, z(i)), ((i + 1) * panel, -half, z(i + 1))))
    return lib.compound(parts)


def build_top_laterals():
    return laterals(True)


def build_bottom_laterals():
    return laterals(False)


def build_sway_frames():
    # --- PARAMETERS sway_frames (mm) ---
    panel = 6400.8          # panel length [drawing]
    half = 2743.2           # half distance between trusses [drawing]
    h0 = 5334.0             # depth at L0 [drawing]
    h8 = 7874.0             # depth at L8 [drawing]
    frame_depth = 2500.0    # depth of the sway frame bracing [ratio]
    # --- END PARAMETERS ---
    parts = []
    for i in (0, 2, 4, 6, 8):
        top = h0 + (h8 - h0) * i / 8
        parts.append(lib.member("L4x4x3/8", (i * panel, -half, top), (i * panel, half, top - frame_depth)))
        parts.append(lib.member("L4x4x3/8", (i * panel, half, top), (i * panel, -half, top - frame_depth)))
        parts.append(lib.member("L4x4x3/8", (i * panel, -half, top - frame_depth), (i * panel, half, top - frame_depth)))
    return lib.compound(parts)


COMPONENTS = [
    ("truss_south", "South truss", build_truss_south, "steelblue"),
    ("truss_north", "North truss", build_truss_north, "steelblue"),
    ("top_laterals", "Top lateral bracing", build_top_laterals, "gray50"),
    ("bottom_laterals", "Bottom lateral bracing", build_bottom_laterals, "gray50"),
    ("sway_frames", "Sway frames", build_sway_frames, "orange"),
]
assembly = lib.assemble("apalachicola_span_1", COMPONENTS)
