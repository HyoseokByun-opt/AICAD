"""Build the offline release package.

    python tools/make_release.py

writes release/AICAD-<version>-offline-win64.zip and SHA256SUMS.txt. The zip
holds the program, the examples, the Python runtime, all wheels and the
three llama.cpp engines; the AI models are downloaded separately
(3_GET_AI_MODEL.bat) because they are larger than a release asset may be.
"""
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from aicad import __version__  # noqa: E402

TOP_FILES = ["README.md", "LICENSE", "CITATION.cff", "requirements-offline.txt", "constraints-offline.txt",
             "_common.bat", "1_INSTALL_OFFLINE.bat", "2_RUN_AICAD.bat", "3_GET_AI_MODEL.bat",
             "4_SELF_TEST.bat", "5_RUN_SERVER.bat"]
DIRS = ["app", "tools", "examples", "docs", "runtime", "wheels", "engine/cuda", "engine/vulkan", "engine/cpu"]
SKIP_PARTS = {"__pycache__", "pyrt", "_build", "logs"}


def files():
    for f in TOP_FILES:
        p = ROOT / f
        if p.exists():
            yield p
    yield ROOT / "models" / "README.md"
    for d in DIRS:
        base = ROOT / d
        if not base.exists():
            raise SystemExit(f"missing {d}/ - run tools/build_offline.py first")
        for p in sorted(base.rglob("*")):
            if p.is_file() and not (SKIP_PARTS & set(p.relative_to(ROOT).parts)) and p.suffix != ".pyc":
                yield p


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    out = ROOT / "release"
    out.mkdir(exist_ok=True)
    name = f"AICAD-{__version__}-offline-win64"
    z = out / f"{name}.zip"
    n = 0
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for p in files():
            rel = p.relative_to(ROOT).as_posix()
            # already-compressed files are stored
            ct = zipfile.ZIP_STORED if p.suffix.lower() in (".whl", ".zip", ".png", ".jpg") else zipfile.ZIP_DEFLATED
            zf.write(p, f"{name}/{rel}", compress_type=ct)
            n += 1
    size = z.stat().st_size
    print(f"{z.name}: {n} files, {size / 1e9:.2f} GB")
    if size > 2 * 1024 ** 3:
        print("WARNING: larger than the 2 GiB limit of a release asset")
    sums = [f"{sha256(z)}  {z.name}"]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    print("\n".join(sums))


if __name__ == "__main__":
    main()
