"""AICAD web server: the user interface and its JSON API (local by default)."""
from __future__ import annotations

import io
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from aicad import __version__, APP_FULL, APP_NAME, assembly, catalog, features, jobs, llm, params, paths, pipeline
from aicad import spec as specmod
from aicad.cadexec import worker
from aicad.ingest import SUPPORTED, IngestError, ingest
from aicad.project import Project

HERE = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(HERE / "static"), template_folder=str(HERE / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 400 * 1024 * 1024
app.json.sort_keys = False


def _err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


def _project(pid) -> Project:
    if not re.fullmatch(r"[\w\-]+", pid or ""):
        abort(404)
    p = Project(pid)
    if not p.exists():
        abort(404)
    return p


@app.after_request
def _nocache(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return render_template("index.html", version=__version__, app=APP_NAME, full=APP_FULL)


# ------------------------------------------------------------------ status
@app.get("/api/status")
def status():
    gpus = llm.detect_gpus()
    vram = llm.best_nvidia_vram(gpus)
    models = llm.installed_models()
    rec = catalog.for_vram(vram)
    chosen, note = llm.choose_model(models, vram, paths.load_settings().get("model", "auto"))
    return jsonify({
        "version": __version__, "app": APP_NAME, "root": str(paths.ROOT),
        "settings": paths.load_settings(), "gpus": gpus, "vram": vram,
        "engines": list(llm.engines().keys()), "models": models,
        "recommended": {"id": rec["id"], "name": rec["name"], "target": rec["target"]},
        "auto_model": chosen and chosen["id"], "model_note": note,
        "profiles": [{k: p[k] for k in ("id", "name", "target", "min_vram_gb", "license", "repo")} |
                     {"size_gb": round(sum(f[1] for f in p["files"]) / 1e9, 1)} for p in catalog.PROFILES],
        "engine": llm.engine().status(),
        "busy": (lambda j: j and j.snapshot(10**9, 10**9))(jobs.busy_ai()),
    })


@app.post("/api/settings")
def settings():
    s = paths.save_settings(request.get_json(force=True) or {})
    return jsonify({"ok": True, "settings": s})


@app.post("/api/engine/start")
def engine_start():
    body = request.get_json(silent=True) or {}
    eng = llm.engine()
    if jobs.busy_ai():
        return _err("An AI job is running.")
    if body.get("restart"):
        eng.stop()
    eng.start(body.get("model") or None, wait=False)
    return jsonify({"ok": True, "engine": eng.status()})


@app.post("/api/engine/stop")
def engine_stop():
    if jobs.busy_ai():
        return _err("An AI job is running; stop it first.")
    llm.engine().stop()
    return jsonify({"ok": True, "engine": llm.engine().status()})


@app.get("/api/engine")
def engine_status():
    return jsonify(llm.engine().status())


@app.post("/api/shutdown")
def shutdown():
    """End the program (from this PC only): AI engine, modelling worker, server."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return _err("Only allowed from this PC.", 403)
    import os
    import threading

    def bye():
        time.sleep(0.4)
        llm.engine().stop()
        worker().kill()
        os._exit(0)
    threading.Thread(target=bye, daemon=True).start()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def projects():
    return jsonify(Project.list_all())


@app.post("/api/projects")
def project_new():
    body = request.get_json(silent=True) or {}
    p = Project.create(body.get("name") or "Untitled")
    return jsonify(_proj_payload(p))


def _proj_payload(p: Project):
    d = p.summary()
    cur = d.get("current")
    d["code"] = p.code(cur) if cur else ""
    d["params"] = params.parse(d["code"]) if d["code"] else []
    d["features"] = features.parse(d["code"]) if d["code"] else []
    d["model_mode"] = features.model_mode(d["code"]) if d["code"] else "result"
    d["compare"] = p.read_json(f"versions/{cur}/compare.json") if cur else None
    d["views"] = p.read_json(f"versions/{cur}/views.json") if cur else None
    plan = p.read_json("assembly/plan.json")
    if plan:
        d["assembly"] = {"plan": plan, "status": p.read_json("assembly/status.json") or {},
                         "sheets": p.read_json("assembly/sheets.json") or [],
                         "scales": p.read_json("assembly/scales.json") or {}}
    elif p.read_json("assembly/sheets.json"):
        d["assembly"] = {"plan": None, "status": {}, "sheets": p.read_json("assembly/sheets.json") or [],
                         "scales": p.read_json("assembly/scales.json") or {}}
    return d


@app.get("/api/projects/<pid>")
def project_get(pid):
    return jsonify(_proj_payload(_project(pid)))


@app.post("/api/projects/<pid>")
def project_update(pid):
    p = _project(pid)
    body = request.get_json(force=True) or {}
    for k in ("name", "request"):
        if k in body:
            p.data[k] = str(body[k])[:4000]
    if "page" in body:
        p.data["page"] = int(body["page"])
    if "current" in body and p.version(body["current"]):
        p.data["current"] = body["current"]
    p.save()
    return jsonify(_proj_payload(p))


@app.delete("/api/projects/<pid>")
def project_delete(pid):
    p = _project(pid)
    if jobs.busy_ai() and jobs.busy_ai().project_id == pid:
        return _err("A job of this project is running.")
    p.delete()
    return jsonify({"ok": True})


@app.post("/api/projects/<pid>/upload")
def upload(pid):
    p = _project(pid)
    f = request.files.get("file")
    if not f or not f.filename:
        return _err("No file was sent.")
    name = re.sub(r"[^\w.\- ]+", "_", Path(f.filename).name)
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED and ext != ".dwg":
        return _err(f"'{ext}' files are not supported. Use PDF, PNG, JPG, TIFF, BMP or DXF.")
    dst = p.dir / "input" / name
    k = 1
    while dst.exists():
        dst = p.dir / "input" / f"{Path(name).stem}_{k}{ext}"
        k += 1
    f.save(dst)
    try:
        pages = ingest(dst, p.dir / "input", re.sub(r"\W+", "_", dst.stem)[:40])
    except IngestError as e:
        dst.unlink(missing_ok=True)
        return _err(str(e))
    p.add_pages(dst.name, pages)
    if p.data.get("name", "").startswith("Untitled"):
        p.data["name"] = Path(name).stem[:60]
        p.save()
    return jsonify(_proj_payload(p))


@app.delete("/api/projects/<pid>/pages/<int:idx>")
def page_delete(pid, idx):
    p = _project(pid)
    p.remove_page(idx)
    return jsonify(_proj_payload(p))


@app.get("/api/projects/<pid>/file/<path:rel>")
def project_file(pid, rel):
    p = _project(pid)
    try:
        f = p.path(rel)
    except ValueError:
        abort(404)
    if not f.exists() or not f.is_file():
        abort(404)
    resp = send_file(f, as_attachment=bool(request.args.get("dl")), download_name=f.name, max_age=0)
    return resp


# ------------------------------------------------------------------ spec & values
@app.post("/api/projects/<pid>/values")
def values_update(pid):
    """Edited values (Report tab): they become 'user' values."""
    p = _project(pid)
    res = p.read_json("resolved.json")
    if not res:
        return _err("Nothing has been read yet.")
    body = request.get_json(force=True) or {}
    changed = body.get("values", {})
    for v in res["values"]:
        if v["name"] in changed:
            try:
                nv = float(changed[v["name"]])
            except (TypeError, ValueError):
                continue
            if abs(nv - v["value"]) > 1e-9:
                v["value"], v["source"] = nv, "user"
    for add in body.get("add", []):
        try:
            res["values"].append({"name": specmod._ident(add["name"]), "value": float(add["value"]), "unit": "mm",
                                  "source": "user", "ref": "user", "describes": str(add.get("describes", ""))})
        except (KeyError, TypeError, ValueError):
            continue
    res["overall"] = {a: next((v["value"] for v in res["values"] if v["name"] == f"overall_{a}"), None) for a in "xyz"}
    p.write_json("resolved.json", res)
    return jsonify(_proj_payload(p))


@app.post("/api/projects/<pid>/views")
def views_update(pid):
    """Moved or retyped view boxes (Drawing tab) -> the scale and the ratio
    values are recomputed."""
    p = _project(pid)
    sp = p.read_json("spec.json")
    if not sp:
        return _err("Nothing has been read yet.")
    page, _ = p.page()
    body = request.get_json(force=True) or {}
    W, H = page["w"], page["h"]
    views = []
    for v in body.get("views", []):
        b = v.get("box")
        if not b or len(b) < 4:
            continue
        views.append({"id": v.get("id"), "type": v.get("type", "other"), "label": v.get("label", ""),
                      "box": [b[0] / W * 1000, b[1] / H * 1000, b[2] / W * 1000, b[3] / H * 1000],
                      "fixed": bool(v.get("fixed"))})
    sp["views"] = views
    for o in ("x", "y", "z"):
        if o in (body.get("overall") or {}):
            sp["overall"][o] = body["overall"][o]
    p.write_json("spec.json", sp)
    pipeline.resolve_and_save(p, sp)
    return jsonify(_proj_payload(p))


@app.post("/api/projects/<pid>/calibrate")
def calibrate(pid):
    p = _project(pid)
    page, _ = p.page()
    body = request.get_json(force=True) or {}
    cal = p.data.setdefault("calib", {})
    if body.get("clear"):
        cal.pop(page["file"], None)
    else:
        px, mm = float(body["px"]), float(body["mm"])
        if px <= 0 or mm <= 0:
            return _err("Both lengths must be positive.")
        cal[page["file"]] = {"mm_per_px": mm / px, "px": px, "mm": mm}
    p.save()
    sp = p.read_json("spec.json")
    if sp:
        pipeline.resolve_and_save(p, sp)
    return jsonify(_proj_payload(p))


# ------------------------------------------------------------------ jobs
def _start_ai(kind, pid, fn, **kw):
    b = jobs.busy_ai()
    if b:
        return _err("Another AI job is running. Stop it or wait until it finishes.")
    j = jobs.start(kind, pid, fn, ai=True, **kw)
    return jsonify({"ok": True, "job": j.id})


@app.post("/api/projects/<pid>/generate")
def generate(pid):
    _project(pid)
    body = request.get_json(force=True) or {}
    mode = body.get("mode", "drawing")
    if mode not in ("drawing", "text", "spec"):
        return _err("unknown mode")
    return _start_ai("generate", pid, pipeline.job_generate, mode=mode, text=str(body.get("text", ""))[:8000])


@app.post("/api/projects/<pid>/read")
def read(pid):
    _project(pid)
    body = request.get_json(silent=True) or {}
    return _start_ai("read", pid, pipeline.job_read, text=str(body.get("text", ""))[:8000])


@app.post("/api/projects/<pid>/edit")
def edit(pid):
    _project(pid)
    body = request.get_json(force=True) or {}
    ins = str(body.get("instruction", "")).strip()
    if not ins:
        return _err("Write what should change.")
    return _start_ai("edit", pid, pipeline.job_edit, instruction=ins[:4000])


@app.post("/api/projects/<pid>/refine")
def refine(pid):
    _project(pid)
    return _start_ai("refine", pid, pipeline.job_refine)


@app.post("/api/projects/<pid>/assembly")
def assembly_generate(pid):
    """Multi-sheet set / large object: survey, read, plan, model per component."""
    p = _project(pid)
    if not p.data.get("pages"):
        return _err("Import the drawing sheets first.")
    body = request.get_json(silent=True) or {}
    return _start_ai("assembly", pid, assembly.job_generate_assembly, text=str(body.get("text", ""))[:8000],
                     pages=body.get("pages") or None)


@app.post("/api/projects/<pid>/replan")
def assembly_replan(pid):
    p = _project(pid)
    if not p.read_json("assembly/sheets.json"):
        return _err("The sheets have not been read yet.")
    body = request.get_json(silent=True) or {}
    return _start_ai("replan", pid, assembly.job_replan, text=str(body.get("text", p.data.get("request", "")))[:8000])


@app.post("/api/projects/<pid>/component")
def assembly_component(pid):
    _project(pid)
    body = request.get_json(force=True) or {}
    cid = str(body.get("cid", ""))
    if not cid:
        return _err("No component given.")
    return _start_ai("component", pid, assembly.job_component, cid=cid,
                     instruction=str(body.get("instruction", ""))[:4000])


@app.post("/api/projects/<pid>/build")
def build(pid):
    p = _project(pid)
    body = request.get_json(force=True) or {}
    if "params" in body:
        code = params.update(p.code(), body["params"])
        src, note = "params", "parameters changed"
    else:
        code = str(body.get("code", ""))
        src, note = "code", body.get("note", "code edited")
    if not code.strip():
        return _err("There is no code to build.")
    j = jobs.start("build", pid, pipeline.job_build, ai=False, code=code, source=src, note=note)
    return jsonify({"ok": True, "job": j.id})


@app.post("/api/projects/<pid>/feature")
def feature(pid):
    """A CAD operation of the user: add, edit, suppress or delete a feature
    block of the current version's script, then build a new version."""
    p = _project(pid)
    code = p.code()
    if not code:
        return _err("Build a model first.")
    body = request.get_json(force=True) or {}
    act = body.get("action", "add")
    try:
        if act == "add":
            new = features.add(code, body["spec"])
            note = features.describe(body["spec"])
        elif act == "edit":
            new = features.edit(code, int(body["n"]), body["spec"])
            note = "edited: " + features.describe(body["spec"])
        elif act == "suppress":
            new = features.suppress(code, int(body["n"]), bool(body.get("on", True)))
            note = f"feature {body['n']} {'suppressed' if body.get('on', True) else 'resumed'}"
        elif act == "delete":
            new = features.delete(code, int(body["n"]))
            note = f"feature {body['n']} deleted"
        else:
            return _err("unknown action")
    except (KeyError, ValueError, StopIteration) as e:
        return _err(f"The operation could not be added: {e}")
    j = jobs.start("build", pid, pipeline.job_build, ai=False, code=new, source="feature", note=note)
    return jsonify({"ok": True, "job": j.id})


@app.get("/api/jobs/<jid>")
def job_get(jid):
    j = jobs.JOBS.get(jid)
    if not j:
        return _err("unknown job", 404)
    return jsonify(j.snapshot(int(request.args.get("log", 0)), int(request.args.get("stream", 0))))


@app.post("/api/jobs/<jid>/stop")
def job_stop(jid):
    j = jobs.JOBS.get(jid)
    if not j:
        return _err("unknown job", 404)
    j.stop.set()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ export
EXPORTS = {"step": ".step", "stl": ".stl", "glb": ".glb", "brep": ".brep", "dxf": ".dxf"}


@app.post("/api/projects/<pid>/export")
def export(pid):
    p = _project(pid)
    body = request.get_json(force=True) or {}
    vid = body.get("version") or p.data.get("current")
    fmt = body.get("format", "step")
    v = p.version(vid)
    if not v or not v.get("ok"):
        return _err("Build a model first.")
    sp = p.read_json("spec.json") or {}
    base = re.sub(r"[^\w\-]+", "_", body.get("filename") or p.data.get("name") or "model").strip("_") or "model"
    exp = p.dir / "exports"
    exp.mkdir(exist_ok=True)
    s = paths.load_settings()
    if fmt == "py":
        out = exp / f"{base}_{vid}.py"
        shutil.copyfile(p.version_dir(vid) / "model.py", out)
    elif fmt == "zip":
        out = exp / f"{base}_{vid}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in p.version_dir(vid).iterdir():
                z.write(f, f.name)
            for f in ("spec.json", "resolved.json"):
                if (p.dir / f).exists():
                    z.write(p.dir / f, f)
    elif fmt in EXPORTS:
        out = exp / f"{base}_{vid}{EXPORTS[fmt]}"
        schema = body.get("schema") or s.get("step_schema", "AP214")
        if fmt == "step" and schema == s.get("step_schema", "AP214") and (p.version_dir(vid) / "model.step").exists():
            shutil.copyfile(p.version_dir(vid) / "model.step", out)
        else:
            r = worker().export(p.version_dir(vid) / "model.py", fmt, out, name=sp.get("part_name") or base,
                                schema=schema, tolerance=float(body.get("tolerance", 0.05)),
                                projection=(sp.get("projection") if sp.get("projection") in ("first-angle", "third-angle")
                                            else "third-angle"))
            if not r.get("ok"):
                return _err(r.get("error", "export failed"))
    else:
        return _err("unknown format")
    return jsonify({"ok": True, "file": f"exports/{out.name}", "size": out.stat().st_size})


@app.post("/api/projects/<pid>/analysis")
def analysis_model(pid):
    """Beam and shell model for structural analysis, derived from the solids of a version."""
    p = _project(pid)
    body = request.get_json(force=True) or {}
    vid = body.get("version") or p.data.get("current")
    v = p.version(vid)
    if not v or not v.get("ok"):
        return _err("Build a model first.")
    base = re.sub(r"[^\w\-]+", "_", p.data.get("name") or "model").strip("_") or "model"
    name = f"{base}_{vid}_analysis"
    out = p.dir / "exports" / name
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    s = paths.load_settings()
    r = worker().idealize(p.version_dir(vid) / "model.py", out, name,
                          esize=float(body.get("esize") or 0), pipes=body.get("pipes", "beam"),
                          join=bool(body.get("join", True)), density=float(s.get("density", 7.85)))
    if not r.get("ok"):
        return _err(r.get("error", "The analysis model could not be made."))
    zp = p.dir / "exports" / f"{name}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in r["files"]:
            if not f.endswith("_view.json"):
                z.write(out / f, f)
    r["zip"] = f"exports/{zp.name}"
    r["view"] = f"exports/{name}/{name}_view.json"
    return jsonify(r)


# ------------------------------------------------------------------ examples
@app.get("/api/examples")
def examples():
    out = []
    idx = paths.EXAMPLES_DIR / "examples.json"
    try:
        for e in json.loads(idx.read_text(encoding="utf-8")):
            out.append(e)
    except (OSError, ValueError):
        pass
    return jsonify(out)


@app.get("/examples/<path:rel>")
def example_file(rel):
    f = (paths.EXAMPLES_DIR / rel).resolve()
    if paths.EXAMPLES_DIR.resolve() not in f.parents or not f.is_file():
        abort(404)
    return send_file(f, max_age=0)


@app.post("/api/examples/open")
def example_open():
    body = request.get_json(force=True) or {}
    try:
        ex = next(e for e in json.loads((paths.EXAMPLES_DIR / "examples.json").read_text(encoding="utf-8"))
                  if e["id"] == body.get("id"))
    except (OSError, ValueError, StopIteration):
        return _err("unknown example")
    p = Project.create(ex["title"])
    for rel in ex.get("drawings") or ([ex["drawing"]] if ex.get("drawing") else []):
        src = paths.EXAMPLES_DIR / rel
        dst = p.dir / "input" / src.name
        shutil.copyfile(src, dst)
        try:
            pages = ingest(dst, p.dir / "input", re.sub(r"\W+", "_", dst.stem)[:40])
            p.add_pages(dst.name, pages)
        except IngestError as e:
            return _err(str(e))
    if p.data.get("pages"):
        p.data["page"] = 0
    p.data["request"] = ex.get("text", "")
    p.data["example"] = ex["id"]
    if ex.get("mode"):
        p.data["mode"] = ex["mode"]
    p.save()
    out = _proj_payload(p)
    if body.get("with_reference") and ex.get("reference"):
        code = (paths.EXAMPLES_DIR / ex["reference"]).read_text(encoding="utf-8")
        j = jobs.start("build", p.id, pipeline.job_build, ai=False, code=code, source="reference",
                       note="reference model of the example")
        out["job"] = j.id
    return jsonify(out)


def create_app():
    worker().warm()
    return app
