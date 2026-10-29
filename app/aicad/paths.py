"""Folder layout of an AICAD installation and the user settings file.

    <root>/app        program (this package, the web server)
    <root>/python     the offline Python runtime (1_INSTALL_OFFLINE.bat)
    <root>/engine     llama.cpp builds: cuda/, vulkan/, cpu/
    <root>/models     one folder per model: *.gguf and mmproj-*.gguf
    <root>/workspace  projects (default; can be moved in Settings)
    <root>/examples   example drawings and descriptions
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("AICAD_ROOT", APP_DIR.parent)).resolve()
ENGINE_DIR = ROOT / "engine"
MODELS_DIR = Path(os.environ.get("AICAD_MODELS", ROOT / "models")).resolve()
EXAMPLES_DIR = ROOT / "examples"
SETTINGS_FILE = ROOT / "settings.json"

DEFAULTS = {
    "workspace": str(ROOT / "workspace"),
    "engine": "auto",            # auto | cuda | vulkan | cpu
    "model": "auto",             # folder name under models/ or "auto"
    "ctx": 0,                    # 0 = from the model profile
    "gpu_layers": "auto",        # auto (fit to memory) or a number
    "threads": 0,                # 0 = llama.cpp default
    "image_max_tokens": 0,       # 0 = from the model profile
    "think_read": True,          # reason before answering, per stage
    "think_code": True,
    "think_repair": False,
    "think_edit": True,
    "think_budget": 8192,        # tokens of reasoning per answer (0 = unlimited)
    "repair_attempts": 4,
    "refine_rounds": 2,
    "mesh_quality": "standard",  # coarse | standard | fine
    "idle_minutes": 0,           # stop the AI engine after this idle time (0 = never)
    "step_schema": "AP214",
    "density": 7.85,             # g/cm3 for the mass shown in the inspector
}

_lock = threading.Lock()


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def save_settings(changes: dict) -> dict:
    with _lock:
        s = load_settings()
        for k, v in changes.items():
            if k in DEFAULTS:
                s[k] = v
        try:
            SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
        except OSError:
            pass
        return s


def workspace() -> Path:
    p = Path(load_settings()["workspace"]).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p
