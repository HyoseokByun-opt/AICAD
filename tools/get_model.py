"""Download AI models (and, if missing, the llama.cpp engines) for AICAD.

    python tools/get_model.py qwen3.6-27b-q4          one profile
    python tools/get_model.py qwen3.6-27b-q4 qwen3.6-27b-q6
    python tools/get_model.py auto                    for the GPU of this PC
    python tools/get_model.py --list
    python tools/get_model.py --engine                llama.cpp builds into engine/

Standard library only, so it runs in the bare Python runtime. Downloads
resume after an interruption (HTTP range requests) and every file is
checked against the SHA-256 digest published by Hugging Face. A proxy is
taken from HTTPS_PROXY if set.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from aicad import catalog  # noqa: E402

MODELS = Path(os.environ.get("AICAD_MODELS", ROOT / "models"))
LLAMA_TAG = "b11606"
ENGINE_FILES = {
    "cuda": [f"llama-{LLAMA_TAG}-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"],
    "vulkan": [f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip"],
    "cpu": [f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip"],
}


def human(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1000 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1000


def download(url, dest: Path, size=None):
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "AICAD-get-model"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0  # server ignored the range: start again
        total = size or (have + int(r.headers.get("Content-Length", 0)))
        mode = "ab" if have else "wb"
        t0, last, got = time.time(), 0, have
        with open(part, mode) as f:
            while True:
                buf = r.read(1 << 20)
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
                now = time.time()
                if now - last > 1.0:
                    last = now
                    rate = (got - have) / max(now - t0, 1e-6)
                    eta = (total - got) / rate if rate > 0 and total else 0
                    pct = 100 * got / total if total else 0
                    print(f"\r    {pct:5.1f} %  {human(got)} of {human(total)}  {human(rate)}/s  "
                          f"{int(eta // 60)} min {int(eta % 60):02d} s left   ", end="", flush=True)
    print()
    part.replace(dest)


def sha256(p: Path):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(8 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def get_profile(pid):
    prof = catalog.BY_ID.get(pid)
    if not prof:
        print(f"  Unknown profile '{pid}'. Use --list.")
        return False
    d = MODELS / pid
    d.mkdir(parents=True, exist_ok=True)
    print(f"\n  {prof['name']}  ({prof['target']})\n  from huggingface.co/{prof['repo']}  licence {prof['license']}")
    ok_file = d / ".verified.json"
    try:
        verified = json.loads(ok_file.read_text())
    except (OSError, ValueError):
        verified = {}
    for name, size, digest in prof["files"]:
        f = d / name
        if f.exists() and f.stat().st_size == size and verified.get(name) == digest:
            print(f"    {name}: present and verified")
            continue
        for attempt in range(1, 6):
            try:
                if not (f.exists() and f.stat().st_size == size):
                    print(f"    {name} ({human(size)})")
                    download(catalog.hf_url(prof["repo"], name), f, size)
                print("    checking SHA-256 ...", end="", flush=True)
                if sha256(f) == digest:
                    print(" ok")
                    verified[name] = digest
                    ok_file.write_text(json.dumps(verified))
                    break
                print(" MISMATCH - downloading again")
                f.unlink()
            except Exception as e:  # network errors: resume
                print(f"\n    interrupted ({e}); retrying in 10 s (attempt {attempt} of 5)")
                time.sleep(10)
        else:
            print(f"    {name} could not be downloaded.")
            return False
    meta = {k: prof[k] for k in ("id", "name", "target", "repo", "base", "license", "ctx", "image_max_tokens")}
    (d / "model.json").write_text(json.dumps(meta, indent=1))
    print(f"  Ready: {d}")
    return True


def get_engine():
    eng = ROOT / "engine"
    tmp = ROOT / "downloads" / "engine"
    tmp.mkdir(parents=True, exist_ok=True)
    for kind, files in ENGINE_FILES.items():
        if (eng / kind / "llama-server.exe").exists():
            print(f"  engine/{kind}: present")
            continue
        (eng / kind).mkdir(parents=True, exist_ok=True)
        for fn in files:
            z = tmp / fn
            if not z.exists():
                print(f"  {fn}")
                download(f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{fn}", z)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(eng / kind)
        print(f"  engine/{kind}: ready")


def auto_profile():
    smi = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    vram = None
    try:
        out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        rows = [l.split(",") for l in out.strip().splitlines() if "," in l]
        if rows:
            vram = max(float(r[1]) / 1024 for r in rows)
            print("  GPU: " + "; ".join(f"{r[0].strip()} {float(r[1]) / 1024:.0f} GB" for r in rows))
    except Exception:
        pass
    if vram is None:
        print("  No NVIDIA GPU found on this PC.")
    p = catalog.for_vram(vram)
    print(f"  Recommended: {p['id']} - {p['name']}")
    return p["id"]


def main(argv):
    if not argv or "--list" in argv:
        print("Profiles:")
        for p in catalog.PROFILES:
            size = sum(f[1] for f in p["files"])
            print(f"  {p['id']:22s} {human(size):>9s}  {p['target']}")
        return 0
    if "--engine" in argv:
        get_engine()
        argv = [a for a in argv if a != "--engine"]
        if not argv:
            return 0
    ok = True
    for a in argv:
        ok &= get_profile(auto_profile() if a == "auto" else a)
    print("\n  All done." if ok else "\n  Some files are missing; run this again to resume.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
