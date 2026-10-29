"""AICAD self-test: known answers for every part that does not need the AI,
and (with --ai) one round trip through the AI engine.

    python app/selftest.py            full test
    python app/selftest.py --quick    kernel, STEP and import only (~10 s)
    python app/selftest.py --ai       also load the model and ask it
"""
from __future__ import annotations

import json
import multiprocessing as mp
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

RESULTS = []


def check(name, fn):
    t0 = time.time()
    try:
        msg = fn() or ""
        RESULTS.append((name, "ok", msg))
        print(f"  ok    {name}  {msg}  ({time.time() - t0:.1f} s)", flush=True)
    except AssertionError as e:
        RESULTS.append((name, "FAIL", str(e)))
        print(f"  FAIL  {name}: {e}", flush=True)
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, "FAIL", f"{type(e).__name__}: {e}"))
        print(f"  FAIL  {name}: {type(e).__name__}: {e}", flush=True)


def warn(name, msg):
    RESULTS.append((name, "warn", msg))
    print(f"  warn  {name}: {msg}", flush=True)


def main():
    quick = "--quick" in sys.argv
    with_ai = "--ai" in sys.argv
    from aicad import __version__, paths
    from aicad.cadexec import worker, check_code
    print(f"AICAD {__version__} self-test\n")
    tmp = Path(tempfile.mkdtemp(prefix="aicad_selftest_"))
    w = worker()
    ex_index = []
    try:
        ex_index = json.loads((paths.EXAMPLES_DIR / "examples.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass

    # ------------------------------------------------------------ kernel
    def kernel():
        r = w.build("import cadquery as cq\nresult = cq.Workplane().box(10, 20, 30)", tmp / "k", views=["front"])
        assert r["ok"], r.get("error")
        assert abs(r["metrics"]["volume"] - 6000) < 1e-6, r["metrics"]["volume"]
        assert r["metrics"]["size"] == [10.0, 20.0, 30.0], r["metrics"]["size"]
        return "box 10x20x30 = 6000 mm3"
    check("OpenCASCADE kernel and CadQuery", kernel)

    def safety():
        assert check_code("import os\nresult=1"), "import os was accepted"
        assert check_code("open('x','w')"), "open() was accepted"
        assert not check_code("import cadquery as cq\nimport math\nresult = cq.Workplane().box(1,1,1)")
        r = w.build("import cadquery as cq\nresult = cq.Workplane().box(1,1,1).edges().fillet(5)", tmp / "f")
        assert not r["ok"] and r.get("line") == 2, r
        return "unsafe code refused; kernel errors reported with the line"
    check("Code check and error reporting", safety)

    def step_roundtrip():
        import cadquery as cq
        code = (paths.EXAMPLES_DIR / "base_plate" / "reference.py").read_text(encoding="utf-8")
        r = w.build(code, tmp / "s", name="base_plate")
        assert r["ok"], r.get("error")
        shp = cq.importers.importStep(str(tmp / "s" / "model.step")).val()
        v = sum(s.Volume() for s in shp.Solids())
        assert abs(v / r["metrics"]["volume"] - 1) < 1e-6, (v, r["metrics"]["volume"])
        txt = (tmp / "s" / "model.step").read_text(errors="replace")
        assert "base_plate" in txt, "part name missing in the STEP file"
        return f"volume {v:.1f} mm3 identical after re-import, part name kept"
    check("STEP export and re-import", step_roundtrip)

    def ingest_all():
        from aicad.ingest import ingest
        out = []
        pdf = paths.EXAMPLES_DIR / "pipe_flange" / "pipe_flange.pdf"
        pg = ingest(pdf, tmp / "in", "pdf")[0]
        texts = [t["t"] for t in pg["texts"]]
        assert "Ø250" in texts and "PCD 205" in texts, texts[:10]
        out.append(f"PDF {len(texts)} exact texts")
        dxf = paths.EXAMPLES_DIR / "pump_skid" / "pump_skid.dxf"
        pg = ingest(dxf, tmp / "in", "dxf")[0]
        dims = sorted(t["dim"] for t in pg["texts"] if t.get("dim"))
        assert 1400.0 in dims and 700.0 in dims, dims
        out.append(f"DXF {len(dims)} dimension values")
        png = paths.EXAMPLES_DIR / "base_plate" / "base_plate.png"
        pg = ingest(png, tmp / "in", "png")[0]
        assert pg["w"] > 1000
        out.append("PNG")
        return ", ".join(out)
    check("Drawing import (PDF, DXF, PNG)", ingest_all)

    if not quick:
        # -------------------------------------------------------- references
        for ex in ex_index:
            def ref(ex=ex):
                code = (paths.EXAMPLES_DIR / ex["reference"]).read_text(encoding="utf-8")
                r = w.build(code, tmp / ("r_" + ex["id"]), name=ex["id"])
                assert r["ok"], r.get("error")
                t = ex["truth"]
                assert all(abs(a - b) < 1e-3 for a, b in zip(r["metrics"]["size"], t["size"])), (r["metrics"]["size"], t["size"])
                assert abs(r["metrics"]["volume"] / t["volume"] - 1) < 1e-4
                return f"{r['metrics']['size']} mm, {r['metrics']['parts']} part(s)"
            check(f"Example reference: {ex['title']}", ref)

        # -------------------------------------------------------- resolver
        def resolver():
            from aicad import spec, vision
            from aicad.ingest import ingest
            ex = next(e for e in ex_index if e["id"] == "l_bracket")
            t = ex["truth"]
            pg = ingest(paths.EXAMPLES_DIR / ex["drawing"], tmp / "rs", "lb")[0]
            path = tmp / "rs" / pg["file"]
            # loose boxes (as an AI would give them) must snap to the linework
            views = []
            for i, v in enumerate(t["views"]):
                b = v["box"]
                g = 0.04 * (b[2] - b[0])
                views.append({"id": f"V{i + 1}", "type": v["type"], "box": [b[0] - g, b[1] - g, b[2] + g, b[3] + g]})
            sp = {"part_name": "l_bracket", "units": "mm", "views": views,
                  "overall": {"x": 100, "y": 60, "z": 80},
                  "estimates": [{"id": "E1", "name": "t", "view": "V2", "p1": t["probe"]["p1"], "p2": t["probe"]["p2"],
                                 "axis": "x", "describes": "wall thickness"}]}
            res = spec.resolve(sp, pg, path)
            mmpx = res["scale"]["mm_per_px"]
            assert abs(mmpx / t["mm_per_px"] - 1) < 0.02, (mmpx, t["mm_per_px"])
            th = next(v for v in res["values"] if v["name"] == "t")
            assert th["source"] == "ratio" and abs(th["value"] - 10) < 0.5, th
            return f"scale {mmpx:.5f} mm/px (true {t['mm_per_px']:.5f}), unwritten thickness measured {th['value']:.2f} mm (true 10)"
        check("Scale from the views and sizes by ratio", resolver)

        def compare():
            from aicad import vision
            from aicad.ingest import ingest
            ex = next(e for e in ex_index if e["id"] == "base_plate")
            pg = ingest(paths.EXAMPLES_DIR / ex["drawing"], tmp / "cp", "bp")[0]
            gray = vision.load_gray(tmp / "cp" / pg["file"])
            vb = next(v for v in ex["truth"]["views"] if v["type"] == "top")["box"]
            box = vision.norm_box_to_px(vb, pg["w"], pg["h"])
            r = w.build((paths.EXAMPLES_DIR / ex["reference"]).read_text(encoding="utf-8"), tmp / "cpm")
            c = vision.compare(vision.drawing_silhouette(gray, box), vision.model_silhouette(tmp / "cpm" / "sil_top.png"))
            assert c and c["iou"] > 0.9, c
            return f"top-view outline agreement {c['iou']:.3f} for the reference model"
        check("Outline comparison drawing vs model", compare)

        def exports():
            code = tmp / "s" / "model.py"
            code.write_text((paths.EXAMPLES_DIR / "pump_skid" / "reference.py").read_text(encoding="utf-8"), encoding="utf-8")
            sizes = []
            for fmt in ("stl", "glb", "brep", "dxf", "step"):
                out = tmp / f"exp.{fmt}"
                r = w.export(code, fmt, out, name="pump_skid")
                assert r["ok"] and out.exists() and out.stat().st_size > 100, (fmt, r)
                sizes.append(f"{fmt.upper()}")
            return ", ".join(sizes) + " written for an assembly"
        check("Other export formats", exports)

    # ------------------------------------------------------------ AI files
    from aicad import llm
    eng = llm.engines()
    if eng:
        print(f"  ok    AI engines: {', '.join(eng)}")
    else:
        warn("AI engine", "engine\\ has no llama-server.exe (the AI cannot run)")
    models = llm.installed_models()
    gpus = llm.detect_gpus(force=True)
    print("  info  GPU: " + ("; ".join(f"{g['name']} {g.get('vram_gb') or ''} GB" for g in gpus) or "none found"))
    if models:
        for m in models:
            print(f"  {'ok  ' if m['complete'] else 'warn'}  model {m['name']} ({m['size_gb']} GB){'' if m['complete'] else ' incomplete'}")
    else:
        warn("AI model", "models\\ is empty: run 3_GET_AI_MODEL.bat on a PC with internet")
    chosen, note = llm.choose_model(models, llm.best_nvidia_vram(gpus))
    if chosen:
        print(f"  info  model used automatically: {chosen['name']}" + (f" ({note})" if note else ""))

    if with_ai and chosen:
        def ai():
            e = llm.engine()
            assert e.start(wait=True, timeout=900), e.error
            r = e.chat([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=64, thinking=False)
            assert "ok" in r["content"].lower(), r["content"][:200]
            t = r.get("timings", {})
            e.stop()
            return f"answered '{r['content'].strip()[:20]}' on {e.engine_kind}, {t.get('predicted_per_second', 0):.1f} tok/s"
        check("AI engine round trip", ai)

    w.kill()
    shutil.rmtree(tmp, ignore_errors=True)
    nfail = sum(1 for r in RESULTS if r[1] == "FAIL")
    print(f"\n{len([r for r in RESULTS if r[1] == 'ok'])} passed, {nfail} failed, "
          f"{len([r for r in RESULTS if r[1] == 'warn'])} warnings")
    return 1 if nfail else 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
