#!/usr/bin/env bash
# ============================================================================
#  Gephid — build completo della .app self-contained (macOS Apple Silicon)
#  Esegui da dentro la cartella del progetto:   ./build.sh   [--install]
#  Produce:  ./Gephid.app   (e con --install lo copia in /Applications)
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/Gephid.app"
MACOS="$APP/Contents/MacOS"
RESOURCES="$APP/Contents/Resources"
STATIC="$HERE/src/backend/static"
PYVER="3.12.13"
PYTAG="20260718"   # release di astral-sh/python-build-standalone
KVER="0.18.1"      # KaTeX (+ mhchem, stessa versione)
MARKEDV="18.0.7"   # versioni JS pinnate: build riproducibile (niente "latest" che cambia sotto i piedi)
PURIFYV="3.4.12"
H2PV="0.10.1"      # html2pdf: lo usa solo la UI legacy /old (la nuova fa il PDF lato server)
# dipendenze Python pinnate (stesso motivo). Per aggiornare: alza qui e rifai il python embeddato.
# Aggiornati il 17/08/2026: mlx-vlm 0.6.7→0.6.13 (è la libreria che serve
# DiffusionGemma, sei versioni di scarto), pypdf 6.14.2→6.16.1, pymupdf 1.28.0→1.28.2.
# python-docx, openpyxl e ocrmac erano già all'ultima.
PYDEPS="mlx-vlm==0.6.13 pypdf==6.16.1 python-docx==1.2.0 openpyxl==3.1.5 pymupdf==1.28.2 ocrmac==1.0.1"

echo "==> 1/6  Librerie front-end (vendoring: l'app gira 100% offline)"
# dl() salta i file già presenti (build idempotente e veloce). Da solo però questo rende i pin
# INEFFICACI: alzare una versione qui sopra non riscaricherebbe mai il file già in static/.
# Lo stamp registra le versioni vendorizzate: se un pin cambia, si ri-vendorizza da zero
# (i font KaTeX sono legati alla versione, quindi va buttata tutta la cartella, non i singoli file).
STAMP="$STATIC/.versions"
WANT="marked=$MARKEDV purify=$PURIFYV katex=$KVER html2pdf=$H2PV"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
  [ -f "$STAMP" ] && echo "    pin cambiati -> ri-scarico le librerie JS"
  rm -rf "$STATIC"
fi
mkdir -p "$STATIC/fonts"
# download atomico: scarica in .part e rinomina solo a esito OK. Senza questo, una rete che cade a
# metà lascerebbe un file troncato che al giro dopo verrebbe "già presente" e mai più riparato.
dl(){ [ -f "$2" ] || { echo "    scarico $(basename "$2")"; curl -fsSL -o "$2.part" "$1" && mv "$2.part" "$2" || { rm -f "$2.part"; return 1; }; }; }
# marked >= 16 non pubblica più marked.min.js nel root del pacchetto: l'UMD sta in lib/.
dl "https://cdn.jsdelivr.net/npm/marked@$MARKEDV/lib/marked.umd.js"                 "$STATIC/marked.min.js"
dl "https://cdn.jsdelivr.net/npm/dompurify@$PURIFYV/dist/purify.min.js"             "$STATIC/purify.min.js"
dl "https://cdn.jsdelivr.net/npm/html2pdf.js@$H2PV/dist/html2pdf.bundle.min.js"     "$STATIC/html2pdf.bundle.min.js"
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
  TB=/tmp/gephid-python.tar.gz
  curl -fsSL -o "$TB" "https://github.com/astral-sh/python-build-standalone/releases/download/$PYTAG/cpython-$PYVER+$PYTAG-aarch64-apple-darwin-install_only.tar.gz"
  mkdir -p "$RESOURCES"; rm -rf "$RESOURCES/python"
  tar -xzf "$TB" -C "$RESOURCES"     # crea Resources/python/
  rm -f "$TB"                        # il tarball (~40MB) non serve più
  "$RESOURCES/python/bin/python3" -m pip install -q --upgrade pip
fi
if [ ! -f "$PYSTAMP" ] || [ "$(tail -1 "$PYSTAMP")" != "$WANT_DEPS" ]; then
  echo "    installo le dipendenze pinnate nel python embeddato"
  # shellcheck disable=SC2086  # PYDEPS è volutamente word-split (una spec per pacchetto)
  "$RESOURCES/python/bin/python3" -m pip install -q --upgrade $PYDEPS
  printf '%s\n%s' "$WANT_PY" "$WANT_DEPS" > "$PYSTAMP"
else
  echo "    già allineato ai pin (per rifare tutto: rm -rf '$RESOURCES/python')"
fi

echo "==> 3/6  Build del launcher Go (cgo / Cocoa+Speech+AVFoundation)"
( cd "$HERE/src/launcher" && CGO_ENABLED=1 go build -o /tmp/Gephid . )

echo "==> 4/6  Assemblo il bundle .app"
mkdir -p "$MACOS" "$RESOURCES"
cp /tmp/Gephid "$MACOS/Gephid"; chmod +x "$MACOS/Gephid"
cp "$HERE/src/backend/diffuchat.py" "$RESOURCES/diffuchat.py"
cp "$HERE/src/backend/page.html" "$RESOURCES/page.html"  # UI di default (servita su / e /new)
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
  <key>CFBundleVersion</key><string>1.6</string>
  <key>CFBundleShortVersionString</key><string>1.6</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSMicrophoneUsageDescription</key><string>Gephid usa il microfono per la dettatura vocale offline.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>Gephid trascrive la tua voce sul dispositivo (offline) per la dettatura.</string>
</dict></plist>
PLIST

echo "==> 5/6  Firma ad-hoc"
codesign --force --deep --sign - "$APP" >/dev/null

if [ "${1:-}" = "--install" ]; then
  echo "==> 6/6  Installo in /Applications"
  pkill -9 -f "Gephid.app/Contents/MacOS/Gephid" 2>/dev/null || true; sleep 1  # pattern stretto: solo i processi di Gephid
  rm -rf /Applications/Gephid.app
  cp -R "$APP" /Applications/Gephid.app
  echo "    installato. Apri /Applications/Gephid.app"
else
  echo "==> 6/6  Pronto: $APP  (usa --install per copiarlo in /Applications)"
fi
echo "FATTO."
