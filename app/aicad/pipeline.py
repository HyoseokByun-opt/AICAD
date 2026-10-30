"""The modelling pipeline: read -> resolve -> write code -> build -> repair
-> compare with the drawing -> refine.

Each step is logged to the job; every successful or failed build becomes a
version of the project, so nothing the AI produced is lost and the user can
continue from any of them (edit the code, change parameters, ask again).
"""
from __future__ import annotations

import json
import statistics

from . import llm, prompts, spec as specmod, vision
from .cadexec import VIEW_AXES, worker
from .jobs import Stopped
from .paths import load_settings
from .project import Project

COMPARE_VIEWS = ("front", "top", "right", "left", "rear", "bottom")


# ------------------------------------------------------------------ AI calls
def ensure_engine(job, need_vision=False):
    eng = llm.engine()
    if eng.state != "ready":
        job.set("Starting the AI engine (loading the model into memory)")
        ok = eng.start(wait=True, stop=job.stop)
        job.check()
        if not ok:
            raise RuntimeError(eng.error or "The AI engine could not be started.")
        if eng.note:
            job.log(eng.note, "warn")
    st = eng.status()
    job.log(f"AI engine: {st['model']['name']} on {st['engine'].upper()}")
    if need_vision and not eng.model.get("vision"):
        raise RuntimeError(f"The model {eng.model['name']} has no vision projector (mmproj file); "
                           "it cannot read drawings. Install a vision model.")
    return eng


def ask(job, messages, stage: str, max_tokens=8192, temperature=0.6):
    eng = llm.engine()
    s = load_settings()
    think = bool(s.get(f"think_{stage}", True)) and eng.engine_kind != "cpu"
    job.stream_mark(f"{stage} · {'thinking on' if think else 'thinking off'}")
    if think:
        max_tokens = max(max_tokens, 16384)
    r = eng.chat(messages, max_tokens=max_tokens, temperature=temperature, thinking=think,
                 top_p=0.95 if think else 0.8, presence_penalty=0.0 if think else 1.0,
                 on_token=job.token, stop=job.stop)
    job.check()
    t = r.get("timings") or {}
    if t:
        job.log(f"AI answer: {int(t.get('predicted_n', 0))} tokens at {t.get('predicted_per_second', 0):.1f} tok/s, "
                f"prompt {int(t.get('prompt_n', 0))} tokens at {t.get('prompt_per_second', 0):.0f} tok/s")
    if r.get("finish") == "length":
        job.log("The answer reached the token limit and may be cut off.", "warn")
    return r["content"]


def _user(text, images=()):
    if not images:
        return {"role": "user", "content": text}
    return {"role": "user", "content": [{"type": "text", "text": text}] + [llm.image_part(i) for i in images]}


# ------------------------------------------------------------------ reading
def _texts_hint(page) -> str:
    rows = []
    for t in (page or {}).get("texts", [])[:300]:
        b = t["box"]
        lab = t["t"].replace("\n", " ")[:40]
        if t.get("dim") is not None:
            lab = f"{lab} (dimension value {t['dim']:g})"
        rows.append(f"{lab} [{(b[0] + b[2]) // 2},{(b[1] + b[3]) // 2}]")
    return "\n".join(rows)


def ai_image(p: Project, page_path):
    out = p.dir / "input" / ("ai_" + page_path.name)
    if not out.exists() or out.stat().st_mtime < page_path.stat().st_mtime:
        vision.prepare_for_ai(page_path, out)
    return out


def read_drawing(job, p: Project, extra: str):
    page, page_path = p.page()
    if page is None:
        raise RuntimeError("No drawing has been imported.")
    job.set("Reading the drawing", 0.08)
    img = ai_image(p, page_path)
    msgs = [{"role": "system", "content": prompts.READ_SYSTEM},
            _user(prompts.read_user(_texts_hint(page), extra), [img])]
    text = ask(job, msgs, "read", max_tokens=8192, temperature=0.3)
    try:
        raw = specmod.parse_json(text)
    except ValueError as e:
        job.log(f"The answer was not valid JSON ({e}); asking again.", "warn")
        msgs += [{"role": "assistant", "content": text[-6000:]},
                 {"role": "user", "content": "That was not one valid JSON object. Return only the JSON object."}]
        raw = specmod.parse_json(ask(job, msgs, "repair", max_tokens=8192, temperature=0.2))
    sp = specmod.normalize(raw)
    # graphic scale bars: measured on the sheet, the AI's points are only a hint
    if sp.get("scale_bars"):
        from . import scalebar
        W, H = page["w"], page["h"]
        for k, b in enumerate(sp["scale_bars"]):
            try:
                r = scalebar.refine(job, ask, p.dir / "input", page, p.dir / "input" / "bars",
                                    [b["p1"][0] / 1000 * W, b["p1"][1] / 1000 * H],
                                    [b["p2"][0] / 1000 * W, b["p2"][1] / 1000 * H], b["length_mm"], tag=f"bar{k + 1}")
            except Exception as e:
                r = None
                job.log(f"The scale bar could not be measured ({e}).", "warn")
            if r:
                b.update(p1=[r["p1"][0] / W * 1000, r["p1"][1] / H * 1000], p2=[r["p2"][0] / W * 1000, r["p2"][1] / H * 1000],
                         length_mm=r["length_mm"], how=r["how"])
                job.log(f"Scale bar {k + 1}: {r['length_mm']:.0f} mm over {vision.dist(r['p1'], r['p2']):.0f} px "
                        f"= {r['mm_per_px']:.4f} mm/px ({r['how']}).")
    p.write_json("spec.json", sp)
    res = resolve_and_save(p, sp)
    nd, ne = len(sp["dimensions"]), len(sp["estimates"])
    job.log(f"Read: '{sp['part_name']}', {len(sp['views'])} views, {nd} written dimensions, "
            f"{ne} sizes to measure on the sheet.")
    sc = res["scale"]
    if sc["mm_per_px"]:
        job.log(f"Scale: {sc['mm_per_px']:.5f} mm per pixel ({sc['source']}).")
    for w in res["warnings"]:
        job.log(w, "warn")
    for q in sp["questions"][:5]:
        job.log("Open question: " + q, "warn")
    if p.data.get("name", "").startswith("Untitled") and sp["part_name"] != "part":
        p.data["name"] = sp["part_name"].replace("_", " ")
    p.save()
    job.result["spec"] = True
    return sp, res


def resolve_and_save(p: Project, sp: dict, keep_user=True):
    page, page_path = p.page()
    res = specmod.resolve(sp, page, page_path, calib=p.calib(page["file"]) if page else None)
    if keep_user:
        old = p.read_json("resolved.json") or {}
        users = {v["name"]: v for v in old.get("values", []) if v.get("source") == "user"}
        for v in res["values"]:
            if v["name"] in users:
                v["value"], v["source"] = users[v["name"]]["value"], "user"
        # user-adjusted view boxes survive a re-read only for the same view ids
    p.write_json("resolved.json", res)
    return res


# ------------------------------------------------------------------ building
def build_version(job, p: Project, code: str, source: str, note: str = ""):
    vid, d = p.new_version(code, source, note)
    s = load_settings()
    sp = p.read_json("spec.json") or {}
    views = ["front", "top", "right", "iso"]
    for v in sp.get("views", []):
        if v.get("type") in VIEW_AXES and v["type"] not in views:
            views.append(v["type"])
    r = worker().build(code, d, name=(sp.get("part_name") or p.data.get("name") or "part"),
                       quality=s.get("mesh_quality", "standard"), schema=s.get("step_schema", "AP214"),
                       views=views, stop_event=job.stop if job else None)
    if r.get("stopped"):
        p.set_version(vid, ok=False, error="Stopped")
        raise Stopped()
    p.set_version(vid, ok=bool(r.get("ok")), error=r.get("error"), line=r.get("line"),
                  metrics=r.get("metrics"), warnings=r.get("warnings", []) + r.get("lint", []))
    if r.get("ok"):
        if job:
            m = r["metrics"]
            job.log(f"Built {vid}: {m['size'][0]:g} x {m['size'][1]:g} x {m['size'][2]:g} mm, "
                    f"{m['solids']} solid(s), {m['faces']} faces, volume {m['volume'] / 1000:.1f} cm3 "
                    f"({r.get('seconds', 0):.1f} s).", "ok")
            for w in r.get("warnings", []):
                job.log(w, "warn")
    elif job:
        job.log(f"Build {vid} failed: {r.get('error')}" + (f" (line {r['line']})" if r.get("line") else ""), "error")
    return vid, r


def repair_loop(job, p: Project, code: str, vid: str, r: dict, base_note: str):
    s = load_settings()
    tries = int(s.get("repair_attempts", 4))
    k = 0
    while (not r.get("ok") or r.get("lint")) and k < tries:
        k += 1
        job.check()
        if r.get("ok"):
            job.log("The code builds but discards operations: " + "; ".join(r["lint"])[:400], "warn")
        job.set(f"Correcting the code (attempt {k} of {tries})")
        msgs = prompts.code_messages(prompts.repair_user(code, r))
        code = prompts.extract_code(ask(job, msgs, "repair", max_tokens=8192, temperature=0.4))
        vid, r = build_version(job, p, code, "ai-repair", f"{base_note}: repair {k}")
    return code, vid, r


# ------------------------------------------------------------------ comparison
def compare(p: Project, vid: str) -> dict | None:
    res = p.read_json("resolved.json")
    v = p.version(vid)
    if not v or not v.get("ok"):
        return None
    m = v["metrics"]
    rep = {"size": m["size"], "expected": {}, "bbox_err": {}, "views": {}}
    if res:
        for i, a in enumerate("xyz"):
            ex = next((x for x in res["values"] if x["name"] == f"overall_{a}"), None)
            if ex and ex["value"]:
                rep["expected"][a] = {"value": ex["value"], "source": ex["source"]}
                rep["bbox_err"][a] = round(m["size"][i] / ex["value"] - 1.0, 4)
    page, page_path = p.page()
    vd = p.version_dir(vid)
    if res and page_path is not None and page_path.exists():
        gray = vision.load_gray(page_path)
        for rv in res.get("views", []):
            t = rv.get("type")
            if t not in COMPARE_VIEWS or not (vd / f"sil_{t}.png").exists():
                continue
            c = vision.compare(vision.drawing_silhouette(gray, rv["box"]), vision.model_silhouette(vd / f"sil_{t}.png"))
            if c:
                c["view_id"] = rv["id"]
                rep["views"][t] = c
    errs = [abs(e) for e in rep["bbox_err"].values()]
    ious = [c["iou"] for c in rep["views"].values()]
    sc = statistics.mean(ious) if ious else 1.0
    if errs:
        sc *= 1.0 - min(0.5, 2.0 * max(errs))
    rep["score"] = round(sc, 4)
    rep["mean_iou"] = round(statistics.mean(ious), 4) if ious else None
    rep["max_size_error"] = round(max(errs), 4) if errs else None
    rep["needs_refine"] = bool((errs and max(errs) > 0.02) or (ious and min(ious) < 0.85)
                               or any("mirror" in c for c in rep["views"].values()))
    if not errs and not ious:
        # nothing to compare against (drawing not read, or description only)
        rep["score"] = None
        rep["needs_refine"] = False
    (vd / "compare.json").write_text(json.dumps(rep, indent=1))
    p.set_version(vid, score=rep["score"])
    return rep


def compare_text(rep: dict) -> str:
    L = []
    sz = rep["size"]
    L.append(f"Overall size of the model: X {sz[0]:g}, Y {sz[1]:g}, Z {sz[2]:g} mm.")
    if rep["expected"]:
        L.append("Expected from the drawing: " + ", ".join(
            f"{a.upper()} {e['value']:g} ({e['source']})" for a, e in rep["expected"].items()) + ".")
        bad = [f"{a.upper()} {e * 100:+.1f} %" for a, e in rep["bbox_err"].items() if abs(e) > 0.01]
        if bad:
            L.append("Size differences: " + ", ".join(bad) + ". Check the orientation of the axes as well.")
    for t, c in rep["views"].items():
        s = (f"View {t.upper()}: outline agreement {c['iou']:.2f} (1 = identical); width/height "
             f"{c['aspect_model']:.3f} for the model against {c['aspect_drawing']:.3f} on the drawing.")
        if c.get("mirror"):
            s += " The model outline fits much better when mirrored " + \
                 ("left-right" if c["mirror"] == "h" else "top-bottom") + ": a feature is on the wrong side."
        L.append(s)
    return "\n".join(L)


def compose_for_refine(p: Project, vid: str, rep: dict):
    res = p.read_json("resolved.json")
    page, page_path = p.page()
    vd = p.version_dir(vid)
    rows = []
    for rv in (res or {}).get("views", []):
        t = rv.get("type")
        if t in COMPARE_VIEWS and (vd / f"view_{t}.png").exists():
            from PIL import Image
            rows.append((t, vision.crop_image(page_path, rv["box"]), Image.open(vd / f"view_{t}.png")))
    if not rows:
        return None
    return vision.compose_pairs(rows, vd / "compare.png")


def refine_loop(job, p: Project, code: str, vid: str, r: dict, rounds: int):
    best = (p.version(vid).get("score", 0) or 0, vid, code)
    rep = compare(p, vid)
    if rep is None or rep["score"] is None:
        return best[1]
    best = (rep["score"], vid, code)
    job.log(f"Comparison with the drawing: score {rep['score']:.3f}"
            + (f", mean outline agreement {rep['mean_iou']:.2f}" if rep["mean_iou"] is not None else "")
            + (f", largest size difference {rep['max_size_error'] * 100:.1f} %" if rep["max_size_error"] is not None else ""))
    page, page_path = p.page()
    for k in range(rounds):
        if not rep or not rep["needs_refine"]:
            break
        job.check()
        job.set(f"Comparing with the drawing and refining (round {k + 1} of {rounds})")
        comp = compose_for_refine(p, best[1], rep)
        imgs = [ai_image(p, page_path)] + ([comp] if comp else [])
        msgs = prompts.code_messages("")
        msgs[-1] = _user(prompts.refine_user(best[2], compare_text(rep)), imgs)
        new = prompts.extract_code(ask(job, msgs, "code", max_tokens=12000, temperature=0.5))
        nvid, nr = build_version(job, p, new, "ai-refine", f"refine {k + 1}")
        if not nr.get("ok") or nr.get("lint"):
            new, nvid, nr = repair_loop(job, p, new, nvid, nr, f"refine {k + 1}")
        if not nr.get("ok"):
            job.log("The refined code could not be built; the previous version is kept.", "warn")
            break
        rep = compare(p, nvid)
        if rep is None or rep["score"] is None:
            break
        job.log(f"Round {k + 1}: score {rep['score']:.3f} (best so far {best[0]:.3f}).")
        if rep["score"] > best[0] + 1e-4:
            best = (rep["score"], nvid, new)
        else:
            rep = p.read_json(f"versions/{best[1]}/compare.json")
    return best[1]


# ------------------------------------------------------------------ jobs
def _finish(job, p: Project, vid: str | None, ok: bool):
    if vid:
        p.data["current"] = vid
    p.save()
    job.result.update(version=vid, ok=ok)


def job_generate(job, pid: str, mode: str, text: str = ""):
    """mode: drawing (drawing, optional text), text (description only),
    spec (rebuild from the reviewed values without reading again)."""
    p = Project(pid)
    p.data["request"] = text
    p.save()
    s = load_settings()
    has_page = p.page()[0] is not None
    if mode == "drawing" and not has_page:
        raise RuntimeError("Import a drawing first, or describe the object in words.")
    if mode == "text" and not text.strip():
        raise RuntimeError("Describe the object first.")
    ensure_engine(job, need_vision=(mode in ("drawing", "spec") and has_page))
    page, page_path = p.page()
    if mode == "drawing":
        sp, res = read_drawing(job, p, text)
    elif mode == "spec":
        sp, res = p.read_json("spec.json"), p.read_json("resolved.json")
        if not sp:
            raise RuntimeError("Nothing has been read from the drawing yet.")
        if not res:
            res = resolve_and_save(p, sp)
    job.check()
    job.set("Writing the model code", 0.35)
    if mode == "text":
        msgs = prompts.code_messages(prompts.code_user_from_text(text))
        note = "from description"
    else:
        body = prompts.code_user_from_spec(specmod.values_table(res),
                                           json.dumps({k: sp[k] for k in ("part_name", "kind", "summary", "projection",
                                                                          "views", "features", "notes") if k in sp},
                                                      ensure_ascii=False), text, True,
                                           [w for w in res.get("warnings", []) if "measures" in w or "differ" in w])
        msgs = prompts.code_messages("")
        msgs[-1] = _user(body, [ai_image(p, page_path)])
        note = "from drawing"
    code = prompts.extract_code(ask(job, msgs, "code", max_tokens=12000, temperature=0.6))
    job.set("Building the model", 0.6)
    vid, r = build_version(job, p, code, "ai", note)
    if not r.get("ok") or r.get("lint"):
        good = (vid, r, code) if r.get("ok") else None
        code, vid, r = repair_loop(job, p, code, vid, r, note)
        if not r.get("ok") and good:      # the lint repair made it worse: keep the version that built
            vid, r, code = good
    if not r.get("ok"):
        _finish(job, p, vid, False)
        raise RuntimeError("The AI could not produce code that builds. The last attempt is kept as "
                           f"{vid}; its code can be corrected on the Code tab.")
    best = vid
    if mode != "text" and int(s.get("refine_rounds", 2)) > 0:
        job.set("Checking the model against the drawing", 0.75)
        best = refine_loop(job, p, code, vid, r, int(s.get("refine_rounds", 2)))
    elif mode != "text":
        compare(p, vid)
    _finish(job, p, best, True)
    job.log(f"Finished: {best} is the current version.", "ok")


def job_read(job, pid: str, text: str = ""):
    p = Project(pid)
    ensure_engine(job, need_vision=True)
    read_drawing(job, p, text)
    p.save()


def job_edit(job, pid: str, instruction: str):
    p = Project(pid)
    code = p.code()
    if not code:
        raise RuntimeError("There is no model to change yet.")
    page, page_path = p.page()
    eng = ensure_engine(job)
    job.set("Changing the model as requested", 0.2)
    msgs = prompts.code_messages("")
    imgs = [ai_image(p, page_path)] if page_path is not None and eng.model.get("vision") else []
    msgs[-1] = _user(prompts.edit_user(code, instruction), imgs)
    new = prompts.extract_code(ask(job, msgs, "edit", max_tokens=12000, temperature=0.5))
    vid, r = build_version(job, p, new, "ai-edit", instruction[:80])
    if not r.get("ok") or r.get("lint"):
        new, vid, r = repair_loop(job, p, new, vid, r, "edit")
    p.log("edit", instruction, version=vid)
    _finish(job, p, vid, bool(r.get("ok")))
    if r.get("ok"):
        compare(p, vid)
    else:
        raise RuntimeError(f"The changed code does not build; it is kept as {vid}.")


def job_refine(job, pid: str):
    p = Project(pid)
    vid = p.data.get("current")
    if not vid or not p.version(vid).get("ok"):
        raise RuntimeError("Build a model first.")
    ensure_engine(job, need_vision=True)
    best = refine_loop(job, p, p.code(vid), vid, {"ok": True}, max(1, int(load_settings().get("refine_rounds", 2))))
    _finish(job, p, best, True)


def job_build(job, pid: str, code: str, source: str = "code", note: str = ""):
    p = Project(pid)
    job.set("Building the model", 0.2)
    vid, r = build_version(job, p, code, source, note)
    _finish(job, p, vid, bool(r.get("ok")))
    if r.get("ok"):
        compare(p, vid)
    else:
        job.result["error"] = r.get("error")
        job.result["line"] = r.get("line")
