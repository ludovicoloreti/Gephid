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
cliccabile. Il modello a diffusione gira in locale sul tuo Mac (Apple Silicon).

## Cos'è
- App `.app` self-contained (Python + librerie tutto dentro). L'unica cosa esterna è il **modello**
  (scaricato nella cache di HuggingFace, configurabile dalle Impostazioni).
- Niente internet: nessuna chiamata di rete, server solo su `127.0.0.1`.

## Funzioni
- **Chat in streaming** con markdown reso mentre scrive e pulsante **Stop**.
- **Memoria** della conversazione (riassunto automatico per non saturare il contesto).
- **Allegati**: immagini (il modello le *vede*), documenti **txt/md/codice/PDF/Word/Excel/CSV**
  (estrazione testo + conteggio token); i documenti troppo grandi per la GPU vengono letti a pezzi
  e riassunti; i **PDF scansionati** vengono letti via **OCR** (Apple Vision, offline).
- **Markdown + formule LaTeX/chimica** (KaTeX).
- **Export** di chat e singoli messaggi in **MD/TXT/HTML/PDF** (salvati in ~/Downloads).
- **Compattazione in 1 prompt**: comprime la chat in un unico prompt da incollare altrove.
- **Dettatura vocale** on-device (offline), attivabile dalle Impostazioni.
- Temi chiaro/scuro/sistema. Cambio modello **a caldo** (senza riavviare).

## Uso
Apri **Gephid** (da `/Applications` o doppio click sulla `.app`). La finestra appare subito con un
overlay di caricamento mentre il modello entra in memoria (qualche secondo; di più al primissimo
avvio se deve ancora scaricarlo); poi è pronta. Scrivi, allega file con la graffetta, esporta o
compatta dal menu di ogni messaggio.

Impostazioni (icona in alto): tema, dettatura, step di denoising (qualità↔velocità), max token,
e selezione del **modello** tra quelli già sul tuo Mac.

## Build da sorgente
La `.app` non è versionata: si ricrea dai sorgenti.
```bash
cd Gephid
./build.sh --install      # scarica tutto, assembla Gephid.app e la installa in /Applications
```
Guida completa (passi, sviluppo rapido, nota su Windows/`.exe`): **[BUILD.md](BUILD.md)**.
Architettura e dettagli tecnici: `CLAUDE.md`.

## Requisiti
macOS Apple Silicon · ~30 GB liberi per il modello · (per ribuildare: Go + Xcode Command Line Tools).

## Licenza
[MIT](LICENSE) — usala, modificala e ridistribuiscila liberamente.
