#!/usr/bin/env bash
# ============================================================================
#  Gephid — build completo della .app self-contained (macOS Apple Silicon)
#  Esegui da dentro la cartella del progetto:   ./build.sh   [--install]
#  Produce:  ./dist/Gephid.app; --install usa staging temporaneo e lascia solo la copia installata.
# ============================================================================
set -euo pipefail
case "${1:-}" in
  ""|--install) ;;
  *) echo "Uso: $0 [--install]" >&2; exit 2 ;;
esac
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo "Gephid richiede macOS su Apple Silicon (arm64)." >&2; exit 1
fi
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/gephid-build.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
HERE="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${GEPHID_INSTALL_DIR:-/Applications}"
BUILD_DIR="${GEPHID_BUILD_DIR:-$HERE/dist}"
INSTALLED_APP="$INSTALL_DIR/Gephid.app"
if [ "${1:-}" = "--install" ]; then
  APP="$WORK_DIR/Gephid.app"
else
  APP="$BUILD_DIR/Gephid.app"
fi
MACOS="$APP/Contents/MacOS"
RESOURCES="$APP/Contents/Resources"
STATIC="$HERE/src/backend/static"
PYVER="3.12.15"
PYTAG="20261013"   # release di astral-sh/python-build-standalone
KVER="0.19.0"      # KaTeX (+ mhchem, stessa versione)
MARKEDV="18.1.1"   # versioni JS pinnate: build riproducibile (niente "latest" che cambia sotto i piedi)
PURIFYV="3.4.17"
HLJSV="11.12.0"    # highlight.js (bundle "common"): evidenziazione del codice, colori dai token CSS della UI
# Un'unica lista di dipendenze per build e sviluppo; lo stamp registra i pin effettivi.
PYDEPS="$(sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$HERE/requirements.txt" | tr '\n' ' ' | sed 's/[[:space:]]*$//')"

# --install riusa il runtime già installato ma lavora su una copia temporanea:
# nessuna .app aggiuntiva nel checkout e nessuna modifica al runtime in uso.
if [ "${1:-}" = "--install" ] && [ -d "$INSTALLED_APP/Contents/Resources/python" ]; then
  mkdir -p "$RESOURCES"
  ditto "$INSTALLED_APP/Contents/Resources/python" "$RESOURCES/python"
fi

echo "==> 1/6  Librerie front-end (vendoring: l'app gira 100% offline)"
# dl() salta i file già presenti (build idempotente e veloce). Da solo però questo rende i pin
# INEFFICACI: alzare una versione qui sopra non riscaricherebbe mai il file già in static/.
# Lo stamp registra le versioni vendorizzate: se un pin cambia, si ri-vendorizza da zero
# (i font KaTeX sono legati alla versione, quindi va buttata tutta la cartella, non i singoli file).
STAMP="$STATIC/.versions"
WANT="marked=$MARKEDV purify=$PURIFYV katex=$KVER hljs=$HLJSV"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  [ -f "$STAMP" ] && echo "    pin cambiati -> ri-scarico le librerie JS"
  rm -rf "$STATIC"
fi
mkdir -p "$STATIC/fonts"
# download atomico: scarica in .part e rinomina solo a esito OK. Senza questo, una rete che cade a
# metà lascerebbe un file troncato che al giro dopo verrebbe "già presente" e mai più riparato.
dl(){
  if [ ! -f "$2" ]; then
    echo "    scarico $(basename "$2")"
    if curl -fsSL -o "$2.part" "$1" && mv "$2.part" "$2"; then
      return 0
    else
      rm -f "$2.part"; return 1
    fi
  fi
}
# marked >= 16 non pubblica più marked.min.js nel root del pacchetto: l'UMD sta in lib/.
dl "https://cdn.jsdelivr.net/npm/marked@$MARKEDV/lib/marked.umd.js"                 "$STATIC/marked.min.js"
dl "https://cdn.jsdelivr.net/npm/dompurify@$PURIFYV/dist/purify.min.js"             "$STATIC/purify.min.js"
dl "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@$HLJSV/highlight.min.js"  "$STATIC/highlight.min.js"
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/katex.min.css"                    "$STATIC/katex.min.css"
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/katex.min.js"                     "$STATIC/katex.min.js"
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/contrib/auto-render.min.js"       "$STATIC/auto-render.min.js"
# mhchem: estensione KaTeX per le formule di chimica (\ce{}, \pu{}). Senza, \ce{H2O} non compila
# — e la chimica è una funzione dichiarata nel README, quindi va vendorizzata come le altre.
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/contrib/mhchem.min.js"            "$STATIC/mhchem.min.js"
grep -oE 'KaTeX_[A-Za-z0-9_-]+\.woff2' "$STATIC/katex.min.css" | sort -u | while read -r f; do
  dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/fonts/$f" "$STATIC/fonts/$f"
done
printf '%s' "$WANT" > "$STAMP"   # vendoring completato: registra le versioni effettive

echo "==> 2/6  Python embeddato + dipendenze"
# Stessa logica dello stamp JS: prima il ramo "else" saltava tutto se il python esisteva già, quindi
# alzare PYDEPS qui sopra NON aggiornava una build esistente (il pin era decorativo). Ora:
#  - PYVER/PYTAG cambiati -> il python embeddato si rifà da zero
#  - solo PYDEPS cambiato  -> basta reinstallare i pacchetti (veloce), senza riscaricare l'interprete
PYSTAMP="$RESOURCES/python/.gephid-deps"
WANT_PY="python=$PYVER+$PYTAG"
WANT_DEPS="$PYDEPS"
if [ -x "$RESOURCES/python/bin/python3" ] && [ -f "$PYSTAMP" ] \
   && ! head -1 "$PYSTAMP" | grep -qxF "$WANT_PY"; then
  echo "    versione di Python cambiata ($WANT_PY) -> rifaccio l'interprete embeddato"
  rm -rf "$RESOURCES/python"
fi
if [ ! -x "$RESOURCES/python/bin/python3" ]; then
  echo "    scarico python-build-standalone $PYVER (eseguibile relocabile, NON l'app-stub di sistema)"
  TB="$WORK_DIR/python.tar.gz"
  curl -fsSL -o "$TB" "https://github.com/astral-sh/python-build-standalone/releases/download/$PYTAG/cpython-$PYVER+$PYTAG-aarch64-apple-darwin-install_only.tar.gz"
  mkdir -p "$RESOURCES"; rm -rf "$RESOURCES/python"
  tar -xzf "$TB" -C "$RESOURCES"     # crea Resources/python/
  rm -f "$TB"                        # il tarball (~40MB) non serve più
  "$RESOURCES/python/bin/python3" -m pip install -q --upgrade pip
fi
if [ ! -f "$PYSTAMP" ] || [ "$(tail -1 "$PYSTAMP")" != "$WANT_DEPS" ]; then
  echo "    installo le dipendenze pinnate nel python embeddato"
  "$RESOURCES/python/bin/python3" -m pip install -q --upgrade -r "$HERE/requirements.txt"
  printf '%s\n%s' "$WANT_PY" "$WANT_DEPS" > "$PYSTAMP"
else
  echo "    già allineato ai pin (per rifare tutto: rm -rf '$RESOURCES/python')"
fi

# Le wheel MLX sono specifiche per la versione di macOS. Il bundle deve dichiarare
# il minimo del runtime realmente incluso, non il vecchio 11.0 del solo launcher.
MIN_MACOS="$("$RESOURCES/python/bin/python3" - <<'PY'
import importlib.util, re, subprocess, sys
versions = ["14.0"]
for binary in (sys.executable, importlib.util.find_spec("mlx.core").origin):
    output = subprocess.check_output(["vtool", "-show-build", binary], text=True)
    versions.extend(re.findall(r"\bminos\s+([\d.]+)", output))
print(max(versions, key=lambda value: tuple(map(int, value.split(".")))))
PY
)"

echo "==> 3/6  Build del launcher Go (cgo / Cocoa+Speech+AVFoundation)"
( cd "$HERE/src/launcher" && CGO_ENABLED=1 go build -o "$WORK_DIR/Gephid" . )

echo "==> 4/6  Assemblo il bundle .app"
mkdir -p "$MACOS" "$RESOURCES"
cp "$WORK_DIR/Gephid" "$MACOS/Gephid"; chmod +x "$MACOS/Gephid"
cp "$HERE"/src/backend/*.py "$RESOURCES/"               # diffuchat.py + moduli (channels, store, agent)
cp "$HERE/src/backend/page.html" "$RESOURCES/page.html"  # UI (servita su /)
# etichetta di build: compare in ~/Library/Logs/Gephid/backend.log per sapere quale versione gira
printf '%s' "$(date +%Y-%m-%d.%H%M) $(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo nogit)" > "$RESOURCES/build-info"
rm -rf "$RESOURCES/static"; cp -R "$STATIC" "$RESOURCES/static"
[ -f "$HERE/assets/icon.icns" ] && cp "$HERE/assets/icon.icns" "$RESOURCES/icon.icns" || true
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Gephid</string>
  <key>CFBundleDisplayName</key><string>Gephid</string>
  <key>CFBundleExecutable</key><string>Gephid</string>
  <key>CFBundleIdentifier</key><string>pro.lloreti.gephid</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>2.0</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSMicrophoneUsageDescription</key><string>Gephid usa il microfono per la dettatura vocale offline.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>Gephid trascrive la tua voce sul dispositivo (offline) per la dettatura.</string>
</dict></plist>
PLIST
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $MIN_MACOS" "$APP/Contents/Info.plist"

echo "==> 5/6  Firma ad-hoc"
codesign --force --deep --sign - "$APP" >/dev/null

if [ "${1:-}" = "--install" ]; then
  echo "==> 6/6  Installo in $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  pkill -9 -f "Gephid.app/Contents/MacOS/Gephid" 2>/dev/null || true; sleep 1  # pattern stretto: solo i processi di Gephid
  rm -rf "$INSTALLED_APP"
  ditto "$APP" "$INSTALLED_APP"
  echo "    installato. Apri $INSTALLED_APP"
else
  echo "==> 6/6  Pronto: $APP  (usa --install per installarlo in $INSTALL_DIR)"
fi
echo "FATTO."
