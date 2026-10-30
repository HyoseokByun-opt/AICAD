"""Survey a drawing and read its main views with the installed AI model,
without modelling - to check how the model copes with a given sheet.

    python tools/survey_test.py <drawing file> [--views 3] [--model qwen3.5-9b-q4]

Creates a project, imports the file, surveys every page and reads the
largest views zoomed from the original; prints what was found (views,
scale bars, dimensions converted to mm, the scale of each view)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--views", type=int, default=3)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    from eval_examples import Job
    from aicad import assembly, llm, paths
    from aicad.ingest import ingest
    from aicad.project import Project
    if a.model:
        paths.save_settings({"model": a.model})
    src = Path(a.file)
    p = Project.create("survey " + src.stem)
    dst = p.dir / "input" / src.name
    shutil.copyfile(src, dst)
    p.add_pages(dst.name, ingest(dst, p.dir / "input", dst.stem[:40]))
    job = Job()
    eng = llm.engine()
    t0 = time.time()
    assembly.ensure_engine(job, need_vision=True)
    out = {"project": p.id, "sheets": [], "readings": {}, "scales": {}}
    for i in range(len(p.data["pages"])):
        sh = assembly.survey_page(job, p, i)
        out["sheets"].append(sh)
        print(json.dumps({k: sh[k] for k in ("id", "title", "kind", "units", "scale_text")}, ensure_ascii=False))
        for v in sh["views"]:
            print(f"   view {v['id']} {v['type']:10s} '{v['label'][:40]}' box {[round(c) for c in v['box']]} ({v['how']})")
        for b in sh["scale_bars"]:
            print(f"   scale bar {b['length_mm']:.0f} mm over {assembly.vision.dist(b['p1'], b['p2']):.0f} px -> {b['mm_per_px']:.4f} mm/px")
        vs = sorted(sh["views"], key=lambda v: -(v["box"][2] - v["box"][0]) * (v["box"][3] - v["box"][1]))[:a.views]
        for v in vs:
            rd = assembly.read_view(job, p, sh, v)
            out["readings"][v["id"]] = rd
            sc, src_ = assembly.view_scale(sh, v, rd)
            out["scales"][v["id"]] = [sc, src_]
            for d in rd["dimensions"][:25]:
                print(f"      {d['text']!r:28s} -> {d['mm']} mm  {d['describes'][:50]}")
            print(f"      scale {sc} ({src_})")
    eng.stop()
    out["seconds"] = round(time.time() - t0, 1)
    (p.dir / "survey_test.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"done in {out['seconds']} s -> {p.dir / 'survey_test.json'}")


if __name__ == "__main__":
    main()
