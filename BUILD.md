# Build

**English** · [Italiano](BUILD.it.md)

Gephid is a **native macOS (Apple Silicon)** app. The `.app` is not versioned: rebuild it from
source with `build.sh`.

## macOS: the `.app`

### Requirements
- macOS on Apple Silicon (M1 or newer), macOS 11+.
- [Go](https://go.dev) and the Xcode Command Line Tools (`xcode-select --install`) to compile the launcher.
- Network only for the **first** build (it downloads the embedded Python and the front-end libraries); at runtime the app is 100% offline.
- About 30 GB free for the model, downloaded separately into the HuggingFace cache.

### Commands
```bash
cd Gephid
./build.sh              # creates ./Gephid.app
./build.sh --install    # creates ./Gephid.app and copies it to /Applications
```

### What `build.sh` does (6 steps)
1. **Front-end**: downloads and vendors marked, DOMPurify, html2pdf, KaTeX and the fonts into `src/backend/static/` (no CDN at runtime).
2. **Embedded Python**: downloads the relocatable interpreter from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) into `Gephid.app/Contents/Resources/python` and installs the dependencies (`mlx-vlm pypdf python-docx openpyxl pymupdf ocrmac`). Idempotent: it skips this step if Python is already present.
3. **Go launcher**: `CGO_ENABLED=1 go build` of the Cocoa/WKWebView shell.
4. **Bundle**: assembles `Contents/` (binary, `diffuchat.py`, `page.html`, `static/`, icon, `Info.plist`).
5. **Sign** ad-hoc (`codesign`).
6. **Install** optionally into `/Applications` (with `--install`).

To rebuild the embedded Python from scratch: `rm -rf Gephid.app/Contents/Resources/python`.

### Model
Default `mlx-community/diffusiongemma-26B-A4B-it-8bit` (about 28 GB). It downloads on first launch
into the HuggingFace cache; the path is configurable from the app's Settings.

### Quick dev loop (without rebuilding everything)
- Only `src/backend/diffuchat.py` or `src/backend/page.html`: copy them into
  `Gephid.app/Contents/Resources/`, then `codesign --force --deep --sign - Gephid.app` and relaunch.
  The Go launcher does not need recompiling.
- `src/launcher/main.go`: `cd src/launcher && CGO_ENABLED=1 go build -o /tmp/Gephid .`, copy the
  binary into `Gephid.app/Contents/MacOS/Gephid`, re-sign.
- Backend without the GUI: `~/.venv-mlxvlm/bin/python src/backend/diffuchat.py`, then `curl localhost:8890/...`.

## Windows: the `.exe`

**It does not exist yet, and it is not an option of `build.sh`.** Gephid is tied to macOS by two deep
dependencies:

- **Model runtime**: inference runs via `mlx-vlm`, and [MLX](https://github.com/ml-explore/mlx) is
  Apple's ML framework, exclusive to Apple Silicon. It is not available on Windows. You would need a
  different runtime (PyTorch+CUDA, llama.cpp, ONNX Runtime) and DiffusionGemma in a format supported
  there: in practice the inference backend has to be rewritten.
- **Native shell**: `main.go` uses cgo with Cocoa, WKWebView, Speech and AVFoundation, all Apple
  APIs. On Windows you would need a WebView2-based shell and a rewrite of the menu, file panels and
  dictation.

**Reusable in a possible port**: the UI (`src/backend/page.html`) and most of the backend's HTTP
logic are portable. The model runtime and the native shell change, with packaging via
PyInstaller/Nuitka for the `.exe`.

In short: a Windows `.exe` would be a **separate port**, to plan on its own, not a target of this build.
