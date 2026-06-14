# Gephid

**English** · [Italiano](README.it.md)

![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Apple%20Silicon-000000?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Go](https://img.shields.io/badge/Go-1.26-00ADD8?logo=go&logoColor=white)
![runtime](https://img.shields.io/badge/runtime-MLX-FF6F00)
![model](https://img.shields.io/badge/model-DiffusionGemma-4169E1)
![offline](https://img.shields.io/badge/network-100%25%20offline-2E7D32)
![packaging](https://img.shields.io/badge/packaging-self--contained%20.app-555555)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Native **macOS** chat for **DiffusionGemma**, ChatGPT-style, **100% offline**, in a single
double-clickable app. The diffusion model runs locally on your Mac (Apple Silicon).

## What it is
- Self-contained `.app` (Python + libraries all bundled). The only external piece is the **model**
  (downloaded into the HuggingFace cache, configurable from Settings).
- No internet: no network calls, server bound to `127.0.0.1` only.

## Features
- **Streaming chat** with markdown rendered as it types and a **Stop** button.
- **Conversation memory** (automatic summary so the context doesn't overflow).
- **Attachments**: images (the model *sees* them), documents **txt/md/code/PDF/Word/Excel/CSV**
  (text extraction + token count); documents too large for the GPU are read in chunks and
  summarized; **scanned PDFs** are read via **OCR** (Apple Vision, offline).
- **Markdown + LaTeX/chemistry formulas** (KaTeX).
- **Export** of chats and single messages to **MD/TXT/HTML/PDF** (saved to ~/Downloads).
- **Compact to 1 prompt**: condenses the chat into a single prompt to paste elsewhere.
- **On-device dictation** (offline), enabled from Settings.
- Light/dark/system themes. **Hot-swap** the model (no restart).

## Usage
Open **Gephid** (from `/Applications` or double-click the `.app`). On first launch the model loads
(~15–30s). Type, attach files with the paperclip, export or compact from each message's menu.

Settings (top icon): theme, dictation, denoising steps (quality↔speed), max tokens, and model
selection among those already on your Mac.

## Build from source
The `.app` isn't versioned: rebuild it from source.
```bash
cd Gephid
./build.sh --install      # downloads everything, assembles Gephid.app and installs it to /Applications
```
Full guide (steps, quick dev loop, note on Windows/`.exe`): **[BUILD.md](BUILD.md)**.
Architecture and technical details: `CLAUDE.md`.

## Requirements
macOS Apple Silicon · ~30 GB free for the model · (to rebuild: Go + Xcode Command Line Tools).

## License
[MIT](LICENSE) — use, modify and redistribute it freely.
