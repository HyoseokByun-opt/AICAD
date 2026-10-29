/* AICAD user interface. Plain script; the 3D viewer is an ES module that
   announces itself with the "viewer3d-ready" event. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: 0 });
  const I = (n, c) => window.ICON(n, c);

  const S = {
    status: null, project: null, tab: "home", ctab: "model", rtab: "inspect",
    job: null, jobLog: 0, jobStream: 0, viewer: null, dv: null, pick: null, measure: null,
    meshVersion: null, codeDirty: false, paramEdits: {}, valueEdits: {}, exported: [], polling: false,
  };

  // ------------------------------------------------------------------ API
  async function api(method, url, body, isForm) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      if (isForm) opt.body = body;
      else { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
    }
    const r = await fetch(url, opt);
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    if (!r.ok || (j && j.ok === false)) throw new Error((j && j.error) || `${r.status} ${r.statusText}`);
    return j;
  }
  function toast(msg, err) {
    const t = $("#toast");
    t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), err ? 6000 : 3200);
  }
  const fileUrl = (rel, dl) => S.project ? `/api/projects/${S.project.id}/file/${rel}${dl ? "?dl=1" : ""}` : "";
  const P = () => S.project;
  const curVer = () => P() && P().versions && P().versions.find((v) => v.id === P().current);

  // ------------------------------------------------------------------ console
  function logLine(msg, level = "info", t) {
    const c = $("#console");
    const d = document.createElement("div");
    d.className = level;
    d.innerHTML = (t !== undefined ? `<span class="t">[${fmt(t, 1).padStart(6)} s]</span> ` : "") + esc(msg);
    c.appendChild(d);
    while (c.childNodes.length > 1500) c.removeChild(c.firstChild);
    c.parentElement.scrollTop = c.parentElement.scrollHeight;
  }

  // ------------------------------------------------------------------ ribbon
  const RIBBON = {
    home: [
      { cap: "Project", items: [["new", "new", "New project"], ["open", "open", "Open project"], ["examples", "examples", "Examples"]] },
      { cap: "Input", items: [["import", "import", "Import drawing", { file: true }], ["describe", "describe", "Describe in words"]] },
      { cap: "Create", items: [["generate", "generate", "Generate 3D model", { primary: true }], ["read", "read", "Read drawing only", { ai: true }]] },
      { cap: "Result", items: [["show-model", "cube", "3D model"], ["show-values", "values", "Dimensions"], ["exp-step", "step", "Export STEP"]] },
    ],
    drawing: [
      { cap: "Sheet", items: [["import", "import", "Import drawing", { file: true }], ["page-prev", "prev", "Previous page"], ["page-next", "next", "Next page"], ["page-del", "delete", "Remove page"]] },
      { cap: "Views", items: [["show-views", "views", "Show views"], ["edit-views", "edit", "Edit view boxes"], ["add-view", "plus", "Add view"]] },
      { cap: "Scale", items: [["measure2d", "ruler", "Measure"], ["calib", "target", "Calibrate scale"], ["calib-clear", "delete", "Clear calibration"]] },
      { cap: "Read", items: [["read", "read", "Read drawing", { ai: true }], ["show-values", "values", "Dimensions"]] },
    ],
    model: [
      { cap: "Build", items: [["rebuild", "rebuild", "Rebuild"], ["show-params", "params", "Parameters"], ["show-code", "code", "Code"]] },
      { cap: "Versions", items: [["ver-prev", "prev", "Previous version"], ["ver-next", "next", "Next version"], ["show-versions", "history", "All versions"]] },
      { cap: "View", items: [["cam-iso", "cube", "Isometric"], ["fit", "fit", "Fit"], ["section", "section", "Section"], ["measure3d", "ruler", "Measure"]] },
      { cap: "Check", items: [["show-compare", "compare", "Compare with drawing"], ["shot", "camera", "Screen capture"]] },
    ],
    ai: [
      { cap: "Engine", items: [["ai-start", "power", "Start engine"], ["ai-stop", "stop", "Stop engine"], ["ai-panel", "chip", "Model and GPU"]] },
      { cap: "Create", items: [["generate", "generate", "Generate 3D model", { primary: true }], ["read", "read", "Read drawing only", { ai: true }], ["from-values", "values", "Build from dimensions", { ai: true }]] },
      { cap: "Improve", items: [["refine", "refine", "Refine against drawing", { ai: true }], ["edit-ai", "edit", "Change by instruction", { ai: true }]] },
    ],
    export: [
      { cap: "3D CAD", items: [["exp-step", "step", "STEP"], ["exp-stl", "stl", "STL"], ["exp-glb", "glb", "glTF (GLB)"], ["exp-brep", "brep", "BREP"]] },
      { cap: "2D", items: [["exp-dxf", "dxf", "2D drawing (DXF)"], ["shot", "camera", "Screen capture"]] },
      { cap: "Source", items: [["exp-py", "python", "Model code (.py)"], ["exp-zip", "zip", "Version package"]] },
    ],
    settings: [
      { cap: "Settings", items: [["set-panel", "gear", "Program settings"], ["ai-panel", "gpu", "AI engine and GPU"]] },
    ],
  };
  const PANEL_HEAD = {
    home: ["home", "Request", "Drawing and/or description → 3D model"],
    drawing: ["sheet", "Drawing", "Pages, views, scale and measured sizes"],
    model: ["cube", "Model", "Versions and checks"],
    ai: ["chip", "AI", "Engine, changes by instruction, refinement"],
    export: ["step", "Export", "STEP and other formats"],
    settings: ["gear", "Settings", "Engine, pipeline and workspace"],
  };

  function renderRibbon() {
    const bar = $("#rbar");
    bar.innerHTML = RIBBON[S.tab].map((g) => `<div class="rgroup"><div class="ritems">${g.items.map(([id, ic, label, o = {}]) =>
      `<button class="rbtn${o.primary ? " primary" : ""}${o.ai ? " ai" : ""}${o.file ? " file" : ""}" data-act="${id}" title="${esc(label)}">${I(ic)}<span>${esc(label)}</span>${o.file ? `<input type="file" accept=".pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.gif,.dxf" data-file="1">` : ""}</button>`).join("")}</div><div class="rcap">${g.cap}</div></div>`).join("");
    $$(".rbtn", bar).forEach((b) => {
      if (b.classList.contains("file")) b.querySelector("input").addEventListener("change", (e) => { importFile(e.target.files[0]); e.target.value = ""; });
      else b.addEventListener("click", () => { if (!b.classList.contains("dis")) act(b.dataset.act); });
    });
    updateRibbonState();
  }
  function updateRibbonState() {
    const has = !!P(), ver = curVer(), ok = ver && ver.ok, pages = has && P().pages.length;
    const busy = S.job && ["queued", "running"].includes(S.job.state) && S.job.ai;
    const need = {
      "exp-step": ok, "exp-stl": ok, "exp-glb": ok, "exp-brep": ok, "exp-dxf": ok, "exp-py": ver, "exp-zip": ver,
      rebuild: ver, "ver-prev": has && P().versions.length > 1, "ver-next": has && P().versions.length > 1,
      refine: ok && pages && !busy, "edit-ai": ver && !busy, read: pages && !busy, generate: !busy,
      "from-values": has && P().resolved && !busy, "page-prev": pages > 1, "page-next": pages > 1, "page-del": pages,
      "edit-views": has && P().resolved, "add-view": has && P().resolved, "calib": pages, "measure2d": pages,
      "calib-clear": pages, section: ok, measure3d: ok, shot: ok, "show-compare": ok,
    };
    $$(".rbtn[data-act]").forEach((b) => { const v = need[b.dataset.act]; if (v !== undefined) b.classList.toggle("dis", !v); });
    $("#btnGenerate").disabled = !!busy;
  }

  // ------------------------------------------------------------------ actions
  async function act(id) {
    try {
      switch (id) {
        case "new": return newProject();
        case "open": return openProjects();
        case "examples": return openExamples();
        case "describe": setTab("home"); setTimeout(() => $("#reqText") && $("#reqText").focus(), 50); return;
        case "generate": return generate();
        case "read": return readOnly();
        case "from-values": return generate("spec");
        case "show-model": return setCtab("model");
        case "show-values": return setCtab("values");
        case "show-code": return setCtab("code");
        case "show-compare": return setCtab("compare");
        case "show-params": return setRtab("params");
        case "show-versions": setTab("model"); return;
        case "exp-step": return doExport("step");
        case "exp-stl": return doExport("stl");
        case "exp-glb": return doExport("glb");
        case "exp-brep": return doExport("brep");
        case "exp-dxf": return doExport("dxf");
        case "exp-py": return doExport("py");
        case "exp-zip": return doExport("zip");
        case "page-prev": return setPage((P().page || 0) - 1);
        case "page-next": return setPage((P().page || 0) + 1);
        case "page-del": return delPage(P().page || 0);
        case "show-views": setCtab("drawing"); toggleDv("views", true); return;
        case "edit-views": setCtab("drawing"); return setDvMode(S.dv.mode === "edit" ? "pan" : "edit");
        case "add-view": return addView();
        case "measure2d": setCtab("drawing"); return setDvMode(S.dv.mode === "measure" ? "pan" : "measure");
        case "calib": setCtab("drawing"); return setDvMode(S.dv.mode === "calib" ? "pan" : "calib");
        case "calib-clear": return clearCalib();
        case "rebuild": return rebuild();
        case "ver-prev": return stepVersion(-1);
        case "ver-next": return stepVersion(1);
        case "cam-iso": setCtab("model"); return S.viewer && S.viewer.view("iso");
        case "fit": setCtab("model"); return S.viewer && S.viewer.fit();
        case "section": setCtab("model"); return cycleSection();
        case "measure3d": setCtab("model"); return $("#vMeasure").click();
        case "shot": return screenshot();
        case "ai-start": return engineStart();
        case "ai-stop": return engineStop();
        case "ai-panel": return setTab("ai");
        case "refine": return refine();
        case "edit-ai": setTab("ai"); setTimeout(() => $("#editText") && $("#editText").focus(), 50); return;
        case "set-panel": return setTab("settings");
      }
    } catch (e) { toast(e.message, true); }
  }

  // ------------------------------------------------------------------ tabs
  function setTab(t) {
    S.tab = t;
    $$("#rtabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
    renderRibbon();
    renderLeft();
  }
  function setCtab(c) {
    S.ctab = c;
    $$("#ctabs button").forEach((b) => b.classList.toggle("on", b.dataset.c === c));
    $$(".cpage").forEach((p) => p.classList.toggle("on", p.id === "c-" + c));
    renderCenter();
  }
  function setRtab(r) {
    S.rtab = r;
    $$("#rptabs button").forEach((b) => b.classList.toggle("on", b.dataset.r === r));
    $$(".rpage").forEach((p) => p.classList.toggle("on", p.id === "r-" + r));
    renderRight();
  }

  // ------------------------------------------------------------------ project
  async function newProject(name) {
    const nm = name || "Untitled";
    S.project = await api("POST", "/api/projects", { name: nm });
    afterProjectLoad(true);
    return S.project;
  }
  async function loadProject(id, quiet) {
    try {
      S.project = await api("GET", `/api/projects/${id}`);
      localStorage.setItem("aicad.project", id);
      afterProjectLoad(!quiet);
    } catch (e) {
      if (!quiet) toast("The project could not be opened: " + e.message, true);
      localStorage.removeItem("aicad.project");
    }
  }
  async function reloadProject() { if (P()) await loadProject(P().id, true); }
  function afterProjectLoad(resetView) {
    localStorage.setItem("aicad.project", P().id);
    $("#projName").value = P().name || "";
    if (!S.codeDirty || resetView) setCode(P().code || "", true);
    S.paramEdits = {}; S.valueEdits = {};
    renderAll();
  }
  function renderAll() { renderLeft(); renderCenter(); renderRight(); updateRibbonState(); renderStatusBar(); }

  async function ensureProject(name) { return P() || newProject(name); }

  async function importFile(f) {
    if (!f) return;
    try {
      await ensureProject(f.name.replace(/\.[^.]+$/, ""));
      const fd = new FormData();
      fd.append("file", f);
      logLine(`Importing ${f.name} ...`);
      S.project = await api("POST", `/api/projects/${P().id}/upload`, fd, true);
      afterProjectLoad(false);
      const pg = P().pages[P().page];
      logLine(`Imported ${f.name}: ${P().pages.length} page(s)` + (pg && pg.texts.length ? `, ${pg.texts.length} text items read exactly from the file` : ""), "ok");
      setCtab("drawing");
    } catch (e) { toast(e.message, true); logLine(e.message, "error"); }
  }

  async function setPage(i) {
    if (!P() || !P().pages.length) return;
    i = (i + P().pages.length) % P().pages.length;
    S.project = await api("POST", `/api/projects/${P().id}`, { page: i });
    renderAll();
  }
  async function delPage(i) {
    if (!confirm("Remove this page from the project?")) return;
    S.project = await api("DELETE", `/api/projects/${P().id}/pages/${i}`);
    renderAll();
  }
  async function setVersion(vid) {
    S.project = await api("POST", `/api/projects/${P().id}`, { current: vid });
    setCode(P().code || "", true);
    renderAll();
  }
  function stepVersion(d) {
    const vs = P().versions; if (!vs.length) return;
    const i = vs.findIndex((v) => v.id === P().current);
    setVersion(vs[Math.max(0, Math.min(vs.length - 1, i + d))].id);
  }

  // ------------------------------------------------------------------ jobs
  async function startJob(promise, label) {
    try {
      const r = await promise;
      S.job = { id: r.job, state: "queued", ai: true, label };
      S.jobLog = 0; S.jobStream = 0;
      $("#aiout").innerHTML = "";
      logLine(label, "stage");
      $("#btnStop").disabled = false;
      updateRibbonState();
      poll();
    } catch (e) { toast(e.message, true); logLine(e.message, "error"); }
  }
  async function poll() {
    if (S.polling || !S.job) return;
    S.polling = true;
    try {
      while (S.job) {
        let j;
        try { j = await api("GET", `/api/jobs/${S.job.id}?log=${S.jobLog}&stream=${S.jobStream}`); }
        catch (e) { await sleep(1500); continue; }
        for (const l of j.logs) if (l.level !== "debug") logLine(l.msg, l.level, l.t);
        S.jobLog = j.log_n;
        renderStream(j);
        S.job = { ...S.job, ...j, ai: S.job.ai };
        renderStatusBar();
        if (!["queued", "running"].includes(j.state)) {
          const job = S.job;
          S.job = null;
          $("#btnStop").disabled = true;
          if (job.state === "done") toast(job.kind === "build" ? "Build finished." : "Finished.");
          else if (job.state === "failed") toast(job.error || "Failed", true);
          await reloadProject();
          if (job.result && job.result.version) {
            if (job.kind === "read") setCtab("values");
            else if (S.ctab !== "compare" && S.ctab !== "code") setCtab("model");
          } else if (job.kind === "read") setCtab("values");
          S.lastJob = job;
          renderStatusBar(job);
          break;
        }
        await sleep(500);
      }
    } finally { S.polling = false; updateRibbonState(); }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function renderStream(j) {
    const out = $("#aiout");
    // the server resends the last piece (it may have grown)
    const pieces = j.stream || [];
    let k = j.stream_from;
    for (const [kind, text] of pieces) {
      let el = out.querySelector(`[data-k="${k}"]`);
      if (!el) { el = document.createElement("span"); el.dataset.k = k; el.className = kind; out.appendChild(el); }
      el.textContent = kind === "mark" ? "▌ " + text + "\n" : text;
      k++;
    }
    S.jobStream = j.stream_n;
    const pg = out.parentElement;
    if (pg.scrollHeight - pg.scrollTop - pg.clientHeight < 120) pg.scrollTop = pg.scrollHeight;
  }

  async function stopJob() {
    if (!S.job) return;
    try { await api("POST", `/api/jobs/${S.job.id}/stop`); logLine("Stopping ...", "warn"); } catch (e) { toast(e.message, true); }
  }

  // ------------------------------------------------------------------ AI actions
  function reqText() { const t = $("#reqText"); return t ? t.value : (P() && P().request) || ""; }
  async function generate(forceMode) {
    const text = reqText().trim();
    if (!P() && !text) { toast("Import a drawing or describe the object first."); setTab("home"); return; }
    await ensureProject(text.slice(0, 40) || "Untitled");
    const pages = P().pages.length;
    let mode = forceMode || (pages ? "drawing" : "text");
    if (mode === "text" && !text) { toast("Import a drawing or describe the object first."); return; }
    const lab = mode === "drawing" ? "Generating the 3D model from the drawing" + (text ? " and the description" : "")
      : mode === "spec" ? "Building the 3D model from the reviewed dimensions" : "Generating the 3D model from the description";
    startJob(api("POST", `/api/projects/${P().id}/generate`, { mode, text }), lab);
    if ($("#d-ai") && !$("#dock").classList.contains("collapsed")) setDock("ai");
  }
  async function readOnly() {
    if (!P() || !P().pages.length) { toast("Import a drawing first."); return; }
    startJob(api("POST", `/api/projects/${P().id}/read`, { text: reqText() }), "Reading the drawing");
    setDock("ai");
  }
  async function refine() {
    startJob(api("POST", `/api/projects/${P().id}/refine`), "Comparing the model with the drawing and refining it");
    setDock("ai");
  }
  async function editAI() {
    const t = $("#editText").value.trim();
    if (!t) { toast("Write what should change."); return; }
    startJob(api("POST", `/api/projects/${P().id}/edit`, { instruction: t }), "Changing the model: " + t.slice(0, 80));
    setDock("ai");
  }
  async function quickBuild(body, label) {
    try {
      const r = await api("POST", `/api/projects/${P().id}/build`, body);
      S.job = { id: r.job, state: "queued", ai: false };
      S.jobLog = 0; S.jobStream = 0;
      logLine(label, "stage");
      poll();
    } catch (e) { toast(e.message, true); }
  }
  function rebuild() {
    if (S.codeDirty) return quickBuild({ code: $("#codeEdit").value, note: "code edited" }, "Building the edited code");
    if (Object.keys(S.paramEdits).length) return applyParams();
    return quickBuild({ code: P().code, note: "rebuild" }, "Rebuilding the current version");
  }
  async function applyParams() {
    if (!Object.keys(S.paramEdits).length) { toast("No parameter was changed."); return; }
    const p = { ...S.paramEdits };
    S.paramEdits = {};
    quickBuild({ params: p }, "Rebuilding with changed parameters: " + Object.entries(p).map(([k, v]) => `${k} = ${v}`).join(", "));
  }

  async function engineStart() {
    try { await api("POST", "/api/engine/start", {}); logLine("Starting the AI engine ...", "stage"); refreshStatus(); } catch (e) { toast(e.message, true); }
  }
  async function engineStop() {
    try { await api("POST", "/api/engine/stop", {}); logLine("AI engine stopped; the graphics memory is free.", "warn"); refreshStatus(); } catch (e) { toast(e.message, true); }
  }

  // ------------------------------------------------------------------ export
  async function doExport(fmt) {
    if (!P()) return;
    try {
      const body = { format: fmt };
      if (fmt === "step") body.schema = ($("#expSchema") && $("#expSchema").value) || undefined;
      if (fmt === "stl") body.tolerance = parseFloat(($("#expTol") && $("#expTol").value) || "0.05");
      if ($("#expName") && $("#expName").value.trim()) body.filename = $("#expName").value.trim();
      logLine(`Exporting ${fmt.toUpperCase()} ...`);
      const r = await api("POST", `/api/projects/${P().id}/export`, body);
      S.exported.unshift({ file: r.file, size: r.size, fmt, t: new Date().toLocaleTimeString() });
      const a = document.createElement("a");
      a.href = fileUrl(r.file, true); a.download = r.file.split("/").pop();
      document.body.appendChild(a); a.click(); a.remove();
      logLine(`Exported ${r.file} (${fmt_bytes(r.size)}).`, "ok");
      if (S.tab === "export") renderLeft();
    } catch (e) { toast(e.message, true); logLine(e.message, "error"); }
  }
  const fmt_bytes = (n) => n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : (n / 1e3).toFixed(1) + " kB";
  function screenshot() {
    if (!S.viewer) return;
    const url = S.viewer.screenshot();
    const a = document.createElement("a");
    a.href = url; a.download = `${(P() && P().name) || "model"}_${P() ? P().current : ""}.png`;
    document.body.appendChild(a); a.click(); a.remove();
  }

  // ------------------------------------------------------------------ left panel
  function sec(title, icon, body, extra = "", cls = "") {
    return `<div class="sec ${cls}"><div class="sh">${I(icon)}<span>${title}</span>${extra ? `<small>${extra}</small>` : ""}</div><div class="sb">${body}</div></div>`;
  }
  function renderLeft() {
    const [ic, t, s] = PANEL_HEAD[S.tab];
    $("#lhead").innerHTML = `${I(ic)}<div><b>${t}</b><small>${s}</small></div>`;
    const f = { home: leftHome, drawing: leftDrawing, model: leftModel, ai: leftAI, export: leftExport, settings: leftSettings }[S.tab];
    // text being typed survives a redraw of the panel
    const keep = {};
    for (const id of ["reqText", "editText", "expName"]) { const el = $("#" + id); if (el) keep[id] = el.value; }
    $("#lbody").innerHTML = f();
    for (const [id, v] of Object.entries(keep)) { const el = $("#" + id); if (el && v) el.value = v; }
    bindLeft();
  }

  function thumbsHtml() {
    if (!P() || !P().pages.length) return "";
    return `<div class="thumbs">${P().pages.map((pg, i) => `<div class="thumb${i === P().page ? " on" : ""}" data-page="${i}" title="${esc(pg.source)} · page ${pg.page}">
      <img src="${fileUrl("input/" + pg.file)}" loading="lazy"><span>${esc(pg.source.slice(0, 14))} p${pg.page}</span><button data-delpage="${i}" title="Remove">✕</button></div>`).join("")}</div>`;
  }

  function engineNote() {
    const st = S.status;
    if (!st) return "";
    const ok = st.models.some((m) => m.complete);
    if (!ok) return `<div class="note err">No AI model is installed. Run <b>3_GET_AI_MODEL.bat</b> on a PC with internet and copy the <span class="mono">models</span> folder here. Recommended for this PC: <b>${esc(st.recommended.name)}</b>.</div>`;
    const e = st.engine;
    if (e.state === "error") return `<div class="note err">${esc(e.error)}</div>`;
    if (e.state !== "ready") return `<div class="note">The AI engine starts automatically with the first request (loading the model takes from a few seconds to a minute). Start it now from the <b>AI</b> tab to save that time.</div>`;
    return "";
  }

  function leftHome() {
    const p = P();
    const pages = p ? p.pages.length : 0;
    let h = engineNote();
    h += sec("Drawing", "sheet", `
      <div class="drop" id="dropZone">${I("import")}<b>Drop a drawing here</b> or click to choose<br><span class="hint">PDF, PNG, JPG, TIFF, BMP or DXF</span><input type="file" id="dropInput" hidden accept=".pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.gif,.dxf"></div>
      ${thumbsHtml()}`, pages ? `${pages} page${pages > 1 ? "s" : ""}` : "");
    h += sec("Description and instructions", "describe", `
      <textarea id="reqText" rows="6" placeholder="Describe the object, or add what the drawing lacks.&#10;Example: Base frame for a pump, 1200 x 600 mm, made of 100 mm channels, four anchor holes of 22 mm, a 20 mm top plate.">${esc(p ? p.request || "" : "")}</textarea>
      <div class="desc">${pages ? "With a drawing, this text is passed on as additional instructions (it takes precedence over the drawing)." : "Without a drawing, the model is built from this text alone; sizes that are not given are chosen and marked as assumed."}</div>`);
    h += `<button class="btn ai lg block" id="homeGen">${I("generate")} Generate 3D model</button>
      <div class="row" style="margin:8px 0 12px;justify-content:space-between"><button class="btn sm" id="homeRead" ${pages ? "" : "disabled"}>${I("read")} Read the drawing only</button>
      <button class="btn sm" id="homeVals" ${p && p.resolved ? "" : "disabled"}>${I("values")} Build from dimensions</button></div>`;
    h += sec("Versions", "history", versionsHtml(), p ? `${p.versions.length}` : "");
    return h;
  }

  function versionsHtml() {
    const p = P();
    if (!p || !p.versions.length) return `<div class="empty">No model yet.</div>`;
    const SRC = { ai: "AI", "ai-repair": "AI correction", "ai-refine": "AI refinement", "ai-edit": "AI change", params: "Parameters", code: "Code edit", reference: "Reference" };
    return `<ul class="tl">${p.versions.slice().reverse().map((v) => `<li data-ver="${v.id}" class="${v.id === p.current ? "on" : ""}">
      ${v.ok ? I("ok", "ok") : I("error", "bad")}<div><b>${v.id}</b> ${esc(SRC[v.source] || v.source)}<small>${esc(v.note || "")}${v.ok ? "" : " — " + esc((v.error || "").slice(0, 90))}</small></div>
      ${v.score !== undefined && v.score !== null ? `<span class="score" title="Agreement with the drawing">${fmt(v.score * 100, 0)} %</span>` : ""}</li>`).join("")}</ul>`;
  }

  function leftDrawing() {
    const p = P();
    if (!p) return `<div class="empty">Open or create a project first.</div>`;
    let h = sec("Pages", "sheet", (p.pages.length ? thumbsHtml() : "") + `<div class="drop" id="dropZone" style="margin-top:8px">${I("import")}Add a drawing<input type="file" id="dropInput" hidden accept=".pdf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.gif,.dxf"></div>`, `${p.pages.length}`);
    const res = p.resolved;
    if (!res) {
      h += `<div class="note">The views, the scale and the measured sizes appear here after the AI has read the drawing (<b>Read drawing</b> or <b>Generate</b>).</div>`;
    } else {
      const types = ["front", "top", "right", "left", "rear", "bottom", "section", "detail", "isometric", "other"];
      h += sec("Views", "views", `<table class="t"><tr><th>View</th><th>Type</th><th>Size (px)</th><th></th></tr>${res.views.map((v, i) => `<tr>
        <td><b style="color:${window.VIEW_COLORS[v.type] || "#57606a"}">${esc(v.id)}</b></td>
        <td><select data-vtype="${i}">${types.map((t) => `<option ${t === v.type ? "selected" : ""}>${t}</option>`).join("")}</select></td>
        <td class="n" title="${esc(({ snap: "Snapped to the outline on the sheet", size: "The AI's box missed; matched by size to the outline on the sheet", ai: "Box as given by the AI (no outline found)", user: "Placed by hand" })[v.how] || "")}">${fmt(v.size_px[0], 0)} × ${fmt(v.size_px[1], 0)}<br><span class="hint">${({ snap: "snapped", size: "matched by size", ai: "AI box", user: "by hand" })[v.how] || ""}</span></td><td><button class="btn sm" data-vdel="${i}" title="Delete">✕</button></td></tr>`).join("")}</table>
        <div class="desc">Drag the boxes with <b>Edit view boxes</b>. The type says which side the view shows; the scale and every size measured on the sheet are recomputed after a change.</div>`, `${res.views.length}`);
      const sc = res.scale || {};
      const cal = p.calib && p.pages[p.page] && p.calib[p.pages[p.page].file];
      h += sec("Scale", "target", `<div class="kv"><div>mm per pixel</div><div>${sc.mm_per_px ? sc.mm_per_px.toFixed(5) : "–"}</div>
        <div>Source</div><div style="font-family:var(--font)">${esc(sc.source || "none")}</div>
        ${sc.spread !== undefined ? `<div>Spread of views</div><div>${fmt(sc.spread * 100, 1)} %</div>` : ""}
        ${cal ? `<div>Calibration</div><div>${fmt(cal.mm, 2)} mm = ${fmt(cal.px, 1)} px</div>` : ""}</div>
        ${(sc.candidates || []).length ? `<div class="subh">Scale from each view</div><table class="t"><tr><th>View</th><th>Axis</th><th>mm/px</th></tr>${sc.candidates.map((c) => `<tr><td>${esc(c.view)}</td><td>${c.axis.toUpperCase()}</td><td class="n">${c.mm_per_px.toFixed(5)}</td></tr>`).join("")}</table>` : ""}
        <div class="desc"><b>Calibrate scale</b>: pick two points on the sheet whose real distance you know. A calibration overrides the scale derived from the dimensions.</div>`);
      const est = res.values.filter((v) => v.source === "ratio");
      h += sec("Sizes measured on the sheet", "ruler", est.length ? `<table class="t"><tr><th>Name</th><th>mm</th><th>From</th></tr>${est.map((v) => `<tr><td title="${esc(v.describes)}">${esc(v.name)}</td><td class="n">${fmt(v.value, 2)}</td><td class="hint">${esc(v.ref)}</td></tr>`).join("")}</table>` : `<div class="empty">None.</div>`, `${est.length}`);
      for (const w of res.warnings || []) h += `<div class="note warn">${esc(w)}</div>`;
    }
    const pg = p.pages[p.page];
    if (pg) h += sec("This page", "info", `<div class="kv"><div>File</div><div style="font-family:var(--font)">${esc(pg.source)} · page ${pg.page}</div><div>Image</div><div>${pg.w} × ${pg.h} px</div><div>Kind</div><div style="font-family:var(--font)">${pg.kind === "pdf-vector" ? "vector PDF" : pg.kind === "dxf" ? "DXF (exact geometry)" : "raster image"}</div><div>Text from file</div><div>${pg.texts.length} items</div>${pg.paper_mm ? `<div>Paper</div><div>${pg.paper_mm[0]} × ${pg.paper_mm[1]} mm</div>` : ""}</div>`);
    return h;
  }

  function leftModel() {
    const p = P();
    if (!p) return `<div class="empty">Open or create a project first.</div>`;
    let h = sec("Versions", "history", versionsHtml() + `<div class="desc">Every build is kept. Click a version to show it; parameter changes, code edits and AI changes continue from the version shown.</div>`, `${p.versions.length}`);
    const v = curVer();
    if (v) {
      const items = [];
      if (!v.ok) items.push(`<div class="note err"><b>Build failed.</b> ${esc(v.error || "")}${v.line ? ` (line ${v.line})` : ""}</div>`);
      for (const w of v.warnings || []) items.push(`<div class="note warn">${esc(w)}</div>`);
      const cmp = p.compare;
      if (cmp && cmp.score !== null && cmp.score !== undefined) {
        if (cmp.max_size_error !== null && cmp.max_size_error > 0.02) items.push(`<div class="note warn">The overall size differs from the drawing by up to ${fmt(cmp.max_size_error * 100, 1)} %.</div>`);
        for (const [t, c] of Object.entries(cmp.views || {})) if (c.mirror) items.push(`<div class="note warn">The ${t} view fits better when mirrored: a feature may be on the wrong side.</div>`);
        if (!cmp.needs_refine) items.push(`<div class="note ok">Overall sizes and view outlines agree with the drawing (score ${fmt(cmp.score * 100, 0)} %).</div>`);
      }
      if (v.ok && !items.length) items.push(`<div class="note ok">The kernel reports a valid solid.</div>`);
      h += sec("Checks", "ok", items.join(""));
    }
    h += sec("Display quality", "cube", `<div class="seg full" id="meshQ">${["coarse", "standard", "fine"].map((q) => `<button data-q="${q}" class="${(S.status && S.status.settings.mesh_quality) === q ? "on" : ""}">${q}</button>`).join("")}</div><div class="desc">Tessellation used for the 3D view (the STEP file is exact in any case). Takes effect with the next build.</div>`);
    return h;
  }

  function leftAI() {
    const st = S.status;
    if (!st) return `<div class="empty"><span class="spin"></span> Reading the hardware ...</div>`;
    const e = st.engine;
    const gpus = st.gpus.length ? st.gpus.map((g) => `${esc(g.name)}${g.vram_gb ? ` · ${g.vram_gb} GB` : ""}`).join("<br>") : "none found";
    const models = st.models;
    let h = engineNote();
    h += sec("AI engine", "chip", `<div class="kv">
        <div>State</div><div style="font-family:var(--font)">${esc(e.state)}${e.state === "starting" ? ' <span class="spin"></span>' : ""}</div>
        <div>Model</div><div style="font-family:var(--font)">${e.model ? esc(e.model.name) : "–"}</div>
        <div>Runs on</div><div style="font-family:var(--font)">${e.engine ? esc(e.engine.toUpperCase()) : "–"}</div>
        <div>GPU</div><div style="font-family:var(--font)">${gpus}</div></div>
      <label class="f">Model</label><select id="aiModel"><option value="auto">Automatic (best that fits the GPU)</option>${models.map((m) => `<option value="${m.id}" ${st.settings.model === m.id ? "selected" : ""} ${m.complete ? "" : "disabled"}>${esc(m.name)} · ${m.size_gb} GB${m.complete ? "" : " (incomplete)"}</option>`).join("")}</select>
      <div class="desc">Recommended for this PC: <b>${esc(st.recommended.name)}</b> (${esc(st.recommended.target)}).${st.model_note ? "<br>" + esc(st.model_note) : ""}</div>
      <div class="row" style="margin-top:8px"><button class="btn primary" id="aiStart">${I("power")} ${e.state === "ready" ? "Restart" : "Start"}</button><button class="btn" id="aiStop" ${e.state === "stopped" ? "disabled" : ""}>${I("stop")} Stop and free GPU memory</button></div>`, "", "ai");
    h += sec("Change the model by instruction", "edit", `<textarea id="editText" rows="4" placeholder="Example: Make the base plate 5 mm thicker, add a 2 mm chamfer on the top edges and change the four holes to M12 clearance (13.5 mm)."></textarea>
      <button class="btn ai block" id="editGo" style="margin-top:6px" ${curVer() ? "" : "disabled"}>${I("edit")} Apply the change</button>
      <div class="desc">The AI edits the code of the version shown and builds a new version. Simple size changes are faster on the <b>Parameters</b> tab.</div>`, "", "ai");
    h += sec("Refine against the drawing", "refine", `<div class="desc">The model is drawn in the views of the drawing; the AI compares both side by side together with the measured outline agreement and size differences, and corrects the code. The best version is kept.</div>
      <button class="btn ai block" id="refineGo" ${curVer() && curVer().ok && P().pages.length ? "" : "disabled"}>${I("refine")} Refine now</button>`, "", "ai");
    h += sec("Reasoning", "spark", ["read", "code", "repair", "edit"].map((k) => `<label class="chk"><span class="switch"><input type="checkbox" data-set="think_${k}" ${st.settings["think_" + k] ? "checked" : ""}><span></span></span> Think before answering: ${({ read: "reading the drawing", code: "writing the model", repair: "correcting errors", edit: "changes" })[k]}</label>`).join("") + `<div class="desc">Thinking improves geometry and dimension reading but takes longer. It is always off on the CPU engine.</div>`);
    return h;
  }

  function leftExport() {
    const v = curVer();
    const s = S.status ? S.status.settings : {};
    let h = "";
    if (!v || !v.ok) h += `<div class="note">Build a model first; the current version is exported.</div>`;
    h += sec("STEP", "step", `<label class="f">File name</label><input id="expName" placeholder="${esc(P() ? P().name : "model")}">
      <label class="f">Application protocol</label><select id="expSchema">${["AP214", "AP203", "AP242"].map((x) => `<option ${s.step_schema === x ? "selected" : ""}>${x}</option>`).join("")}</select>
      <button class="btn primary block" style="margin-top:8px" data-exp="step" ${v && v.ok ? "" : "disabled"}>${I("download")} Export STEP</button>
      <div class="desc">Exact B-rep solid in millimetres with the part name; assemblies keep their components and colours.</div>`);
    h += sec("Other formats", "layers", `<label class="f">STL tolerance <span class="u">mm</span></label><input id="expTol" value="0.05">
      <div class="g2" style="margin-top:8px;gap:6px">${[["stl", "STL"], ["glb", "glTF (GLB)"], ["brep", "BREP"], ["dxf", "2D drawing (DXF)"], ["py", "Code (.py)"], ["zip", "Package (.zip)"]].map(([f, l]) => `<button class="btn" data-exp="${f}" ${v && (v.ok || f === "py" || f === "zip") ? "" : "disabled"}>${l}</button>`).join("")}</div>
      <div class="desc">The DXF holds the front, top and right views with hidden lines and overall dimensions.</div>`);
    h += sec("Exported in this session", "download", S.exported.length ? `<table class="t">${S.exported.map((e) => `<tr><td><a href="${fileUrl(e.file, true)}">${esc(e.file.split("/").pop())}</a></td><td class="n">${fmt_bytes(e.size)}</td></tr>`).join("")}</table>` : `<div class="empty">Nothing yet.</div>`);
    return h;
  }

  function leftSettings() {
    const st = S.status;
    if (!st) return "";
    const s = st.settings;
    const num = (k, label, u = "", hint = "") => `<label class="f">${label}${u ? `<span class="u">${u}</span>` : ""}</label><input data-set="${k}" value="${esc(s[k])}">${hint ? `<div class="desc">${hint}</div>` : ""}`;
    let h = sec("AI engine", "chip", `
      <label class="f">Engine</label><select data-set="engine">${[["auto", "Automatic (CUDA when an NVIDIA GPU is present)"], ["cuda", "CUDA (NVIDIA)"], ["vulkan", "Vulkan (any GPU)"], ["cpu", "CPU only"]].map(([v, l]) => `<option value="${v}" ${s.engine === v ? "selected" : ""} ${v !== "auto" && !st.engines.includes(v) ? "disabled" : ""}>${l}${v !== "auto" && !st.engines.includes(v) ? " (not installed)" : ""}</option>`).join("")}</select>
      ${num("ctx", "Context length", "tokens", "0 = from the model profile (32 768 for 24 GB, 65 536 for 48 GB cards).")}
      ${num("gpu_layers", "GPU layers", "", "auto = as many as fit in graphics memory.")}
      ${num("threads", "CPU threads", "", "0 = automatic.")}
      ${num("image_max_tokens", "Image detail", "tokens", "0 = from the model profile. More tokens let the AI read smaller text on large sheets.")}
      ${num("idle_minutes", "Stop the engine when idle after", "min", "0 = keep the model loaded.")}
      <div class="desc">Engine settings take effect when the engine is (re)started.</div>`);
    h += sec("Pipeline", "generate", `${num("repair_attempts", "Correction attempts after a failed build")}${num("refine_rounds", "Refinement rounds against the drawing", "", "0 = no automatic refinement.")}${num("think_budget", "Reasoning budget per answer", "tokens", "Limits the time the AI thinks before answering (0 = unlimited). Takes effect when the engine is restarted.")}`);
    h += sec("Model and export", "cube", `<label class="f">Mesh quality of the 3D view</label><select data-set="mesh_quality">${["coarse", "standard", "fine"].map((q) => `<option ${s.mesh_quality === q ? "selected" : ""}>${q}</option>`).join("")}</select>
      <label class="f">STEP protocol</label><select data-set="step_schema">${["AP214", "AP203", "AP242"].map((q) => `<option ${s.step_schema === q ? "selected" : ""}>${q}</option>`).join("")}</select>
      ${num("density", "Density for the mass", "g/cm³")}`);
    h += sec("Workspace", "folder", `${num("workspace", "Project folder", "", "Projects are stored here, one folder each. Restart the program after a change.")}`);
    h += `<button class="btn primary block" id="setSave">Save settings</button>`;
    h += sec("Installed AI models", "gpu", `<table class="t"><tr><th>Model</th><th>Size</th><th>GPU memory</th></tr>${st.models.map((m) => `<tr><td>${esc(m.name)}${m.complete ? "" : ' <span class="src assumed">incomplete</span>'}</td><td class="n">${m.size_gb} GB</td><td class="n">≥ ${m.min_vram_gb} GB</td></tr>`).join("") || `<tr><td colspan="3" class="hint">none</td></tr>`}</table>
      <div class="subh">Available profiles (3_GET_AI_MODEL.bat)</div><table class="t"><tr><th>Profile</th><th>For</th><th>Download</th></tr>${st.profiles.map((pr) => `<tr><td><b class="mono" style="font-size:11px">${esc(pr.id)}</b><br><span class="hint">${esc(pr.name)} · ${esc(pr.license)}</span></td><td class="hint">${esc(pr.target)}</td><td class="n">${pr.size_gb} GB</td></tr>`).join("")}</table>`);
    return h;
  }

  function bindLeft() {
    const dz = $("#dropZone"), di = $("#dropInput");
    if (dz && di) {
      dz.addEventListener("click", () => di.click());
      di.addEventListener("change", (e) => { importFile(e.target.files[0]); e.target.value = ""; });
      dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
      dz.addEventListener("dragleave", () => dz.classList.remove("over"));
      dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); importFile(e.dataTransfer.files[0]); });
    }
    $$("[data-page]").forEach((t) => t.addEventListener("click", (e) => { if (e.target.dataset.delpage) return; setPage(+t.dataset.page); setCtab("drawing"); }));
    $$("[data-delpage]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); delPage(+b.dataset.delpage); }));
    $$("[data-ver]").forEach((li) => li.addEventListener("click", () => setVersion(li.dataset.ver)));
    const rt = $("#reqText");
    if (rt) rt.addEventListener("change", () => P() && api("POST", `/api/projects/${P().id}`, { request: rt.value }).then((p) => { P().request = p.request; }).catch(() => {}));
    on("#homeGen", "click", () => generate());
    on("#homeRead", "click", readOnly);
    on("#homeVals", "click", () => generate("spec"));
    on("#aiStart", "click", async () => {
      await api("POST", "/api/settings", { model: $("#aiModel").value });
      try { await api("POST", "/api/engine/start", { restart: S.status.engine.state === "ready" }); logLine("Starting the AI engine ...", "stage"); } catch (e) { toast(e.message, true); }
      refreshStatus();
    });
    on("#aiStop", "click", engineStop);
    on("#aiModel", "change", (e) => api("POST", "/api/settings", { model: e.target.value }).then(refreshStatus));
    on("#editGo", "click", editAI);
    on("#refineGo", "click", refine);
    $$("[data-exp]").forEach((b) => b.addEventListener("click", () => doExport(b.dataset.exp)));
    $$("#meshQ button").forEach((b) => b.addEventListener("click", async () => { await api("POST", "/api/settings", { mesh_quality: b.dataset.q }); await refreshStatus(); renderLeft(); }));
    // switches save immediately; text fields with Save
    $$('input[type=checkbox][data-set]').forEach((c) => c.addEventListener("change", () => api("POST", "/api/settings", { [c.dataset.set]: c.checked }).then(refreshStatus)));
    on("#setSave", "click", async () => {
      const ch = {};
      $$("#lbody [data-set]").forEach((el) => {
        if (el.type === "checkbox") return;
        let v = el.value;
        if (["ctx", "threads", "image_max_tokens", "repair_attempts", "refine_rounds", "think_budget"].includes(el.dataset.set)) v = parseInt(v || "0", 10) || 0;
        if (["idle_minutes", "density"].includes(el.dataset.set)) v = parseFloat(v || "0") || 0;
        ch[el.dataset.set] = v;
      });
      await api("POST", "/api/settings", ch);
      toast("Settings saved.");
      refreshStatus();
    });
    $$("[data-vtype]").forEach((s) => s.addEventListener("change", () => {
      const vs = P().resolved.views.map((v) => ({ ...v }));
      vs[+s.dataset.vtype].type = s.value;
      saveViews(vs);
    }));
    $$("[data-vdel]").forEach((b) => b.addEventListener("click", () => {
      const vs = P().resolved.views.filter((_, i) => i !== +b.dataset.vdel);
      saveViews(vs);
    }));
  }
  function on(sel, ev, fn) { const el = $(sel); if (el) el.addEventListener(ev, fn); }

  // ------------------------------------------------------------------ center
  function renderCenter() {
    const p = P();
    $("#cTitle").textContent = p ? `${p.name}${p.current ? " · " + p.current : ""}` : "";
    if (S.ctab === "model") renderModel();
    if (S.ctab === "drawing") renderDrawing();
    if (S.ctab === "compare") renderCompare();
    if (S.ctab === "code") renderCodeInfo();
    if (S.ctab === "values") renderValues();
  }

  async function renderModel() {
    const v = curVer();
    const empty = $("#vEmpty");
    if (!P() || !v || !v.ok) {
      if (S.viewer) S.viewer.clear();
      S.meshVersion = null;
      empty.hidden = false;
      empty.innerHTML = !P() || !P().versions.length ? `${I("logo")}<b>AICAD · AI-assisted CAD modelling</b><div>Turn a drawing or a description into a 3D solid and export it as STEP.</div>
        <div class="steps"><div>${I("import")}<b>1. Import</b>a drawing (PDF, image, DXF) or describe the object</div><div>${I("generate")}<b>2. Generate</b>the AI reads, models and checks against the drawing</div><div>${I("step")}<b>3. Review and export</b>adjust parameters and export STEP</div></div>`
        : `${I("error")}<b>This version did not build.</b><div>${esc(v && v.error || "")}</div><div class="hint">Correct the code on the Code tab, choose another version, or ask the AI again.</div>`;
      $("#vHud").textContent = "";
      return;
    }
    empty.hidden = true;
    const key = P().id + "/" + v.id;
    if (S.meshVersion === key || !S.viewer) return;
    S.meshVersion = key;
    try {
      const r = await fetch(fileUrl(`versions/${v.id}/mesh.json`));
      const data = await r.json();
      const keep = S._lastProject === P().id;
      S.viewer.load(data, keep);
      S._lastProject = P().id;
      const m = v.metrics;
      $("#vHud").textContent = `${v.id} · ${fmt(m.size[0])} × ${fmt(m.size[1])} × ${fmt(m.size[2])} mm · ${m.solids} solid${m.solids > 1 ? "s" : ""} · ${m.faces} faces`;
      renderRight();
    } catch (e) { S.meshVersion = null; logLine("The 3D view could not be loaded: " + e.message, "error"); }
  }

  function renderDrawing() {
    const p = P();
    const pg = p && p.pages[p.page];
    $("#dEmpty").hidden = !!pg;
    $("#dEmpty").innerHTML = `${I("sheet")}<b>No drawing</b><div>Import a PDF, image or DXF (Home → Import drawing, or drop the file here).</div>`;
    $("#dPages").innerHTML = p && p.pages.length > 1 ? p.pages.map((x, i) => `<button data-pg="${i}" class="${i === p.page ? "on" : ""}">${i + 1}</button>`).join("") : "";
    $$("#dPages button").forEach((b) => b.addEventListener("click", () => setPage(+b.dataset.pg)));
    if (!S.dv) return;
    if (!pg) { S.dv.setPage(null); return; }
    S.dv.setPage(fileUrl("input/" + pg.file), pg.w, pg.h);
    const res = p.resolved;
    const cal = p.calib && p.calib[pg.file];
    S.dv.setOverlay({
      views: res ? res.views : [],
      estimates: res ? res.values.filter((v) => v.p1) : [],
      texts: pg.texts || [],
      scale: cal ? cal.mm_per_px : (res && res.scale ? res.scale.mm_per_px : null),
    });
    const sc = cal ? cal.mm_per_px : res && res.scale && res.scale.mm_per_px;
    $("#dInfo").textContent = `${pg.source} · p${pg.page} · ${pg.w}×${pg.h}px` + (sc ? ` · ${sc.toFixed(4)} mm/px` : " · no scale yet");
  }
  function toggleDv(k, val) {
    S.dv.show[k] = val !== undefined ? val : !S.dv.show[k];
    $("#dShowViews").classList.toggle("on", S.dv.show.views);
    $("#dShowEst").classList.toggle("on", S.dv.show.est);
    $("#dShowText").classList.toggle("on", S.dv.show.text);
    S.dv.draw();
  }
  function setDvMode(m) {
    if (m === "edit" && !(P() && P().resolved)) { toast("Read the drawing first."); m = "pan"; }
    S.dv.setMode(m);
    $("#dEdit").classList.toggle("on", m === "edit");
    $("#dMeasure").classList.toggle("on", m === "measure");
    $("#dCalib").classList.toggle("on", m === "calib");
    if (m === "measure") toast("Click two points (hold Shift for horizontal/vertical).");
    if (m === "calib") toast("Click two points whose real distance you know.");
  }
  async function saveViews(views) {
    try {
      S.project = await api("POST", `/api/projects/${P().id}/views`, { views: views.map((v) => ({ id: v.id, type: v.type, label: v.label, box: v.box, fixed: !!v.fixed })) });
      logLine("View boxes changed: scale and measured sizes recomputed.", "ok");
      renderAll();
    } catch (e) { toast(e.message, true); }
  }
  function addView() {
    const p = P(), pg = p.pages[p.page];
    const vs = p.resolved.views.map((v) => ({ ...v }));
    const n = vs.length + 1;
    vs.push({ id: "V" + n + "u", type: "other", label: "", box: [pg.w * 0.4, pg.h * 0.4, pg.w * 0.6, pg.h * 0.6], fixed: true });
    saveViews(vs).then(() => { setCtab("drawing"); setDvMode("edit"); });
  }
  async function clearCalib() {
    S.project = await api("POST", `/api/projects/${P().id}/calibrate`, { clear: true });
    toast("Calibration cleared."); renderAll();
  }

  // ---- compare
  function renderCompare() {
    const p = P(), v = curVer(), box = $("#cmpBody");
    if (!p || !v || !v.ok) { box.innerHTML = `<div class="empty">Build a model first.</div>`; return; }
    const cmp = p.compare, views = p.views || {};
    const res = p.resolved;
    let h = `<div class="row" style="margin-bottom:10px"><b style="font-size:14px">Model ${v.id} against the drawing</b><div class="grow"></div>
      ${p.pages.length ? `<button class="btn ai" id="cmpRefine">${I("refine")} Refine against drawing</button>` : ""}</div>`;
    const m = v.metrics;
    h += `<table class="t sizes" style="max-width:640px;margin-bottom:14px"><tr><th>Axis</th><th>Model (mm)</th><th>Drawing (mm)</th><th>Source</th><th>Difference</th></tr>${["x", "y", "z"].map((a, i) => {
      const e = cmp && cmp.expected[a];
      const d = cmp && cmp.bbox_err[a];
      return `<tr><td><b>${a.toUpperCase()}</b></td><td class="n">${fmt(m.size[i], 3)}</td><td class="n">${e ? fmt(e.value, 3) : "–"}</td><td>${e ? `<span class="src ${e.source}">${e.source}</span>` : ""}</td><td class="n ${d === undefined ? "" : Math.abs(d) > 0.02 ? "bad" : "good"}">${d === undefined ? "–" : (d * 100).toFixed(2) + " %"}</td></tr>`;
    }).join("")}</table>`;
    if (!cmp || cmp.score === null || cmp.score === undefined) h += `<div class="note">${p.pages.length ? "The drawing has not been read yet, so there is nothing to compare with. Use <b>Read drawing</b> (or Generate) first." : "This model was made from a description; there is no drawing to compare with."}</div>`;
    else h += `<div class="note ${cmp.needs_refine ? "warn" : "ok"}">Agreement score ${fmt(cmp.score * 100, 1)} %${cmp.mean_iou !== null ? ` · mean outline agreement ${fmt(cmp.mean_iou * 100, 1)} %` : ""}. ${cmp.needs_refine ? "Differences remain; <b>Refine against drawing</b> lets the AI correct them, or adjust the parameters." : "The model agrees with the drawing within the checks."}</div>`;
    h += `<div class="cmpgrid">`;
    const vlist = res ? res.views.filter((x) => ["front", "top", "right", "left", "rear", "bottom"].includes(x.type)) : [];
    const shown = vlist.length ? vlist.map((x) => [x.type, x]) : ["front", "top", "right"].map((t) => [t, null]);
    for (const [t, rv] of shown) {
      const c = cmp && cmp.views && cmp.views[t];
      const pct = c ? c.iou * 100 : null;
      const col = pct === null ? "#8c959f" : pct >= 90 ? "#1a7f37" : pct >= 75 ? "#bf8700" : "#cf222e";
      h += `<div class="cmpcard"><div class="sh">${t.toUpperCase()} view${rv ? ` · ${esc(rv.id)}` : ""}<span class="meter">${c ? `outline ${fmt(pct, 1)} %<span class="bar"><i style="width:${pct}%;background:${col}"></i></span>` : ""}${c && c.mirror ? ' <span class="src assumed">mirrored?</span>' : ""}</span></div>
        <div class="cmppair"><div><span class="cap">DRAWING</span>${rv ? `<canvas data-crop='${JSON.stringify(rv.box)}'></canvas>` : '<span class="hint">no such view on the drawing</span>'}</div>
        <div><span class="cap">MODEL</span>${svgView(views[t])}</div></div></div>`;
    }
    if (views.iso) h += `<div class="cmpcard"><div class="sh">ISOMETRIC</div><div class="cmppair" style="grid-template-columns:1fr"><div>${svgView(views.iso)}</div></div></div>`;
    h += `</div>`;
    box.innerHTML = h;
    on("#cmpRefine", "click", refine);
    const pg = p.pages[p.page];
    if (pg) {
      const img = new Image();
      img.onload = () => $$("canvas[data-crop]", box).forEach((cv) => {
        const b = JSON.parse(cv.dataset.crop), pad = 8;
        const w = b[2] - b[0] + 2 * pad, hh = b[3] - b[1] + 2 * pad;
        const s = Math.min(260 / hh, 480 / w, 3);
        cv.width = w * s; cv.height = hh * s;
        cv.getContext("2d").drawImage(img, b[0] - pad, b[1] - pad, w, hh, 0, 0, w * s, hh * s);
      });
      img.src = fileUrl("input/" + pg.file);
    }
  }
  function svgView(v) {
    if (!v || !v.bounds) return `<span class="hint">no projection</span>`;
    const [x0, y0, x1, y1] = v.bounds;
    const w = Math.max(x1 - x0, 1e-6), h = Math.max(y1 - y0, 1e-6), pad = Math.max(w, h) * 0.04;
    const sw = Math.max(w, h) / 320;
    const path = (pl) => { let s = ""; for (let i = 0; i + 1 < pl.length; i += 2) s += (i ? "L" : "M") + pl[i].toFixed(3) + "," + (-pl[i + 1]).toFixed(3) + " "; return s; };
    const seg = (arr) => arr.map((pl) => `<path d="${path(pl)}"/>`).join("");
    return `<svg viewBox="${x0 - pad} ${-y1 - pad} ${w + 2 * pad} ${h + 2 * pad}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%">
      <g fill="none" stroke="#8c959f" stroke-width="${sw * 0.8}" stroke-dasharray="${sw * 4} ${sw * 3}">${seg(v.h || [])}</g>
      <g fill="none" stroke="#1f2328" stroke-width="${sw * 1.6}" stroke-linejoin="round">${seg(v.v || [])}</g></svg>`;
  }

  // ---- code
  function setCode(code, resetDirty) {
    const ta = $("#codeEdit");
    ta.value = code || "";
    if (resetDirty) S.codeDirty = false;
    gutter();
    renderCodeInfo();
  }
  function gutter() {
    const ta = $("#codeEdit");
    const n = ta.value.split("\n").length;
    const v = curVer();
    const errLine = v && !v.ok && !S.codeDirty ? v.line : null;
    let s = "";
    for (let i = 1; i <= n; i++) s += (i === errLine ? `<span class="err">${i}</span>` : i) + "\n";
    $("#codeGutter").innerHTML = s;
    $("#codeGutter").scrollTop = ta.scrollTop;
  }
  function renderCodeInfo() {
    const v = curVer();
    $("#codeInfo").innerHTML = v ? `${v.id} · ${esc(v.source)}${S.codeDirty ? ' · <b style="color:var(--amber)">edited, not built</b>' : ""}` : "No model yet. Code written here can be built directly.";
    const err = $("#codeErr");
    if (v && !v.ok && !S.codeDirty) { err.hidden = false; err.textContent = (v.line ? `Line ${v.line}: ` : "") + (v.error || ""); }
    else err.hidden = true;
    gutter();
  }

  // ---- values (dimensions)
  function renderValues() {
    const p = P(), box = $("#valBody");
    if (!p) { box.innerHTML = `<div class="empty">Open or create a project first.</div>`; return; }
    const res = p.resolved, sp = p.spec;
    if (!res) {
      box.innerHTML = `<div class="note">This table lists every dimension the AI read from the drawing, every size measured on the sheet and the scale used. It appears after <b>Read drawing</b> or <b>Generate</b>.</div>`;
      return;
    }
    let h = `<div class="row" style="margin-bottom:6px"><b style="font-size:15px">${esc(sp.part_name)}</b><span class="hint">${esc(sp.kind || "")} · ${esc(sp.units)} · ${esc(sp.projection || "")}${sp.drawing_scale ? " · scale " + esc(sp.drawing_scale) : ""}</span><div class="grow"></div>
      <button class="btn" id="valSave">Save changes</button><button class="btn ai" id="valBuild">${I("generate")} Build model from these values</button></div>`;
    if (sp.summary) h += `<div class="desc" style="font-size:12.5px;margin-bottom:10px">${esc(sp.summary)}</div>`;
    h += `<div class="row wrap" style="gap:12px;margin:6px 0 10px">${["drawing", "ratio", "user", "assumed"].map((s) => `<span><span class="src ${s}">${s}</span> <span class="hint">${({ drawing: "written on the drawing", ratio: "measured on the sheet × scale", user: "entered by you", assumed: "chosen default" })[s]}</span></span>`).join("")}</div>`;
    h += `<table class="t"><tr><th>Name</th><th style="width:120px">Value</th><th>Unit</th><th>Source</th><th>Reference</th><th>Meaning</th></tr>${res.values.map((v) => `<tr class="${S.valueEdits[v.name] !== undefined ? "changed" : ""}">
      <td class="mono">${esc(v.name)}</td><td><input data-val="${esc(v.name)}" value="${S.valueEdits[v.name] ?? v.value}"></td><td>${esc(v.unit)}</td>
      <td><span class="src ${v.source}">${v.source}</span></td><td class="hint">${esc(v.ref || "")}</td><td>${esc(v.describes || "")}</td></tr>`).join("")}</table>`;
    for (const w of res.warnings || []) h += `<div class="note warn">${esc(w)}</div>`;
    if ((sp.questions || []).length) h += `<div class="subh">Open questions</div>` + sp.questions.map((q) => `<div class="note ai">${esc(q)}</div>`).join("");
    if ((sp.features || []).length) h += `<div class="subh">Modelling steps read from the drawing</div><table class="t"><tr><th>#</th><th>Operation</th><th>Description</th></tr>${sp.features.map((f) => `<tr><td class="mono">${esc(f.id || "")}</td><td>${esc(f.op || "")}</td><td>${esc(f.description || "")}</td></tr>`).join("")}</table>`;
    if ((sp.notes || []).length) h += `<div class="subh">Notes</div><ul style="margin:0;padding-left:18px">${sp.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`;
    box.innerHTML = h;
    $$("[data-val]", box).forEach((inp) => inp.addEventListener("input", () => { S.valueEdits[inp.dataset.val] = inp.value; inp.closest("tr").classList.add("changed"); }));
    on("#valSave", "click", saveValues);
    on("#valBuild", "click", async () => { if (Object.keys(S.valueEdits).length) await saveValues(); generate("spec"); });
  }
  async function saveValues() {
    if (!Object.keys(S.valueEdits).length) { toast("Nothing was changed."); return; }
    S.project = await api("POST", `/api/projects/${P().id}/values`, { values: S.valueEdits });
    S.valueEdits = {};
    toast("Values saved (marked as user values).");
    renderAll();
  }

  // ------------------------------------------------------------------ right panel
  function renderRight() {
    if (S.rtab === "inspect") renderInspector();
    if (S.rtab === "params") renderParams();
    if (S.rtab === "parts") renderParts();
  }
  function renderInspector() {
    const v = curVer(), box = $("#r-inspect");
    if (!v || !v.ok) { box.innerHTML = `<div class="empty">No model to inspect.</div>`; return; }
    const m = v.metrics, dens = (S.status && S.status.settings.density) || 7.85;
    let h = sec("Model", "cube", `<div class="kv">
      <div>Version</div><div>${v.id}</div>
      <div>Size X</div><div>${fmt(m.size[0], 3)} mm</div><div>Size Y</div><div>${fmt(m.size[1], 3)} mm</div><div>Size Z</div><div>${fmt(m.size[2], 3)} mm</div>
      <div>Volume</div><div>${fmt(m.volume / 1000, 3)} cm³</div><div>Surface</div><div>${fmt(m.area / 100, 2)} cm²</div>
      <div>Mass</div><div>${fmt(m.volume / 1000 * dens / 1000, 3)} kg</div>
      <div>Solids</div><div>${m.solids}</div><div>Faces / edges</div><div>${m.faces} / ${m.edges}</div>
      <div>Triangles (view)</div><div>${fmt(m.triangles, 0)}</div></div>
      <div class="desc">Mass at ${dens} g/cm³ (Settings).</div>`);
    if (S.pick && S.pick.face) {
      const f = S.pick.face;
      const T = { PLANE: "Plane", CYLINDER: "Cylinder", CONE: "Cone", SPHERE: "Sphere", TORUS: "Torus", BSPLINE: "B-spline surface" };
      let rows = `<div>Part</div><div>${esc(S.pick.part)}</div><div>Face</div><div>#${S.pick.faceIndex + 1}</div><div>Type</div><div>${T[f.t] || f.t}</div><div>Area</div><div>${fmt(f.a, 3)} mm²</div>`;
      if (f.t === "CYLINDER") rows += `<div>Diameter</div><div><b>Ø ${fmt(f.r * 2, 4)}</b> mm</div><div>Axis</div><div>${f.d.map((x) => fmt(x, 3)).join(", ")}</div><div>Axis point</div><div>${f.c.map((x) => fmt(x, 3)).join(", ")}</div>`;
      if (f.t === "PLANE" && f.d) rows += `<div>Normal</div><div>${f.d.map((x) => fmt(x, 3)).join(", ")}</div>`;
      if (f.t === "SPHERE" || f.t === "CONE") rows += `<div>Radius</div><div>${fmt(f.r, 4)} mm</div>`;
      if (f.t === "CONE") rows += `<div>Half angle</div><div>${fmt(f.ang, 3)}°</div>`;
      if (f.t === "TORUS") rows += `<div>Radii</div><div>${fmt(f.r, 3)} / ${fmt(f.r2, 3)}</div>`;
      rows += `<div>Picked point</div><div>${S.pick.point.map((x) => fmt(x, 2)).join(", ")}</div>`;
      h += sec("Selected face", "target", `<div class="kv">${rows}</div>`);
    } else h += sec("Selected face", "target", `<div class="empty">Click a face in the 3D view.</div>`);
    if (S.measure) {
      const d = S.measure;
      h += sec("Measurement", "ruler", `<div class="kv"><div>Distance</div><div><b>${fmt(d.d, 4)}</b> mm</div><div>ΔX</div><div>${fmt(d.dx, 4)}</div><div>ΔY</div><div>${fmt(d.dy, 4)}</div><div>ΔZ</div><div>${fmt(d.dz, 4)}</div></div>`);
    }
    box.innerHTML = h;
  }
  function renderParams() {
    const box = $("#r-params"), p = P();
    const params = p ? p.params || [] : [];
    if (!params.length) { box.innerHTML = `<div class="empty">The model code has no parameter block yet.</div>`; return; }
    let h = `<div class="desc">Every dimension of the model. Change values and press <b>Apply</b>: the model is rebuilt at once without the AI.</div>
      <table class="t"><tr><th>Parameter</th><th style="width:92px">Value</th><th></th></tr>${params.map((q) => `<tr class="${S.paramEdits[q.name] !== undefined ? "changed" : ""}" title="${esc(q.desc)}">
      <td><span class="mono" style="font-size:11.5px">${esc(q.name)}</span><br><span class="hint">${esc(q.desc).slice(0, 60)}</span></td>
      <td><input data-par="${esc(q.name)}" value="${S.paramEdits[q.name] ?? (q.int ? q.value.toFixed(0) : +q.value.toFixed(6))}"></td>
      <td>${q.source ? `<span class="src ${q.source}">${q.source}</span>` : ""}</td></tr>`).join("")}</table>
      <div class="row" style="margin-top:8px"><button class="btn primary" id="parApply">${I("rebuild")} Apply</button><button class="btn" id="parReset">Reset</button></div>`;
    box.innerHTML = h;
    $$("[data-par]", box).forEach((inp) => {
      inp.addEventListener("input", () => { S.paramEdits[inp.dataset.par] = inp.value; inp.closest("tr").classList.add("changed"); });
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") applyParams(); });
    });
    on("#parApply", "click", applyParams);
    on("#parReset", "click", () => { S.paramEdits = {}; renderParams(); });
  }
  function renderParts() {
    const box = $("#r-parts");
    if (!S.viewer || !S.viewer.parts.length) { box.innerHTML = `<div class="empty">No model loaded.</div>`; return; }
    box.innerHTML = `<table class="t"><tr><th></th><th>Part</th><th></th></tr>${S.viewer.parts.map((pt, i) => `<tr>
      <td><input type="checkbox" data-part="${i}" ${pt.visible ? "checked" : ""}></td><td>${esc(pt.name)}</td>
      <td><span style="display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid var(--line2);background:#${pt.color.getHexString()}"></span></td></tr>`).join("")}</table>
      <div class="desc">${S.viewer.parts.length > 1 ? "Components of the assembly; they are kept as separate bodies in the STEP file." : "A single part."}</div>`;
    $$("[data-part]", box).forEach((c) => c.addEventListener("change", () => S.viewer.setPartVisible(+c.dataset.part, c.checked)));
  }

  // ------------------------------------------------------------------ status
  async function refreshStatus() {
    try {
      S.status = await api("GET", "/api/status");
    } catch (e) { return; }
    const e = S.status.engine;
    const chip = $("#aiChip");
    const busy = S.job && S.job.ai;
    chip.className = "chip " + (busy ? "busy" : e.state);
    chip.innerHTML = `<i></i>${busy ? "AI working" : e.state === "ready" ? `AI ready · ${esc(e.model.name)} · ${esc((e.engine || "").toUpperCase())}` : e.state === "starting" ? `Loading ${esc(e.model ? e.model.name : "model")} ...` : e.state === "error" ? "AI engine error" : "AI engine stopped"}`;
    chip.title = e.error || (e.state === "stopped" ? "The engine starts with the first AI request." : "");
    const g = S.status.gpus.find((x) => x.vendor === "NVIDIA") || S.status.gpus[0];
    $("#sbGpu").innerHTML = g ? `${I("gpu")} ${esc(g.name)}${g.vram_gb ? ` · ${g.vram_gb} GB` : ""}` : "";
    $("#sbModel").textContent = e.model ? e.model.name : "";
    $("#sbVer").textContent = "AICAD " + S.status.version;
    $("#englog").textContent = (e.log || []).join("\n");
    if (S.status.busy && !S.job) {
      S.job = { id: S.status.busy.id, state: S.status.busy.state, ai: true };
      S.jobLog = S.status.busy.log_n; S.jobStream = S.status.busy.stream_n;
      $("#btnStop").disabled = false;
      poll();
    }
    // the AI panel shows the engine state: redraw it only when that changes
    const sig = [e.state, e.model && e.model.id, e.engine, !!S.job].join("|");
    if (sig !== S._engSig) {
      S._engSig = sig;
      if (S.tab === "ai" && !$("#lbody").contains(document.activeElement)) renderLeft();
    }
    if (S.tab === "home" && !S._homeNoted && S.status) { S._homeNoted = true; renderLeft(); }
  }
  function renderStatusBar(done) {
    const j = S.job || done;
    const st = j ? j.state : "idle";
    $("#sbDot").className = "dot " + (st === "queued" ? "running" : st);
    $("#sbState").textContent = { idle: "Ready", queued: "Waiting", running: "Working", done: "Done", failed: "Failed", stopped: "Stopped" }[st] || st;
    $("#sbStage").textContent = j ? (j.stage || j.label || "") : "";
    $("#sbProg").style.width = j ? ((j.progress || 0) * 100) + "%" : "0";
    $("#sbTime").textContent = j && j.elapsed ? fmt(j.elapsed, 0) + " s" : "";
  }

  // ------------------------------------------------------------------ modals
  function modal(title, html) {
    $("#mTitle").textContent = title; $("#mBody").innerHTML = html; $("#modal").hidden = false;
  }
  const closeModal = () => ($("#modal").hidden = true);
  async function openProjects() {
    const list = await api("GET", "/api/projects");
    modal("Open a project", list.length ? `<div class="plist">${list.map((r) => `<div class="pcard" data-open="${r.id}">
      <div class="im">${r.thumb ? `<img src="/api/projects/${r.id}/file/${r.thumb}">` : I("cube")}</div>
      <div class="tx"><b>${esc(r.name)}</b><small>${esc(r.modified.replace("T", " "))} · ${r.versions} version(s)</small>
      <div style="margin-top:4px"><button class="btn sm danger" data-del="${r.id}">Delete</button></div></div></div>`).join("")}</div>` : `<div class="empty">No projects yet.</div>`);
    $$("[data-open]").forEach((c) => c.addEventListener("click", (e) => { if (e.target.dataset.del) return; closeModal(); loadProject(c.dataset.open); }));
    $$("[data-del]").forEach((b) => b.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this project and all its files?")) return;
      await api("DELETE", `/api/projects/${b.dataset.del}`);
      if (P() && P().id === b.dataset.del) { S.project = null; renderAll(); }
      openProjects();
    }));
  }
  async function openExamples() {
    const list = await api("GET", "/api/examples");
    modal("Examples", list.length ? `<div class="desc" style="margin-bottom:10px">Each example opens as a new project. <b>Open</b> starts with the drawing or description only (to run the AI); <b>With reference</b> also builds the hand-made reference model for comparison.</div><div class="plist">${list.map((x) => `<div class="pcard">
      <div class="im">${x.thumb ? `<img src="/examples/${x.thumb}">` : I("describe")}</div>
      <div class="tx"><b>${esc(x.title)}</b><small>${esc(x.description)}</small>
      <div class="row" style="margin-top:6px"><button class="btn sm primary" data-ex="${x.id}">Open</button>${x.reference ? `<button class="btn sm" data-exref="${x.id}">With reference</button>` : ""}</div></div></div>`).join("")}</div>` : `<div class="empty">No examples are installed.</div>`);
    const openEx = async (id, ref) => {
      closeModal();
      try {
        const r = await api("POST", "/api/examples/open", { id, with_reference: ref });
        S.project = r;
        afterProjectLoad(true);
        setTab("home");
        if (r.job) {
          S.job = { id: r.job, state: "queued", ai: false };
          S.jobLog = 0; S.jobStream = 0;
          logLine("Building the reference model of the example", "stage");
          setCtab("model");
          poll();
        } else setCtab(P().pages.length ? "drawing" : "model");
      } catch (e) { toast(e.message, true); }
    };
    $$("[data-ex]").forEach((b) => b.addEventListener("click", () => openEx(b.dataset.ex, false)));
    $$("[data-exref]").forEach((b) => b.addEventListener("click", () => openEx(b.dataset.exref, true)));
  }

  function cycleSection() {
    const order = ["", "x", "y", "z"];
    const cur = $("#vSection button.on").dataset.a;
    $(`#vSection button[data-a="${order[(order.indexOf(cur) + 1) % 4]}"]`).click();
  }
  function setDock(d) {
    $$("#dtabs button[data-d]").forEach((b) => b.classList.toggle("on", b.dataset.d === d));
    $$(".dpage").forEach((p) => p.classList.toggle("on", p.id === "d-" + d));
  }

  // ------------------------------------------------------------------ init
  function init() {
    $("#brand").innerHTML = `${I("logo")}<div><b>AICAD</b><small>AI-assisted CAD Modelling</small></div>`;
    $("#btnProjects").innerHTML = I("open");
    $("#btnGenerate").innerHTML = I("generate") + "Generate";
    $("#btnStop").innerHTML = I("stop") + "Stop";
    $("#vFit").innerHTML = I("fit");
    $("#vMeasure").innerHTML = I("ruler") + "Measure";
    $("#vShot").innerHTML = I("camera");
    $("#dFit").innerHTML = I("fit");
    $("#dockToggle").innerHTML = I("collapse");
    const CT = { model: ["cube", "3D Model"], drawing: ["sheet", "Drawing"], compare: ["compare", "Compare"], code: ["code", "Code"], values: ["values", "Dimensions"] };
    $$("#ctabs button[data-c]").forEach((b) => { b.innerHTML = I(CT[b.dataset.c][0]) + CT[b.dataset.c][1]; b.addEventListener("click", () => setCtab(b.dataset.c)); });
    $$("#rtabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    $$("#rptabs button").forEach((b) => b.addEventListener("click", () => setRtab(b.dataset.r)));
    $$("#dtabs button[data-d]").forEach((b) => b.addEventListener("click", () => { setDock(b.dataset.d); $("#dock").classList.remove("collapsed"); }));
    $("#dockToggle").addEventListener("click", () => $("#dock").classList.toggle("collapsed"));
    $("#btnGenerate").addEventListener("click", () => generate());
    $("#btnStop").addEventListener("click", stopJob);
    $("#btnProjects").addEventListener("click", openProjects);
    $("#aiChip").addEventListener("click", () => setTab("ai"));
    $("#mClose").addEventListener("click", closeModal);
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
    $("#projName").addEventListener("change", async (e) => {
      if (!P()) { await newProject(e.target.value); return; }
      S.project = await api("POST", `/api/projects/${P().id}`, { name: e.target.value });
      renderCenter();
    });
    // code editor
    const ta = $("#codeEdit");
    ta.addEventListener("input", () => { S.codeDirty = true; gutter(); renderCodeInfo(); });
    ta.addEventListener("scroll", () => { $("#codeGutter").scrollTop = ta.scrollTop; });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Tab") { e.preventDefault(); const s = ta.selectionStart; ta.setRangeText("    ", s, ta.selectionEnd, "end"); S.codeDirty = true; gutter(); }
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#codeRun").click(); }
    });
    $("#codeRun").addEventListener("click", async () => {
      await ensureProject("Untitled");
      S.codeDirty = false;
      quickBuild({ code: ta.value, note: "code edited" }, "Building the edited code");
    });
    $("#codeRevert").addEventListener("click", () => setCode(P() ? P().code : "", true));
    $("#codeCopy").addEventListener("click", () => { navigator.clipboard.writeText(ta.value).then(() => toast("Copied.")); });
    // 3D toolbar
    $$("#vStyle button").forEach((b) => b.addEventListener("click", () => {
      $$("#vStyle button").forEach((x) => x.classList.toggle("on", x === b)); S.viewer && S.viewer.setStyle(b.dataset.s);
    }));
    $$("#vSection button").forEach((b) => b.addEventListener("click", () => {
      $$("#vSection button").forEach((x) => x.classList.toggle("on", x === b));
      $("#vSecPos").disabled = !b.dataset.a;
      S.viewer && S.viewer.setSection(b.dataset.a, $("#vSecPos").value / 1000, S._secFlip);
    }));
    $("#vSecPos").addEventListener("input", (e) => S.viewer && S.viewer.setSection($("#vSection button.on").dataset.a, e.target.value / 1000, S._secFlip));
    $("#vSecFlip").addEventListener("click", () => { S._secFlip = !S._secFlip; S.viewer && S.viewer.setSection($("#vSection button.on").dataset.a, $("#vSecPos").value / 1000, S._secFlip); });
    $$("[data-cam]").forEach((b) => b.addEventListener("click", () => S.viewer && S.viewer.view(b.dataset.cam)));
    $("#vFit").addEventListener("click", () => S.viewer && S.viewer.fit());
    $("#vOrtho").classList.add("on");
    $("#vOrtho").addEventListener("click", (e) => { const on = !e.currentTarget.classList.contains("on"); e.currentTarget.classList.toggle("on", on); S.viewer && S.viewer.setOrtho(on); });
    $("#vDims").addEventListener("click", (e) => { const on = !e.currentTarget.classList.contains("on"); e.currentTarget.classList.toggle("on", on); S.viewer && S.viewer.setDims(on); });
    $("#vMeasure").addEventListener("click", (e) => { const on = !e.currentTarget.classList.contains("on"); e.currentTarget.classList.toggle("on", on); S.viewer && S.viewer.setMeasure(on); if (on) toast("Click two points on the model."); });
    $("#vShot").addEventListener("click", screenshot);
    // drawing toolbar
    S.dv = new window.DrawingView($("#dCanvas"));
    $("#dShowViews").classList.add("on"); $("#dShowEst").classList.add("on");
    $("#dShowViews").addEventListener("click", () => toggleDv("views"));
    $("#dShowEst").addEventListener("click", () => toggleDv("est"));
    $("#dShowText").addEventListener("click", () => toggleDv("text"));
    $("#dEdit").addEventListener("click", () => setDvMode(S.dv.mode === "edit" ? "pan" : "edit"));
    $("#dMeasure").addEventListener("click", () => setDvMode(S.dv.mode === "measure" ? "pan" : "measure"));
    $("#dCalib").addEventListener("click", () => setDvMode(S.dv.mode === "calib" ? "pan" : "calib"));
    $("#dFit").addEventListener("click", () => S.dv.fit());
    S.dv.onViews = (views) => saveViews(views);
    S.dv.onMeasure = (L) => logLine(`Measured on the sheet: ${S.dv.mmText(L)}`);
    S.dv.onCalib = async (L) => {
      const mm = prompt(`The two points are ${L.toFixed(1)} px apart. Enter their real distance in mm:`);
      if (!mm) return;
      try {
        S.project = await api("POST", `/api/projects/${P().id}/calibrate`, { px: L, mm: parseFloat(mm) });
        logLine(`Calibrated: ${mm} mm = ${L.toFixed(1)} px (${(parseFloat(mm) / L).toFixed(5)} mm/px).`, "ok");
        setDvMode("pan"); renderAll();
      } catch (e) { toast(e.message, true); }
    };
    // drop anywhere
    document.addEventListener("dragover", (e) => e.preventDefault());
    document.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files.length) importFile(e.dataTransfer.files[0]); });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); if (S.dv && S.dv.mode !== "pan") setDvMode("pan"); } });

    setTab("home");
    setCtab("model");
    refreshStatus();
    setInterval(refreshStatus, 4000);
    const last = localStorage.getItem("aicad.project");
    if (last) loadProject(last, true); else renderAll();
  }

  function attachViewer() {
    if (S.viewer || !window.Viewer3D) return;
    S.viewer = window.Viewer3D.create($("#vStage"));
    S.viewer.onPick = (p) => { S.pick = p; if (S.rtab !== "inspect") setRtab("inspect"); else renderInspector(); };
    S.viewer.onMeasure = (m) => { S.measure = m; logLine(`Measured: ${m.d.toFixed(4)} mm (ΔX ${m.dx.toFixed(3)}, ΔY ${m.dy.toFixed(3)}, ΔZ ${m.dz.toFixed(3)})`); setRtab("inspect"); };
    S.meshVersion = null;
    if (S.ctab === "model") renderModel();
  }
  window.addEventListener("viewer3d-ready", attachViewer);
  document.addEventListener("DOMContentLoaded", () => { init(); attachViewer(); });
})();
