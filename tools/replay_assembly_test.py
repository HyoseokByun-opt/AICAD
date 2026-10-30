"""End-to-end test of the assembly pipeline with recorded AI answers.

    python tools/replay_assembly_test.py downloads/hard/steel_truss/truss_span1.tif

The AI is replaced by fixed answers for the steel truss erection drawing
(Apalachicola River Bridge, span 1; public domain, HAER FL-12): the survey,
the zoomed reading of the elevation, the component plan and one script per
component, including a component whose first script fails and is corrected
and one that cannot be built at all (it must become a placeholder). Every
other step - ingest, view snapping, zoom crops, scale from the dimensions,
digest, contact sheet, component builds, the combined assembly script,
STEP export - runs for real. Exits non-zero when a check fails.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

SURVEY = {
    "sheet": {"title": "Apalachicola River Bridge - Erection Plan Span 1", "number": "E1 5505-6", "kind": "assembly"},
    "units": "ft-in", "scale_text": None, "scale_bars": [],
    "views": [
        {"id": "V1", "type": "plan", "label": "TOP LATERALS", "box": [150, 215, 645, 360], "level_or_cut": "top chord"},
        {"id": "V2", "type": "elevation", "label": "ELEVATION (truss)", "box": [150, 395, 660, 545], "level_or_cut": ""},
        {"id": "V3", "type": "plan", "label": "BOTTOM LATERALS", "box": [150, 600, 645, 745], "level_or_cut": "bottom chord"},
        {"id": "V4", "type": "section", "label": "SWAY FRAME AT U2-L2 SECTION CC", "box": [675, 240, 770, 345], "level_or_cut": ""},
    ],
    "tables": [{"kind": "title block", "box": [790, 800, 900, 920]}],
    "objects": ["two Warren trusses", "top lateral bracing", "bottom lateral bracing", "sway frames"],
    "summary": "Erection plan of a riveted Warren deck truss span: top and bottom lateral systems in plan, the truss "
               "elevation with member marks, and sway frame sections.",
}
READ_ELEV = {
    "dimensions": [
        {"text": "17'-6\"", "describes": "truss depth at U0-L0", "axis": "v", "p1": [102, 300], "p2": [102, 715]},
        {"text": "25'-10\"", "describes": "truss depth at U8-L8", "axis": "v", "p1": [948, 105], "p2": [948, 715]},
        {"text": "8 PANELS @ 21'-0\" = 168'-0\"", "describes": "span, centre of end pins", "axis": "h",
         "p1": [102, 715], "p2": [920, 715]},
    ],
    "levels": [],
    "grid": [],
    "labels": [{"text": "FIXED END", "at": [120, 850]}, {"text": "EXPANSION END", "at": [860, 850]}],
    "members": [{"mark": "U0-U8", "section": "top chord", "p1": [102, 300], "p2": [920, 105]},
                {"mark": "L0-L8", "section": "bottom chord", "p1": [102, 715], "p2": [920, 715]}],
    "shapes": "Warren truss with verticals: 8 panels, bottom chord straight, top chord straight and rising from U0 "
              "(17'-6\") to U8 (25'-10\"); diagonals U0-L1, L1-U2, U2-L3, L3-U4, U4-L5, L5-U6, U6-L7, L7-U8.",
    "notes": ["pin at L0 fixed end, expansion end at L8", "camber diagram below the elevation"],
}
READ_PLAN = {"dimensions": [{"text": "18'-0\" C to C of trusses", "describes": "distance between the trusses",
                             "axis": "v", "p1": [40, 160], "p2": [40, 830]}],
             "levels": [], "grid": [], "labels": [], "members": [],
             "shapes": "X bracing in every panel between the two truss chords, transverse struts at each panel point",
             "notes": []}
PLAN = {
    "name": "Apalachicola River Bridge span 1",
    "datum": "origin at the centre of the fixed end pin L0 of the south truss line projected to the bridge axis; "
             "x along the span, y across, z up from the bottom chord",
    "overall": {"x": 51206, "y": 5786, "z": 8274},
    "components": [
        {"id": "truss_s", "name": "South truss", "kind": "structure", "views": ["S1V2"], "min": [-200, -2950, -250],
         "max": [51400, -2540, 8100], "description": "Warren truss, 8 panels of 6400.8 mm, depth 5334 at L0 to 7874 at L8", "color": "steelblue"},
        {"id": "truss_n", "name": "North truss", "kind": "structure", "views": ["S1V2"], "min": [-200, 2540, -250],
         "max": [51400, 2950, 8100], "description": "as the south truss at y = +2743.2", "color": "steelblue"},
        {"id": "top_lat", "name": "Top laterals", "kind": "structure", "views": ["S1V1"], "min": [-100, -2800, 5200],
         "max": [51300, 2800, 8000], "description": "struts and X bracing between the top chords", "color": "gray50"},
        {"id": "bot_lat", "name": "Bottom laterals", "kind": "structure", "views": ["S1V3"], "min": [-100, -2800, -100],
         "max": [51300, 2800, 100], "description": "struts and X bracing between the bottom chords", "color": "gray50"},
        {"id": "sway", "name": "Sway frames", "kind": "structure", "views": ["S1V4"], "min": [12700, -2800, 3000],
         "max": [51300, 2800, 8000], "description": "X bracing between the verticals at U2-L2, U4-L4, U6-L6, U8-L8", "color": "orange"},
        {"id": "deck", "name": "Deck stringers", "kind": "structure", "views": [], "min": [0, -2500, 7900],
         "max": [51206, 2500, 8300], "description": "not drawn on this sheet", "color": "lightgray"},
    ],
    "notes": ["member sections are not given on this sheet; typical riveted sections were assumed"],
}
TRUSS = '''import cadquery as cq
import aicad_lib as lib
# component: {cid}
# --- PARAMETERS (mm) ---
panel = 6400.8          # panel length, 8 panels @ 21'-0" [drawing]
n_panels = 8            # number of panels [drawing]
h0 = 5334.0             # depth at U0-L0, 17'-6" [drawing]
h8 = 7874.0             # depth at U8-L8, 25'-10" [drawing]
y = {y}                 # truss line, 18'-0" between trusses [drawing]
# --- END PARAMETERS ---
nodes = {{}}
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
result = lib.frame(nodes, members)
'''
LATERALS = '''import cadquery as cq
import aicad_lib as lib
# component: {cid}
# --- PARAMETERS (mm) ---
panel = 6400.8          # panel length [drawing]
n_panels = 8            # panels [drawing]
half = 2743.2           # half distance between trusses [drawing]
h0 = 5334.0             # depth at L0 [drawing]
h8 = 7874.0             # depth at L8 [drawing]
# --- END PARAMETERS ---
def z(i):
    return {zexpr}
parts = []
for i in range(n_panels + 1):
    parts.append(lib.member("L6x4x1/2", (i * panel, -half, z(i)), (i * panel, half, z(i))))
for i in range(n_panels):
    parts.append(lib.member("L5x3x3/8", (i * panel, -half, z(i)), ((i + 1) * panel, half, z(i + 1))))
    parts.append(lib.member("L5x3x3/8", (i * panel, half, z(i)), ((i + 1) * panel, -half, z(i + 1))))
result = lib.compound(parts)
'''
SWAY_BAD = '''import cadquery as cq
import aicad_lib as lib
# component: sway
# --- PARAMETERS (mm) ---
panel = 6400.8          # panel length [drawing]
half = 2743.2           # half distance between trusses [drawing]
# --- END PARAMETERS ---
parts = []
for i in (2, 4, 6, 8):
    top = h0 + (h8 - h0) * i / 8
    parts.append(lib.member("L4x4x3/8", (i * panel, -half, top), (i * panel, half, top - 2500)))
result = lib.compound(parts)
'''
SWAY_GOOD = SWAY_BAD.replace("half = 2743.2           # half distance between trusses [drawing]",
                             "half = 2743.2           # half distance between trusses [drawing]\n"
                             "h0 = 5334.0             # depth at L0 [drawing]\nh8 = 7874.0             # depth at L8 [drawing]").replace(
    "    parts.append(lib.member(\"L4x4x3/8\", (i * panel, -half, top), (i * panel, half, top - 2500)))",
    "    parts.append(lib.member(\"L4x4x3/8\", (i * panel, -half, top), (i * panel, half, top - 2500)))\n"
    "    parts.append(lib.member(\"L4x4x3/8\", (i * panel, half, top), (i * panel, -half, top - 2500)))")
DECK_BAD = '''import cadquery as cq
import aicad_lib as lib
# component: deck
result = lib.member("ZZ999", (0, 0, 8000), (51206, 0, 8000))
'''


def answer(messages):
    from aicad import prompts_asm as PA
    sys_ = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    u = messages[-1]["content"]
    text = u if isinstance(u, str) else " ".join(x.get("text", "") for x in u if x.get("type") == "text")
    if sys_.startswith(PA.SURVEY_SYSTEM[:60]):
        return json.dumps(SURVEY)
    if sys_.startswith(PA.READ_VIEW_SYSTEM[:60]):
        return json.dumps(READ_ELEV if "S1V2" in text else READ_PLAN)
    if sys_.startswith(PA.PLAN_SYSTEM[:60]):
        return json.dumps(PLAN)
    if "runs, but some operations" in text or "failed when it was run" in text:
        if "# component: sway" in text:
            return "```python\n" + SWAY_GOOD + "```"
        return "```python\n" + DECK_BAD + "```"      # the deck cannot be repaired
    cid = text.split("Component to build: ")[1].split(" ")[0]
    code = {"truss_s": TRUSS.format(cid=cid, y=-2743.2), "truss_n": TRUSS.format(cid=cid, y=2743.2),
            "top_lat": LATERALS.format(cid=cid, zexpr="h0 + (h8 - h0) * i / n_panels"),
            "bot_lat": LATERALS.format(cid=cid, zexpr="0.0"), "sway": SWAY_BAD, "deck": DECK_BAD}[cid]
    return "```python\n" + code + "```"


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "downloads/hard/steel_truss/truss_span1.tif")
    from eval_examples import Job
    from aicad import assembly, pipeline
    from aicad.ingest import ingest
    from aicad.project import Project
    calls = []

    def fake_ask(job, messages, stage, max_tokens=8192, temperature=0.6):
        calls.append(stage)
        return answer(messages)
    assembly.ask = fake_ask
    pipeline.ask = fake_ask
    assembly.ensure_engine = lambda job, need_vision=False: None
    p = Project.create("replay truss")
    dst = p.dir / "input" / src.name
    shutil.copyfile(src, dst)
    p.add_pages(dst.name, ingest(dst, p.dir / "input", dst.stem))
    job = Job()
    t0 = time.time()
    assembly.job_generate_assembly(job, p.id, "")
    p = Project(p.id)
    st = p.read_json("assembly/status.json")
    v = p.version()
    sc = p.read_json("assembly/scales.json")
    checks = []
    checks.append(("all views snapped or kept", len(p.read_json("assembly/sheets.json")[0]["views"]) == 4))
    s2 = sc.get("S1V2", [None])[0]
    # 168'-0" over the span and 17'-6"/25'-10" over the depths must agree on one scale
    checks.append(("scale of the elevation from its dimensions", bool(s2)))
    checks.append(("sway frame repaired", st["sway"]["ok"] and st["sway"]["attempts"] >= 2))
    checks.append(("deck became a placeholder", not st["deck"]["ok"]))
    checks.append(("trusses built", st["truss_s"]["ok"] and st["truss_n"]["ok"]))
    checks.append(("assembly version built", bool(v and v.get("ok"))))
    m = v["metrics"] if v and v.get("ok") else {}
    checks.append(("all components in the STEP", m.get("parts") == 6))
    checks.append(("STEP written", (p.version_dir(v["id"]) / "model.step").exists() if v else False))
    code = p.code()
    from aicad import params
    ps = params.parse(code)
    checks.append(("grouped parameters", any(x["group"] == "truss_s" for x in ps)))
    print(f"\n{time.time() - t0:.1f} s, AI calls: {len(calls)} ({', '.join(calls)})")
    print(f"assembly: {m.get('size')} mm, {m.get('solids')} solids, {m.get('faces')} faces, {m.get('triangles')} triangles")
    print(f"scale S1V2: {s2} mm/px ({sc.get('S1V2', [None, None])[1]})")
    bad = 0
    for name, ok in checks:
        print(("ok    " if ok else "FAIL  ") + name)
        bad += not ok
    print("project:", p.id)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
