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
double-clickable app. The diffusion model runs locally on your Mac (Apple Silicon) and nothing
leaves your computer.

## What it is
- A self-contained `.app`: the Python runtime and every library are bundled inside. The only
  external piece is the **model weights**, downloaded once into the HuggingFace cache and
  configurable from Settings.
- No internet at runtime: no network calls, no account, no telemetry. The local server binds to
  `127.0.0.1` only.

## Features
- **Streaming chat** with markdown rendered as it types, a live view of the diffusion as each block
  forms, and a **Stop** button.
- **Conversation memory**: a rolling window plus an automatic running summary, so long chats never
  overflow the context.
- **Attachments**:
  - Images: the model sees them (vision).
  - Documents: txt, md, source code, PDF, Word, Excel, CSV. Text is extracted and token-counted;
    documents too large for the GPU are read in chunks and summarized (map-reduce).
  - Scanned PDFs: read with on-device OCR (Apple Vision), no network.
- **Markdown plus LaTeX and chemistry formulas** (KaTeX).
- **Export** of a whole chat or a single message to MD, TXT, HTML or PDF (saved to `~/Downloads`).
  PDF and HTML carry a header (model used, export date) and a per-page footer.
- **Compact to one prompt**: condense the whole conversation into a single prompt you can paste
  elsewhere.
- **On-device dictation** (offline), opt-in from Settings.
- **Adjustable reading size**, light/dark/system themes, and **hot-swap** of the model without a
  restart.

## How it works
A small **Go launcher** opens a native window (WKWebView), starts the **Python backend** as a
subprocess, shows a loading screen until the model is ready, then points the window at the local UI.
The backend (`127.0.0.1:8890`) loads the diffusion model via MLX and serves both the interface and
the API. The launcher supervises the backend, restarts it if it ever stops, and shuts it down when
the last window closes. Technical details: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Usage
Open **Gephid** (from `/Applications`, or by double-clicking the `.app`). The window appears right
away with a loading screen while the model loads into memory (a few seconds; longer on the very
first launch if it still needs to download the weights). Then type, attach files with the paperclip,
or export and compact from each message's menu.

Settings (top right): theme, reading size, dictation, denoising steps (quality vs speed), max
response tokens, OCR engine, and which **model** to use among those already on your Mac.

## Build from source
The `.app` is not versioned (it is about 1 GB with the embedded Python); rebuild it from source:
```bash
cd Gephid
./build.sh --install      # downloads everything, assembles Gephid.app, installs it to /Applications
```
`build.sh` is idempotent (it reuses an existing embedded Python). Full guide, quick dev loop and a
note on Windows/`.exe`: **[BUILD.md](BUILD.md)**.

## Requirements
- macOS on Apple Silicon (M1 or newer).
- About 30 GB free for the model weights (in `~/.cache/huggingface/hub`).
- To rebuild from source: Go and the Xcode Command Line Tools.

Default model: `mlx-community/diffusiongemma-26B-A4B-it-8bit` (about 28 GB).

## License
[MIT](LICENSE). Use, modify and redistribute it freely.
