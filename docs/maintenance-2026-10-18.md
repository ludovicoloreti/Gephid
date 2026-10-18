# Controllo Gephid — 18 ottobre 2026

Verificato su Apple M5 Max, 128 GB, macOS 26.6.2, Go 1.27.2.
La `.app` installata in Applicazioni include Python e dipendenze; il modello resta nella cache locale.

## Aggiornamenti

| Componente | Prima | Dopo |
|---|---|---|
| Python standalone | 3.12.15+20261003 | 3.12.15+20261013 |
| mlx-vlm | 0.7.4 | 0.7.8 |
| pypdf | 6.19.0 | 6.21.1 |
| marked | 18.0.14 | 18.1.1 |
| DOMPurify | 3.4.16 | 3.4.17 |

KaTeX 0.19.0, highlight.js 11.12.0, python-docx 1.2.0, openpyxl 3.1.5,
PyMuPDF 1.28.2, ocrmac 1.0.1 e webview_go risultavano già aggiornati.
Il nuovo ambiente include anche MLX/Metal 0.32.4, Transformers 5.20.1 e huggingface-hub 2.2.0.
Fonti delle versioni: [PyPI](https://pypi.org/project/mlx-vlm/), [npm](https://www.npmjs.com/package/marked),
[DOMPurify](https://www.npmjs.com/package/dompurify), [release Astral](https://github.com/astral-sh/python-build-standalone/releases/tag/20261013)
e `go list -m -u all`.

## Correzioni

- Launcher e backend normalizzano allo stesso modo le porte configurate, evitando attese su porte diverse.
- La UI usa URL degli asset con versione e risposte `no-cache`: un aggiornamento non riusa per un anno le vecchie librerie.
- Le richieste con JSON malformato/non oggetto o lunghezza negativa/non numerica ricevono HTTP 400.
- Il fallback della generazione conserva immagini e opzioni di decodifica se cambia l'API privata MLX-VLM.
- La build usa file temporanei isolati e segnala opzioni/piattaforme non supportate.
- Il launcher disabilita la scrittura dei `.pyc`, anche nei processi Python figli: la firma resta valida dopo l'uso della `.app`.
- `Info.plist` registra il minimo macOS del Python e di MLX effettivamente inclusi: **26.2** per questa build.

## Portabilità del checkout

- Il launcher trova il backend rispetto al bundle, alla directory corrente o al binario, anche in un checkout spostato o rinominato.
- In sviluppo usa `GEPHID_PYTHON`, `.venv`, l'ambiente virtuale attivo o `PATH`; nel bundle usa il proprio interprete.
- I percorsi degli strumenti configurati dall'utente sono mantenuti, con fallback alle directory standard macOS.
- Build e sviluppo condividono `requirements.txt`; i test usano `requirements-dev.txt`.
- `--install` riusa il runtime installato attraverso staging temporaneo e lascia solo la copia installata. La build senza installazione produce `dist/Gephid.app`.
- Le destinazioni sono configurabili con `GEPHID_INSTALL_DIR` e `GEPHID_BUILD_DIR`.
- I test del resolver verificano cartelle rinominate, spazi nei percorsi e scelta dell'interprete. La sandbox viene collaudata su file temporanei.

## Verifiche

- 60 test pytest passati nel runtime Python 3.12 della build, senza caricare il modello nei test automatici.
- Test Go passati, inclusi 11 casi della configurazione porta; `go vet`, ShellCheck, sintassi Bash e `git diff --check` superati.
- Build completa e successiva build incrementale riuscite; dipendenze coerenti (`pip check`), plist valido e firma verificata con `codesign --verify --deep --strict`.
- Avvio della finestra WKWebView e apertura/chiusura delle Impostazioni verificati.
- Prova del frontend con DOM simulato e sole risorse locali: inizializzazione, markdown, LaTeX, chimica, codice evidenziato, sanitizzazione e rimozione dei marcatori dei canali.
- Inferenza reale offline: chat (`6 × 7 = 42`), agente con calcolatrice (`123 × 7 = 861`), ragionamento separato dalla risposta e compattazione. Dopo l'interruzione di uno stream lungo, il worker ha completato una nuova richiesta in 1,56 secondi.
- Documento allegato: codice `ZAFFIRO-7731` conservato e ripetuto correttamente nel turno successivo.
- Immagine allegata: testo `ZAFFIRO 7731` riconosciuto dal modello vision.
- OCR GLM locale e Apple Vision: entrambi hanno letto `ZAFFIRO 7731 - Totale 120 euro` da una pagina sintetica.
- Word con tabelle, Excel, email HTML, testo Unicode, PDF esportato e riallegato, salvataggio/ripristino/eliminazione di chat con documenti e sandbox verificati dai test.

PyMuPDF emette cinque warning di deprecazione SWIG durante pytest: nessun test fallito.
La dettatura con microfono, i dialoghi di permesso macOS e il router oMLX opzionale non sono stati collaudati end-to-end.
Il download di decine di GB dei pesi non è stato ripetuto: le prove reali usano i modelli già in cache.

## Ripetere i controlli

Comandi in [BUILD.it.md](../BUILD.it.md). Aprire `/Applications/Gephid.app`.
Per aggiornarla: `./build.sh --install`. L'installer usa staging temporaneo e lascia solo la copia installata.
