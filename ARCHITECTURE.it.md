# Architettura di Gephid

[English](ARCHITECTURE.md) · **Italiano**

App nativa macOS (Apple Silicon) che dà a DiffusionGemma una chat in stile ChatGPT,
100% offline, racchiusa in un'unica `.app`. Il modello resta esterno e configurabile.
Nome: **Ge**mma + **diffusion**.

## Struttura
```
Gephid/
├── build.sh                  # build della .app da zero
├── BUILD.md / BUILD.it.md    # guida di build (.app; nota su Windows/.exe)
├── README.md / README.it.md  # questa guida nelle due lingue
├── ARCHITECTURE.md / .it.md  # questo documento
├── LICENSE
├── assets/icon.icns          # icona (serratura royalblue inclinata 13.37°)
├── src/
│   ├── backend/
│   │   ├── diffuchat.py      # backend: server HTTP + worker del modello + ciclo agente
│   │   ├── channels.py       # separa lo stream del modello: risposta / pensiero / chiamate a strumenti
│   │   ├── agent.py          # strumenti dell'agente: calcolatrice, ricerca documenti, file, sandbox codice
│   │   ├── store.py          # chat salvate SU RICHIESTA (di default non si salva nulla)
│   │   ├── page.html         # UI (HTML/CSS/JS), riletta da disco quando cambia
│   │   └── static/           # librerie vendorizzate: marked, DOMPurify, highlight.js, KaTeX (+ mhchem) + font
│   └── launcher/
│       ├── main.go           # guscio Go + WKWebView + cgo (menu, file/save panel, dettatura)
│       └── go.mod go.sum logo.svg
├── tests/                    # pytest: funzioni pure, sandbox, confinamento dei percorsi (senza modello)
└── Gephid.app                # artefatto buildato (~1GB, non versionato: si ricrea con build.sh)
```

## Architettura
1. **Launcher Go** (`src/launcher/main.go`): apre una finestra WKWebView, avvia il backend Python
   come sottoprocesso, mostra uno splash finché `/api/health` non risponde, naviga a
   `http://127.0.0.1:8890`, sorveglia il backend (lo riavvia se muore) e lo spegne quando si chiude
   l'ultima finestra. cgo/Cocoa fornisce menu nativo, pannelli file/salvataggio e dettatura
   on-device (Speech + AVFoundation).
2. **Backend Python** (`src/backend/diffuchat.py`): `ThreadingHTTPServer` su `127.0.0.1:8890`.
   Carica il modello via `mlx-vlm` e serve UI + API. La UI vive in `page.html`, riletta da disco a
   ogni richiesta.
3. **Bundle .app**: Python embeddato (`Contents/Resources/python`, da python-build-standalone) +
   `src/backend/*.py` + `page.html` + `static/` + `icon.icns` + `build-info`. Firmato ad-hoc.

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
  `127.0.0.1`; check header `Origin` + `Host` (anti-CSRF / anti DNS-rebinding). Rendering fail-safe:
  markdown solo se `marked` e `DOMPurify` sono presenti, altrimenti testo grezzo.
- **Canali dell'output del modello**: il template apre sempre un canale di pensiero (`<|channel>thought …
  <channel|>`, vuoto col ragionamento spento) e avvolge le chiamate a strumenti in `<|tool_call> …
  <tool_call|>`. Ogni generazione passa da `ChannelSplitter`: mai mostrare output che lo salta.
- **Istruzioni e documenti nel turno `system`**: pre-prompt e documenti della chat formano un prefisso
  stabile; il frontend rimanda a OGNI turno tutti gli id degli allegati della chat (un documento
  allegato al turno 1 deve valere al turno 5). Gli allegati vivono solo in RAM (LRU); dopo un riavvio
  del backend la UI chiede di riallegarli invece di rispondere senza. La prefix cache di mlx-vlm 0.7.4
  non si attiva con DiffusionGemma (verificato): i documenti lunghi si rileggono a ogni turno.
- **Niente si salva se non richiesto**: la chat corrente vive in `sessionStorage`; solo "Salva chat"
  scrive in `~/Library/Application Support/Gephid/chats`.
- **Sicurezza dell'agente**: l'output degli strumenti non è fidato. Gli strumenti file sono confinati
  nella cartella di lavoro (`safe_path`, symlink risolti); scrittura ed esecuzione di codice chiedono
  sempre il clic dell'utente (`/api/agent/confirm`, 300s senza risposta = negato). Il codice gira in
  `sandbox-exec` (niente rete in uscita tranne localhost, scrittura solo nella sua cartella
  temporanea, timeout 30s); un processo in background che ascolta oltre 127.0.0.1 viene fermato
  (controllo con `lsof`), e tutti muoiono col backend.
- **WKWebView**: non scarica via blob → salvataggio lato server (`/api/save`, in `~/Downloads` o nel
  percorso scelto col pannello di salvataggio nativo, solo dentro la home).
  `<input type=file>` non apre il picker → `gephidOpenFiles` (NSOpenPanel via bind); i pannelli
  nativi rubano il focus, quindi va ripristinato con `inp.focus()` al ritorno. `alert()/confirm()`
  non funzionano.
- **cgo + ARC**: il blocco cgo è compilato con `-fobjc-arc` (senza, la dettatura salvava una
  `NSString` autorelease in una static → use-after-free → crash). Non rimuoverlo.
- **Diffusione a blocchi**: il modello genera "tele" da 256 token e le raffina a `steps` (denoising).
  Step bassi degenerano in ripetizioni su testi lunghi → `STEP_MIN=16`, default 48; il guard
  `_degenerate` ferma le ripetizioni patologiche. Frontend: typewriter (rAF) con markdown reso live
  e diffusione visibile mentre il blocco si forma.
- **Runtime**: solo `mlx-vlm` (mlx-lm dà `Model type diffusion_gemma not supported`); venv di test
  `~/.venv-mlxvlm`. Velocità (M5 Max): 8 step ≈ 44 tok/s, 16 ≈ 104 tok/s. Modello default
  `mlx-community/diffusiongemma-26B-A4B-it-8bit` (~28GB).

## API (su 127.0.0.1:8890)
`GET /` UI · `GET /api/health` · `GET /api/models` · `GET /api/config` · `GET /static/...` ·
`POST /api/chat` (NDJSON streaming, `attach`=id immagini/doc) · `POST /api/compact` (streaming) ·
`POST /api/ingest` (file→immagine/doc, OCR per pagine scansionate — anche in PDF misti;
`cancel_token` per annullare) · `POST /api/ingest/cancel` · `POST /api/save` (default `~/Downloads`;
`path` dal pannello nativo, solo dentro la home) · `POST /api/config` (step/maxtok/ocr/pre-prompt,
effetto immediato) · `POST /api/reload` (ricarica modello a caldo) · `POST /api/download`
(scarica/aggiorna il modello; il totale mostrato è il delta) · `POST /api/download/pause` ·
`POST /api/model/check` (revisione locale vs HuggingFace) · `GET /api/chats` ·
`POST /api/chats/save|get|delete` (chat salvate) · `POST /api/agent/confirm` (consenti/nega
un'azione) · `GET /api/agent/procs` · `POST /api/agent/stop`. `/api/chat` accetta anche `think`
(ragionamento) e `agent` (strumenti) e streamma eventi `thought`, `agent`, `confirm`, `procs`.

Rete usata **solo** da `/api/download` e `/api/model/check`, entrambe su azione esplicita
dell'utente: nessun controllo automatico all'avvio. Nessuno strumento dell'agente tocca la rete.

## Funzioni
Streaming + stop · memoria per-sessione (finestra + riassunto cumulativo) · compattazione in 1
prompt · export MD/TXT/HTML/PDF · markdown + LaTeX/chimica (KaTeX) · temi · allegati: immagini
(vision), documenti txt/md/codice/PDF/Word/Excel/CSV (estrazione + map-reduce per i grandi), PDF
scansionate via OCR (3 motori: GLM-OCR in-process di default, Apple Vision, router oMLX; vision
come ultimo fallback) · dettatura on-device opt-in · Ragiona (pensiero visibile) · Agente (strumenti
locali) · chat salvate solo su richiesta · rigenera/modifica · codice evidenziato · menu nativi con
scorciatoie.

## Build
`./build.sh` assembla `Gephid.app`; `./build.sh --install` la installa anche in /Applications.
Scarica python-build-standalone, fa `pip install` con versioni PINNATE (mlx-vlm, pypdf, python-docx,
openpyxl, pymupdf, ocrmac) e le librerie JS pinnate, compila il Go, assembla e firma ad-hoc. Due
stamp — `static/.versions` e `Resources/python/.gephid-deps` — rendono i pin effettivi: se un pin
cambia si ri-vendorizza o reinstalla, se non cambia si salta tutto (idempotente, ~4s). Per rifare da
zero: `rm -rf Gephid.app/Contents/Resources/python src/backend/static`. Dettagli in
[BUILD.it.md](BUILD.it.md).

## Requisiti
macOS Apple Silicon, ~30GB liberi per il modello (in `~/.cache/huggingface/hub`), Go + Xcode CLT
per ribuildare. Modello default: `mlx-community/diffusiongemma-26B-A4B-it-8bit`.
