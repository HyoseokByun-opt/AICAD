"""Download AI models (and, if missing, the llama.cpp engines) for AICAD.

    python tools/get_model.py qwen3.6-27b-q4          one profile
    python tools/get_model.py qwen3.6-27b-q4 qwen3.6-27b-q6
    python tools/get_model.py auto                    for the GPU of this PC
    python tools/get_model.py --list
    python tools/get_model.py --engine                llama.cpp builds into engine/
    python tools/get_model.py qwen3.6-27b-q4 --release   the parts of the GitHub release instead
    python tools/get_model.py --parts D:/download     unpack release parts already downloaded

Standard library only, so it runs in the bare Python runtime. Downloads
resume after an interruption (HTTP range requests) and every file is
checked against the SHA-256 digest published by Hugging Face. The GitHub
release holds the larger models as parts below 2 GiB (one GGUF shard per
zip, see tools/make_model_parts.py); --release downloads and unpacks them,
--parts unpacks parts that were downloaded by hand, both checking every part
against the release's SHA256SUMS.txt. A proxy is taken from HTTPS_PROXY if
set.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
    for entry in prof["files"]:
        name, size, digest = entry[:3]
        repo = entry[3] if len(entry) > 3 else prof["repo"]      # a file may come from another conversion
        f = d / name
        if f.exists() and f.stat().st_size == size and verified.get(name) == digest:
            print(f"    {name}: present and verified")
            continue
        for attempt in range(1, 6):
            try:
                if not (f.exists() and f.stat().st_size == size):
                    print(f"    {name} ({human(size)})")
                    download(catalog.hf_url(repo, name), f, size)
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


# ------------------------------------------------------------------ release parts
PART = re.compile(r"AICAD-(?P<ver>[\d.]+)-model-(?P<pid>.+)-part(?P<i>\d+)of(?P<n>\d+)\.zip$")
RELEASE_REPO = os.environ.get("AICAD_RELEASE_REPO", "HyoseokByun-opt/AICAD")


def _sums(text):
    out = {}
    for ln in text.splitlines():
        if "  " in ln:
            h, n = ln.strip().split("  ", 1)
            out[n.strip()] = h.lower()
    return out


def install_parts(zips, sums=None, remove=False):
    """Unpack release parts (AICAD-<v>-model-<profile>-partNNofMM.zip) into
    models/<profile>/, after checking that every part is there and, when the
    SHA256SUMS.txt of the release is at hand, that every part is intact."""
    groups = {}
    for z in zips:
        m = PART.search(z.name)
        if m:
            groups.setdefault(m["pid"], {})[int(m["i"])] = (z, int(m["n"]))
    if not groups:
        print("  No model parts (AICAD-<version>-model-<profile>-partNNofMM.zip) found.")
        return False
    ok = True
    for pid, parts in sorted(groups.items()):
        n = next(iter(parts.values()))[1]
        missing = [i for i in range(1, n + 1) if i not in parts]
        print(f"\n  {pid}: {len(parts)} of {n} parts")
        if missing:
            print(f"    missing part(s) {', '.join(str(i) for i in missing)} - download them too")
            ok = False
            continue
        d = MODELS / pid
        d.mkdir(parents=True, exist_ok=True)
        for i in range(1, n + 1):
            z = parts[i][0]
            if sums and z.name in sums:
                print(f"    {z.name}: checking SHA-256 ...", end="", flush=True)
                if sha256(z) != sums[z.name]:
                    print(" MISMATCH - the file is damaged; download it again")
                    ok = False
                    break
                print(" ok")
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    parts_ = info.filename.replace("\\", "/").split("/")
                    if info.is_dir() or "models" not in parts_:
                        continue
                    rel = parts_[parts_.index("models") + 1:]
                    if len(rel) != 2 or rel[0] != pid or rel[1] in ("", "..", "."):
                        continue
                    with zf.open(info) as src, open(d / rel[1], "wb") as dst:
                        shutil.copyfileobj(src, dst, 8 << 20)
                    print(f"    unpacked {rel[1]}")
            if remove:
                z.unlink()
        else:
            prof = catalog.BY_ID.get(pid)
            if prof:
                meta = {k: prof[k] for k in ("id", "name", "target", "repo", "base", "license", "ctx", "image_max_tokens")}
                (d / "model.json").write_text(json.dumps(meta, indent=1))
            print(f"  Ready: {d}")
    return ok


def get_release(pids, keep=False):
    """Download the model parts of this version's GitHub release and unpack them."""
    from aicad import __version__
    tag = f"v{__version__}"
    base = f"https://github.com/{RELEASE_REPO}/releases/download/{tag}"
    tmp = ROOT / "downloads" / "release"
    tmp.mkdir(parents=True, exist_ok=True)
    print(f"  Release {tag} of github.com/{RELEASE_REPO}")
    sf = tmp / "SHA256SUMS.txt"
    download(f"{base}/SHA256SUMS.txt", sf)
    sums = _sums(sf.read_text())
    ok = True
    for pid in pids:
        names = sorted(n for n in sums if (m := PART.search(n)) and m["pid"] == pid)
        if not names:
            print(f"  The release has no parts for '{pid}'. Profiles in it: "
                  + ", ".join(sorted({PART.search(n)["pid"] for n in sums if PART.search(n)})))
            ok = False
            continue
        for name in names:
            z = tmp / name
            for attempt in range(1, 6):
                try:
                    if not (z.exists() and sha256(z) == sums[name]):
                        print(f"    {name}")
                        if z.exists():
                            z.unlink()
                        download(f"{base}/{name}", z)
                    break
                except Exception as e:  # network errors: resume
                    print(f"\n    interrupted ({e}); retrying in 10 s (attempt {attempt} of 5)")
                    time.sleep(10)
        ok &= install_parts([tmp / n for n in names], sums, remove=not keep)
    return ok


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
    if "--parts" in argv:
        i = argv.index("--parts")
        folder = Path(argv[i + 1]) if i + 1 < len(argv) else ROOT
        zips = sorted(folder.glob("AICAD-*-model-*-part*of*.zip"))
        sf = folder / "SHA256SUMS.txt"
        ok = install_parts(zips, _sums(sf.read_text()) if sf.exists() else None)
        print("\n  All done." if ok else "\n  Not complete - see above.")
        return 0 if ok else 1
    pids = [auto_profile() if a == "auto" else a for a in argv if not a.startswith("--")]
    if "--release" in argv:
        ok = get_release(pids, keep="--keep-parts" in argv)
        print("\n  All done." if ok else "\n  Some parts are missing; run this again to resume.")
        return 0 if ok else 1
    ok = True
    for a in pids:
        ok &= get_profile(a)
    print("\n  All done." if ok else "\n  Some files are missing; run this again to resume.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
