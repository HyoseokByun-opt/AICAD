"""Pack AI models as release parts below GitHub's 2 GiB limit per file.

    python tools/make_model_parts.py qwen3.6-27b-q4 qwen3.6-27b-q6 [--keep]

The model file is split with llama.cpp's gguf-split into shards
(Qwen3.6-27B-Q4_K_M-00001-of-00010.gguf, ...) that llama-server loads as
one model, and every shard goes into a zip of its own:

    release/AICAD-<version>-model-<profile>-part01of10.zip
        AICAD-<version>/models/<profile>/<shard>.gguf

The vision projector and the model licence go into the part with the
smallest shard (or into one more part). Unzipped where the offline package
was unzipped, all parts of a profile give a working models/<profile>/
folder; tools/get_model.py --release does the same and checks every part.
The SHA-256 of every part is added to release/SHA256SUMS.txt. The shards
are removed after zipping; with --keep the original model is kept too.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from aicad import __version__, catalog  # noqa: E402

LIMIT = 2_000_000_000          # bytes per part (GitHub's limit is 2 GiB = 2 147 483 648)
SHARD = "1850M"                # gguf-split maximum shard size
SPLIT = ROOT / "engine" / "cpu" / "llama-gguf-split.exe"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def licence_text(prof) -> str:
    url = f"https://huggingface.co/{prof['base']}/resolve/main/LICENSE"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - the licence is named in any case
        return (f"{prof['base']} is released under the {prof['license']} licence.\n"
                f"See https://huggingface.co/{prof['base']}\n")


def pack(pid: str, keep: bool) -> list[Path]:
    prof = catalog.BY_ID[pid]
    src = ROOT / "models" / pid
    model, mmproj = src / prof["files"][0][0], src / prof["files"][1][0]
    for f, entry in ((model, prof["files"][0]), (mmproj, prof["files"][1])):
        if not f.exists() or f.stat().st_size != entry[1]:
            raise SystemExit(f"{f} is missing or incomplete - run tools/get_model.py {pid} first")
    work = ROOT / "release" / "shards" / pid
    work.mkdir(parents=True, exist_ok=True)
    prefix = work / model.stem
    if not list(work.glob(f"{model.stem}-*-of-*.gguf")):
        print(f"  splitting {model.name} ({model.stat().st_size / 1e9:.1f} GB) ...", flush=True)
        subprocess.run([str(SPLIT), "--split", "--split-max-size", SHARD, str(model), str(prefix)], check=True,
                       stdout=subprocess.DEVNULL)
    shards = sorted(work.glob(f"{model.stem}-*-of-*.gguf"))
    lic = work / f"LICENSE-{pid}.txt"
    lic.write_text(f"{prof['name']}\nBase model: https://huggingface.co/{prof['base']} ({prof['license']})\n"
                   f"GGUF conversion: https://huggingface.co/{prof['repo']}\n\n" + licence_text(prof), encoding="utf-8")
    # the projector and the licence ride with the smallest shard if they fit, else in a part of their own
    extra = [mmproj, lic]
    extra_size = sum(f.stat().st_size for f in extra)
    groups = [[s] for s in shards]
    small = min(range(len(groups)), key=lambda i: groups[i][0].stat().st_size)
    if groups[small][0].stat().st_size + extra_size <= LIMIT:
        groups[small] += extra
    else:
        groups.append(extra)
    n = len(groups)
    out, top = [], f"AICAD-{__version__}"
    for i, g in enumerate(groups, 1):
        z = ROOT / "release" / f"AICAD-{__version__}-model-{pid}-part{i:02d}of{n:02d}.zip"
        print(f"  {z.name}: {', '.join(f.name for f in g)}", flush=True)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
            for f in g:
                zf.write(f, f"{top}/models/{pid}/{f.name}")
        if z.stat().st_size > 2 * 1024 ** 3:
            raise SystemExit(f"{z.name} is larger than 2 GiB")
        with zipfile.ZipFile(z) as zf:
            bad = zf.testzip()
        if bad:
            raise SystemExit(f"{z.name}: damaged entry {bad}")
        for f in g:
            if f.suffix == ".gguf" and f.parent == work:
                f.unlink()
        out.append(z)
    lic.unlink(missing_ok=True)
    if not keep:
        model.unlink()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles", nargs="+")
    ap.add_argument("--keep", action="store_true", help="keep the original model file")
    a = ap.parse_args()
    sums_file = ROOT / "release" / "SHA256SUMS.txt"
    sums = {}
    if sums_file.exists():
        for ln in sums_file.read_text().splitlines():
            if "  " in ln:
                h, n = ln.split("  ", 1)
                sums[n] = h
    for pid in a.profiles:
        print(f"{pid}:")
        for z in pack(pid, a.keep):
            sums[z.name] = sha256(z)
            print(f"    {z.stat().st_size / 1e9:6.2f} GB  {sums[z.name]}")
        sums_file.write_text("".join(f"{h}  {n}\n" for n, h in sorted(sums.items())))
    print(f"written to {ROOT / 'release'}")


if __name__ == "__main__":
    main()
