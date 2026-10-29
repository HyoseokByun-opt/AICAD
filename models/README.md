# AI models

One folder per model, each with the model weights (`*.gguf`) and the vision
projector (`mmproj-*.gguf`). `3_GET_AI_MODEL.bat` downloads them from Hugging
Face and checks every file against its SHA-256 digest:

| Folder | Model | For | Download |
|---|---|---|---|
| `qwen3.6-27b-q6` | Qwen3.6-27B, Q6_K | 48 GB GPU (RTX 6000 Ada) | 23.5 GB |
| `qwen3.6-27b-q4` | Qwen3.6-27B, Q4_K_M | 24 GB GPU (RTX 4090) | 17.7 GB |
| `qwen3.6-35b-a3b-q4` | Qwen3.6-35B-A3B, Q4_K_M | 48 GB GPU, faster | 23.0 GB |
| `qwen3.5-9b-q4` | Qwen3.5-9B, Q4_K_M | 8-16 GB GPU or CPU | 6.6 GB |
| `qwen3.5-4b` | Qwen3.5-4B, Q4_K_M | CPU trial | 3.4 GB |

Any other GGUF vision model can be used: put the model file and its
`mmproj` file into a new folder here and choose it on the AI tab.
