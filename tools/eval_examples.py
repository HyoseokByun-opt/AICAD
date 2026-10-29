"""Run every example through the full AI pipeline and score the result.

    python tools/eval_examples.py                 all examples
    python tools/eval_examples.py base_plate      selected ones
    python tools/eval_examples.py --rounds 0      without refinement

For each example a project is created, the drawing or description is given
to the AI exactly as in the program, and the final model is compared with
the hand-made reference model: overall size per axis, volume, number of
solids, the time taken and the number of builds. The table is printed and
written to workspace/eval_<date>.json. Run it on the PC with the GPU.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class Job:
    """Stand-in for the web job: prints the log."""

    def __init__(self):
        import threading
        self.stop = threading.Event()
        self.result = {}
        self.t0 = time.time()

    def log(self, msg, level="info"):
        if level != "debug":
            print(f"    [{time.time() - self.t0:6.1f}] {msg}", flush=True)

    def set(self, stage=None, progress=None):
        if stage:
            self.log(stage)

    def token(self, kind, text):
        pass

    def stream_mark(self, title):
        pass

    def check(self):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--rounds", type=int, default=None, help="refinement rounds (default: settings)")
    a = ap.parse_args()
    from aicad import paths, pipeline, llm
    from aicad.ingest import ingest
    from aicad.project import Project
    if a.rounds is not None:
        paths.save_settings({"refine_rounds": a.rounds})
    ex = json.loads((paths.EXAMPLES_DIR / "examples.json").read_text(encoding="utf-8"))
    if a.ids:
        ex = [e for e in ex if e["id"] in a.ids]
    rows = []
    eng = llm.engine()
    for e in ex:
        print(f"\n== {e['title']}")
        p = Project.create("eval " + e["id"])
        if e.get("drawing"):
            src = paths.EXAMPLES_DIR / e["drawing"]
            dst = p.dir / "input" / src.name
            shutil.copyfile(src, dst)
            p.add_pages(dst.name, ingest(dst, p.dir / "input", dst.stem))
        job = Job()
        t0 = time.time()
        err = ""
        try:
            pipeline.job_generate(job, p.id, "drawing" if e.get("drawing") else "text", e.get("text", ""))
        except Exception as x:  # noqa: BLE001
            err = str(x)
        p = Project(p.id)
        v = p.version()
        t = e["truth"]
        row = {"id": e["id"], "seconds": round(time.time() - t0, 1), "builds": len(p.data["versions"]),
               "ok": bool(v and v.get("ok")), "error": err}
        if row["ok"]:
            m = v["metrics"]
            row["size"] = m["size"]
            row["size_err"] = [round(mv / tv - 1, 4) if tv else None for mv, tv in zip(m["size"], t["size"])]
            row["volume_err"] = round(m["volume"] / t["volume"] - 1, 4)
            row["solids"] = m["solids"]
            row["score"] = v.get("score")
        rows.append(row)
        print(f"   -> {json.dumps(row)}")
    eng.stop()
    print("\nexample            ok  builds  time(s)  max size err  volume err  drawing score")
    for r in rows:
        if r["ok"]:
            mse = max(abs(x) for x in r["size_err"] if x is not None)
            sc = "" if r.get("score") is None else "%.0f %%" % (r["score"] * 100)
            print(f"{r['id']:18s} yes {r['builds']:6d} {r['seconds']:8.0f}  {mse * 100:10.1f} %  "
                  f"{r['volume_err'] * 100:8.1f} %  {sc}")
        else:
            print(f"{r['id']:18s} NO  {r['builds']:6d} {r['seconds']:8.0f}  {r['error'][:60]}")
    st = eng.status()
    out = paths.workspace() / f"eval_{dt.datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({"model": st["model"], "engine": st["engine"], "gpus": llm.detect_gpus(),
                               "rows": rows}, indent=1))
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
