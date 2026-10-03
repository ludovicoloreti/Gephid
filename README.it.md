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
  si forma, e un pulsante **Stop** che interrompe davvero il modello. **Rigenera** l'ultima risposta,
  **modifica** i tuoi messaggi. La velocità mostrata (tok/s) conta tutti i token generati, ragionamento
  compreso.
- **Ragiona** (spento di default): il modello ragiona prima di rispondere; vedi il ragionamento
  scorrere, poi si compatta in una riga "Ha ragionato · 8s" che puoi riaprire con un clic.
- **Agente** (spento di default): Gephid usa strumenti locali, nessuno dei quali tocca la rete:
  calcolatrice esatta, ricerca nei documenti della chat e, in una **cartella di lavoro scelta da te**,
  elenca/leggi/cerca file e ne crea di **nuovi** (sempre con anteprima e scheda Consenti/Nega; non può
  mai modificare, sovrascrivere o cancellare i tuoi file). Può anche eseguire un breve programma
  **Python o Node** in una sandbox di macOS (niente rete, nessun altro programma — niente `rm`, niente
  shell —, scrittura solo in una cartella temporanea, limite di 30s), sempre dopo il tuo consenso; i
  server lasciati attivi possono ascoltare solo su 127.0.0.1. Senza cartella di lavoro ti spiega come
  sceglierla.
- **Allegati che restano nella conversazione**: alleghi un documento una volta e ci fai tutte le
  domande che vuoi.
  - Immagini: il modello le vede (vision). Si incollano anche con ⌘V.
  - Documenti: txt, md, codice, PDF, Word, Excel, CSV, eml. I documenti troppo grandi per la GPU
    vengono letti a pezzi e riassunti (map-reduce).
  - PDF scansionati (anche misti testo+scansione): letti con OCR on-device — GLM-OCR locale di
    default, Apple Vision o router oMLX selezionabili dalle Impostazioni. Senza rete.
- **Non si salva nulla se non lo chiedi.** La chat corrente sopravvive a una ricarica ma sparisce
  quando chiudi l'app. **Salva chat** (⌘S) la tiene, con i suoi documenti, in
  `~/Library/Application Support/Gephid`; **Chat salvate** la riapre o la elimina.
- **Markdown più formule LaTeX e di chimica** (KaTeX); **codice evidenziato** con pulsante copia.
- **Export** di un'intera chat o di un singolo messaggio in MD, TXT, HTML o PDF, col pannello di
  salvataggio nativo.
- **Compattazione in un prompt**: comprime tutta la conversazione in un unico prompt da incollare
  altrove.
- **App Mac nativa**: barra dei menu completa con scorciatoie (⌘N ⌘O ⌘S ⌘E ⌘, ⌘+/⌘−), finestra che
  ricorda la sua dimensione, dettatura on-device (offline, opzionale), temi chiaro/scuro/sistema,
  dimensione del testo regolabile, interfaccia italiano/inglese e cambio del **modello a caldo**
  senza riavviare.

## Come funziona
Un piccolo **launcher Go** apre una finestra nativa (WKWebView), avvia il **backend Python** come
sottoprocesso, mostra una schermata di caricamento finché il modello non è pronto, poi punta la
finestra sulla UI locale. Il backend (`127.0.0.1:8890`) carica il modello a diffusione via MLX e
serve sia l'interfaccia sia le API. Il launcher sorveglia il backend, lo riavvia se si ferma, e lo
spegne quando si chiude l'ultima finestra. Dettagli tecnici: **[ARCHITECTURE.it.md](ARCHITECTURE.it.md)**.

## Uso
Apri **Gephid** (da `/Applications`, o con doppio click sulla `.app`). La finestra appare subito con
una schermata di caricamento mentre il modello entra in memoria (qualche secondo; di più al
primissimo avvio se deve ancora scaricare i pesi). Poi scrivi, allega file con la graffetta, oppure
esporta e compatta dal menu Esporta. Accendi **Ragiona** o **Agente** dalle pillole accanto al
campo del messaggio quando ti servono.

Impostazioni (in alto a destra): tema, dimensione del testo, dettatura, step di denoising (qualità o
velocità), max token di risposta, motore OCR, la **cartella di lavoro** dell'agente, le istruzioni al
modello e quale **modello** usare tra quelli già sul tuo Mac.

## Build da sorgente
La `.app` non è versionata (pesa circa 1 GB col Python embeddato); si ricrea dai sorgenti:
```bash
cd Gephid
./build.sh --install      # scarica tutto, assembla Gephid.app e la installa in /Applications
```
`build.sh` è idempotente (riusa un Python embeddato già presente). Guida completa, ciclo di sviluppo
rapido e nota su Windows/`.exe`: **[BUILD.it.md](BUILD.it.md)**.

## Requisiti
- Mac **Apple Silicon** (M1 o più recente). I Mac Intel non sono supportati: l'inferenza usa MLX, solo Apple Silicon.
- **macOS 11** o più recente.
- **Disco**: circa 30 GB liberi per il modello (sta in `~/.cache/huggingface/hub`).
- **Internet solo al primo avvio** per scaricare il modello; poi gira tutto offline. L'unica altra
  volta in cui Gephid tocca la rete è se premi tu **Impostazioni → Modello → Cerca aggiornamenti**:
  ti dice quali file cambierebbero e quanto pesano prima di scaricare qualsiasi cosa. Nessun
  controllo automatico all'avvio.
- Per ribuildare dai sorgenti: Go e gli Xcode Command Line Tools.

### Memoria e quale modello usare
Il modello deve stare in memoria unificata, quindi il quant giusto dipende dalla tua RAM. Il default
è la versione 8-bit (`mlx-community/diffusiongemma-26B-A4B-it-8bit`, circa 26 GB su disco). Su Mac con
meno RAM, passa a un quant più leggero da **Impostazioni → Modello** (incolla un id HuggingFace o una
cartella locale). Gephid adatta da solo la lunghezza del contesto alla tua memoria, quindi su Mac più
piccoli il contesto si accorcia invece di esaurire la memoria.

| Memoria unificata | Versione consigliata | Peso su disco | Note |
|---|---|---|---|
| 64 GB o più | 8-bit (default) | ~26 GB | qualità migliore |
| 48 GB | 8-bit | ~26 GB | funziona, contesto più corto |
| 32 GB | 4-bit | ~13 GB | la 8-bit non ci sta comoda |
| 24 GB | 4-bit | ~13 GB | contesto corto |
| 16 GB | 4-bit, contesto breve | ~13 GB | al limite; meglio un modello più piccolo |

Il modello è un mixture-of-experts da 26B con 4B di parametri attivi: è veloce per la sua taglia, ma
tutti i pesi restano in memoria, quindi per la RAM conta la dimensione del quant intero, non i 4B attivi.

## Licenza
[MIT](LICENSE). Usala, modificala e ridistribuiscila liberamente.
