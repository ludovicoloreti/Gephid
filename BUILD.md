# Build

**English** · [Italiano](BUILD.it.md)

Gephid is a **native macOS (Apple Silicon)** app. The `.app` is not versioned: rebuild it from
source with `build.sh`.

## macOS: the `.app`

### Requirements
- macOS on Apple Silicon (M1 or newer), macOS 14+ for source builds. The minimum OS of the `.app` depends on the MLX wheel selected for the build Mac and is detected and recorded automatically in `Info.plist` (26.2 in the build verified on 2026-10-18).
- [Go](https://go.dev) and the Xcode Command Line Tools (`xcode-select --install`) to compile the launcher.
- Network for the **first** build and dependency updates (it downloads the embedded Python and the front-end libraries); at runtime the app is 100% offline.
- About 30 GB free for the model, downloaded separately into the HuggingFace cache.

### Commands
```bash
cd Gephid
./build.sh              # creates ./dist/Gephid.app
./build.sh --install    # installs into /Applications using temporary staging
```

`--install` reuses the installed Python and leaves no second `.app` in the checkout.
Choose another destination with `GEPHID_INSTALL_DIR="$HOME/Applications" ./build.sh --install`.
For a build without installation: `GEPHID_BUILD_DIR="/path/to/build" ./build.sh`.
The checkout can be moved or renamed; `build.sh` resolves sources relative to itself.

### What `build.sh` does (6 steps)
1. **Front-end**: downloads and vendors marked, DOMPurify, highlight.js, KaTeX + mhchem (chemistry) and the fonts into `src/backend/static/` (no CDN at runtime). All versions are pinned at the top of `build.sh`; a `static/.versions` stamp records what was vendored, so bumping a pin actually re-downloads instead of silently keeping the old file.
2. **Embedded Python**: downloads the relocatable interpreter from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) into the target bundle and installs the dependencies pinned in `requirements.txt`. A `Resources/python/.gephid-deps` stamp records the interpreter and dependency pins: changing the list reinstalls packages, changing `PYVER`/`PYTAG` rebuilds the interpreter, and an unchanged build reuses the runtime.
3. **Go launcher**: `CGO_ENABLED=1 go build` of the Cocoa/WKWebView shell.
4. **Bundle**: assembles `Contents/` (binary, the backend modules `src/backend/*.py`, `page.html`, `static/`, icon, `Info.plist`, and a `build-info` label shown in the backend log).
5. **Sign** ad-hoc (`codesign`).
6. **Install** optionally into `/Applications` (with `--install`).

To rebuild a local build's embedded Python from scratch: `rm -rf dist/Gephid.app/Contents/Resources/python`.

### Model
Default `mlx-community/diffusiongemma-26B-A4B-it-8bit` (about 28 GB). It downloads on first launch
into the HuggingFace cache; the path is configurable from the app's Settings.

### Quick dev loop (without rebuilding everything)
- Only the backend (`src/backend/*.py`) or `src/backend/page.html`: copy them into
  `dist/Gephid.app/Contents/Resources/`, then `codesign --force --deep --sign - dist/Gephid.app` and relaunch.
  The Go launcher does not need recompiling.
- `src/launcher/main.go`: `cd src/launcher && CGO_ENABLED=1 go build -o /tmp/Gephid .`, copy the
  binary into `dist/Gephid.app/Contents/MacOS/Gephid`, re-sign.
- Backend without the GUI: `.venv/bin/python src/backend/diffuchat.py`, then `curl localhost:8890/...`.
  Log of the installed app: `~/Library/Logs/Gephid/backend.log`.
- Unbundled launcher: after the setup below, `(cd src/launcher && go run .)`.
  It locates the checkout from the working directory or executable. Interpreter discovery uses
  `GEPHID_PYTHON`, `.venv`, the active virtual environment, then `PATH`; a bundle always uses its embedded Python.

Setup and checks from the checkout (Python 3.10+, 3.12 recommended; pytest does not need the model):
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
(cd src/launcher && go test ./... && go vet ./...)
shellcheck build.sh       # optional: requires ShellCheck
codesign --verify --deep --strict /Applications/Gephid.app
```
To test the exact installed runtime, create `.venv` with
`PYTHONDONTWRITEBYTECODE=1 /Applications/Gephid.app/Contents/Resources/python/bin/python3 -m venv --system-site-packages .venv`
and use `PYTHONDONTWRITEBYTECODE=1` for subsequent commands using that environment too.
The latest maintenance checks and their scope are recorded in [docs/maintenance-2026-10-18.md](docs/maintenance-2026-10-18.md).

UI scrolling tests with real WebKit (Node.js 20+, no model required):
```bash
npm ci
npx playwright install webkit
npm run test:ui
```
The test server only serves the local UI and a synthetic stream; it does not use the app's open conversation.

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
