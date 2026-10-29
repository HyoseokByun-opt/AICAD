"""Fetch everything the offline package needs (run once on a PC with internet).

    python tools/build_offline.py

    runtime/   python-3.11.9-embed-amd64.zip (python.org)
    wheels/    every package for CPython 3.11 / Windows x64 (PyPI)
    engine/    llama.cpp builds: cuda (12.4), vulkan, cpu (GitHub releases)

Any Python 3.8+ with pip can run this; the packages are downloaded for the
bundled runtime, not for the Python that runs the script.
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_EMBED = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"


def main():
    rt = ROOT / "runtime"
    rt.mkdir(exist_ok=True)
    z = rt / PY_EMBED.rsplit("/", 1)[1]
    if not z.exists():
        print("runtime:", z.name)
        urllib.request.urlretrieve(PY_EMBED, z)
    wh = ROOT / "wheels"
    wh.mkdir(exist_ok=True)
    print("wheels: downloading for CPython 3.11, win_amd64 ...")
    cmd = [sys.executable, "-m", "pip", "download", "--python-version", "3.11", "--platform", "win_amd64",
           "--only-binary=:all:", "-d", str(wh), "-r", str(ROOT / "requirements-offline.txt"),
           "-c", str(ROOT / "constraints-offline.txt"), "pip"]
    subprocess.check_call(cmd)
    sys.path.insert(0, str(ROOT / "tools"))
    import get_model
    get_model.get_engine()
    print("Done. Run 1_INSTALL_OFFLINE.bat to install, 3_GET_AI_MODEL.bat for a model.")


if __name__ == "__main__":
    main()
