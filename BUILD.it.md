# Build

[English](BUILD.md) · **Italiano**

Gephid è un'app **nativa macOS (Apple Silicon)**. La `.app` non è versionata: si ricrea dai
sorgenti con `build.sh`.

## macOS: la `.app`

### Requisiti
- macOS su Apple Silicon (M1 o successivi), macOS 14+ per i sorgenti. La versione minima della `.app` dipende dalla wheel MLX scelta per il Mac di build e viene rilevata e scritta automaticamente in `Info.plist` (26.2 nella build verificata il 18/10/2026).
- [Go](https://go.dev) e gli Xcode Command Line Tools (`xcode-select --install`) per compilare il launcher.
- Rete per il **primo** build e per gli aggiornamenti delle dipendenze (scarica il Python embeddato e le librerie front-end); a runtime l'app è 100% offline.
- Circa 30 GB liberi per il modello, scaricato a parte nella cache di HuggingFace.

### Comandi
```bash
cd Gephid
./build.sh              # crea ./dist/Gephid.app
./build.sh --install    # installa in /Applications usando staging temporaneo
```

`--install` riusa il Python già installato e non lascia una seconda `.app` nel checkout.
Per scegliere un'altra destinazione: `GEPHID_INSTALL_DIR="$HOME/Applications" ./build.sh --install`.
Per una build senza installazione: `GEPHID_BUILD_DIR="/percorso/build" ./build.sh`.
Il checkout può essere spostato o rinominato; `build.sh` risolve i sorgenti rispetto a se stesso.

### Cosa fa `build.sh` (6 passi)
1. **Front-end**: scarica e vendorizza marked, DOMPurify, highlight.js, KaTeX + mhchem (chimica) e i font in `src/backend/static/` (niente CDN a runtime). Le versioni sono pinnate in cima a `build.sh`; lo stamp `static/.versions` registra cosa è stato vendorizzato, così alzare un pin riscarica davvero invece di tenersi in silenzio il file vecchio.
2. **Python embeddato**: scarica l'interprete relocabile di [python-build-standalone](https://github.com/astral-sh/python-build-standalone) nel bundle di destinazione e installa le dipendenze pinnate in `requirements.txt`. Lo stamp `Resources/python/.gephid-deps` registra interprete e pin: se cambia la lista reinstalla i pacchetti, se cambiano `PYVER`/`PYTAG` rifà l'interprete, altrimenti riusa il runtime.
3. **Launcher Go**: `CGO_ENABLED=1 go build` del guscio Cocoa/WKWebView.
4. **Bundle**: assembla `Contents/` (binario, i moduli del backend `src/backend/*.py`, `page.html`, `static/`, icona, `Info.plist` e un'etichetta `build-info` che compare nel log del backend).
5. **Firma** ad-hoc (`codesign`).
6. **Install** opzionale in `/Applications` (con `--install`).

Per rifare il Python di una build locale da zero: `rm -rf dist/Gephid.app/Contents/Resources/python`.

### Modello
Default `mlx-community/diffusiongemma-26B-A4B-it-8bit` (circa 28 GB). Si scarica al primo avvio nella
cache di HuggingFace; il path è configurabile dalle Impostazioni dell'app.

### Sviluppo rapido (senza ribuildare tutto)
- Solo il backend (`src/backend/*.py`) o `src/backend/page.html`: copiali in `dist/Gephid.app/Contents/Resources/`,
  poi `codesign --force --deep --sign - dist/Gephid.app` e riavvia. Il launcher Go non va ricompilato.
- `src/launcher/main.go`: `cd src/launcher && CGO_ENABLED=1 go build -o /tmp/Gephid .`, copia il
  binario in `dist/Gephid.app/Contents/MacOS/Gephid`, ri-firma.
- Backend senza GUI: `.venv/bin/python src/backend/diffuchat.py`, poi `curl localhost:8890/...`.
  Log dell'app installata: `~/Library/Logs/Gephid/backend.log`.
- Launcher senza bundle: dopo il setup seguente, `(cd src/launcher && go run .)`.
  Trova il checkout dalla directory corrente o dal binario. L'interprete viene scelto da
  `GEPHID_PYTHON`, `.venv`, ambiente virtuale attivo o `PATH`; nel bundle usa sempre il Python incluso.

Setup e controlli dal checkout (Python 3.10+, consigliato 3.12; il modello non serve per pytest):
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
(cd src/launcher && go test ./... && go vet ./...)
shellcheck build.sh       # facoltativo: richiede ShellCheck
codesign --verify --deep --strict /Applications/Gephid.app
```
Per collaudare esattamente il runtime installato, crea invece `.venv` con
`PYTHONDONTWRITEBYTECODE=1 /Applications/Gephid.app/Contents/Resources/python/bin/python3 -m venv --system-site-packages .venv`
e usa `PYTHONDONTWRITEBYTECODE=1` anche per i comandi successivi che usano quell'ambiente.
L'ultimo controllo di aggiornamento e le prove effettuate sono in [docs/maintenance-2026-10-18.md](docs/maintenance-2026-10-18.md).

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
