# Gephid architecture

**English** · [Italiano](ARCHITECTURE.it.md)

A native macOS (Apple Silicon) app that gives DiffusionGemma a ChatGPT-style chat, 100% offline,
wrapped in a single `.app`. The model stays external and configurable.
Name: **Ge**mma + **diffusion**.

## Layout
```
Gephid/
├── build.sh                  # builds the .app from scratch
├── BUILD.md / BUILD.it.md    # build guide (.app; note on Windows/.exe)
├── README.md / README.it.md  # this guide in both languages
├── ARCHITECTURE.md / .it.md  # this document
├── LICENSE
├── assets/icon.icns          # icon (royalblue padlock, tilted 13.37 degrees)
├── src/
│   ├── backend/
│   │   ├── diffuchat.py       # backend: HTTP server + model
│   │   ├── page.html         # UI (HTML/CSS/JS), served from disk on every request
│   │   └── static/           # vendored libraries: marked, DOMPurify, html2pdf, KaTeX + fonts
│   └── launcher/
│       ├── main.go           # Go shell + WKWebView + cgo (menu, file/save panel, dictation)
│       └── go.mod go.sum logo.svg
└── Gephid.app                # built artifact (~1GB, not versioned: rebuild with build.sh)
```

## Architecture
1. **Go launcher** (`src/launcher/main.go`): opens a WKWebView window, starts the Python backend as
   a subprocess, shows a splash until `/api/health` responds, navigates to `http://127.0.0.1:8890`,
   supervises the backend (restarts it if it dies), and shuts it down when the last window closes.
   cgo/Cocoa provides the native menu, file/save panels and on-device dictation (Speech +
   AVFoundation).
2. **Python backend** (`src/backend/diffuchat.py`): `ThreadingHTTPServer` on `127.0.0.1:8890`. Loads
   the model via `mlx-vlm` and serves the UI and the API. The UI lives in `page.html`, re-read from
   disk on every request.
3. **`.app` bundle**: embedded Python (`Contents/Resources/python`, from python-build-standalone) +
   `diffuchat.py` + `page.html` + `static/` + `icon.icns`. Ad-hoc signed.

## Constraints not to reintroduce
- **Model thread**: MLX wants the model ops on the thread that loaded the weights. So
  `serve_forever()` runs on a daemon thread and the main thread acts as the worker (`_model_worker`,
  consuming `JOBS`). HTTP handlers never touch the model: they enqueue a `Job` and stream its events
  (`stream_job`). On another thread you get `no Stream(gpu) in current thread`.
- **Startup**: the model loads in `__main__` with `load_model()`, after the server starts and on the
  main thread. This way `/api/health` responds immediately (`model_ok=false`) and the window appears
  in ~1s with a loading overlay, instead of waiting on the ~28GB. Do not move `load()` back to
  import time.
- **GPU memory**: the diffusion model uses bidirectional attention, so a single buffer grows ~seq²
  (≈32 bytes/token²). The limit is not the context window (256K) but the GPU's `max_buffer_length`.
  `SAFE_SEQ` (derived from `mx.device_info()` at each startup) keeps `prompt+output` under that
  limit; `DOC_CTX` derives from it. Larger documents are compressed with map-reduce
  (`build_doc_context` → `map_reduce_summarize`), not passed raw.
- **Embedded Python, not the system one**: Homebrew's framework Python launched from the GUI hangs at
  startup. You need the relocatable python-build-standalone executable, with a clean env (`cmd.Env`).
- **100% offline**: `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`; JS libraries in `/static`; bind to
  `127.0.0.1`; `Origin` + `Host` header checks (anti-CSRF / anti DNS-rebinding). Fail-safe rendering:
  markdown only if `marked` and `DOMPurify` are present, otherwise raw text.
- **WKWebView**: it cannot download via blob → server-side save (`/api/save`, into `~/Downloads`
  only). `<input type=file>` does not open the picker → `gephidOpenFiles` (NSOpenPanel via bind);
  native panels steal focus, so restore it with `inp.focus()` on return. `alert()/confirm()` do not
  work.
- **cgo + ARC**: the cgo block is compiled with `-fobjc-arc` (without it, dictation stored an
  autorelease `NSString` in a static → use-after-free → crash). Do not remove it.
- **Block diffusion**: the model generates 256-token "canvases" and refines them over `steps`
  (denoising). Low step counts degenerate into repetition on long text → `STEP_MIN=16`, default 48;
  the `_degenerate` guard stops pathological repetition. Frontend: typewriter (rAF) with markdown
  rendered live and the diffusion visible as the block forms.
- **Runtime**: `mlx-vlm` only (`mlx-lm` gives `Model type diffusion_gemma not supported`); test venv
  `~/.venv-mlxvlm`. Speed (M5 Max): 8 steps ≈ 44 tok/s, 16 ≈ 104 tok/s. Default model
  `mlx-community/diffusiongemma-26B-A4B-it-8bit` (~28GB).

## API (on 127.0.0.1:8890)
`GET /` UI · `GET /api/health` · `GET /api/models` · `GET /api/config` · `GET /static/...` ·
`POST /api/chat` (NDJSON streaming, `attach`=image/doc ids) · `POST /api/compact` (streaming) ·
`POST /api/ingest` (file→image/doc, OCR for scanned PDFs) · `POST /api/save` ·
`POST /api/config` (steps/maxtok, immediate effect) · `POST /api/reload` (hot model reload).

## Features
Streaming + stop · per-session memory (window + cumulative summary) · compact to one prompt · export
MD/TXT/HTML/PDF · markdown + LaTeX/chemistry (KaTeX) · themes · attachments: images (vision),
documents txt/md/code/PDF/Word/Excel/CSV (extraction + map-reduce for large ones), scanned PDFs via
Apple Vision OCR with a vision fallback · opt-in on-device dictation.

## Build
`./build.sh` assembles `Gephid.app`; `./build.sh --install` also installs it to /Applications. It
downloads python-build-standalone, runs `pip install` (mlx-vlm, pypdf, python-docx, openpyxl,
pymupdf, ocrmac) and the JS libraries, compiles the Go, assembles and signs ad-hoc. Idempotent (it
reuses an existing Python; to redo from scratch: `rm -rf Gephid.app/Contents/Resources/python`).
Details in [BUILD.md](BUILD.md).

## Requirements
macOS Apple Silicon, ~30GB free for the model (in `~/.cache/huggingface/hub`), Go + Xcode CLT to
rebuild. Default model: `mlx-community/diffusiongemma-26B-A4B-it-8bit`.
