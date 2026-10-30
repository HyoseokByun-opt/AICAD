/* CAD editing: a command line and a feature history.

   Commands are typed (or started from the ribbon) and then ask, step by
   step, for what they need: a face, edges or a component clicked in the 3D
   view, and values typed in the command line. Enter takes the default
   shown in brackets, several values can be given at once as key=value,
   Esc cancels, Enter on an empty line repeats the last command. Each
   finished command becomes a parametric feature of the model script; the
   History tab lists them for editing, suppressing and deleting. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const r3 = (v) => Math.round(v * 1000) / 1000;
  const vec = (p) => p.map(r3);

  // ------------------------------------------------------------- commands
  const C = {
    hole: { title: "Hole", steps: [
      { pick: "face", prompt: "Click the face where the hole goes" },
      { num: "d", prompt: "Diameter", def: 10 },
      { num: "depth", prompt: "Depth (0 = through all)", def: 0 }],
      extra: "options: at=x,y,z offset=dx,dy,dz count=3 pitch=50,0,0 cbore=18 cdepth=5" },
    pocket: { title: "Pocket", steps: [
      { pick: "face", prompt: "Click the face to cut into" },
      { choice: "shape", prompt: "Shape", options: ["rect", "circle", "slot"], def: "rect" },
      { num: "w", prompt: "Width (diameter for a circle)", def: 20 },
      { num: "h", prompt: "Height", def: null, skipIf: (s) => s.shape === "circle" },
      { num: "depth", prompt: "Depth", def: 10 }],
      extra: "options: at=x,y,z offset=dx,dy,dz angle=30 count=3 pitch=40,0,0" },
    pad: { title: "Pad", op: "boss", steps: [
      { pick: "face", prompt: "Click the face to build on" },
      { choice: "shape", prompt: "Shape", options: ["rect", "circle", "slot"], def: "rect" },
      { num: "w", prompt: "Width (diameter for a circle)", def: 20 },
      { num: "h", prompt: "Height of the outline", def: null, skipIf: (s) => s.shape === "circle" },
      { num: "height", prompt: "Pad height", def: 10 }],
      extra: "options: at=x,y,z offset=dx,dy,dz angle=30 count=3 pitch=40,0,0" },
    fillet: { title: "Fillet", steps: [
      { pick: "edges", prompt: "Click the edges to round, Enter when done" },
      { num: "r", prompt: "Radius", def: 3 }] },
    chamfer: { title: "Chamfer", steps: [
      { pick: "edges", prompt: "Click the edges to bevel, Enter when done" },
      { num: "d", prompt: "Size", def: 2 }] },
    shell: { title: "Shell", steps: [
      { pick: "face", prompt: "Click the face to open" },
      { num: "t", prompt: "Wall thickness", def: 3 }] },
    box: { title: "Box", steps: [
      { pick: "face", prompt: "Click the face the box stands on" },
      { num: "lx", prompt: "Length X", def: 50 }, { num: "ly", prompt: "Length Y", def: 50 }, { num: "lz", prompt: "Length Z", def: 50 },
      { choice: "mode", prompt: "Join", options: ["add", "cut", "new"], def: "add" }] },
    cylinder: { title: "Cylinder", steps: [
      { pick: "face", prompt: "Click the face the cylinder stands on" },
      { num: "d", prompt: "Diameter", def: 50 }, { num: "height", prompt: "Height", def: 50 },
      { choice: "mode", prompt: "Join", options: ["add", "cut", "new"], def: "add" }] },
    move: { title: "Move", steps: [
      { pick: "part", prompt: "Click the body or component to move" },
      { vec: "d", prompt: "Displacement dx,dy,dz", def: [0, 0, 100] }] },
    rotate: { title: "Rotate", steps: [
      { pick: "part", prompt: "Click the body or component; the clicked point is the pivot" },
      { choice: "axis", prompt: "Axis", options: ["x", "y", "z"], def: "z" },
      { num: "angle", prompt: "Angle (degrees)", def: 90 }] },
    mirror: { title: "Mirror", steps: [
      { pick: "part", prompt: "Click a face of the body: its plane is the mirror plane" },
      { choice: "plane", prompt: "Plane", options: ["face", "x", "y", "z"], def: "face" },
      { choice: "keep", prompt: "Keep the original", options: ["yes", "no"], def: "yes" }] },
    array: { title: "Array", steps: [
      { pick: "part", prompt: "Click the body or component to repeat" },
      { num: "count", prompt: "Number of copies", def: 3 },
      { vec: "step", prompt: "Step dx,dy,dz", def: [100, 0, 0] }] },
    delete: { title: "Delete component", steps: [{ pick: "part", prompt: "Click the component to delete" }] },
  };
  const ALIAS = { h: "hole", p: "pocket", boss: "pad", extrude: "pad", f: "fillet", c: "chamfer", m: "move", ro: "rotate",
    mi: "mirror", ar: "array", del: "delete", cyl: "cylinder", b: "box" };

  let ctx = null;          // set by init(): viewer, project, api, build, toast, log
  let cur = null;          // running command
  let last = null;
  const hist = [];
  let hpos = 0;

  function prompt(text, hint) {
    $("#cmdPrompt").textContent = text;
    $("#cmdHint").textContent = hint || "";
  }
  function idle() {
    cur = null;
    if (ctx && ctx.viewer()) ctx.viewer().setPickMode(null);
    prompt("Command:", "hole · pocket · pad · fillet · chamfer · shell · box · cylinder · move · rotate · mirror · array · delete · undo · redo");
    $("#cmdBar").classList.remove("active");
  }

  function start(name) {
    name = (ALIAS[name] || name || "").toLowerCase();
    if (name === "undo") return ctx.undo();
    if (name === "redo") return ctx.redo();
    const def = C[name];
    if (!def) { ctx.toast(`Unknown command '${name}'.`, true); return; }
    const v = ctx.version();
    if (!v || !v.ok) { ctx.toast("Build a model first.", true); return; }
    if (name === "delete" && ctx.mode() !== "assembly") { ctx.toast("Only components of an assembly can be deleted.", true); return; }
    cur = { name, def, i: -1, spec: { op: def.op || name }, picks: [] };
    last = name;
    $("#cmdBar").classList.add("active");
    ctx.setCtab("model");
    next();
  }

  function stepNow() { return cur && cur.def.steps[cur.i]; }

  function next() {
    cur.i++;
    while (cur.i < cur.def.steps.length) {
      const st = cur.def.steps[cur.i];
      if (st.skipIf && st.skipIf(cur.spec)) { cur.i++; continue; }
      if (st.num && cur.spec[st.num] !== undefined) { cur.i++; continue; }       // given with key=value
      if (st.choice && cur.spec[st.choice] !== undefined) { cur.i++; continue; }
      break;
    }
    if (cur.i >= cur.def.steps.length) return finish();
    const st = stepNow();
    const head = `${cur.def.title}: ${st.prompt}`;
    if (st.pick) {
      ctx.viewer().setPickMode(st.pick === "edges" ? "edge" : "face");
      prompt(head + (st.pick === "edges" ? ` (${cur.picks.length} picked)` : ""), cur.def.extra || "Esc cancels");
    } else {
      ctx.viewer().setPickMode(null);
      const d = st.num ? (st.def === null ? cur.spec.w : st.def) : st.vec ? st.def.join(",") : st.def;
      const opts = st.choice ? ` (${st.options.join("/")})` : "";
      prompt(`${head}${opts} <${d}>`, cur.def.extra || "Enter takes the value in < >");
    }
    $("#cmdInput").focus();
  }

  // values typed as key=value anywhere in the command
  const KEYS = { count: "count", pitch: "pitch", cbore: "cbore_d", cdepth: "cbore_depth", angle: "angle", d: "d", depth: "depth",
    w: "w", h: "h", height: "height", r: "r", t: "t", lx: "lx", ly: "ly", lz: "lz", mode: "mode", shape: "shape",
    dx: "dx", dy: "dy", dz: "dz", axis: "axis", step: "step", keep: "keep", plane: "plane", at: "at", offset: "offset" };
  function takePairs(text) {
    let rest = text;
    text.replace(/([a-z]+)\s*=\s*([^\s]+)/gi, (m, k, v) => {
      const key = KEYS[k.toLowerCase()];
      if (!key) return m;
      if (["pitch", "step", "at", "offset"].includes(key)) cur.spec[key] = v.split(",").map(Number);
      else if (["mode", "shape", "axis", "keep", "plane"].includes(key)) cur.spec[key] = v.toLowerCase();
      else cur.spec[key] = Number(v);
      rest = rest.replace(m, "");
      return m;
    });
    return rest.trim();
  }

  function onEnter(text) {
    text = text.trim();
    if (!cur) {
      if (!text) { if (last) start(last); return; }
      const [name, ...more] = text.split(/\s+/);
      start(name);
      if (cur && more.length) onEnter(more.join(" "));
      return;
    }
    const st = stepNow();
    if (!st) return;
    // a command name typed while a command runs cancels it and starts the new one
    const word = text.split(/\s+/)[0].toLowerCase();
    const isOption = st.choice && st.options.some((o) => o.startsWith(word));
    if (word && !isOption && (C[word] || word === "undo" || word === "redo")) {
      cancel();
      return onEnter(text);
    }
    if (text) text = takePairs(text);
    if (st.pick) {
      if (st.pick === "edges" && !text) {
        if (!cur.picks.length) { ctx.toast("Click at least one edge."); return; }
        cur.spec.points = cur.picks.map((p) => vec(p.point));
        return next();
      }
      if (text) ctx.toast("Click in the 3D view for this step.");
      return;
    }
    if (st.num) {
      const v = text === "" ? (st.def === null ? cur.spec.w : st.def) : Number(text);
      if (!isFinite(v)) { ctx.toast("Type a number."); return; }
      cur.spec[st.num] = v;
    } else if (st.vec) {
      const v = text === "" ? st.def : text.split(/[,\s]+/).map(Number);
      if (v.length !== 3 || v.some((x) => !isFinite(x))) { ctx.toast("Type three numbers: dx,dy,dz."); return; }
      cur.spec[st.vec] = v;
    } else if (st.choice) {
      const v = text === "" ? st.def : (st.options.find((o) => o.startsWith(text.toLowerCase())) || st.options[+text - 1]);
      if (!v) { ctx.toast(`Choose one of ${st.options.join(", ")}.`); return; }
      cur.spec[st.choice] = v;
    }
    next();
  }

  function onPick(info) {
    const st = stepNow();
    if (!st || !st.pick || !info) return;
    if (st.pick === "edges") {
      cur.picks.push(info);
      prompt(`${cur.def.title}: ${st.prompt} (${cur.picks.length} picked)`, "Enter finishes the selection");
      return;
    }
    cur.pick = info;
    if (ctx.mode() === "assembly") cur.spec.part = info.part;
    cur.spec.point = vec(info.point);
    cur.spec.normal = vec(info.normal);
    next();
  }

  function finish() {
    const s = cur.spec, pk = cur.pick;
    const name = cur.name;
    // exact position: at=x,y,z replaces the clicked point, offset=dx,dy,dz moves it
    if (s.point && Array.isArray(s.at) && s.at.length === 3) s.point = vec(s.at);
    if (s.point && Array.isArray(s.offset) && s.offset.length === 3) s.point = vec(s.point.map((c, i) => c + s.offset[i]));
    delete s.at; delete s.offset;
    // derive the geometric parameters of each operation from the picks
    if (name === "move") { s.dx = s.d[0]; s.dy = s.d[1]; s.dz = s.d[2]; delete s.d; }
    if (["move", "array", "delete"].includes(name)) { delete s.point; delete s.normal; }
    if (name === "rotate") {
      s.origin = s.point; s.axis = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }[s.axis || "z"]; delete s.point; delete s.normal;
    }
    if (name === "mirror") {
      const pl = s.plane || "face";
      s.origin = s.point;
      s.normal = pl === "face" ? s.normal : { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }[pl];
      s.keep = (s.keep || "yes") !== "no";
      delete s.point; delete s.plane;
    }
    if (name === "box") {
      const n = s.normal, p = s.point;
      // the box stands on the clicked face: its centre half its size out along the normal
      const ext = Math.abs(n[0]) * s.lx + Math.abs(n[1]) * s.ly + Math.abs(n[2]) * s.lz;
      s.center = vec([p[0] + n[0] * ext / 2, p[1] + n[1] * ext / 2, p[2] + n[2] * ext / 2]);
      if (s.mode === "cut") s.center = vec([p[0] - n[0] * ext / 2, p[1] - n[1] * ext / 2, p[2] - n[2] * ext / 2]);
      delete s.point; delete s.normal;
      if (s.mode === "new") s.name = "part_" + Date.now().toString(36).slice(-4);
    }
    if (name === "cylinder") {
      s.base = s.point; s.axis = s.mode === "cut" ? s.normal.map((x) => -x) : s.normal;
      delete s.point; delete s.normal;
      if (s.mode === "new") s.name = "part_" + Date.now().toString(36).slice(-4);
    }
    if (name === "pocket" || name === "pad") { if (s.shape === "circle") s.h = s.w; }
    if (s.part === undefined && pk && ctx.mode() === "assembly") s.part = pk.part;
    const title = cur.def.title;
    idle();
    ctx.applyFeature({ action: "add", spec: s }, `${title}: ${describe(s)}`);
  }

  function describe(s) {
    return Object.entries(s).filter(([k]) => !["op", "point", "normal", "points", "origin", "center", "base"].includes(k))
      .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : v}`).join(" ");
  }

  function cancel() {
    if (cur) { ctx.log("Command cancelled.", "warn"); idle(); }
  }

  // ------------------------------------------------------------- history panel
  const ICON = { hole: "target", pocket: "cube", boss: "cube", fillet: "refine", chamfer: "refine", shell: "cube",
    box: "cube", cylinder: "cube", move: "fit", rotate: "rebuild", mirror: "compare", array: "layers", delete: "delete" };
  function renderHistory(box, project) {
    const feats = (project && project.features) || [];
    const v = ctx.version();
    let h = `<div class="desc">Operations added in the program, in order. Double-click one to change its values; the model is rebuilt from the AI's script plus these features.</div>
      <ul class="ftree"><li class="base">${window.ICON("generate")}<div><b>Base model</b><small>${v ? esc(v.id) : ""} · the script written by the AI or by hand</small></div></li>`;
    for (const f of feats) {
      h += `<li data-fn="${f.n}" class="${f.suppressed ? "sup" : ""}" title="Double-click to edit">${window.ICON(ICON[f.spec.op] || "cube")}
        <div><b>${esc(f.text)}</b><small>feature ${f.n}${f.suppressed ? " · suppressed" : ""}</small></div>
        <span class="fbtn"><button data-fedit="${f.n}" title="Edit">✎</button><button data-fsup="${f.n}" title="${f.suppressed ? "Resume" : "Suppress"}">${f.suppressed ? "◉" : "○"}</button><button data-fdel="${f.n}" title="Delete">✕</button></span></li>`;
    }
    h += `</ul>${feats.length ? "" : `<div class="empty">No features yet. Type a command below the 3D view, e.g. <b>hole</b>, or use Model → Modify.</div>`}
      <div class="desc">Undo / redo: Ctrl+Z / Ctrl+Y step through the versions.</div>`;
    box.innerHTML = h;
    box.querySelectorAll("[data-fn]").forEach((li) => li.addEventListener("dblclick", () => editFeature(project, +li.dataset.fn)));
    box.querySelectorAll("[data-fedit]").forEach((b) => b.addEventListener("click", () => editFeature(project, +b.dataset.fedit)));
    box.querySelectorAll("[data-fsup]").forEach((b) => b.addEventListener("click", () => {
      const f = feats.find((x) => x.n === +b.dataset.fsup);
      ctx.applyFeature({ action: "suppress", n: f.n, on: !f.suppressed }, `${f.suppressed ? "Resuming" : "Suppressing"} feature ${f.n}`);
    }));
    box.querySelectorAll("[data-fdel]").forEach((b) => b.addEventListener("click", () => {
      if (!confirm(`Delete feature ${b.dataset.fdel}?`)) return;
      ctx.applyFeature({ action: "delete", n: +b.dataset.fdel }, `Deleting feature ${b.dataset.fdel}`);
    }));
  }

  const EDITABLE = ["d", "depth", "cbore_d", "cbore_depth", "count", "w", "h", "height", "angle", "r", "t", "lx", "ly", "lz",
    "dx", "dy", "dz", "shape", "mode", "keep"];
  function editFeature(project, n) {
    const f = (project.features || []).find((x) => x.n === n);
    if (!f) return;
    const keys = EDITABLE.filter((k) => f.spec[k] !== undefined);
    const vecs = ["pitch", "step", "point", "origin", "axis", "center", "base"].filter((k) => Array.isArray(f.spec[k]));
    let h = `<div class="desc">${esc(f.text)}</div><div class="g2">`;
    for (const k of keys) h += `<div><label class="f">${k}</label><input data-k="${k}" value="${esc(f.spec[k])}"></div>`;
    for (const k of vecs) h += `<div><label class="f">${k} <span class="u">x, y, z</span></label><input data-v="${k}" value="${esc(f.spec[k].join(", "))}"></div>`;
    h += `</div><div class="row" style="margin-top:12px"><button class="btn primary" id="feOk">Apply</button><button class="btn" id="feCancel">Cancel</button></div>`;
    ctx.modal(`Edit feature ${n}`, h);
    $("#feCancel").onclick = ctx.closeModal;
    $("#feOk").onclick = () => {
      const spec = { ...f.spec };
      document.querySelectorAll("#mBody [data-k]").forEach((i) => {
        const k = i.dataset.k, v = i.value.trim();
        spec[k] = typeof f.spec[k] === "number" ? Number(v) : typeof f.spec[k] === "boolean" ? ["true", "yes", "1"].includes(v.toLowerCase()) : v;
      });
      document.querySelectorAll("#mBody [data-v]").forEach((i) => { spec[i.dataset.v] = i.value.split(/[,\s]+/).filter(Boolean).map(Number); });
      ctx.closeModal();
      ctx.applyFeature({ action: "edit", n, spec }, `Editing feature ${n}`);
    };
  }

  const NAMES = [...Object.keys(C), "undo", "redo"];
  function matches(text) {
    const w = text.trim().toLowerCase();
    if (!w || /\s/.test(text.trimStart())) return [];
    const full = ALIAS[w] ? [ALIAS[w]] : [];
    return [...new Set([...full, ...NAMES.filter((n) => n.startsWith(w))])];
  }
  function suggest() {
    if (cur) return;
    const inp = $("#cmdInput");
    const m = matches(inp.value);
    if (!inp.value.trim()) { idle(); return; }
    if (m.length) {
      const d = C[m[0]];
      $("#cmdHint").textContent = `${m.join(" · ")}   Tab completes` + (d && d.extra ? `   ${d.extra}` : "");
    } else if (!/\s/.test(inp.value.trim())) {
      $("#cmdHint").textContent = "no such command";
    }
  }

  // ------------------------------------------------------------- init
  function init(c) {
    ctx = c;
    const inp = $("#cmdInput");
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); const t = inp.value; if (t.trim()) { hist.push(t); hpos = hist.length; } inp.value = ""; onEnter(t); }
      else if (e.key === "Escape") { e.preventDefault(); inp.value = ""; cancel(); }
      else if (e.key === "ArrowUp" && !cur) { if (hpos > 0) inp.value = hist[--hpos]; e.preventDefault(); }
      else if (e.key === "ArrowDown" && !cur) { if (hpos < hist.length - 1) inp.value = hist[++hpos]; else { hpos = hist.length; inp.value = ""; } e.preventDefault(); }
      else if (e.key === "Tab" && !cur) {
        const m = matches(inp.value);
        if (m.length) { e.preventDefault(); inp.value = m[0] + " "; suggest(); }
      }
    });
    // while a command name is typed, the matching commands are offered; Tab completes the first
    inp.addEventListener("input", suggest);
    // typing anywhere (outside fields) goes to the command line; Ctrl+Z / Ctrl+Y step versions
    window.addEventListener("keydown", (e) => {
      const tag = (document.activeElement && document.activeElement.tagName) || "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); ctx.undo(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); ctx.redo(); return; }
      if (e.key === "Escape") { cancel(); return; }
      if (e.key === "Enter" && !cur && last && ctx.activeCtab() === "model") { start(last); return; }
      if (!e.ctrlKey && !e.altKey && !e.metaKey && e.key.length === 1 && /[a-z]/i.test(e.key) && ctx.activeCtab() === "model") {
        inp.focus();
      }
    });
    idle();
  }

  window.CAD = { init, start, onPick, cancel, renderHistory, commands: C, busy: () => !!cur };
})();
