"""Model profiles: which open model runs on which graphics card.

All models are open-weight vision-language models from Hugging Face in GGUF
form for llama.cpp. The SHA-256 digests are those of the Hugging Face files
and are checked after download (tools/get_model.py).

Memory needed = weights + vision projector + context (KV cache) + about
1.5 GB of work buffers. The 27B dense model is the strongest one that fits
both a 48 GB and a 24 GB card; the quantisation is chosen per card.
"""
from __future__ import annotations

PROFILES = [
    {
        "id": "qwen3.6-27b-q6",
        "name": "Qwen3.6-27B · Q6_K",
        "target": "48 GB GPU (RTX 6000 Ada / A6000 Ada)",
        "min_vram_gb": 30, "ctx": 65536, "image_max_tokens": 4096, "rank": 100,
        "repo": "unsloth/Qwen3.6-27B-GGUF", "base": "Qwen/Qwen3.6-27B", "license": "Apache-2.0",
        "files": [
            ["Qwen3.6-27B-Q6_K.gguf", 22523238624, "ec1805fe87e6519c461c1ed2d179865464a875ed241032ead65a354f979cfe14"],
            ["mmproj-F16.gguf", 927607360, "eacf610d1ee4bd5ed0197a0777dd8f4fceb8eefa27009067c7d496cb68fbde45"],
        ],
    },
    {
        "id": "qwen3.6-27b-q4",
        "name": "Qwen3.6-27B · Q4_K_M",
        "target": "24 GB GPU (RTX 4090)",
        "min_vram_gb": 20, "ctx": 32768, "image_max_tokens": 3072, "rank": 90,
        "repo": "unsloth/Qwen3.6-27B-GGUF", "base": "Qwen/Qwen3.6-27B", "license": "Apache-2.0",
        "files": [
            ["Qwen3.6-27B-Q4_K_M.gguf", 16817244384, "5ed60d0af4650a854b1755bd392f9aef4872643dc25a254bc68043fa638392a0"],
            ["mmproj-F16.gguf", 927607360, "eacf610d1ee4bd5ed0197a0777dd8f4fceb8eefa27009067c7d496cb68fbde45"],
        ],
    },
    {
        "id": "qwen3.6-35b-a3b-q4",
        "name": "Qwen3.6-35B-A3B · Q4_K_M (fast, mixture of experts)",
        "target": "48 GB GPU, optional: faster, slightly weaker than the 27B",
        "min_vram_gb": 28, "ctx": 65536, "image_max_tokens": 4096, "rank": 80,
        "repo": "unsloth/Qwen3.6-35B-A3B-GGUF", "base": "Qwen/Qwen3.6-35B-A3B", "license": "Apache-2.0",
        "files": [
            ["Qwen3.6-35B-A3B-UD-Q4_K_M.gguf", 22134528992, "ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61"],
            ["mmproj-F16.gguf", 899283680, "8971ee4f331ff0a4c609374f32984b3d4e6dc086c0aa35f1d637fad1829e887f"],
        ],
    },
    {
        "id": "qwen3.5-9b-q4",
        "name": "Qwen3.5-9B · Q4_K_M",
        "target": "8-16 GB GPU, or CPU (slow)",
        "min_vram_gb": 9, "ctx": 32768, "image_max_tokens": 2048, "rank": 50,
        "repo": "unsloth/Qwen3.5-9B-GGUF", "base": "Qwen/Qwen3.5-9B", "license": "Apache-2.0",
        "files": [
            ["Qwen3.5-9B-Q4_K_M.gguf", 5680522464, "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"],
            ["mmproj-F16.gguf", 918166080, "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f"],
        ],
    },
    {
        "id": "qwen3.5-4b",
        "name": "Qwen3.5-4B · Q4_K_M",
        "target": "CPU only / trial (limited accuracy)",
        "min_vram_gb": 0, "ctx": 16384, "image_max_tokens": 1280, "rank": 30,
        "repo": "unsloth/Qwen3.5-4B-GGUF", "base": "Qwen/Qwen3.5-4B", "license": "Apache-2.0",
        "files": [
            ["Qwen3.5-4B-Q4_K_M.gguf", 2740937888, "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"],
            ["mmproj-F16.gguf", 672423616, "cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864"],
        ],
    },
]
BY_ID = {p["id"]: p for p in PROFILES}


def for_vram(vram_gb: float | None) -> dict:
    """The recommended profile for a card with this much memory."""
    v = vram_gb or 0
    for p in sorted(PROFILES, key=lambda p: -p["rank"]):
        if p["id"] == "qwen3.6-35b-a3b-q4":
            continue  # optional, never the default
        if v >= p["min_vram_gb"]:
            return p
    return BY_ID["qwen3.5-4b"]


def hf_url(repo: str, fname: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{fname}"
