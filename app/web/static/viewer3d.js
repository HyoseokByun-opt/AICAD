/* 3D model viewer (three.js): Z up as in CAD, orthographic by default,
   shaded / edges / wireframe / X-ray, a section plane with coloured cut
   faces, face picking with the geometry of the face (plane normal, hole
   diameter ...), point-to-point measurement and the overall dimensions.
   Rendering happens on demand only, so an idle view costs nothing. */
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";

const VIEW_DIRS = {
  iso: [1, -1, 0.85], front: [0, -1, 0], rear: [0, 1, 0], top: [0, -1e-4, 1],
  bottom: [0, -1e-4, -1], right: [1, 0, 0], left: [-1, 0, 0],
};

class Viewer {
  constructor(stage) {
    this.stage = stage;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.localClippingEnabled = true;
    stage.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.persp = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
    this.ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e7, 1e7);
    for (const c of [this.persp, this.ortho]) c.up.set(0, 0, 1);
    this.camera = this.ortho;
    this.camera.position.set(1, -1, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.screenSpacePanning = true;
    this.controls.zoomToCursor = true;
    this.controls.addEventListener("change", () => this.render());
    // lights: hemisphere + two directionals that follow the camera
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a96a3, 1.6));
    this.key = new THREE.DirectionalLight(0xffffff, 1.6);
    this.fill = new THREE.DirectionalLight(0xffffff, 0.55);
    this.scene.add(this.key, this.fill);
    this.root = new THREE.Group();
    this.scene.add(this.root);
    this.helpers = new THREE.Group();
    this.scene.add(this.helpers);
    this.parts = [];
    this.style = "shaded-edges";
    this.clip = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);
    this.secAxis = "";
    this.secPos = 0.5;
    this.secFlip = false;
    this.measureOn = false;
    this.measurePts = [];
    this.labels = [];
    this.showDims = false;
    this.onPick = null;
    this.onMeasure = null;
    // triad
    this.triScene = new THREE.Scene();
    this.triCam = new THREE.OrthographicCamera(-1.6, 1.6, 1.6, -1.6, -10, 10);
    this.triCam.up.set(0, 0, 1);
    const ax = (dir, color) => {
      const a = new THREE.ArrowHelper(new THREE.Vector3(...dir), new THREE.Vector3(), 1, color, 0.3, 0.16);
      this.triScene.add(a);
    };
    ax([1, 0, 0], 0xd1242f); ax([0, 1, 0], 0x1a7f37); ax([0, 0, 1], 0x0b62c4);
    this.triLabels = ["X", "Y", "Z"].map((t, i) => {
      const d = document.createElement("div");
      d.className = "vlabel3d";
      d.style.cssText = "background:none;border:0;font-weight:700;color:" + ["#d1242f", "#1a7f37", "#0b62c4"][i];
      d.textContent = t;
      stage.appendChild(d);
      return d;
    });
    this._down = null;
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", (e) => { this._down = [e.clientX, e.clientY]; });
    el.addEventListener("pointerup", (e) => {
      if (!this._down || e.button !== 0) return;
      const moved = Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]);
      this._down = null;
      if (moved < 4) this._click(e);
    });
    new ResizeObserver(() => this.resize()).observe(stage);
    this.resize();
  }

  resize() {
    const w = this.stage.clientWidth || 1, h = this.stage.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.persp.aspect = w / h;
    this.persp.updateProjectionMatrix();
    this._orthoFrustum();
    this.render();
  }

  _orthoFrustum() {
    const w = this.stage.clientWidth || 1, h = this.stage.clientHeight || 1;
    const half = this._orthoHalf || 100;
    this.ortho.left = -half * w / h; this.ortho.right = half * w / h;
    this.ortho.top = half; this.ortho.bottom = -half;
    this.ortho.updateProjectionMatrix();
  }

  clear() {
    for (const p of this.parts) {
      p.mesh.geometry.dispose(); p.edges.geometry.dispose(); p.cap.geometry.dispose?.();
    }
    this.root.clear();
    this.helpers.clear();
    this.parts = [];
    this.bbox = null;
    this._clearMeasure();
    this._clearHighlight();
    this.render();
  }

  load(data, keepCamera) {
    this.clear();
    if (!data || !data.parts) return;
    const box = new THREE.Box3();
    data.parts.forEach((pt, i) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pt.pos, 3));
      g.setIndex(pt.idx);
      g.computeVertexNormals();
      g.computeBoundingBox();
      box.union(g.boundingBox);
      const color = new THREE.Color().setRGB(pt.color[0], pt.color[1], pt.color[2], THREE.SRGBColorSpace);
      const mat = new THREE.MeshStandardMaterial({
        color, metalness: 0.12, roughness: 0.58, side: THREE.FrontSide,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, clippingPlanes: [],
      });
      const mesh = new THREE.Mesh(g, mat);
      mesh.userData.part = i;
      // the cut face of a section: back faces drawn flat in a signal colour
      const capMat = new THREE.MeshBasicMaterial({ color: 0xe8743b, side: THREE.BackSide, clippingPlanes: [] });
      const cap = new THREE.Mesh(g, capMat);
      cap.visible = false;
      const segs = [];
      for (const pl of pt.edges) {
        for (let k = 0; k + 5 < pl.length; k += 3) segs.push(pl[k], pl[k + 1], pl[k + 2], pl[k + 3], pl[k + 4], pl[k + 5]);
      }
      const eg = new THREE.BufferGeometry();
      eg.setAttribute("position", new THREE.Float32BufferAttribute(segs, 3));
      const edges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: 0x1b1f24, clippingPlanes: [] }));
      const grp = new THREE.Group();
      grp.add(mesh, cap, edges);
      this.root.add(grp);
      this.parts.push({ name: pt.name, mesh, cap, edges, group: grp, faces: pt.faces, color, visible: true });
    });
    this.bbox = box;
    this._grid();
    this.setStyle(this.style);
    this.setSection(this.secAxis, this.secPos, this.secFlip);
    if (!keepCamera || !this._fitted) { this.view("iso"); this._fitted = true; }
    else this.render();
    this._dims();
  }

  _grid() {
    if (!this.bbox) return;
    const s = this.bbox.getSize(new THREE.Vector3());
    const c = this.bbox.getCenter(new THREE.Vector3());
    const L = Math.max(s.x, s.y) * 2.2 || 100;
    const step = Math.pow(10, Math.floor(Math.log10(L / 10)));
    const n = Math.max(4, Math.round(L / step));
    const grid = new THREE.GridHelper(n * step, n, 0xc5ced8, 0xdde3ea);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(c.x, c.y, this.bbox.min.z - 1e-3 * (s.z || 1));
    grid.material.transparent = true;
    grid.material.opacity = 0.7;
    grid.userData.helper = "grid";
    this.helpers.add(grid);
  }

  setStyle(style) {
    this.style = style;
    for (const p of this.parts) {
      const m = p.mesh.material;
      p.mesh.visible = p.visible && style !== "wire";
      p.edges.visible = p.visible && style !== "shaded";
      m.transparent = style === "xray";
      m.opacity = style === "xray" ? 0.22 : 1;
      m.depthWrite = style !== "xray";
      p.edges.material.color.set(style === "xray" ? 0x24292f : 0x1b1f24);
      p.edges.material.opacity = 1;
      m.needsUpdate = true;
    }
    this._capVis();
    this.render();
  }

  setPartVisible(i, v) {
    const p = this.parts[i];
    if (!p) return;
    p.visible = v;
    this.setStyle(this.style);
  }

  _capVis() {
    for (const p of this.parts) p.cap.visible = p.visible && !!this.secAxis && this.style !== "wire" && this.style !== "xray";
  }

  setSection(axis, pos, flip) {
    this.secAxis = axis || "";
    this.secPos = pos ?? this.secPos;
    this.secFlip = !!flip;
    const planes = [];
    if (this.secAxis && this.bbox) {
      const n = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }[this.secAxis];
      const i = { x: "x", y: "y", z: "z" }[this.secAxis];
      const v = this.bbox.min[i] + (this.bbox.max[i] - this.bbox.min[i]) * this.secPos;
      const s = this.secFlip ? 1 : -1;
      this.clip.normal.set(n[0] * s, n[1] * s, n[2] * s);
      this.clip.constant = -s * v;
      planes.push(this.clip);
    }
    for (const p of this.parts) {
      p.mesh.material.clippingPlanes = planes;
      p.cap.material.clippingPlanes = planes;
      p.edges.material.clippingPlanes = planes;
    }
    this._capVis();
    this.render();
  }

  setOrtho(on) {
    const from = this.camera;
    const to = on ? this.ortho : this.persp;
    if (from === to) return;
    const target = this.controls.target.clone();
    const dist = from.position.distanceTo(target);
    if (on) {
      this._orthoHalf = dist * Math.tan(THREE.MathUtils.degToRad(this.persp.fov / 2));
      this.ortho.zoom = 1;
      this._orthoFrustum();
    } else if (from === this.ortho) {
      // keep the apparent size
      const half = this._orthoHalf / from.zoom;
      const d = half / Math.tan(THREE.MathUtils.degToRad(this.persp.fov / 2));
      const dir = from.position.clone().sub(target).normalize();
      from.position.copy(target.clone().add(dir.multiplyScalar(d)));
    }
    to.position.copy(from.position);
    to.quaternion.copy(from.quaternion);
    this.camera = to;
    this.controls.object = to;
    this.controls.update();
    this.render();
  }

  view(name) {
    if (!this.bbox) return;
    const d = VIEW_DIRS[name] || VIEW_DIRS.iso;
    const dir = new THREE.Vector3(...d).normalize();
    const c = this.bbox.getCenter(new THREE.Vector3());
    const r = Math.max(this.bbox.getSize(new THREE.Vector3()).length() / 2, 1e-3);
    this.controls.target.copy(c);
    const dist = r / Math.sin(THREE.MathUtils.degToRad(this.persp.fov / 2)) * 1.08;
    // top/bottom carry a tiny Y offset so that, with Z up, the screen axes
    // match the program's projections (top: X right, Y up; bottom: X right, -Y up)
    this.camera.position.copy(c.clone().add(dir.multiplyScalar(dist)));
    this._orthoHalf = r * 1.12;
    this.ortho.zoom = 1;
    this._orthoFrustum();
    this.camera.lookAt(c);
    this.controls.update();
    this._lastView = name;
    this.render();
  }

  fit() { this.view(this._lastView || "iso"); }

  // ---------------------------------------------------------- picking
  _ray(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const v = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster();
    rc.setFromCamera(v, this.camera);
    const meshes = this.parts.filter((p) => p.visible).map((p) => p.mesh);
    let hits = rc.intersectObjects(meshes, false);
    if (this.secAxis) hits = hits.filter((h) => this.clip.distanceToPoint(h.point) >= -1e-6);
    return hits[0];
  }

  _click(e) {
    const hit = this._ray(e);
    if (this.measureOn) {
      if (!hit) return;
      this._addMeasure(hit.point);
      return;
    }
    this._clearHighlight();
    if (!hit) { if (this.onPick) this.onPick(null); this.render(); return; }
    const p = this.parts[hit.object.userData.part];
    const tri = hit.faceIndex;
    let face = null, fi = -1;
    for (let k = 0; k < p.faces.length; k++) {
      const f = p.faces[k];
      if (tri >= f.s && tri < f.s + f.k) { face = f; fi = k; break; }
    }
    if (face) this._highlight(p, face);
    if (this.onPick) this.onPick({ part: p.name, partIndex: hit.object.userData.part, face, faceIndex: fi,
      point: [hit.point.x, hit.point.y, hit.point.z] });
    this.render();
  }

  _highlight(p, f) {
    const src = p.mesh.geometry;
    const idx = src.index.array.slice(f.s * 3, (f.s + f.k) * 3);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", src.getAttribute("position"));
    g.setIndex(Array.from(idx));
    const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0x2f81f7, transparent: true, opacity: 0.55,
      depthTest: true, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
      clippingPlanes: p.mesh.material.clippingPlanes }));
    m.userData.helper = "highlight";
    this.helpers.add(m);
    this._hl = m;
  }

  _clearHighlight() {
    if (this._hl) { this.helpers.remove(this._hl); this._hl.geometry.dispose(); this._hl = null; }
  }

  setMeasure(on) {
    this.measureOn = on;
    this.renderer.domElement.style.cursor = on ? "crosshair" : "";
    if (!on) this._clearMeasure();
    this.render();
  }

  _addMeasure(pt) {
    if (this.measurePts.length >= 2) this._clearMeasure();
    this.measurePts.push(pt.clone());
    const r = this.bbox ? this.bbox.getSize(new THREE.Vector3()).length() * 0.006 : 1;
    const dot = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 8), new THREE.MeshBasicMaterial({ color: 0xcf222e, depthTest: false }));
    dot.position.copy(pt);
    dot.renderOrder = 10;
    dot.userData.helper = "measure";
    this.helpers.add(dot);
    if (this.measurePts.length === 2) {
      const [a, b] = this.measurePts;
      const g = new THREE.BufferGeometry().setFromPoints([a, b]);
      const ln = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xcf222e, depthTest: false }));
      ln.renderOrder = 10;
      ln.userData.helper = "measure";
      this.helpers.add(ln);
      const d = a.distanceTo(b);
      this._label(a.clone().add(b).multiplyScalar(0.5), d.toFixed(3) + " mm", "meas", "measure");
      if (this.onMeasure) this.onMeasure({ d, dx: b.x - a.x, dy: b.y - a.y, dz: b.z - a.z, a: a.toArray(), b: b.toArray() });
    }
    this.render();
  }

  _clearMeasure() {
    this.measurePts = [];
    for (const o of [...this.helpers.children]) if (o.userData.helper === "measure") this.helpers.remove(o);
    this.labels = this.labels.filter((l) => { if (l.kind === "measure") { l.el.remove(); return false; } return true; });
  }

  _label(pos, text, cls, kind) {
    const el = document.createElement("div");
    el.className = "vlabel3d" + (cls ? " " + cls : "");
    el.textContent = text;
    this.stage.appendChild(el);
    this.labels.push({ el, pos, kind });
  }

  setDims(on) { this.showDims = on; this._dims(); this.render(); }

  _dims() {
    for (const o of [...this.helpers.children]) if (o.userData.helper === "dims") this.helpers.remove(o);
    this.labels = this.labels.filter((l) => { if (l.kind === "dims") { l.el.remove(); return false; } return true; });
    if (!this.showDims || !this.bbox) return;
    const b = this.bbox, mn = b.min, mx = b.max;
    const pts = [
      [mn.x, mn.y, mn.z], [mx.x, mn.y, mn.z], [mx.x, mx.y, mn.z], [mn.x, mx.y, mn.z],
      [mn.x, mn.y, mx.z], [mx.x, mn.y, mx.z], [mx.x, mx.y, mx.z], [mn.x, mx.y, mx.z]].map((p) => new THREE.Vector3(...p));
    const E = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
    const arr = [];
    for (const [i, j] of E) arr.push(pts[i], pts[j]);
    const ls = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(arr),
      new THREE.LineDashedMaterial({ color: 0x0b62c4, dashSize: b.getSize(new THREE.Vector3()).length() / 80, gapSize: b.getSize(new THREE.Vector3()).length() / 120 }));
    ls.computeLineDistances();
    ls.userData.helper = "dims";
    this.helpers.add(ls);
    const s = b.getSize(new THREE.Vector3());
    this._label(new THREE.Vector3((mn.x + mx.x) / 2, mn.y, mn.z), "X " + s.x.toFixed(2), "", "dims");
    this._label(new THREE.Vector3(mx.x, (mn.y + mx.y) / 2, mn.z), "Y " + s.y.toFixed(2), "", "dims");
    this._label(new THREE.Vector3(mx.x, mn.y, (mn.z + mx.z) / 2), "Z " + s.z.toFixed(2), "", "dims");
  }

  // ---------------------------------------------------------- render
  render() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this._draw(); });
  }

  _draw() {
    const w = this.stage.clientWidth, h = this.stage.clientHeight;
    const cam = this.camera;
    const off = new THREE.Vector3(0.5, -0.4, 1).applyQuaternion(cam.quaternion);
    this.key.position.copy(cam.position).add(off.multiplyScalar(10));
    this.key.target.position.copy(this.controls.target);
    this.fill.position.copy(cam.position).add(new THREE.Vector3(-1, 0.5, -0.5).applyQuaternion(cam.quaternion));
    this.renderer.setScissorTest(false);
    this.renderer.setViewport(0, 0, w, h);
    this.renderer.render(this.scene, cam);
    // labels
    for (const l of this.labels) {
      const p = l.pos.clone().project(cam);
      l.el.style.left = ((p.x + 1) / 2 * w) + "px";
      l.el.style.top = ((1 - p.y) / 2 * h) + "px";
      l.el.style.display = p.z > 1 ? "none" : "";
    }
    // triad in the lower-right corner
    const S = 96;
    const dir = new THREE.Vector3().subVectors(cam.position, this.controls.target).normalize();
    this.triCam.position.copy(dir.multiplyScalar(4));
    this.triCam.quaternion.copy(cam.quaternion);
    this.renderer.setScissorTest(true);
    this.renderer.setScissor(w - S - 6, 6, S, S);
    this.renderer.setViewport(w - S - 6, 6, S, S);
    this.renderer.autoClear = false;
    this.renderer.clearDepth();
    this.renderer.render(this.triScene, this.triCam);
    this.renderer.autoClear = true;
    this.renderer.setScissorTest(false);
    const tips = [[1.25, 0, 0], [0, 1.25, 0], [0, 0, 1.25]];
    tips.forEach((t, i) => {
      const p = new THREE.Vector3(...t).project(this.triCam);
      this.triLabels[i].style.left = (w - S - 6 + (p.x + 1) / 2 * S) + "px";
      this.triLabels[i].style.top = (h - 6 - S + (1 - p.y) / 2 * S) + "px";
    });
  }

  screenshot() {
    this._draw();
    return this.renderer.domElement.toDataURL("image/png");
  }
}

window.Viewer3D = { create: (el) => new Viewer(el) };
window.dispatchEvent(new Event("viewer3d-ready"));
