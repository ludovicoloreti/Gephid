# Gephid

[English](README.md) · **Italiano**

![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Apple%20Silicon-000000?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Go](https://img.shields.io/badge/Go-1.26-00ADD8?logo=go&logoColor=white)
![runtime](https://img.shields.io/badge/runtime-MLX-FF6F00)
![model](https://img.shields.io/badge/model-DiffusionGemma-4169E1)
![offline](https://img.shields.io/badge/network-100%25%20offline-2E7D32)
![packaging](https://img.shields.io/badge/packaging-self--contained%20.app-555555)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Chat **nativa macOS** per **DiffusionGemma**, stile ChatGPT, **100% offline**, in un'unica app
cliccabile. Il modello a diffusione gira in locale sul tuo Mac (Apple Silicon) e niente esce dal
computer.

## Cos'è
- Una `.app` self-contained: il runtime Python e ogni libreria sono dentro il pacchetto. L'unica
  cosa esterna sono i **pesi del modello**, scaricati una volta nella cache di HuggingFace e
  configurabili dalle Impostazioni.
- Nessuna rete a runtime: nessuna chiamata, nessun account, nessuna telemetria. Il server locale
  ascolta solo su `127.0.0.1`.

## Funzioni
- **Chat in streaming** con markdown reso mentre scrive, la diffusione visibile mentre ogni blocco
  si forma, e un pulsante **Stop**.
- **Memoria** della conversazione: una finestra scorrevole più un riassunto automatico, così le
  chat lunghe non saturano mai il contesto.
- **Allegati**:
  - Immagini: il modello le vede (vision).
  - Documenti: txt, md, codice, PDF, Word, Excel, CSV. Il testo viene estratto e conteggiato in
    token; i documenti troppo grandi per la GPU vengono letti a pezzi e riassunti (map-reduce).
  - PDF scansionati: letti con OCR on-device (Apple Vision), senza rete.
- **Markdown più formule LaTeX e di chimica** (KaTeX).
- **Export** di un'intera chat o di un singolo messaggio in MD, TXT, HTML o PDF (salvati in
  `~/Downloads`). PDF e HTML hanno un'intestazione (modello usato, data di export) e un footer su
  ogni pagina.
- **Compattazione in un prompt**: comprime tutta la conversazione in un unico prompt da incollare
  altrove.
- **Dettatura on-device** (offline), attivabile dalle Impostazioni.
- **Dimensione del testo regolabile**, temi chiaro/scuro/sistema, e cambio del **modello a caldo**
  senza riavviare.

## Come funziona
Un piccolo **launcher Go** apre una finestra nativa (WKWebView), avvia il **backend Python** come
sottoprocesso, mostra una schermata di caricamento finché il modello non è pronto, poi punta la
finestra sulla UI locale. Il backend (`127.0.0.1:8890`) carica il modello a diffusione via MLX e
serve sia l'interfaccia sia le API. Il launcher sorveglia il backend, lo riavvia se si ferma, e lo
spegne quando si chiude l'ultima finestra. Dettagli tecnici: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Uso
Apri **Gephid** (da `/Applications`, o con doppio click sulla `.app`). La finestra appare subito con
una schermata di caricamento mentre il modello entra in memoria (qualche secondo; di più al
primissimo avvio se deve ancora scaricare i pesi). Poi scrivi, allega file con la graffetta, oppure
esporta e compatta dal menu di ogni messaggio.

Impostazioni (in alto a destra): tema, dimensione del testo, dettatura, step di denoising (qualità o
velocità), max token di risposta, motore OCR, e quale **modello** usare tra quelli già sul tuo Mac.

## Build da sorgente
La `.app` non è versionata (pesa circa 1 GB col Python embeddato); si ricrea dai sorgenti:
```bash
cd Gephid
./build.sh --install      # scarica tutto, assembla Gephid.app e la installa in /Applications
```
`build.sh` è idempotente (riusa un Python embeddato già presente). Guida completa, ciclo di sviluppo
rapido e nota su Windows/`.exe`: **[BUILD.md](BUILD.md)**.

## Requisiti
- macOS su Apple Silicon (M1 o successivi).
- Circa 30 GB liberi per i pesi del modello (in `~/.cache/huggingface/hub`).
- Per ribuildare dai sorgenti: Go e gli Xcode Command Line Tools.

Modello di default: `mlx-community/diffusiongemma-26B-A4B-it-8bit` (circa 28 GB).

## Licenza
[MIT](LICENSE). Usala, modificala e ridistribuiscila liberamente.
