# Build

[English](BUILD.md) · **Italiano**

Gephid è un'app **nativa macOS (Apple Silicon)**. La `.app` non è versionata: si ricrea dai
sorgenti con `build.sh`.

## macOS: la `.app`

### Requisiti
- macOS su Apple Silicon (M1 o successivi), macOS 11+.
- [Go](https://go.dev) e gli Xcode Command Line Tools (`xcode-select --install`) per compilare il launcher.
- Rete solo per il **primo** build (scarica il Python embeddato e le librerie front-end); a runtime l'app è 100% offline.
- Circa 30 GB liberi per il modello, scaricato a parte nella cache di HuggingFace.

### Comandi
```bash
cd Gephid
./build.sh              # crea ./Gephid.app
./build.sh --install    # crea ./Gephid.app e la copia in /Applications
```

### Cosa fa `build.sh` (6 passi)
1. **Front-end**: scarica e vendorizza marked, DOMPurify, html2pdf, KaTeX e i font in `src/backend/static/` (niente CDN a runtime).
2. **Python embeddato**: scarica l'interprete relocabile di [python-build-standalone](https://github.com/astral-sh/python-build-standalone) in `Gephid.app/Contents/Resources/python` e installa le dipendenze (`mlx-vlm pypdf python-docx openpyxl pymupdf ocrmac`). Idempotente: salta se è già presente.
3. **Launcher Go**: `CGO_ENABLED=1 go build` del guscio Cocoa/WKWebView.
4. **Bundle**: assembla `Contents/` (binario, `diffuchat.py`, `page.html`, `static/`, icona, `Info.plist`).
5. **Firma** ad-hoc (`codesign`).
6. **Install** opzionale in `/Applications` (con `--install`).

Per rifare il Python embeddato da zero: `rm -rf Gephid.app/Contents/Resources/python`.

### Modello
Default `mlx-community/diffusiongemma-26B-A4B-it-8bit` (circa 28 GB). Si scarica al primo avvio nella
cache di HuggingFace; il path è configurabile dalle Impostazioni dell'app.

### Sviluppo rapido (senza ribuildare tutto)
- Solo `src/backend/diffuchat.py` o `src/backend/page.html`: copiali in `Gephid.app/Contents/Resources/`,
  poi `codesign --force --deep --sign - Gephid.app` e riavvia. Il launcher Go non va ricompilato.
- `src/launcher/main.go`: `cd src/launcher && CGO_ENABLED=1 go build -o /tmp/Gephid .`, copia il
  binario in `Gephid.app/Contents/MacOS/Gephid`, ri-firma.
- Backend senza GUI: `~/.venv-mlxvlm/bin/python src/backend/diffuchat.py`, poi `curl localhost:8890/...`.

## Windows: la `.exe`

**Non esiste ancora, e non è un'opzione di `build.sh`.** Gephid è legata a macOS da due dipendenze
di fondo:

- **Runtime del modello**: l'inferenza gira via `mlx-vlm`, e [MLX](https://github.com/ml-explore/mlx)
  è il framework ML di Apple, esclusivo per Apple Silicon. Su Windows non c'è. Servirebbe un runtime
  diverso (PyTorch+CUDA, llama.cpp, ONNX Runtime) e DiffusionGemma in un formato supportato lì: di
  fatto il backend di inferenza va riscritto.
- **Guscio nativo**: `main.go` usa cgo con Cocoa, WKWebView, Speech e AVFoundation, tutte API Apple.
  Su Windows servirebbe un guscio basato su WebView2 e la riscrittura di menu, pannelli file e dettatura.

**Riutilizzabile in un eventuale port**: la UI (`src/backend/page.html`) e gran parte della logica
HTTP del backend sono portabili. Cambiano il runtime del modello e il guscio nativo, con packaging
via PyInstaller/Nuitka per la `.exe`.

In breve: una `.exe` Windows sarebbe un **port a parte**, da pianificare separatamente, non un
target di questa build.
