# Architettura di Gephid

App nativa macOS (Apple Silicon) che dà a DiffusionGemma una chat in stile ChatGPT,
100% offline, racchiusa in un'unica `.app`. Il modello resta esterno e configurabile.
Nome: **Ge**mma + **diffusion**, scritto come "zaffiro".

## Struttura
```
Gephid/
├── build.sh                  # build della .app da zero
├── BUILD.md                  # guida di build (.app; nota su Windows/.exe)
├── README.md  README.it.md  ARCHITECTURE.md  LICENSE
├── assets/icon.icns          # icona (serratura royalblue inclinata 13.37°)
├── src/
│   ├── backend/
│   │   ├── diffuchat.py       # backend: server HTTP + UI (HTML/CSS/JS inline) + modello
│   │   └── static/           # librerie vendorizzate: marked, DOMPurify, html2pdf, KaTeX + fonts
│   └── launcher/
│       ├── main.go           # guscio Go + WKWebView + cgo (menu, file/save panel, dettatura)
│       └── go.mod go.sum logo.svg
└── Gephid.app                # artefatto buildato (~1GB, non versionato: si ricrea con build.sh)
```

## Architettura
1. **Launcher Go** (`src/launcher/main.go`): apre una finestra WKWebView, avvia il backend Python
   come sottoprocesso, mostra uno splash finché `/api/health` non risponde, naviga a
   `http://127.0.0.1:8890`, e alla chiusura uccide il backend. cgo/Cocoa fornisce menu nativo,
   pannelli file/salvataggio nativi e dettatura on-device (Speech + AVFoundation).
2. **Backend Python** (`src/backend/diffuchat.py`): `ThreadingHTTPServer` su `127.0.0.1:8890`.
   Carica il modello via `mlx-vlm` e serve UI + API. La UI è tutta inline nella stringa `PAGE`.
3. **Bundle .app**: Python embeddato (`Contents/Resources/python`, da python-build-standalone) +
   `diffuchat.py` + `static/` + `icon.icns`. Firmato ad-hoc.

## Vincoli da non reintrodurre
- **Thread del modello**: MLX vuole le ops del modello sul thread che ha caricato i pesi. Quindi
  `serve_forever()` gira su un thread daemon e il main thread fa da worker (`_model_worker`, che
  consuma `JOBS`). Gli handler HTTP non toccano il modello: accodano un `Job` e ne streamano gli
  eventi (`stream_job`). Su un altro thread si ottiene `no Stream(gpu) in current thread`.
- **Avvio**: il modello si carica in `__main__` con `load_model()`, dopo l'avvio del server e sul
  main thread. Così `/api/health` risponde subito (`model_ok=false`) e la finestra appare in ~1s
  con un overlay di caricamento, invece di restare in attesa dei ~28GB. Non riportare la `load()`
  a import-time.
- **Memoria GPU**: il modello a diffusione usa attenzione bidirezionale, quindi la memoria di un
  singolo buffer cresce ~seq² (≈32 byte/token²). Il limite non è la finestra di contesto (256K) ma
  il `max_buffer_length` della GPU. `SAFE_SEQ` (derivato da `mx.device_info()` a ogni avvio) tiene
  `prompt+output` sotto quel limite; `DOC_CTX` ne deriva. Documenti più grandi vengono compressi
  con map-reduce (`build_doc_context` → `map_reduce_summarize`), non passati grezzi.
- **Python embeddato, non quello di sistema**: il framework-python di Homebrew lanciato da GUI si
  blocca all'avvio. Serve l'eseguibile relocabile di python-build-standalone, con env pulito (`cmd.Env`).
- **100% offline**: `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`; librerie JS in `/static`; bind
  `127.0.0.1`; check header `Origin` (anti-CSRF). Rendering fail-safe: markdown solo se `marked` e
  `DOMPurify` sono presenti, altrimenti testo grezzo.
- **WKWebView**: non scarica via blob → salvataggio lato server (`/api/save`). `<input type=file>`
  non apre il picker → `gephidOpenFiles` (NSOpenPanel via bind); i pannelli nativi rubano il focus,
  quindi va ripristinato con `inp.focus()` al ritorno. `alert()/confirm()` non funzionano.
- **cgo + ARC**: il blocco cgo è compilato con `-fobjc-arc` (senza, la dettatura salvava una
  `NSString` autorelease in una static → use-after-free → crash). Non rimuoverlo.
- **Diffusione a blocchi**: il modello genera "tele" da 256 token e le raffina a `steps` (denoising).
  Step bassi degenerano in ripetizioni su testi lunghi → `STEP_MIN=16`, default 32; il guard
  `_degenerate` ferma le ripetizioni patologiche. Frontend: typewriter (rAF) con markdown reso live
  (throttle ~80ms; formule KaTeX a fine risposta) e caret lampeggiante.
- **Runtime**: solo `mlx-vlm` (mlx-lm dà `Model type diffusion_gemma not supported`); venv di test
  `~/.venv-mlxvlm`. Velocità (M5 Max): 8 step ≈ 44 tok/s, 16 ≈ 104 tok/s. Modello default
  `mlx-community/diffusiongemma-26B-A4B-it-8bit` (~28GB).

## API (su 127.0.0.1:8890)
`GET /` UI · `GET /api/health` · `GET /api/models` · `GET /api/config` · `GET /static/...` ·
`POST /api/chat` (NDJSON streaming, `attach`=id immagini/doc) · `POST /api/compact` (streaming) ·
`POST /api/ingest` (file→immagine/doc, OCR per PDF scansionati) · `POST /api/save` ·
`POST /api/config` (step/maxtok, effetto immediato) · `POST /api/reload` (ricarica modello a caldo).

## Funzioni
Streaming + stop · memoria per-sessione (finestra + riassunto cumulativo) · compattazione in 1
prompt · export MD/TXT/HTML/PDF · markdown + LaTeX/chimica (KaTeX) · temi · allegati: immagini
(vision), documenti txt/md/codice/PDF/Word/Excel/CSV (estrazione + map-reduce per i grandi), PDF
scansionati via OCR Apple Vision con fallback vision · dettatura on-device opt-in.

## Build
`./build.sh` assembla `Gephid.app`; `./build.sh --install` la installa anche in /Applications.
Scarica python-build-standalone, fa `pip install` (mlx-vlm, pypdf, python-docx, openpyxl, pymupdf,
ocrmac) e le librerie JS, compila il Go, assembla e firma ad-hoc. Idempotente (riusa il python
esistente; per rifarlo da zero: `rm -rf Gephid.app/Contents/Resources/python`).

## Sviluppo rapido
- Solo `diffuchat.py`: ricopialo in `Gephid.app/Contents/Resources/diffuchat.py` (+ `/Applications`),
  `codesign --force --deep --sign - Gephid.app`, riavvia. Il Go non serve ribuildarlo.
- `main.go`: `cd src/launcher && CGO_ENABLED=1 go build -o /tmp/Gephid .`, copia il binario in
  `Contents/MacOS/Gephid`, ri-firma.
- Test backend senza GUI: `~/.venv-mlxvlm/bin/python src/backend/diffuchat.py`, poi `curl localhost:8890/...`.

## Requisiti
macOS Apple Silicon, ~30GB liberi per il modello (in `~/.cache/huggingface/hub`), Go + Xcode CLT
per ribuildare. Modello default: `mlx-community/diffusiongemma-26B-A4B-it-8bit`.
