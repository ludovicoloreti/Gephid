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
  forms, and a **Stop** button that really interrupts the model. **Regenerate** the last answer,
  **edit** any of your messages. The speed shown (tok/s) counts every generated token, reasoning
  included.
- **Think** (off by default): the model reasons before answering; you watch the reasoning stream,
  then it folds into a one-line "Thought · 8s" you can click to reopen.
- **Agent** (off by default): Gephid can use local tools, none of which touches the network: an exact
  calculator, search inside the chat's documents, and, in a **working folder you choose**, list/read/
  search files and **write** them (always with a preview and an Allow/Deny card). It can also run a
  short **Python or Node** program in a macOS sandbox (no outbound network, writes only to a temp
  folder, 30s limit), again only after you allow it; long-running servers may listen on 127.0.0.1 only.
- **Attachments that stay in the conversation**: attach a document once and ask about it as many
  times as you like.
  - Images: the model sees them (vision). Paste them with ⌘V.
  - Documents: txt, md, source code, PDF, Word, Excel, CSV, eml. Documents too large for the GPU are
    read in chunks and summarized (map-reduce).
  - Scanned PDFs (even mixed text+scan ones): read with on-device OCR — local GLM-OCR by default,
    Apple Vision or an oMLX router selectable from Settings. No network.
- **Nothing is saved unless you ask.** The current chat survives a reload but disappears when you
  quit. **Save chat** (⌘S) keeps it, with its documents, in `~/Library/Application Support/Gephid`;
  **Saved chats** reopens or deletes it.
- **Markdown plus LaTeX and chemistry formulas** (KaTeX); **highlighted code** with a copy button.
- **Export** a whole chat or a single message to MD, TXT, HTML or PDF via the native save panel.
- **Compact to one prompt**: condense the whole conversation into a single prompt you can paste
  elsewhere.
- **Native Mac app**: full menu bar with shortcuts (⌘N ⌘O ⌘S ⌘E ⌘, ⌘+/⌘−), window that remembers its
  size, on-device dictation (offline, opt-in), light/dark/system themes, adjustable reading size,
  English/Italian UI, and **hot-swap** of the model without a restart.

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
or export and compact from the Export menu. Turn on **Think** or **Agent** from the pills next to
the message field when you need them.

Settings (top right): theme, reading size, dictation, denoising steps (quality vs speed), max
response tokens, OCR engine, the agent's **working folder**, the model instructions, and which
**model** to use among those already on your Mac.

## Build from source
The `.app` is not versioned (it is about 1 GB with the embedded Python); rebuild it from source:
```bash
cd Gephid
./build.sh --install      # downloads everything, assembles Gephid.app, installs it to /Applications
```
`build.sh` is idempotent (it reuses an existing embedded Python). Full guide, quick dev loop and a
note on Windows/`.exe`: **[BUILD.md](BUILD.md)**.

## Requirements
- **Apple Silicon** Mac (M1 or newer). Intel Macs are not supported: inference uses MLX, which is Apple Silicon only.
- **macOS 11** or newer.
- **Disk**: about 30 GB free for the model (it lives in `~/.cache/huggingface/hub`).
- **Internet only on first launch** to download the model; everything runs offline afterwards. The
  only other time Gephid touches the network is if *you* press **Settings → Model → Check for
  updates**: it tells you which files would change and how big they are before downloading anything.
  No automatic check at startup.
- To rebuild from source: Go and the Xcode Command Line Tools.

### Memory and which model to use
The model has to fit in unified memory, so the right quant depends on your RAM. The default is the
8-bit build (`mlx-community/diffusiongemma-26B-A4B-it-8bit`, about 26 GB on disk). On Macs with less
RAM, switch to a lighter quant from **Settings → Model** (paste a HuggingFace id or a local folder).
Gephid sizes the usable context to your memory automatically, so on smaller Macs the context simply
gets shorter instead of running out of memory.

| Unified memory | Recommended build | Size on disk | Notes |
|---|---|---|---|
| 64 GB or more | 8-bit (default) | ~26 GB | best quality |
| 48 GB | 8-bit | ~26 GB | works, shorter context |
| 32 GB | 4-bit | ~13 GB | 8-bit does not fit comfortably |
| 24 GB | 4-bit | ~13 GB | short context |
| 16 GB | 4-bit, short context | ~13 GB | borderline; a smaller model is the safer choice |

The model is a 26B mixture-of-experts with 4B active parameters: it is fast for its size, but all the
weights stay resident, so what matters for memory is the full quant size, not the active 4B.

## License
[MIT](LICENSE). Use, modify and redistribute it freely.
