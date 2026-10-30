"""The local AI engine: llama.cpp's llama-server with a vision model.

The server runs on 127.0.0.1 only, on a free port, and is tied to this
program through a Windows job object, so closing AICAD always ends it.
Requests use llama-server's chat-completions endpoint with streamed answers;
images travel inline as base64 PNG.
"""
from __future__ import annotations

import base64
import collections
import ctypes
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import catalog
from .paths import ENGINE_DIR, MODELS_DIR, load_settings


# ------------------------------------------------------------------ hardware
def _nvidia_smi():
    for c in (shutil.which("nvidia-smi"), r"C:\Windows\System32\nvidia-smi.exe",
              r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        if c and Path(c).exists():
            return c
    return None


_GPU_CACHE = {"t": 0, "v": None}


def detect_gpus(force=False) -> list[dict]:
    if not force and _GPU_CACHE["v"] is not None and time.time() - _GPU_CACHE["t"] < 30:
        return _GPU_CACHE["v"]
    gpus = []
    smi = _nvidia_smi()
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total,memory.used,driver_version",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                 timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    gpus.append({"name": parts[0], "vendor": "NVIDIA", "vram_gb": round(float(parts[1]) / 1024, 1),
                                 "used_gb": round(float(parts[2]) / 1024, 1), "driver": parts[3]})
        except Exception:
            pass
    if not gpus and os.name == "nt":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                                 capture_output=True, text=True, timeout=15,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            for n in out.strip().splitlines():
                if n.strip():
                    gpus.append({"name": n.strip(), "vendor": "other", "vram_gb": None})
        except Exception:
            pass
    _GPU_CACHE.update(t=time.time(), v=gpus)
    return gpus


def best_nvidia_vram(gpus=None):
    gpus = gpus if gpus is not None else detect_gpus()
    v = [g["vram_gb"] for g in gpus if g.get("vendor") == "NVIDIA" and g.get("vram_gb")]
    return max(v) if v else None


def engines() -> dict:
    out = {}
    for k in ("cuda", "vulkan", "cpu"):
        exe = ENGINE_DIR / k / "llama-server.exe"
        if exe.exists():
            out[k] = str(exe)
    return out


def installed_models() -> list[dict]:
    out = []
    if not MODELS_DIR.exists():
        return out
    for d in sorted(MODELS_DIR.iterdir()):
        if not d.is_dir():
            continue
        ggufs = sorted(d.glob("*.gguf"))
        mm = [g for g in ggufs if g.name.lower().startswith("mmproj")]
        main = [g for g in ggufs if g not in mm and ("-of-" not in g.name or "-00001-of-" in g.name)]
        if not main:
            continue
        prof = catalog.BY_ID.get(d.name, {})
        meta = {}
        try:
            meta = json.loads((d / "model.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        size = sum(g.stat().st_size for g in ggufs if g not in mm) / 1e9
        complete = True
        if prof:
            names = {g.name for g in ggufs}
            complete = all(f[0] in names for f in prof["files"])
        out.append({
            "id": d.name, "name": meta.get("name") or prof.get("name") or main[0].stem,
            "model": str(main[0]), "mmproj": str(mm[0]) if mm else None,
            "size_gb": round(size, 1), "vision": bool(mm), "complete": complete,
            "ctx": meta.get("ctx") or prof.get("ctx") or 32768,
            "image_max_tokens": meta.get("image_max_tokens") or prof.get("image_max_tokens") or 2048,
            "min_vram_gb": prof.get("min_vram_gb", round(size * 1.25, 1)),
            "rank": prof.get("rank", 10), "target": prof.get("target", ""),
            "license": meta.get("license") or prof.get("license", ""),
        })
    return out


def choose_model(models=None, vram=None, wanted="auto"):
    models = models if models is not None else installed_models()
    models = [m for m in models if m["complete"]]
    if not models:
        return None, "No model is installed. Run 3_GET_AI_MODEL.bat on a PC with internet and copy the models folder."
    if wanted and wanted != "auto":
        for m in models:
            if m["id"] == wanted:
                return m, ""
    v = vram or 0
    fits = [m for m in models if m["min_vram_gb"] <= v]
    if fits:
        return max(fits, key=lambda m: m["rank"]), ""
    small = min(models, key=lambda m: m["min_vram_gb"])
    note = ""
    if small["min_vram_gb"] > v:
        note = (f"{small['name']} needs about {small['min_vram_gb']} GB of graphics memory; "
                f"{'no NVIDIA GPU was found' if not v else f'the GPU has {v} GB'}. "
                "Layers that do not fit run on the CPU, which is much slower.")
    return small, note


# ------------------------------------------------------------------ job object
class _JobObject:
    """Windows job object with KILL_ON_JOB_CLOSE: children die with us."""

    def __init__(self):
        self.h = None
        if os.name != "nt":
            return
        try:
            k32 = ctypes.windll.kernel32

            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in
                            ("r", "w", "o", "rb", "wb", "ob")]

            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                            ("PerJobUserTimeLimit", ctypes.c_longlong),
                            ("LimitFlags", ctypes.c_uint32),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", ctypes.c_uint32),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", ctypes.c_uint32),
                            ("SchedulingClass", ctypes.c_uint32)]

            class EXT(ctypes.Structure):
                _fields_ = [("Basic", BASIC), ("Io", IO),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32.CreateJobObjectW.restype = ctypes.c_void_p
            h = k32.CreateJobObjectW(None, None)
            info = EXT()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(ctypes.c_void_p(h), 9, ctypes.byref(info), ctypes.sizeof(info))
            self.h = h
        except Exception:
            self.h = None

    def add(self, proc):
        if not self.h:
            return
        try:
            k32 = ctypes.windll.kernel32
            k32.OpenProcess.restype = ctypes.c_void_p
            ph = k32.OpenProcess(0x1F0FFF, False, proc.pid)
            k32.AssignProcessToJobObject(ctypes.c_void_p(self.h), ctypes.c_void_p(ph))
            k32.CloseHandle(ctypes.c_void_p(ph))
        except Exception:
            pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------------ engine
class Engine:
    def __init__(self):
        self.proc = None
        self.port = None
        self.state = "stopped"     # stopped | starting | ready | error
        self.error = ""
        self.model = None
        self.engine_kind = None
        self.note = ""
        self.log = collections.deque(maxlen=400)
        self.last_used = time.time()
        self.started_at = None
        self._lock = threading.Lock()
        self._job = _JobObject()
        threading.Thread(target=self._idle_watch, daemon=True).start()

    # ---------------------------------------------------------- status
    def status(self) -> dict:
        if self.proc is not None and self.proc.poll() is not None and self.state in ("ready", "starting"):
            self.state = "error"
            self.error = self.error or "The AI engine stopped unexpectedly. See the engine log."
        return {"state": self.state, "error": self.error, "note": self.note,
                "model": self.model and {k: self.model[k] for k in ("id", "name", "size_gb", "vision")},
                "engine": self.engine_kind, "port": self.port,
                "log": list(self.log)[-60:]}

    def _reader(self, stream):
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.log.append(line)

    def _pick_engine(self, wanted):
        have = engines()
        if not have:
            return None, None
        if wanted in have:
            return wanted, have[wanted]
        if best_nvidia_vram() and "cuda" in have:
            return "cuda", have["cuda"]
        if "cpu" in have:
            return "cpu", have["cpu"]
        k = next(iter(have))
        return k, have[k]

    def start(self, model_id=None, wait=True, timeout=900, stop=None):
        with self._lock:
            if self.state == "ready" and self.proc and self.proc.poll() is None:
                if not model_id or model_id == "auto" or (self.model and model_id == self.model["id"]):
                    return True
                self._stop_locked()
            if self.state == "starting" and self.proc and self.proc.poll() is None:
                pass
            else:
                s = load_settings()
                kind, exe = self._pick_engine(s.get("engine", "auto"))
                if not exe:
                    self.state, self.error = "error", "No AI engine was found in the engine folder (llama-server.exe)."
                    return False
                vram = best_nvidia_vram() if kind in ("cuda", "vulkan") else 0
                m, note = choose_model(vram=vram, wanted=model_id or s.get("model", "auto"))
                if not m:
                    self.state, self.error = "error", note
                    return False
                self.note = note
                ctx = int(s.get("ctx") or 0) or int(m["ctx"])
                imt = int(s.get("image_max_tokens") or 0) or int(m["image_max_tokens"])
                if kind == "cpu":
                    ctx = min(ctx, 16384)
                    imt = min(imt, 1280)
                self.port = _free_port()
                cmd = [exe, "-m", m["model"], "--host", "127.0.0.1", "--port", str(self.port),
                       "-c", str(ctx), "--jinja", "-np", "1", "--no-webui", "-fa", "auto"]
                if m["mmproj"]:
                    cmd += ["--mmproj", m["mmproj"], "--image-max-tokens", str(imt)]
                gl = str(s.get("gpu_layers", "auto"))
                if kind != "cpu" and gl not in ("auto", "", "None"):
                    cmd += ["-ngl", gl]
                tb = int(s.get("think_budget") or 0)
                if tb > 0:
                    cmd += ["--reasoning-budget", str(tb), "--reasoning-budget-message",
                            "The thinking budget is used up. Write the final answer now."]
                if int(s.get("threads") or 0) > 0:
                    cmd += ["-t", str(int(s["threads"]))]
                self.log.clear()
                self.log.append("> " + " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd)))
                env = dict(os.environ)
                try:
                    self.proc = subprocess.Popen(cmd, cwd=str(Path(exe).parent), stdout=subprocess.PIPE,
                                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except OSError as e:
                    self.state, self.error = "error", f"The AI engine could not be started: {e}"
                    return False
                self._job.add(self.proc)
                threading.Thread(target=self._reader, args=(self.proc.stdout,), daemon=True).start()
                self.model, self.engine_kind = m, kind
                self.state, self.error, self.started_at = "starting", "", time.time()
        if not wait:
            threading.Thread(target=self._wait_ready, args=(timeout, None), daemon=True).start()
            return True
        return self._wait_ready(timeout, stop)

    def _wait_ready(self, timeout, stop):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if stop is not None and stop.is_set():
                return False
            if self.proc is None or self.proc.poll() is not None:
                tail = " | ".join(list(self.log)[-6:])
                self.state = "error"
                self.error = "The AI engine stopped while loading the model. " + tail[-600:]
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=3) as r:
                    if r.status == 200 and json.loads(r.read() or b"{}").get("status") == "ok":
                        self.state = "ready"
                        self.last_used = time.time()
                        return True
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.5)
        self.state, self.error = "error", f"The model did not finish loading within {timeout} s."
        return False

    def _stop_locked(self):
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.state = "stopped"

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _idle_watch(self):
        while True:
            time.sleep(30)
            try:
                mins = float(load_settings().get("idle_minutes") or 0)
            except (TypeError, ValueError):
                mins = 0
            if mins > 0 and self.state == "ready" and time.time() - self.last_used > mins * 60:
                self.log.append(f"Stopped after {mins:g} min without requests (Settings).")
                self.stop()

    # ---------------------------------------------------------- chat
    def chat(self, messages, max_tokens=8192, temperature=0.6, top_p=0.95, top_k=20,
             presence_penalty=0.0, thinking=True, on_token=None, stop=None, timeout=1800):
        """Streamed chat completion. Returns dict(content, reasoning, timings).

        on_token(kind, text) receives 'think' and 'text' pieces as they arrive;
        a set `stop` event closes the connection and ends generation."""
        if self.state != "ready":
            raise RuntimeError("The AI engine is not running.")
        self.last_used = time.time()
        body = {"messages": messages, "stream": True, "max_tokens": int(max_tokens),
                "temperature": temperature, "top_p": top_p, "top_k": top_k,
                "presence_penalty": presence_penalty, "min_p": 0.0,
                "chat_template_kwargs": {"enable_thinking": bool(thinking)},
                "timings_per_token": False, "cache_prompt": True}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        content, reasoning, timings, finish = [], [], {}, None
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:800]
            raise RuntimeError(f"The AI engine refused the request ({e.code}): {msg}") from e
        with resp:
            for raw in resp:
                if stop is not None and stop.is_set():
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ch = json.loads(data)
                except ValueError:
                    continue
                if ch.get("timings"):
                    timings = ch["timings"]
                for c in ch.get("choices") or []:
                    d = c.get("delta") or {}
                    if d.get("reasoning_content"):
                        reasoning.append(d["reasoning_content"])
                        if on_token:
                            on_token("think", d["reasoning_content"])
                    if d.get("content"):
                        content.append(d["content"])
                        if on_token:
                            on_token("text", d["content"])
                        if len(content) % 64 == 0 and _looping("".join(content[-400:])):
                            finish = "repetition"
                    if c.get("finish_reason"):
                        finish = c["finish_reason"]
                if finish == "repetition":
                    break        # closing the stream ends the generation in the engine
        self.last_used = time.time()
        return {"content": "".join(content), "reasoning": "".join(reasoning), "timings": timings,
                "finish": finish, "stopped": bool(stop is not None and stop.is_set())}


def _looping(tail: str) -> bool:
    """A small model sometimes repeats the same lines until the token limit
    (minutes of output on a CPU). True when the last 30 lines hold no more
    than 3 different lines, or the tail is one block repeated four times."""
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    if len(lines) >= 30 and len(set(lines[-30:])) <= 3:
        return True
    t = tail[-1600:]
    for p in range(20, 401):
        if len(t) >= 4 * p and t[-p:] == t[-2 * p:-p] == t[-3 * p:-2 * p] == t[-4 * p:-3 * p]:
            return True
    return False


def image_part(path) -> dict:
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


_ENGINE = None


def engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = Engine()
    return _ENGINE
