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
PYTAG="20260610"   # release di astral-sh/python-build-standalone
KVER="0.16.11"     # KaTeX

echo "==> 1/6  Librerie front-end (vendoring: l'app gira 100% offline)"
mkdir -p "$STATIC/fonts"
dl(){ [ -f "$2" ] || { echo "    scarico $(basename "$2")"; curl -fsSL -o "$2" "$1"; }; }
dl "https://cdn.jsdelivr.net/npm/marked/marked.min.js"                              "$STATIC/marked.min.js"
dl "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"                    "$STATIC/purify.min.js"
dl "https://cdn.jsdelivr.net/npm/html2pdf.js@0.10.1/dist/html2pdf.bundle.min.js"    "$STATIC/html2pdf.bundle.min.js"
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/katex.min.css"                    "$STATIC/katex.min.css"
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/katex.min.js"                     "$STATIC/katex.min.js"
dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/contrib/auto-render.min.js"       "$STATIC/auto-render.min.js"
grep -oE 'KaTeX_[A-Za-z0-9_-]+\.woff2' "$STATIC/katex.min.css" | sort -u | while read -r f; do
  dl "https://cdn.jsdelivr.net/npm/katex@$KVER/dist/fonts/$f" "$STATIC/fonts/$f"
done

echo "==> 2/6  Python embeddato + dipendenze (solo se manca)"
if [ ! -x "$RESOURCES/python/bin/python3" ]; then
  echo "    scarico python-build-standalone $PYVER (eseguibile relocabile, NON l'app-stub di sistema)"
  TB=/tmp/gephid-python.tar.gz
  curl -fsSL -o "$TB" "https://github.com/astral-sh/python-build-standalone/releases/download/$PYTAG/cpython-$PYVER+$PYTAG-aarch64-apple-darwin-install_only.tar.gz"
  mkdir -p "$RESOURCES"; rm -rf "$RESOURCES/python"
  tar -xzf "$TB" -C "$RESOURCES"     # crea Resources/python/
  echo "    installo le dipendenze nel python embeddato"
  "$RESOURCES/python/bin/python3" -m pip install -q --upgrade pip
  "$RESOURCES/python/bin/python3" -m pip install -q mlx-vlm pypdf python-docx openpyxl pymupdf ocrmac
else
  echo "    già presente (per rifarlo: rm -rf '$RESOURCES/python')"
fi

echo "==> 3/6  Build del launcher Go (cgo / Cocoa+Speech+AVFoundation)"
( cd "$HERE/src/launcher" && CGO_ENABLED=1 go build -o /tmp/Gephid . )

echo "==> 4/6  Assemblo il bundle .app"
mkdir -p "$MACOS" "$RESOURCES"
cp /tmp/Gephid "$MACOS/Gephid"; chmod +x "$MACOS/Gephid"
cp "$HERE/src/backend/diffuchat.py" "$RESOURCES/diffuchat.py"
cp "$HERE/src/backend/page.html" "$RESOURCES/page.html"  # nuova UI redesign (servita su /new)
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
  <key>CFBundleVersion</key><string>1.5</string>
  <key>CFBundleShortVersionString</key><string>1.5</string>
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
  pkill -9 -f "Gephid.app" 2>/dev/null || true; sleep 1
  rm -rf /Applications/Gephid.app
  cp -R "$APP" /Applications/Gephid.app
  echo "    installato. Apri /Applications/Gephid.app"
else
  echo "==> 6/6  Pronto: $APP  (usa --install per copiarlo in /Applications)"
fi
echo "FATTO."
