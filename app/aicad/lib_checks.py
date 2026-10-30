"""Known-answer checks of the modelling library (run by selftest.py).

Each case is model code as the AI would write it, built in the sandbox
worker, and the expected bounding box (mm, tolerance 0.5 mm)."""

CASES = [
    ("units", "result = lib.box(0, 0, 0, lib.ftin(\"18'-10 1/2\\\"\"), lib.ft(1), lib.inch(2))",
     [5753.1, 304.8, 50.8]),
    ("cyl between points", "result = lib.cyl((0, 0, 0), (300, 400, 0), 50)", None),
    ("tube", "result = lib.tube((0, 0, 0), (0, 0, 1000), 168.3, 7.1)", [168.3, 168.3, 1000]),
    ("cone", "result = lib.cone((0, 0, 0), (0, 0, 500), 400, 100)", [400, 400, 500]),
    ("prism (plan outline)", "result = lib.prism([(0,0),(4000,0),(4000,2000),(2000,3000),(0,2000)], -1500, 0)",
     [4000, 3000, 1500]),
    ("extrude_on XZ", "result = lib.extrude_on('XZ', [(0,0),(3000,0),(3000,500),(0,2000)], -400, 400)",
     [3000, 800, 2000]),
    ("extrude_on YZ", "result = lib.extrude_on('YZ', [(0,0),(1000,0),(500,800)], 0, 250)", [250, 1000, 800]),
    ("revolve half section", "result = lib.revolve([(0,0),(1500,0),(1500,400),(600,900),(600,3000),(0,3000)], origin=(0,0,1000))",
     [3000, 3000, 3000]),
    ("revolve about X", "result = lib.revolve([(0,0),(200,0),(200,800),(0,800)], axis='x')", [800, 400, 400]),
    ("member H horizontal", "result = lib.member('H300x300x10x15', (0,0,0), (6000,0,0))", [6000, 300, 300]),
    ("member HEB vertical", "result = lib.member('HEB300', (0,0,0), (0,0,5000))", [300, 300, 5000]),
    ("member W14x30 sloped", "result = lib.member('W14x30', (0,0,0), (3000,0,3000))", None),
    ("member angle imperial", "result = lib.member('L4x4x1/2', (0,0,0), (0,2000,0))", [101.6, 2000, 101.6]),
    ("member pipe", "result = lib.member('PIPE168.3x7.1', (0,0,0), (0,0,3000))", [168.3, 168.3, 3000]),
    ("member SHS top-aligned", "result = lib.member('SHS100x100x6', (0,0,0), (2000,0,0), align='top')", [2000, 100, 100]),
    ("frame (portal)", """nodes = {"a": (0,0,0), "b": (0,0,4000), "c": (6000,0,4000), "d": (6000,0,0)}
result = lib.frame(nodes, [("a","b","HEB240"), ("b","c","IPE360",0,"top"), ("c","d","HEB240"), ("a","c","L80x80x8")])""",
     None),
    ("grating + handrail", "result = lib.compound(lib.grating(0,0,3000,1500,2500), lib.handrail([(0,0,2500),(3000,0,2500)]))", None),
    ("ladder", "result = lib.ladder((0,0,0), 3000)", None),
    ("stair", "result = lib.stair((0,0,0), (3000,0,2400), width=900)", None),
    ("pipe with bends", "result = lib.pipe([(0,0,0),(1000,0,0),(1000,1000,0),(1000,1000,800)], 114.3, 6.0)", None),
    ("flange with bolts", "result = lib.flange((0,0,0), (0,0,1), 285, 24, bore=110, pcd=240, n_bolts=8, bolt_d=22)",
     [285, 285, 24]),
    ("nozzle with flange", "result = lib.nozzle((0,0,0), (1,0,0), 114.3, 300, flange_od=229, flange_t=20, t=6)", None),
    ("vessel 2:1", "result = lib.vessel((0,0,500), 1000, 2000, head='2:1')", [1000, 1000, 2500]),
    ("vessel horizontal hemi", "result = lib.vessel((0,0,0), 800, 3000, head='hemi', axis='x')", [3800, 800, 800]),
    ("blade row", "result = lib.blade_row((0,0,0), 13, 600, 1400, 400, stagger=40, twist=20)", None),
    ("transition circle to rectangle", "result = lib.transition((0,0,0), ('circle', 2000), (0,0,-3000), ('rect', 3000, 1500))",
     [3000, 2000, 3000]),
    ("spiral case", "result = lib.spiral_case((0,0,0), 1800, 2000)", None),
    ("polar + bolt holes", """disc = lib.cyl((0,0,0), (0,0,50), 1000)
result = disc.cut(lib.bolt_holes((0,0,0), (0,0,1), 850, 12, 40, 50))""", [1000, 1000, 50]),
    ("linear", "result = lib.linear(lib.member('HEB200', (0,0,0), (0,0,3000)), 5, (6000, 0, 0))", None),
    ("edit: hole, counterbore and a row", """b = lib.box(0,0,0,200,100,20)
b = lib.f_hole(b, (40,50,20), (0,0,1), 10, 0, cbore_d=18, cbore_depth=5, count=3, pitch=(60,0,0))
result = b""", [200, 100, 20]),
    ("edit: boss and pocket", """b = lib.box(0,0,0,200,100,20)
b = lib.f_boss(b, (50,50,20), (0,0,1), 40, 30, height=15)
result = lib.f_pocket(b, (150,50,20), (0,0,1), 30, depth=8, shape="circle")""", [200, 100, 35]),
    ("edit: fillet and chamfer by clicked points", """b = lib.box(0,0,0,100,100,50)
b = lib.f_fillet(b, [(0,0,25), (100,0,25)], 8)
result = lib.f_chamfer(b, [(50,100,50)], 3)""", [100, 100, 50]),
    ("edit: shell", "result = lib.f_shell(lib.box(0,0,0,100,80,60), (50,40,60), 4)", [100, 80, 60]),
    ("edit: move, rotate, mirror, array", """b = lib.box(0,0,0,50,20,10)
b = lib.f_move(b, 10, 0, 0)
b = lib.f_rotate(b, (0,0,0), (0,0,1), 90)
b = lib.f_mirror(b, (0,0,0), (0,1,0), keep=True)
result = lib.f_array(b, 3, (0,0,100))""", [20, 120, 210]),
    ("edit: assembly component", """a = lib.assemble("t", [("p1", "P1", lambda: lib.box(0,0,0,100,100,10), "gray"),
                         ("p2", "P2", lambda: lib.box(0,0,10,50,50,60), "red")])
a = lib.edit_part(a, "p2", lambda s: lib.f_hole(s, (25,25,60), (0,0,1), 20))
a = lib.add_part(a, "p3", lib.cyl((80,80,10), (80,80,40), 20), "steelblue")
assembly = lib.remove_part(a, "p1")""", [90, 90, 50]),
    ("assemble with a failing component", """def ok():
    return lib.box(0,0,0,100,100,100)
def bad():
    return lib.member('XYZ123', (0,0,0), (1,0,0))
assembly = lib.assemble('test', [('good', 'Good part', ok, 'steelblue'), ('bad', 'Bad part', bad)])""", [100, 100, 100]),
]


def run(worker, tmp):
    out = []
    for name, body, size in CASES:
        code = "import cadquery as cq\nimport aicad_lib as lib\n" + body + "\n"
        r = worker.build(code, tmp / ("lib_" + "".join(c if c.isalnum() else "_" for c in name)),
                         views=["iso"], hlr=False)
        ok = r.get("ok")
        msg = r.get("error", "")
        if ok and size:
            got = r["metrics"]["size"]
            if any(abs(a - b) > 0.5 for a, b in zip(got, size)):
                ok, msg = False, f"size {got} expected {size}"
        if ok and name.startswith("assemble") and not r.get("failed_components"):
            ok, msg = False, "the failing component was not reported"
        out.append((name, bool(ok), msg, r.get("metrics", {}).get("size")))
    return out
