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
│   │   ├── diffuchat.py      # backend: HTTP server + model worker + agent loop
│   │   ├── channels.py       # splits the model stream: answer / thought / tool calls
│   │   ├── agent.py          # agent tools: calculator, doc search, working-folder files, code sandbox
│   │   ├── store.py          # chats saved ON REQUEST (nothing is saved by default)
│   │   ├── page.html         # UI (HTML/CSS/JS), re-read from disk when it changes
│   │   └── static/           # vendored libraries: marked, DOMPurify, highlight.js, KaTeX (+ mhchem) + fonts
│   └── launcher/
│       ├── main.go           # Go shell + WKWebView + cgo (menu, file/save panel, dictation)
│       └── go.mod go.sum logo.svg
├── tests/                    # pytest: pure functions, sandbox, path confinement (no model needed)
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
   `src/backend/*.py` + `page.html` + `static/` + `icon.icns` + `build-info`. Ad-hoc signed.

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
- **Real streaming = `_run_generation`**: for DiffusionGemma, mlx-vlm runs the model's own diffusion
  generator, which buffers every result until the end unless it gets an `on_result` callback (true
  for 0.6.x and 0.7.x). Through plain `stream_generate` the text appeared only when generation
  finished and Stop could not interrupt it. `_run_generation` passes `on_result`: text arrives block
  by block and returning `False` stops the model at the next block. It relies on the private
  `dispatch._prepare_generation_inputs` and falls back to `stream_generate` if that changes: re-check
  after every mlx-vlm bump.
- **tok/s** is the library's `generation_tps`: every generated token (reasoning included), prompt
  reading excluded.
- **Model output channels**: the template always opens a thought channel (`<|channel>thought …
  <channel|>`, empty when thinking is off) and wraps tool calls in `<|tool_call> … <tool_call|>`.
  Every generation goes through `ChannelSplitter`: never print model output that skipped it.
- **Instructions and documents in the `system` turn**: the pre-prompt and the chat's documents form a
  stable prefix; the frontend resends ALL the chat's attachment ids on every turn (a document attached
  at turn 1 must still count at turn 5). Attachments live in RAM only (LRU); after a backend restart
  the UI asks to re-attach instead of answering without them. mlx-vlm 0.7.4's prefix cache does not
  engage with DiffusionGemma (verified), so long documents are re-read each turn.
- **Nothing is saved unless asked**: the current chat lives in `sessionStorage`; only "Save chat"
  writes to `~/Library/Application Support/Gephid/chats`.
- **Agent safety**: tool output is untrusted. File tools resolve the path the model gives
  ("Scrivania", `~/Downloads/x.pdf`, ...) inside the home only, never `~/Library` or hidden folders
  (`resolve_user_path`, symlinks resolved); the first read of a folder asks the user in the chat and the
  grant lives in RAM for the session (`GRANTS`, plus the optional always-allowed folder); the agent can
  only create NEW files, never modify, overwrite or delete; writing and running code always need the user's click
  (`/api/agent/confirm`, 300s without an answer = deny). Code runs under `sandbox-exec`: no outbound
  connections at all, not even to localhost (otherwise it could drive Gephid's own API), no DNS,
  LaunchServices or Apple Events, no exec of anything but the interpreter (no `rm`, shell, `osascript`),
  no signals to other processes, writes only in its temp folder, secrets unreadable, 30s timeout. A
  server it starts stays reachable from outside, but a process group listening beyond 127.0.0.1 is
  killed (`lsof` check); leftovers are cleaned up when the backend starts and when Gephid quits.
- **WKWebView**: it cannot download via blob → server-side save (`/api/save`, `~/Downloads` or the
  path chosen in the native save panel, home only). `<input type=file>` does not open the picker → `gephidOpenFiles` (NSOpenPanel via bind);
  native panels steal focus, so restore it with `inp.focus()` on return. `alert()/confirm()` do not
  work.
- **cgo + ARC**: the cgo block is compiled with `-fobjc-arc` (without it, dictation stored an
  autorelease `NSString` in a static → use-after-free → crash). Do not remove it.
- **Block diffusion**: the model generates 256-token "canvases" and refines them over `steps`
  (denoising). Low step counts degenerate into repetition on long text → `STEP_MIN=16`, default 48;
  the `_degenerate` guard stops pathological repetition. Frontend: typewriter (rAF) with markdown
  rendered live and the diffusion visible as the block forms.
- **Runtime**: `mlx-vlm` only (`mlx-lm` gives `Model type diffusion_gemma not supported`); test venv
  `~/.venv-mlxvlm`. Speed (M5 Max, mlx-vlm 0.7.4, 40 steps): ~89 tok/s on a long answer,
  first text after the first block (~2.4s), ~135 tok/s with Think. Default model
  `mlx-community/diffusiongemma-26B-A4B-it-8bit` (~28GB).

## API (on 127.0.0.1:8890)
`GET /` UI · `GET /api/health` · `GET /api/models` · `GET /api/config` ·
`GET /static/...` · `POST /api/chat` (NDJSON streaming, `attach`=ALL the chat's attachment ids) · `POST /api/compact`
(streaming) · `POST /api/ingest` (file→image/doc, OCR for scanned pages — also in mixed PDFs;
`cancel_token` to abort) · `POST /api/ingest/cancel` · `POST /api/save` (`~/Downloads` by default;
`path` from the native panel, home-only) · `POST /api/config` (steps/maxtok/ocr/pre-prompt, immediate
effect) · `POST /api/reload` (hot model reload) · `POST /api/download` (downloads/updates the model;
the reported total is the delta) · `POST /api/download/pause` · `POST /api/model/check` (local
revision vs HuggingFace) · `GET /api/chats` · `POST /api/chats/save|get|delete` (saved chats) ·
`POST /api/agent/confirm` (allow/deny a tool action) · `GET /api/agent/procs` · `POST /api/agent/stop`.
`/api/chat` also takes `think` (reasoning) and `agent` (tools) and streams `thought`, `agent`,
`confirm` and `procs` events.

The network is used **only** by `/api/download` and `/api/model/check`, both on an explicit user
action: there is no automatic check at startup. No agent tool touches the network.

## Features
Streaming + stop · per-session memory (window + cumulative summary) · compact to one prompt · export
MD/TXT/HTML/PDF · markdown + LaTeX/chemistry (KaTeX) · themes · attachments: images (vision),
documents txt/md/code/PDF/Word/Excel/CSV (extraction + map-reduce for large ones), scanned pages via
OCR (3 engines: in-process GLM-OCR by default, Apple Vision, oMLX router; vision as last fallback) ·
opt-in on-device dictation · Think (visible reasoning) · Agent (local tools) · chats saved only on
request · regenerate/edit · highlighted code · native menus with shortcuts.

## Build
`./build.sh` assembles `Gephid.app`; `./build.sh --install` also installs it to /Applications. It
downloads python-build-standalone, runs `pip install` with PINNED versions (mlx-vlm, pypdf,
python-docx, openpyxl, pymupdf, ocrmac) plus the pinned JS libraries, compiles the Go, assembles and
signs ad-hoc. Two stamp files — `static/.versions` and `Resources/python/.gephid-deps` — make the
pins effective: a changed pin triggers re-vendoring or a reinstall, an unchanged one skips everything
(idempotent, ~4s). To redo from scratch:
`rm -rf Gephid.app/Contents/Resources/python src/backend/static`. Details in [BUILD.md](BUILD.md).

## Requirements
macOS Apple Silicon, ~30GB free for the model (in `~/.cache/huggingface/hub`), Go + Xcode CLT to
rebuild. Default model: `mlx-community/diffusiongemma-26B-A4B-it-8bit`.
