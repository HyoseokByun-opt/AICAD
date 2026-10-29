"""Projects: one folder per modelled object in the workspace.

    <workspace>/<id>/project.json     name, inputs, pages, request, versions
    <workspace>/<id>/input/           the original files and the page images
    <workspace>/<id>/spec.json        what the AI read from the drawing
    <workspace>/<id>/resolved.json    the values (with provenance) and the scale
    <workspace>/<id>/versions/v001/   model.py, model.step, mesh.json, views ...
    <workspace>/<id>/exports/         files written by Export
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import threading
from pathlib import Path

from .paths import workspace

_locks: dict[str, threading.Lock] = {}


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", name.strip(), flags=re.A).strip("-").lower()
    return s[:40] or "project"


class Project:
    def __init__(self, pid: str):
        self.id = pid
        self.dir = workspace() / pid
        self.file = self.dir / "project.json"
        _locks.setdefault(pid, threading.Lock())
        self.data = self._load()

    # ------------------------------------------------------------ storage
    def _load(self):
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self):
        with _locks[self.id]:
            self.data["modified"] = _now()
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)

    @classmethod
    def create(cls, name: str) -> "Project":
        base = slug(name) + "-" + _dt.datetime.now().strftime("%y%m%d-%H%M%S")
        pid, k = base, 1
        while (workspace() / pid).exists():
            k += 1
            pid = f"{base}-{k}"
        (workspace() / pid / "input").mkdir(parents=True)
        (workspace() / pid / "versions").mkdir()
        p = cls(pid)
        p.data = {"id": pid, "name": name.strip() or "Untitled", "created": _now(), "inputs": [], "pages": [],
                  "page": 0, "request": "", "versions": [], "current": None, "calib": {}, "history": []}
        p.save()
        return p

    @staticmethod
    def list_all() -> list[dict]:
        out = []
        for d in workspace().iterdir():
            f = d / "project.json"
            if d.is_dir() and f.exists():
                try:
                    j = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                thumb = None
                cur = j.get("current")
                if cur and (d / "versions" / cur / "view_iso.png").exists():
                    thumb = f"versions/{cur}/view_iso.png"
                elif j.get("pages"):
                    thumb = "input/" + j["pages"][0]["file"]
                out.append({"id": j.get("id", d.name), "name": j.get("name", d.name),
                            "modified": j.get("modified", ""), "versions": len(j.get("versions", [])),
                            "pages": len(j.get("pages", [])), "thumb": thumb})
        out.sort(key=lambda r: r["modified"], reverse=True)
        return out

    def exists(self):
        return self.file.exists()

    def summary(self) -> dict:
        d = dict(self.data)
        d["spec"] = self.read_json("spec.json")
        d["resolved"] = self.read_json("resolved.json")
        return d

    def read_json(self, rel):
        try:
            return json.loads((self.dir / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_json(self, rel, obj):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")

    def path(self, rel: str) -> Path:
        """A file inside the project; refuses paths that leave the folder."""
        p = (self.dir / rel).resolve()
        if self.dir.resolve() not in p.parents and p != self.dir.resolve():
            raise ValueError("path outside the project")
        return p

    # ------------------------------------------------------------ inputs
    def add_pages(self, src_name: str, pages: list[dict]):
        self.data.setdefault("inputs", []).append({"file": src_name, "added": _now(), "pages": len(pages)})
        self.data.setdefault("pages", []).extend(pages)
        self.data["page"] = len(self.data["pages"]) - len(pages)
        self.save()

    def page(self, idx=None):
        pages = self.data.get("pages") or []
        if not pages:
            return None, None
        i = self.data.get("page", 0) if idx is None else idx
        i = max(0, min(int(i), len(pages) - 1))
        return pages[i], self.dir / "input" / pages[i]["file"]

    def remove_page(self, idx):
        pages = self.data.get("pages") or []
        if 0 <= idx < len(pages):
            pages.pop(idx)
            self.data["page"] = max(0, min(self.data.get("page", 0), len(pages) - 1))
            self.save()

    def calib(self, page_file):
        return (self.data.get("calib") or {}).get(page_file)

    # ------------------------------------------------------------ versions
    def new_version(self, code: str, source: str, note: str = "") -> tuple[str, Path]:
        n = 1 + max([int(v["id"][1:]) for v in self.data.get("versions", []) if v["id"][1:].isdigit()] or [0])
        vid = f"v{n:03d}"
        d = self.dir / "versions" / vid
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.py").write_text(code, encoding="utf-8")
        self.data.setdefault("versions", []).append({"id": vid, "created": _now(), "source": source,
                                                     "note": note, "ok": None})
        self.save()
        return vid, d

    def set_version(self, vid: str, **kw):
        for v in self.data.get("versions", []):
            if v["id"] == vid:
                v.update(kw)
        self.save()

    def version(self, vid: str | None = None):
        vid = vid or self.data.get("current")
        for v in self.data.get("versions", []):
            if v["id"] == vid:
                return v
        return None

    def version_dir(self, vid: str) -> Path:
        return self.dir / "versions" / vid

    def code(self, vid: str | None = None) -> str:
        vid = vid or self.data.get("current")
        if not vid:
            return ""
        try:
            return (self.version_dir(vid) / "model.py").read_text(encoding="utf-8")
        except OSError:
            return ""

    def log(self, kind: str, text: str, **kw):
        h = self.data.setdefault("history", [])
        h.append({"t": _now(), "kind": kind, "text": text, **kw})
        del h[:-200]

    def delete(self):
        shutil.rmtree(self.dir, ignore_errors=True)
