# AI models

One folder per model, each with the model weights (`*.gguf`, possibly split
into shards `...-00001-of-00010.gguf`) and the vision projector
(`mmproj-*.gguf`). The program finds every folder here by itself; Settings →
*Installed AI models* lists them.

| Folder | Model | For | Size |
|---|---|---|---|
| `qwen3.6-27b-q6` | Qwen3.6-27B, Q6_K | 48 GB GPU (RTX 6000 Ada) | 23.5 GB |
| `qwen3.6-27b-q4` | Qwen3.6-27B, Q4_K_M | 24 GB GPU (RTX 4090) | 17.7 GB |
| `qwen3.6-35b-a3b-q4` | Qwen3.6-35B-A3B, Q4_K_M | 48 GB GPU, faster | 23.0 GB |
| `qwen3.6-35b-a3b-iq2` | Qwen3.6-35B-A3B, IQ2_XXS | 12-16 GB GPU or CPU | 11.4 GB |
| `qwen3.5-9b-q4` | Qwen3.5-9B, Q4_K_M | 8-16 GB GPU or CPU | 6.6 GB |
| `qwen3.5-4b` | Qwen3.5-4B, Q4_K_M | CPU trial | 3.4 GB |

Three ways to fill this folder:

1. **Release parts** (no tools needed): download every
   `AICAD-<version>-model-<profile>-partNNofMM.zip` of one profile from the
   GitHub release and unzip all of them where the offline package was
   unzipped - each part holds `AICAD-<version>/models/<profile>/...`. Or put
   the parts next to `3_GET_AI_MODEL.bat` with the release's
   `SHA256SUMS.txt` and choose *20* in its menu: every part is checked
   before it is unpacked.
2. **`3_GET_AI_MODEL.bat`** on a PC with internet: downloads from Hugging
   Face (choices 1-8) or the release parts from GitHub (11-13), resumes after
   an interruption and checks every file against its SHA-256 digest.
3. **Any other GGUF vision model**: put the model file and its `mmproj` file
   into a new folder here and choose it on the AI tab.
