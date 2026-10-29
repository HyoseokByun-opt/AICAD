/* Drawing sheet viewer: pan and zoom, the view boxes read by the AI (which
   the user can move and resize), the sizes measured on the sheet, the text
   read from the file, and two tools: Measure and Calibrate. */
(function () {
  "use strict";
  const VIEW_COLORS = { front: "#0b62c4", top: "#1a7f37", right: "#d15704", left: "#9a6700", rear: "#6e7781",
    bottom: "#8250df", section: "#cf222e", detail: "#bf3989", isometric: "#0a7d8c", other: "#57606a" };

  class DrawingView {
    constructor(canvas) {
      this.c = canvas;
      this.g = canvas.getContext("2d");
      this.img = null; this.W = 1; this.H = 1;
      this.s = 1; this.ox = 0; this.oy = 0;
      this.views = []; this.est = []; this.texts = []; this.scale = null;
      this.show = { views: true, est: true, text: false };
      this.mode = "pan";
      this.sel = -1;
      this.pts = [];
      this.hover = null;
      this.onViews = null; this.onMeasure = null; this.onCalib = null;
      canvas.addEventListener("wheel", (e) => this._wheel(e), { passive: false });
      canvas.addEventListener("pointerdown", (e) => this._down(e));
      window.addEventListener("pointermove", (e) => this._move(e));
      window.addEventListener("pointerup", (e) => this._up(e));
      canvas.addEventListener("dblclick", () => this.fit());
      new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    }

    resize() {
      const r = this.c.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.c.width = Math.max(1, r.width * dpr); this.c.height = Math.max(1, r.height * dpr);
      this.c.style.width = r.width + "px"; this.c.style.height = r.height + "px";
      this.dpr = dpr;
      if (this._needFit) this.fit(); else this.draw();
    }

    setPage(url, w, h) {
      if (!url) { this.img = null; this.draw(); return; }
      if (this._url === url) return;
      this._url = url;
      const im = new Image();
      im.onload = () => { this.img = im; this.W = w || im.width; this.H = h || im.height; this.fit(); };
      im.src = url;
    }

    setOverlay(o) {
      this.views = (o.views || []).map((v) => ({ ...v, box: v.box.slice() }));
      this.est = o.estimates || [];
      this.texts = o.texts || [];
      this.scale = o.scale || null;
      this.draw();
    }

    setMode(m) {
      this.mode = m; this.pts = []; this.sel = m === "edit" ? this.sel : -1;
      this.c.classList.toggle("cross", m === "measure" || m === "calib");
      this.draw();
    }

    fit() {
      const cw = this.c.width / (this.dpr || 1), ch = this.c.height / (this.dpr || 1);
      if (!this.img || cw < 2) { this._needFit = true; this.draw(); return; }
      this._needFit = false;
      this.s = Math.min(cw / this.W, ch / this.H) * 0.96;
      this.ox = (cw - this.W * this.s) / 2; this.oy = (ch - this.H * this.s) / 2;
      this.draw();
    }

    toImg(e) {
      const r = this.c.getBoundingClientRect();
      return [(e.clientX - r.left - this.ox) / this.s, (e.clientY - r.top - this.oy) / this.s];
    }

    _wheel(e) {
      e.preventDefault();
      const r = this.c.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const f = Math.exp(-e.deltaY * 0.0015);
      const ns = Math.min(Math.max(this.s * f, 0.02), 40);
      this.ox = mx - (mx - this.ox) * ns / this.s; this.oy = my - (my - this.oy) * ns / this.s;
      this.s = ns;
      this.draw();
    }

    _hitView(p) {
      const tol = 8 / this.s;
      for (let i = this.views.length - 1; i >= 0; i--) {
        const b = this.views[i].box;
        const corners = [[b[0], b[1], "tl"], [b[2], b[1], "tr"], [b[0], b[3], "bl"], [b[2], b[3], "br"]];
        for (const [x, y, k] of corners) if (Math.abs(p[0] - x) < tol && Math.abs(p[1] - y) < tol) return [i, k];
        if (p[0] > b[0] && p[0] < b[2] && p[1] > b[1] && p[1] < b[3]) return [i, "move"];
      }
      return [-1, null];
    }

    _down(e) {
      if (e.button !== 0 && e.button !== 1) return;
      const p = this.toImg(e);
      if (e.button === 1 || this.mode === "pan" || (this.mode === "edit" && this._hitView(p)[0] < 0)) {
        this.drag = { kind: "pan", x: e.clientX, y: e.clientY, ox: this.ox, oy: this.oy };
        if (this.mode === "edit") { this.sel = -1; this.draw(); }
        return;
      }
      if (this.mode === "edit") {
        const [i, k] = this._hitView(p);
        this.sel = i;
        this.drag = { kind: k, i, p0: p, box0: this.views[i].box.slice() };
        this.draw();
        return;
      }
      if (this.mode === "measure" || this.mode === "calib") {
        let q = p;
        if (e.shiftKey && this.pts.length === 1) q = this._ortho(this.pts[0], p);
        this.pts.push(q);
        if (this.pts.length === 2) {
          const L = Math.hypot(this.pts[1][0] - this.pts[0][0], this.pts[1][1] - this.pts[0][1]);
          if (this.mode === "calib" && this.onCalib) this.onCalib(L, this.pts.slice());
          if (this.mode === "measure" && this.onMeasure) this.onMeasure(L, this.pts.slice());
          this._done = this.pts.slice();
        } else if (this.pts.length > 2) {
          this.pts = [q]; this._done = null;
        }
        this.draw();
      }
    }

    _ortho(a, b) {
      return Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]) ? [b[0], a[1]] : [a[0], b[1]];
    }

    _move(e) {
      if (this.drag) {
        if (this.drag.kind === "pan") {
          this.ox = this.drag.ox + e.clientX - this.drag.x; this.oy = this.drag.oy + e.clientY - this.drag.y;
        } else {
          const p = this.toImg(e), d = this.drag, b = d.box0.slice();
          const dx = p[0] - d.p0[0], dy = p[1] - d.p0[1];
          if (d.kind === "move") { b[0] += dx; b[2] += dx; b[1] += dy; b[3] += dy; }
          if (d.kind.includes("l")) b[0] += dx;
          if (d.kind.includes("r")) b[2] += dx;
          if (d.kind.includes("t")) b[1] += dy;
          if (d.kind.includes("b") && d.kind !== "move") b[3] += dy;
          this.views[d.i].box = [Math.min(b[0], b[2]), Math.min(b[1], b[3]), Math.max(b[0], b[2]), Math.max(b[1], b[3])];
          this.views[d.i].fixed = true;   // a box placed by hand is not snapped again
          this._dirty = true;
        }
        this.draw();
        return;
      }
      if ((this.mode === "measure" || this.mode === "calib") && this.pts.length === 1 && e.target === this.c) {
        let p = this.toImg(e);
        if (e.shiftKey) p = this._ortho(this.pts[0], p);
        this.hover = p;
        this.draw();
      }
    }

    _up() {
      if (this.drag && this.drag.kind !== "pan" && this._dirty && this.onViews) this.onViews(this.views);
      this._dirty = false;
      this.drag = null;
    }

    mmText(px) {
      if (!this.scale) return px.toFixed(1) + " px";
      return (px * this.scale).toFixed(2) + " mm  (" + px.toFixed(1) + " px)";
    }

    draw() {
      const g = this.g, dpr = this.dpr || 1;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, this.c.width, this.c.height);
      if (!this.img) return;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.save();
      g.translate(this.ox, this.oy); g.scale(this.s, this.s);
      g.shadowColor = "rgba(0,0,0,.18)"; g.shadowBlur = 12 / this.s;
      g.fillStyle = "#fff"; g.fillRect(0, 0, this.W, this.H);
      g.shadowBlur = 0;
      g.imageSmoothingQuality = "high";
      g.drawImage(this.img, 0, 0, this.W, this.H);
      g.restore();
      const T = (x, y) => [this.ox + x * this.s, this.oy + y * this.s];
      g.font = "600 11.5px Segoe UI, sans-serif";
      if (this.show.text) {
        g.strokeStyle = "rgba(130,80,223,.7)"; g.lineWidth = 1;
        for (const t of this.texts) {
          const b = t.box;
          const [x0, y0] = T(b[0] / 1000 * this.W, b[1] / 1000 * this.H), [x1, y1] = T(b[2] / 1000 * this.W, b[3] / 1000 * this.H);
          g.strokeRect(x0, y0, x1 - x0, y1 - y0);
        }
      }
      if (this.show.views) {
        this.views.forEach((v, i) => {
          const col = VIEW_COLORS[v.type] || VIEW_COLORS.other;
          const [x0, y0] = T(v.box[0], v.box[1]), [x1, y1] = T(v.box[2], v.box[3]);
          g.lineWidth = i === this.sel ? 2.5 : 1.6;
          g.strokeStyle = col; g.setLineDash(i === this.sel ? [] : [6, 4]);
          g.strokeRect(x0, y0, x1 - x0, y1 - y0);
          g.setLineDash([]);
          g.fillStyle = col + "18"; g.fillRect(x0, y0, x1 - x0, y1 - y0);
          const lab = v.id + " · " + v.type;
          const tw = g.measureText(lab).width + 10;
          g.fillStyle = col; g.fillRect(x0, y0 - 18, tw, 18);
          g.fillStyle = "#fff"; g.fillText(lab, x0 + 5, y0 - 5);
          if (this.mode === "edit") {
            g.fillStyle = "#fff"; g.strokeStyle = col; g.lineWidth = 1.5;
            for (const [x, y] of [[x0, y0], [x1, y0], [x0, y1], [x1, y1]]) { g.fillRect(x - 4, y - 4, 8, 8); g.strokeRect(x - 4, y - 4, 8, 8); }
          }
        });
      }
      if (this.show.est) {
        for (const e of this.est) {
          if (!e.p1 || !e.p2) continue;
          const a = T(...e.p1), b = T(...e.p2);
          this._dimLine(a, b, "#0b62c4", e.name + " = " + Number(e.value).toFixed(1));
        }
      }
      const pts = this._done || this.pts;
      if ((this.mode === "measure" || this.mode === "calib") && pts.length) {
        const col = this.mode === "calib" ? "#8250df" : "#cf222e";
        const a = T(...pts[0]);
        const bp = pts[1] || this.hover;
        if (bp) {
          const b = T(...bp);
          const L = Math.hypot(bp[0] - pts[0][0], bp[1] - pts[0][1]);
          this._dimLine(a, b, col, this.mode === "calib" ? L.toFixed(1) + " px" : this.mmText(L));
        } else {
          g.fillStyle = col; g.beginPath(); g.arc(a[0], a[1], 4, 0, 7); g.fill();
        }
      }
    }

    _dimLine(a, b, col, text) {
      const g = this.g;
      g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1.8;
      g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
      for (const p of [a, b]) { g.beginPath(); g.arc(p[0], p[1], 3.5, 0, 7); g.fill(); }
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      const tw = g.measureText(text).width + 10;
      g.fillStyle = "rgba(255,255,255,.95)"; g.fillRect(mx - tw / 2, my - 20, tw, 17);
      g.strokeStyle = col; g.lineWidth = 1; g.strokeRect(mx - tw / 2, my - 20, tw, 17);
      g.fillStyle = col; g.fillText(text, mx - tw / 2 + 5, my - 7);
    }
  }
  window.DrawingView = DrawingView;
  window.VIEW_COLORS = VIEW_COLORS;
})();
