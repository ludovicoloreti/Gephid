#!/usr/bin/env python3
"""
diffuchat — chat web per Gephid (text diffusion, MLX).
Avvio (nel venv mlx-vlm):  ~/.venv-mlxvlm/bin/python ~/Desktop/AI/diffuchat.py
UI: temi chiaro/scuro/sistema, impostazioni (modello + percorsi), markdown.
"""
import http.server, json, threading, time, sys, os, hashlib, base64, subprocess, tempfile, uuid, io, re

# 100% offline: niente chiamate di rete a HuggingFace (il modello è già in cache).
# Senza questo, lanciata via .app (senza token HF nell'ambiente) si blocca su un controllo di rete.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
CONFIG_DIR = os.path.expanduser("~/.config/diffuchat")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULTS = {"model": "mlx-community/diffusiongemma-26B-A4B-it-8bit",
            "port": 8890, "default_steps": 32, "default_max_tokens": 32768,
            "ocr_engine": "local"}  # apple (Apple Vision) | local (GLM-OCR in-process) | omlx | paranoid (router oMLX)
STEP_MIN, STEP_MAX = 16, 64   # sotto 16 il modello a diffusione degenera su testi lunghi
TOK_MIN, TOK_MAX = 128, 32768   # max token di output per risposta (il modello si ferma all'EOS; il contesto è 256K)

def _coerce_int(v, lo, hi, default):
    try: n = int(v)
    except (TypeError, ValueError): return default
    return max(lo, min(hi, n))

def validate_config(cfg):
    """Forza tipi/limiti corretti; ignora valori non validi tenendo i default."""
    out = dict(DEFAULTS)
    if isinstance(cfg, dict):
        m = cfg.get("model")
        if isinstance(m, str) and m.strip(): out["model"] = m.strip()
        out["port"] = _coerce_int(cfg.get("port"), 1, 65535, DEFAULTS["port"])
        out["default_steps"] = _coerce_int(cfg.get("default_steps"), STEP_MIN, STEP_MAX, DEFAULTS["default_steps"])
        out["default_max_tokens"] = _coerce_int(cfg.get("default_max_tokens"), TOK_MIN, TOK_MAX, DEFAULTS["default_max_tokens"])
        oe = cfg.get("ocr_engine")
        if oe in ("apple", "local", "omlx", "paranoid"): out["ocr_engine"] = oe
    return out

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    raw = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f: raw = json.load(f)
        except Exception as e:
            print(f"config.json illeggibile, uso i default: {e}", flush=True)
    return validate_config(raw)

def save_config(cfg):
    """Scrittura atomica: tmp + os.replace, così un crash non corrompe il config."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    cfg = validate_config(cfg)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
    return cfg

CFG = load_config()
PORT = int(CFG.get("port", 8890))
MODEL = CFG.get("model", DEFAULTS["model"])

print(f"diffuchat — carico {MODEL} (~30GB)...", flush=True)
try:
    from mlx_vlm import load, stream_generate
except Exception as e:
    print(f"mlx_vlm non importabile (usa il venv ~/.venv-mlxvlm/bin/python).\n   {e}")
    sys.exit(1)

MODELO = PROC = TOK = None
OCR_MODELO = OCR_PROC = None   # GLM-OCR caricato in-process (lazy) per l'OCR self-contained
MODEL_OK = False
MODEL_ERR = ""
GEN_LOCK = threading.Lock()

def load_model():
    """Carica i pesi sul thread CHIAMANTE. DEVE essere il main thread: MLX vuole le ops del
    modello sullo stesso thread che le ha caricate. Chiamata da __main__ dopo l'avvio del server
    HTTP, così /api/health risponde subito (model_ok=false) e la finestra appare in ~1s."""
    global MODELO, PROC, TOK, MODEL_OK, MODEL_ERR
    t0 = time.time()
    try:
        MODELO, PROC = load(MODEL)
        TOK = PROC.tokenizer if hasattr(PROC, "tokenizer") else PROC
        MODEL_OK = True
        print(f"Modello caldo in {time.time()-t0:.0f}s — http://localhost:{PORT}", flush=True)
    except Exception as e:
        MODEL_ERR = str(e)
        print(f"Modello '{MODEL}' non caricato: {e}", flush=True)

# ---- Worker singolo per il modello ----
# Il server HTTP è multi-thread (ThreadingHTTPServer) per restare reattivo (static,
# health, ingest) durante lo streaming di una risposta. MLX però vuole le ops del
# modello su un solo thread: tutto il lavoro del modello passa da qui.
import queue
class Job:
    __slots__ = ("fn", "q", "cancel")
    def __init__(self, fn):
        self.fn = fn
        self.q = queue.Queue()          # eventi: ("delta",s)/("status",s)/("done",tps,dt)/("error",m)/("end",)
        self.cancel = threading.Event()  # settato dal thread HTTP se il client sparisce
JOBS = queue.Queue()
_WORKER_ALIVE = threading.Event(); _WORKER_ALIVE.set()  # il worker (main thread) sta consumando i job
JOB_EVENT_TIMEOUT = 300  # s senza alcun evento dal worker -> lo consideriamo bloccato: fallisci, non appendere all'infinito
def _model_worker():
    try:  # MLX usa stream thread-local: aggancia questo thread allo stream GPU del device
        import mlx.core as mx
        mx.set_default_stream(mx.default_stream(mx.gpu))
    except Exception as e:
        print("set_default_stream:", e, flush=True)
    try:
        while True:
            job = JOBS.get()
            try:
                job.fn(job)
            except Exception as e:
                job.q.put(("error", str(e)[:300]))
            finally:
                job.q.put(("end",))
    finally:
        _WORKER_ALIVE.clear()  # worker uscito (es. fault non gestibile): i job futuri falliscono subito invece di appendersi
def start_worker():
    threading.Thread(target=_model_worker, daemon=True, name="gephid-model").start()
def stream_job(job, emit):
    """Esegue un Job sul worker e riversa i suoi eventi sul socket via emit() (thread HTTP)."""
    if not _WORKER_ALIVE.is_set():  # worker non attivo: fallisci subito invece di appendere il client per sempre
        emit({"error": "Il motore locale non è attivo. Riavvia Gephid."}); return
    JOBS.put(job)
    while True:
        try:
            ev = job.q.get(timeout=JOB_EVENT_TIMEOUT)
        except queue.Empty:  # nessun evento per troppo tempo -> worker bloccato
            emit({"error": "Il motore locale non risponde. Riavvia Gephid."}); job.cancel.set(); break
        if ev[0] == "end": break
        ok = True
        if ev[0] == "delta": ok = emit({"delta": ev[1]})
        elif ev[0] == "status": ok = emit({"status": ev[1]})
        elif ev[0] == "diff": ok = emit({"diff": ev[1]})  # telemetria diffusione reale
        elif ev[0] == "done": ok = emit({"done": True, "tps": ev[1], "secs": ev[2]})
        elif ev[0] == "error": ok = emit({"error": ev[1]})
        if ok is False: job.cancel.set()  # client disconnesso -> ferma il worker

# Niente emoji/emoticon nell'output del modello: rimozione deterministica
# (range emoji; le frecce U+2190-21FF come "→" restano, sono testo legittimo).
# NB: il blocco U+2600-27BF (Misc Symbols + Dingbats) NON è solo emoji: contiene glifi di testo
# che il modello usa legittimamente (✓ ✗ ★ ☆ ⚠ ❯ ✦ ➤ ✱ ...). Quelli vanno protetti, altrimenti
# una checklist ("✓ fatto", "✗ errore") o un avviso ("⚠ nota") perderebbe i caratteri.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D\U000020E3]+")
# whitelist: simboli TESTUALI/funzionali che il modello usa in markdown/prosa (NON emoji decorative).
# Le emoji vere (anche ❤ ✨ ⚙ ☀ ⚡ ➡ ➕) NON sono qui -> vengono rimosse. Le frecce → (U+2192) sono
# fuori dal range di _EMOJI, quindi già salve.
_KEEP_SYMBOLS = set("✓✔✕✖✗✘"   # spunte e croci (checklist, esiti)
                    "★☆"        # stelle (rating)
                    "⚠"         # avviso
                    "❯❮❭❬➤"    # chevron / puntatori (usati come bullet)
                    "☐☑☒"       # checkbox / ballot (liste task)
                    "♀♂"        # segni biologici
                    "♪♫♩♬"      # note musicali
                    "♠♣♥♦")     # semi delle carte
def _strip_emoji(s):
    if not s:
        return s
    return _EMOJI.sub(lambda m: "".join(ch for ch in m.group(0) if ch in _KEEP_SYMBOLS), s)

def _html_to_pdf(html, footer=""):
    """Rende un documento HTML in un PDF con testo selezionabile (pymupdf/fitz Story).
    Usato dall'export chat in PDF: niente html2canvas lato browser (produceva PDF vuoti).
    `footer`: stringa stampata in fondo a OGNI pagina."""
    import fitz
    buf = io.BytesIO()
    story = fitz.Story(html=html)
    writer = fitz.DocumentWriter(buf)
    MEDIA = fitz.paper_rect("a4")
    AREA = MEDIA + (40, 40, -40, -52)  # margine inferiore extra: spazio per il footer
    more = 1
    while more:
        dev = writer.begin_page(MEDIA)
        more, _ = story.place(AREA)
        story.draw(dev)
        writer.end_page()
    writer.close()
    if not footer:
        return buf.getvalue()
    # footer in fondo a OGNI pagina: riapro il PDF e lo stampo con insert_textbox (più affidabile dello Story)
    doc = fitz.open("pdf", buf.getvalue())
    rect = fitz.Rect(40, MEDIA.height - 34, MEDIA.width - 40, MEDIA.height - 14)
    for pg in doc:
        pg.insert_textbox(rect, footer, fontsize=8, fontname="cour", color=(0.60, 0.64, 0.70), align=fitz.TEXT_ALIGN_CENTER)
    out = doc.tobytes()
    doc.close()
    return out

def genera(messages, steps, max_tokens):
    formatted = TOK.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    with GEN_LOCK:
        t0 = time.time()
        parts = []
        for c in stream_generate(MODELO, PROC, prompt=formatted,
                                 max_tokens=int(max_tokens), max_denoising_steps=int(steps),
                                 skip_special_tokens=True):
            parts.append(_strip_emoji(getattr(c, "text", "") or ""))
        dt = time.time() - t0
    text = "".join(parts).strip()
    try: ntok = len(TOK.encode(text))
    except Exception: ntok = len(text.split())
    return text, round(ntok / dt, 1) if dt > 0 else 0, round(dt, 1)

def genera_stream(messages, steps, max_tokens, on_delta, images=None, on_event=None, reveal=False, cont=False):
    """Come genera(), ma invoca on_delta(testo) per ogni blocco generato (streaming).
    Se on_delta restituisce False (client disconnesso) la generazione si ferma.
    images: lista di path immagine -> il modello le "vede" (vision-language).
    on_event(dict): telemetria di diffusione REALE per ogni chunk (step di denoising,
    blocco, draft "testo che si risolve dal rumore", tok/s) — alimenta lo stream a diffusione
    della UI con dati veri del modello invece di un timer."""
    if images:
        from mlx_vlm.prompt_utils import apply_chat_template as _vlm_tmpl
        formatted = _vlm_tmpl(PROC, getattr(MODELO, "config", None), messages, num_images=len(images))
    elif cont and messages and messages[-1].get("role") == "assistant":
        # CONTINUAZIONE: il prompt finisce col parziale assistant (turno non chiuso) -> il modello prosegue da lì
        partial = messages[-1].get("content", "") or ""
        formatted = TOK.apply_chat_template(messages[:-1], add_generation_prompt=True, tokenize=False) + partial
    else:
        formatted = TOK.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    kw = {"max_tokens": int(max_tokens), "max_denoising_steps": int(steps), "skip_special_tokens": True}
    if images: kw["image"] = images
    # "Formazione dal rumore": se reveal=True abilita gli unmasking-draft -> il modello emette
    # lo stato intermedio di ogni blocco (token rivelati + [Mask]) ad ogni 'interval' step, così
    # la UI mostra lo skeleton che si forma. Costa un po' di velocità -> è un toggle nelle Impostazioni.
    if reveal and on_event is not None:
        try:
            from mlx_vlm.generate.diffusion import is_diffusion_model
            if is_diffusion_model(MODELO):
                kw["diffusion_show_unmasking"] = True
                kw["diffusion_unmasking_interval"] = 2  # un draft ogni 2 step (fluido ma non troppo pesante)
        except Exception:
            pass
    with GEN_LOCK:
        t0 = time.time()
        parts = []
        _last_diff = None  # dedup: evita il flood di eventi 'diff' identici (stesso step/blocco)
        try:
            for c in stream_generate(MODELO, PROC, prompt=formatted, **kw):
                if on_event is not None:
                    step = int(getattr(c, "diffusion_step", 0) or 0)
                    blk = int(getattr(c, "diffusion_canvas_index", 0) or 0)
                    bdone = bool(getattr(c, "diffusion_block_complete", False))
                    is_draft = bool(getattr(c, "is_draft", False))
                    # il modello a diffusione spesso NON popola diffusion_total_steps sui chunk: uso 'steps' come totale
                    tot = int(getattr(c, "diffusion_total_steps", 0) or 0) or int(steps)
                    key = (step, blk, bdone)
                    if key != _last_diff:  # un evento per avanzamento reale (nuovo blocco / step / fine blocco)
                        _last_diff = key
                        on_event({
                            "step": step, "total_steps": tot, "block": blk, "block_done": bdone,
                            "draft": (_strip_emoji(getattr(c, "draft_text", "") or "")) if is_draft else None,
                            "tps": round(float(getattr(c, "generation_tps", 0.0) or 0.0), 1),
                        })
                delta = _strip_emoji(getattr(c, "text", "") or "")
                if delta:
                    parts.append(delta)
                    if on_delta(delta) is False:  # client sparito -> stop, non sprecare GPU
                        break
                    if _degenerate("".join(parts[-3:])):  # loop di ripetizione (step bassi) -> stop
                        break
        except Exception as e:  # rete di sicurezza: OOM GPU -> messaggio chiaro invece del traceback metal
            s = str(e)
            if "malloc" in s or "buffer size" in s or "memory" in s.lower():
                raise RuntimeError("Contesto troppo grande per la memoria della GPU. Riduci i 'Max token risposta' nelle Impostazioni o allega un documento più piccolo.")
            raise
        dt = time.time() - t0
    text = "".join(parts).strip()
    try: ntok = len(TOK.encode(text))
    except Exception: ntok = len(text.split())
    return text, round(ntok / dt, 1) if dt > 0 else 0, round(dt, 1)

_DEGEN_RUN = re.compile(r"([.,])\1{24,}")  # 25+ punti o virgole di fila (spam patologico)
def _degenerate(tail):
    """Rileva SOLO degenerazione patologica chiara: PAROLE vere ripetute all'infinito, o lunghe
    sequenze di punti/virgole. NB: NON guarda spazi/underscore/simboli né la diversità di caratteri,
    altrimenti ucciderebbe ASCII art, diagrammi, tabelle e codice allineato (legittimamente pieni di
    run di spazi/_/| e a bassa diversità)."""
    w = [x for x in tail.split() if any(c.isalnum() for c in x)]  # conta solo "parole" reali
    if len(w) >= 50 and (len(set(w)) / len(w)) < 0.20:
        return True
    if _DEGEN_RUN.search(tail):
        return True
    return False

def count_tokens(text):
    try: return len(TOK.encode(text))
    except Exception: return max(1, len(text) // 4)

# ---------- Tetto memoria GPU ----------
# Il modello a diffusione usa attenzione bidirezionale, quindi la memoria di un singolo
# buffer cresce ~ seq^2 (≈ 32 byte/token^2, calibrato sull'errore metal::malloc reale). Il limite
# non è la finestra di contesto del modello (256K) ma il max_buffer_length della GPU: oltre
# sqrt(max_buffer/32) token l'allocazione supera il buffer massimo e crasha. Teniamo un margine.
def _gpu_seq_cap():
    try:
        import mlx.core as mx, math
        di = mx.device_info()  # {'max_buffer_length': ...}
        mb = di.get("max_buffer_length")
        if mb: return int(math.sqrt(mb / 32.0))
    except Exception as e:
        print("device_info non disponibile, uso tetto prudente:", e, flush=True)
    return 28000  # fallback prudente (Mac con buffer ~48GB)
MAX_SEQ = _gpu_seq_cap()                  # limite fisico del singolo buffer di attenzione
SAFE_SEQ = max(4096, int(MAX_SEQ * 0.82)) # tetto prompt+output con margine per altri buffer
print(f"tetto sequenza GPU: MAX_SEQ={MAX_SEQ}, SAFE_SEQ={SAFE_SEQ}", flush=True)

# ---------- ALLEGATI: immagini (vision) + documenti (estrazione testo) ----------
# budget token per i documenti nel prompt: non la finestra di contesto, ma quanto la GPU regge.
# Oltre, build_doc_context comprime con map-reduce (legge tutto il documento a pezzi).
DOC_CTX = max(8000, SAFE_SEQ // 2)
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "gephid-uploads")
INGEST = {}        # id -> {"kind":"image"/"doc","name","path"(img)/"text"(doc),"tokens"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tiff"}

MAX_DECOMPRESSED = 300 * 1024 * 1024  # 300MB: difesa contro "zip bomb" in docx/xlsx
MAX_PDF_PAGES = 5000

def _html_to_text(s):
    import re, html as _h
    s = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</(p|div|tr|li|h[1-6]|table)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = _h.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", s)
    return s.strip()

def _check_zip_bomb(data):
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(i.file_size for i in z.infolist())
            if total > MAX_DECOMPRESSED:
                raise ValueError("File troppo grande una volta decompresso.")
    except zipfile.BadZipFile:
        raise ValueError("File non valido.")

def _extract_text(name, data):
    ext = os.path.splitext(name)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        if len(r.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF con troppe pagine ({len(r.pages)}).")
        return "\n\n".join((p.extract_text() or "") for p in r.pages)
    if ext == ".docx":
        _check_zip_bomb(data)
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    if ext in (".xlsx", ".xlsm"):
        _check_zip_bomb(data)
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append("### Foglio: " + str(ws.title))
            for row in ws.iter_rows(values_only=True):
                out.append("\t".join("" if c is None else str(c) for c in row))
        return "\n".join(out)
    if ext == ".eml":
        import email
        from email import policy
        msg = email.message_from_bytes(data, policy=policy.default)
        out = []
        for h in ("From", "To", "Date", "Subject"):
            if msg[h]: out.append(f"{h}: {msg[h]}")
        out.append("")
        try:
            body = msg.get_body(preferencelist=("plain", "html"))
        except Exception:
            body = None
        if body is not None:
            content = body.get_content()
            if body.get_content_type() == "text/html":
                content = _html_to_text(content)
            out.append(content)
        else:  # niente body strutturato: ripiega sul testo grezzo ripulito
            out.append(_html_to_text(data.decode("utf-8", "ignore")))
        return "\n".join(out).strip()
    return data.decode("utf-8", "ignore")  # txt/md/csv/codice/json/...

MAX_PDF_RENDER_PAGES = 8  # PDF scansionato: quante pagine rendere in immagini per la vision

def _render_pdf_to_images(fid, data):
    import pymupdf
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    doc = pymupdf.open(stream=data, filetype="pdf")
    n = min(doc.page_count, MAX_PDF_RENDER_PAGES)
    paths = []
    for i in range(n):
        pix = doc.load_page(i).get_pixmap(dpi=200)  # 200 dpi: buona resa per OCR
        p = os.path.join(UPLOAD_DIR, f"{fid}_p{i}.png")
        pix.save(p)
        paths.append(p)
    doc.close()
    return paths

# OCR: due motori selezionabili. Default "apple" = autosufficiente (Apple Vision, dentro la .app).
# "omlx" = router multi-modello potente (GLM-OCR + dots.mocr) servito da oMLX su :8000, con
# fallback automatico ad Apple Vision se il server non risponde. Si attiva con GEPHID_OCR=omlx.
# selezione motore: env GEPHID_OCR ha priorità (utile per test da shell), poi config.json
# (così è configurabile anche nella .app lanciata da GUI, dove l'env è pulito), default "apple".
OCR_ENGINE   = os.environ.get("GEPHID_OCR", CFG.get("ocr_engine", "local")).lower()
OCR_LOCAL_MODEL = os.environ.get("OCR_LOCAL_MODEL", "mlx-community/GLM-OCR-8bit")  # OCR in-process
OMLX_OCR_URL = os.environ.get("OMLX_URL", "http://127.0.0.1:8000/v1/chat/completions")
OMLX_OCR_PROMPT = ("You are a precise OCR engine. Transcribe ALL text from this page into clean "
    "GitHub-Flavored Markdown, preserving headings, lists, tables (Markdown or HTML) and math "
    "(LaTeX). Keep the original language (Italian/English). Output ONLY the Markdown, nothing else.")

def _omlx_ocr_page(model, png_path, timeout=300):
    import urllib.request
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {"model": model, "temperature": 0.0, "max_tokens": 8000, "messages": [
        {"role": "user", "content": [
            {"type": "text", "text": OMLX_OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    req = urllib.request.Request(OMLX_OCR_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
    if out.startswith("```"):                       # togli eventuali fence
        out = out.split("\n", 1)[-1]
        if out.rstrip().endswith("```"): out = out.rstrip()[:-3]
    return out.strip()

def _ocr_idnums(text):
    """Estrae token critici: identificativi (P.IVA/CF: 11/16 cifre) e importi (formato europeo)."""
    import re
    clean = "\n".join(ln for ln in text.splitlines()
                      if not re.search(r"(?i)\b(tel|fax|cell|e-?mail|web|http|www|@)", ln))
    ids = set()
    for raw in re.findall(r"\d(?:[ .\-]?\d){10,}", clean):
        d = re.sub(r"\D", "", raw)
        if len(d) in (11, 16): ids.add(d)
    amounts = set(re.findall(r"\b\d{1,3}(?:\.\d{3})+(?:,\d{2})?\b|\b\d+,\d{2}\b", clean))
    return ids, amounts

def _ocr_vote_note(reads):
    """reads: {modello: markdown}. Nota di verifica per i token NON unanimi (o '' se tutti d'accordo)."""
    n = len(reads)
    idv, amv = {}, {}
    for m, md in reads.items():
        ids, ams = _ocr_idnums(md)
        for t in ids: idv.setdefault(t, set()).add(m)
        for t in ams: amv.setdefault(t, set()).add(m)
    lines = []
    for label, v in (("identificativi", idv), ("importi", amv)):
        if v and any(len(s) < n for s in v.values()):
            items = sorted(v.items(), key=lambda kv: -len(kv[1]))
            lines.append(label + ": " + ", ".join(f"`{t}`={len(s)}/{n}" for t, s in items))
    if not lines: return ""
    return f"\n\n> ⚠ **Cifre da verificare (voto a {n} modelli):**\n> " + "\n> ".join(lines)

def _ocr_images_omlx(paths, paranoid=False):
    """Router OCR su oMLX: GLM-OCR di default; pagine strutturate (tabelle/listini) -> dots.mocr.
    Se paranoid, sulle pagine con cifre critiche fa votare 3 modelli e appende la nota di verifica."""
    import re
    out = []
    for p in paths:
        glm = _omlx_ocr_page("GLM-OCR-8bit", p)
        rows = len(re.findall(r"<tr[ >]", glm, re.I)) + sum(1 for ln in glm.splitlines() if ln.count("|") >= 2)
        nums = sum(1 for ln in glm.splitlines() if re.match(r"^\s*€?\s*\d[\d.,]*\s*%?\s*$", ln.strip()))
        md, reads = glm, {"GLM-OCR-8bit": glm}
        if rows >= 5 or nums >= 4:                  # tabelle/moduli-prezzo -> specialista layout
            try:
                dm = _omlx_ocr_page("dots.mocr-8bit", p); md = dm; reads["dots.mocr-8bit"] = dm
            except Exception: pass
        if paranoid:
            ids, ams = _ocr_idnums(glm)
            if ids or len(ams) >= 2:                # pagina con cifre critiche -> voto a 3
                if "dots.mocr-8bit" not in reads:
                    try: reads["dots.mocr-8bit"] = _omlx_ocr_page("dots.mocr-8bit", p)
                    except Exception: pass
                try: reads["olmOCR-2-8bit"] = _omlx_ocr_page("olmOCR-2-8bit", p)
                except Exception: pass
                md = md + _ocr_vote_note(reads)
        out.append(md)
    return "\n\n".join(out).strip()

def run_on_worker(fn):
    """Esegue fn() sul thread-worker del modello (lo stesso della chat) e ne ritorna il risultato.
    Serializza OCR e generazione: mai concorrenti sulla GPU → niente contesa, niente impallamento.
    Bloccante; chiamato dal thread HTTP dell'ingest."""
    box = {}
    def job_fn(job):
        box["val"] = fn()
    job = Job(job_fn)
    if not _WORKER_ALIVE.is_set(): raise RuntimeError("motore locale non attivo")
    JOBS.put(job)
    while True:
        try:
            ev = job.q.get(timeout=JOB_EVENT_TIMEOUT)
        except queue.Empty:
            raise RuntimeError("il motore locale non risponde")
        if ev[0] == "error": box["err"] = ev[1]
        if ev[0] == "end": break
    if "err" in box: raise RuntimeError(box["err"])
    return box.get("val", "")

def _ensure_ocr_model():
    """Carica GLM-OCR in-process al primo uso. DEVE girare sul worker (MLX: ops sul thread che carica)."""
    global OCR_MODELO, OCR_PROC
    if OCR_MODELO is None:
        print(f"OCR locale: carico {OCR_LOCAL_MODEL} (~1GB)…", flush=True)
        OCR_MODELO, OCR_PROC = load(OCR_LOCAL_MODEL)
        print("OCR locale pronto.", flush=True)

def _ocr_page_inproc(path):
    """OCR di una pagina con GLM-OCR in-process. Da chiamare sul worker, dentro GEN_LOCK."""
    from mlx_vlm.prompt_utils import apply_chat_template as _vlm_tmpl
    messages = [{"role": "user", "content": OMLX_OCR_PROMPT}]
    formatted = _vlm_tmpl(OCR_PROC, getattr(OCR_MODELO, "config", None), messages, num_images=1)
    parts = []
    for c in stream_generate(OCR_MODELO, OCR_PROC, prompt=formatted, image=[path], max_tokens=6000):
        parts.append(getattr(c, "text", "") or "")
    out = "".join(parts).strip()
    if out.startswith("```"):
        out = out.split("\n", 1)[-1]
        if out.rstrip().endswith("```"): out = out.rstrip()[:-3]
    return out.strip()

def _ocr_images_local(paths):
    """OCR self-contained: GLM-OCR nel processo di Gephid, eseguito sul worker del modello.
    Niente server esterni, niente seconda GPU-engine: OCR e chat si alternano sullo stesso thread."""
    def work():
        _ensure_ocr_model()
        out = []
        with GEN_LOCK:
            for p in paths:
                out.append(_ocr_page_inproc(p))
        return "\n\n".join(out).strip()
    return run_on_worker(work)

def _ocr_images_apple(paths):
    """OCR nativo macOS (Apple Vision, offline). Ritorna il testo riconosciuto."""
    try:
        from ocrmac import ocrmac
    except Exception as e:
        print("ocrmac non disponibile:", e, flush=True); return ""
    out = []
    for p in paths:
        try:
            res = ocrmac.OCR(p, language_preference=["it-IT", "en-US"]).recognize()
            out.append("\n".join(t[0] for t in res))
        except Exception:
            pass
    return "\n\n".join(out).strip()

def _ocr_images(paths):
    """Dispatcher OCR: 'local' = GLM-OCR in-process (self-contained); 'omlx'/'paranoid' = router
    oMLX esterno; default Apple Vision. Tutti con fallback ad Apple Vision in caso di problemi."""
    if OCR_ENGINE == "local":
        try:
            txt = _ocr_images_local(paths)
            if txt.strip():
                print("OCR locale in-process (GLM-OCR)", flush=True)
                return txt
            print("OCR locale vuoto → fallback Apple Vision", flush=True)
        except Exception as e:
            print("OCR locale fallito → fallback Apple Vision:", e, flush=True)
    elif OCR_ENGINE in ("omlx", "paranoid"):
        try:
            txt = _ocr_images_omlx(paths, paranoid=(OCR_ENGINE == "paranoid"))
            if txt.strip():
                print(f"OCR via router oMLX ({OCR_ENGINE})", flush=True)
                return txt
            print("OCR oMLX vuoto → fallback Apple Vision", flush=True)
        except Exception as e:
            print("OCR oMLX non raggiungibile → fallback Apple Vision:", e, flush=True)
    return _ocr_images_apple(paths)

def ingest_file(name, data):
    fid = uuid.uuid4().hex[:12]
    ext = os.path.splitext(name)[1].lower()
    if len(INGEST) > 24:  # cap memoria: scarta i più vecchi
        for k in list(INGEST)[:len(INGEST) - 24]: INGEST.pop(k, None)
    if ext in IMG_EXT:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        path = os.path.join(UPLOAD_DIR, fid + ext)
        with open(path, "wb") as f: f.write(data)
        INGEST[fid] = {"kind": "image", "name": name, "paths": [path]}
        return {"id": fid, "kind": "image", "name": name}
    if ext == ".pdf":
        text = _extract_text(name, data)
        if text.strip():
            INGEST[fid] = {"kind": "doc", "name": name, "text": text, "tokens": count_tokens(text)}
            return {"id": fid, "kind": "doc", "name": name, "tokens": INGEST[fid]["tokens"], "chars": len(text)}
        # PDF scansionato (nessun testo digitale): rendi le pagine in immagini
        paths = _render_pdf_to_images(fid, data)
        if not paths: raise ValueError("PDF vuoto o non leggibile.")
        ocr = _ocr_images(paths)  # OCR nativo Apple Vision: prova a estrarre testo (economico, riusabile)
        if len(ocr) >= 8:
            for p in paths:  # testo ottenuto: non servono più le immagini
                try: os.remove(p)
                except Exception: pass
            INGEST[fid] = {"kind": "doc", "name": name, "text": ocr, "tokens": count_tokens(ocr), "ocr": True}
            return {"id": fid, "kind": "doc", "name": name, "tokens": INGEST[fid]["tokens"], "chars": len(ocr), "ocr": True}
        # OCR vuoto (es. solo foto/grafica): usa la vision sulle immagini
        INGEST[fid] = {"kind": "image", "name": name, "paths": paths}
        return {"id": fid, "kind": "image", "name": name, "pages": len(paths)}
    text = _extract_text(name, data)
    if not text.strip():
        raise ValueError("Nessun testo estraibile da questo file.")
    INGEST[fid] = {"kind": "doc", "name": name, "text": text, "tokens": count_tokens(text)}
    return {"id": fid, "kind": "doc", "name": name, "tokens": INGEST[fid]["tokens"], "chars": len(text)}

def _chunk_by_chars(text, n):
    return [text[i:i + n] for i in range(0, len(text), n)]

MR_MAX_CHUNKS = 50      # oltre questi pezzi non chiamiamo il modello centinaia di volte
# Pezzi grandi = meno passaggi = più veloce (il modello è uno solo, su una GPU: i pezzi si
# elaborano in serie, non in parallelo). ~7000 token/pezzo sta comodo sotto il tetto GPU.
MR_CHUNK_CHARS = 28000  # ~7000 token a pezzo
MR_CHUNK_TOK = 7000
SUMMARY_CACHE = {}      # (doc_id, budget) -> riassunto, per non ri-comprimere lo stesso doc

def _truncate_head_tail(text, approx_tok):
    half = max(1000, approx_tok * 2)  # ~4 char/token, metà testa metà coda
    if len(text) <= half * 2: return text
    return text[:half] + "\n\n[...porzione centrale omessa...]\n\n" + text[-half:]

def map_reduce_summarize(text, budget_tok, on_status, cancel=None, depth=0):
    """Comprime un testo grande con map-reduce, con tetti per non bloccare l'app."""
    if count_tokens(text) <= budget_tok:
        return text
    if depth >= 3:  # niente compressione infinita: tronca testa+coda
        on_status("Documento enorme: tengo le porzioni iniziali e finali…")
        return _truncate_head_tail(text, budget_tok)
    chunks = _chunk_by_chars(text, MR_CHUNK_CHARS)
    if len(chunks) > MR_MAX_CHUNKS:  # troppi pezzi -> campiona testa+coda prima di riassumere
        on_status(f"Documento enorme ({len(chunks)} parti): tengo le porzioni principali…")
        text = _truncate_head_tail(text, MR_MAX_CHUNKS * MR_CHUNK_TOK)
        chunks = _chunk_by_chars(text, MR_CHUNK_CHARS)
    pass_label = "Rileggo per condensare" if depth else "Leggo il documento"  # i giri successivi ricomprimono
    on_status(f"{pass_label}: troppo grande per leggerlo tutto insieme, lo divido in {len(chunks)} parti…")
    summaries = []
    for i, ch in enumerate(chunks):
        if cancel is not None and cancel.is_set(): break
        on_status(f"{pass_label} e riassumo: parte {i + 1} di {len(chunks)}…")
        s, _, _ = genera([{"role": "user", "content": "Riassumi in italiano, in modo fedele e denso, mantenendo dati/numeri/nomi e fatti chiave, questo estratto di documento:\n\n" + ch}], 16, 900)
        summaries.append(s)
    combined = "\n".join(summaries)
    if count_tokens(combined) >= count_tokens(text):  # nessun progresso: tronca e basta
        return _truncate_head_tail(combined, budget_tok)
    if count_tokens(combined) > budget_tok:
        return map_reduce_summarize(combined, budget_tok, on_status, cancel, depth + 1)
    return combined

def build_doc_context(doc_ids, on_status, cancel=None):
    """Assembla il testo dei documenti allegati entro DOC_CTX (map-reduce se serve, con cache)."""
    docs = [(i, INGEST[i]["name"], INGEST[i]["text"]) for i in doc_ids if i in INGEST and INGEST[i]["kind"] == "doc"]
    if not docs: return ""
    combined = "\n\n".join(f"===== DOCUMENTO: {n} =====\n{t}" for _, n, t in docs)
    if count_tokens(combined) <= DOC_CTX:
        return combined
    per = max(2000, DOC_CTX // len(docs))
    parts = []
    for i, n, t in docs:
        key = (i, per)
        if key not in SUMMARY_CACHE:
            SUMMARY_CACHE[key] = map_reduce_summarize(t, per, on_status, cancel)
        parts.append(f"===== DOCUMENTO: {n} (compresso) =====\n" + SUMMARY_CACHE[key])
    return "\n\n".join(parts)

# ---- Gestione contesto: finestra scorrevole + riassunto cumulativo ----
# Il contesto di Gephid è limitato: rimandare tutta la cronologia a ogni
# turno lo riempie in fretta. Il frontend tiene la storia completa (per l'export),
# ma al modello passiamo solo: [riassunto delle parti vecchie] + [ultimi N integrali].
# Il riassunto si aggiorna a blocchi (ogni FOLD_AT messaggi invecchiati), non ad ogni turno.
KEEP = 12         # ultimi messaggi tenuti integrali (il modello regge 256K, quindi siamo larghi)
FOLD_AT = 8       # quando i messaggi invecchiati raggiungono questa soglia, vengono riassunti
CTX_BUDGET = min(32768, SAFE_SEQ - 2048)  # tetto token del prompt; non superare il limite GPU (~seq^2)
MAX_SESS = 32     # quante sessioni di memoria tenere in RAM
SUMMARY_PREFIX = "[Contesto delle parti precedenti della conversazione, da ricordare]:\n"
SESSIONS = {}     # chat_id -> {"covered": int, "summary": str, "fp": str}

def _clean(messages):
    """Tiene solo messaggi ben formati user/assistant con content stringa (evita KeyError)."""
    out = []
    for m in (messages or []):
        if isinstance(m, dict):
            r, c = m.get("role"), m.get("content")
            if r in ("user", "assistant") and isinstance(c, str):
                out.append({"role": r, "content": c})
    return out

def _fp(msgs):
    """Fingerprint della regione già riassunta: se cambia (edit/regen/nuova chat) si resetta."""
    h = hashlib.md5()
    for m in msgs:
        h.update((m["role"] + "\x1f" + m["content"]).encode("utf-8", "ignore"))
    return h.hexdigest()

def _merge_roles(msgs):
    out = []
    for m in msgs:
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n\n" + m["content"]
        else:
            out.append({"role": m["role"], "content": m["content"]})
    while out and out[0]["role"] == "assistant":
        out.pop(0)
    return out

def _ntok(msgs):
    try: return len(TOK.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True))
    except Exception: return sum(len(m["content"]) // 4 for m in msgs) + 8 * len(msgs)

def _trim_budget(fed):
    """Se si sfora il budget, taglia i messaggi più vecchi dal centro tenendo riassunto + ultimo."""
    while len(fed) > 2 and _ntok(fed) > CTX_BUDGET:
        drop = 1 if fed[0]["content"].startswith(SUMMARY_PREFIX) else 0
        if drop >= len(fed) - 1: break
        fed.pop(drop)
    return fed

def _fit_prompt(msgs, cap_tok):
    """Garanzia anti-OOM: l'attenzione del modello a diffusione cresce ~seq^2, quindi il prompt
    non può superare cap_tok token (oltre, la GPU non alloca il buffer). Se sfora, riduce
    testa+coda dell'ULTIMO messaggio (quello che porta il contesto dei documenti)."""
    if not msgs or _ntok(msgs) <= cap_tok:
        return msgs
    base = _ntok(msgs[:-1]) if len(msgs) > 1 else 0
    room = max(500, cap_tok - base - 256)  # token lasciati all'ultimo messaggio
    out = msgs
    for _ in range(5):
        last = dict(msgs[-1]); last["content"] = _truncate_head_tail(msgs[-1]["content"], room)
        out = msgs[:-1] + [last]
        if _ntok(out) <= cap_tok: break
        room = int(room * 0.7)
    return out

def _summarize(prev, msgs):
    tr = "\n".join((("Utente: " if m["role"] == "user" else "Assistente: ") + m["content"]) for m in msgs)
    base = ("Aggiorna il RIASSUNTO della conversazione integrando i nuovi scambi. "
            "Mantieni in italiano fatti chiave, nomi, numeri, decisioni e stato attuale; "
            "sii conciso (max ~150 parole). Restituisci solo il riassunto aggiornato.\n\n")
    if prev: base += "RIASSUNTO ATTUALE:\n" + prev + "\n\n"
    base += "NUOVI SCAMBI:\n" + tr
    text, _, _ = genera([{"role": "user", "content": base}], 20, 400)
    return text.strip()

def fit_context(messages, chat_id="default", on_status=None):
    msgs = _clean(messages)
    if not msgs: return msgs
    if chat_id not in SESSIONS and len(SESSIONS) >= MAX_SESS:
        SESSIONS.clear()  # cap memoria: scarta le vecchie sessioni
    s = SESSIONS.setdefault(chat_id, {"covered": 0, "summary": "", "fp": ""})
    # reset se la storia si è accorciata o la regione già riassunta è cambiata (nuova chat / edit / regen)
    if len(msgs) < s["covered"] or _fp(msgs[:s["covered"]]) != s["fp"]:
        s.update(covered=0, summary="", fp="")
    if len(msgs) <= KEEP:
        return _merge_roles(msgs)
    end = len(msgs) - KEEP
    aged = msgs[s["covered"]:end]
    if len(aged) >= FOLD_AT:
        fold_end = s["covered"] + (len(aged) - len(aged) % 2)  # solo coppie (utente,assistente) complete
        if on_status: on_status("comprimo la memoria della conversazione…")  # indicatore per la UI
        try:
            s["summary"] = _summarize(s["summary"], msgs[s["covered"]:fold_end])
            s["covered"] = fold_end
            s["fp"] = _fp(msgs[:fold_end])
        except Exception as e:
            print(f"riassunto fallito, ritento al prossimo turno: {e}", flush=True)
        aged = msgs[s["covered"]:end]  # se il fold è fallito, restano integrali
    fed = []
    if s["summary"]:
        fed.append({"role": "user", "content": SUMMARY_PREFIX + s["summary"]})
    fed += aged + msgs[end:]
    return _merge_roles(_trim_budget(fed))

def list_local_models():
    """Elenca i modelli a DIFFUSIONE già presenti sul Mac (gli unici che Gephid può usare):
    cache HuggingFace + LM Studio. Filtra fuori Qwen/Gemma/Whisper ecc. (incompatibili)."""
    out, seen = [], set()
    def is_diff(s): return "diffusion" in s.lower()
    hub = os.path.expanduser("~/.cache/huggingface/hub")
    if os.path.isdir(hub):
        for d in sorted(os.listdir(hub)):
            if not d.startswith("models--"): continue
            snap = os.path.join(hub, d, "snapshots")
            if not (os.path.isdir(snap) and os.listdir(snap)): continue  # scaricato davvero
            hid = d[len("models--"):].replace("--", "/")
            if is_diff(hid) and hid not in seen:
                seen.add(hid); out.append({"id": hid, "label": hid})
    lms = os.path.expanduser("~/.lmstudio/models")
    if os.path.isdir(lms):
        for pub in sorted(os.listdir(lms)):
            pp = os.path.join(lms, pub)
            if not os.path.isdir(pp): continue
            for repo in sorted(os.listdir(pp)):
                p = os.path.join(pp, repo)
                if not is_diff(repo): continue
                try: files = os.listdir(p)
                except Exception: continue
                if any(f.endswith(".safetensors") for f in files):
                    out.append({"id": p, "label": pub + "/" + repo + "  (LM Studio)"})
    return out

# ---------- Downloader del modello (primo avvio) ----------
# È l'UNICO momento in cui Gephid usa la rete: scarica il modello una volta, poi 100% offline.
_DL = {"got": 0, "total": 0, "active": False, "cancel": False}
_DL_LOCK = threading.Lock()  # rende atomico il check-and-set del download
_NEEDS_DL = None  # memoizzato: True se il modello non è ancora su disco

def model_cached(repo):
    """True se il modello è già su disco (cartella locale o cache HF completa)."""
    try:
        if os.path.isdir(os.path.expanduser(repo)):
            return any(f.endswith(".safetensors") for f in os.listdir(os.path.expanduser(repo)))
        from huggingface_hub import snapshot_download
        snapshot_download(repo, local_files_only=True)
        return True
    except Exception:
        return False

def download_model_stream(emit):
    """Scarica MODEL da HuggingFace con progresso (GB/%/velocità). Pausa via _DL['cancel']."""
    import threading, time as _t
    os.environ["HF_HUB_OFFLINE"] = "0"; os.environ["TRANSFORMERS_OFFLINE"] = "0"
    try:
        from huggingface_hub import constants as _hc; _hc.HF_HUB_OFFLINE = False
    except Exception: pass
    from huggingface_hub import snapshot_download, HfApi
    from huggingface_hub.utils import tqdm as _hf_tqdm
    try:
        info = HfApi().model_info(MODEL, files_metadata=True)
        total = sum((s.size or 0) for s in info.siblings)
    except Exception:
        total = 0
    _DL.update(got=0, total=total, active=True, cancel=False)
    class _P(_hf_tqdm):
        def update(self, n=1):
            # somma solo le barre in byte (download file), non quella conta-file
            if getattr(self, "unit", "") in ("B", "iB") or (getattr(self, "total", 0) or 0) > 100000:
                _DL["got"] += n
            if _DL["cancel"]: raise KeyboardInterrupt("paused")
            return super().update(n)
    stop = threading.Event()
    def pump():
        last = (_DL["got"], _t.time())
        while not stop.is_set():
            _t.sleep(0.5)
            now = _t.time(); g = _DL["got"]; tot = _DL["total"] or 1
            speed = (g - last[0]) / max(1e-6, now - last[1]); last = (g, now)
            emit({"gotGB": round(g / 1e9, 1), "totalGB": round(tot / 1e9, 1),
                  "pct": min(100, int(g / tot * 100)), "speed": round(speed / 1e6, 1)})
    th = threading.Thread(target=pump, daemon=True); th.start()
    try:
        snapshot_download(MODEL, tqdm_class=_P)
        emit({"downloaded": True})
    except KeyboardInterrupt:
        emit({"paused": True, "gotGB": round(_DL["got"] / 1e9, 1)})
    except Exception as e:
        emit({"error": str(e)[:200]})
    finally:
        stop.set(); _DL["active"] = False
        os.environ["HF_HUB_OFFLINE"] = "1"; os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from huggingface_hub import constants as _hc2; _hc2.HF_HUB_OFFLINE = True
        except Exception: pass

def config_payload():
    return {"model": CFG["model"], "loaded_model": MODEL,
            "default_steps": CFG["default_steps"], "default_max_tokens": CFG["default_max_tokens"],
            "ocr_engine": CFG.get("ocr_engine", "apple"),
            "paths": {"config": CONFIG_PATH, "python": sys.executable,
                      "script": os.path.abspath(__file__),
                      "hf_cache": os.path.expanduser("~/.cache/huggingface/hub")}}

# HTML in stringa normale (mai f-string).
PAGE = r"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Gephid</title>
<script src="/static/marked.min.js"></script>
<script src="/static/purify.min.js"></script>
<script src="/static/html2pdf.bundle.min.js"></script>
<link rel="stylesheet" href="/static/katex.min.css">
<script src="/static/katex.min.js"></script>
<script src="/static/auto-render.min.js"></script>
<style>
  [data-theme="dark"]{--bg:#0b0e14;--panel:#141925;--panel2:#1c2333;--text:#e6edf3;--accent:#4169e1;--accent-text:#8ab0ff;--accent-ink:#fff;--dim:#8b98a5;--border:#222b3a;--shadow:rgba(0,0,0,.45);--ubub:#4169e1;--utext:#fff}
  [data-theme="light"]{--bg:#f4f6f9;--panel:#fff;--panel2:#eef1f6;--text:#1a1f29;--accent:#4169e1;--accent-text:#2f54c9;--accent-ink:#fff;--dim:#5d6675;--border:#dde3ec;--shadow:rgba(0,0,0,.12);--ubub:#4169e1;--utext:#fff}
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;transition:background .2s,color .2s}
  header{padding:12px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:11px;background:var(--panel)}
  header .logo{width:30px;height:30px;flex:none}
  header h1{font-size:1.02rem;margin:0;font-weight:600}
  header .badge{font-size:.66rem;color:var(--dim);background:var(--panel2);border-radius:6px;padding:3px 8px}
  header .sp{margin-left:auto}
  .iconbtn{background:transparent;border:1px solid var(--border);color:var(--dim);width:36px;height:36px;border-radius:10px;cursor:pointer;font-size:1.1rem;display:flex;align-items:center;justify-content:center}
  .iconbtn:hover{color:var(--accent);border-color:var(--accent)}
  .txtbtn{background:transparent;border:1px solid var(--border);color:var(--dim);height:36px;padding:0 14px;border-radius:10px;cursor:pointer;font-size:.85rem;font-family:inherit}
  .txtbtn:hover{color:var(--accent);border-color:var(--accent)}
  #chat{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:15px;max-width:min(1100px,92vw);width:100%;margin:0 auto}
  .msg{padding:12px 16px;border-radius:14px;max-width:82%;line-height:1.5;word-wrap:break-word;position:relative}
  .msgexp{position:absolute;top:6px;right:8px;opacity:0;background:var(--bg);border:1px solid var(--border);color:var(--dim);width:24px;height:24px;border-radius:7px;cursor:pointer;font-size:.72rem;display:flex;align-items:center;justify-content:center;transition:opacity .15s}
  .msg:hover .msgexp{opacity:.85}.msgexp:hover{color:var(--accent);opacity:1}
  .msgactions{display:flex;gap:6px;margin-top:9px}
  .actbtn{display:flex;align-items:center;gap:4px;background:transparent;border:1px solid var(--border);color:var(--dim);border-radius:7px;padding:3px 9px;font-size:.72rem;cursor:pointer;font-family:inherit;line-height:1.4}
  .actbtn:hover{color:var(--accent);border-color:var(--accent)}.actbtn svg{width:12px;height:12px}
  .user .actbtn{border-color:rgba(255,255,255,.35);color:rgba(255,255,255,.85)}
  .user .actbtn:hover{border-color:#fff;color:#fff}
  .exportmenu{position:fixed;background:var(--panel);border:1px solid var(--border);border-radius:11px;box-shadow:0 10px 34px var(--shadow);padding:6px;display:none;z-index:30;min-width:150px}
  .exportmenu.on{display:block}
  .exportmenu button{display:block;width:100%;text-align:left;background:transparent;border:none;color:var(--text);padding:9px 12px;border-radius:8px;cursor:pointer;font-size:.86rem}
  .exportmenu button:hover{background:var(--panel2);color:var(--accent)}
  .user{align-self:flex-end;background:var(--ubub);color:var(--utext);border-bottom-right-radius:4px;white-space:pre-wrap}
  .assistant{align-self:flex-start;background:var(--panel2);border-bottom-left-radius:4px}
  .assistant .tps{display:block;margin-top:8px;font-size:.72rem;color:var(--accent-text)}
  .thinking{align-self:flex-start;color:var(--dim);font-style:italic;display:flex;flex-direction:column;gap:8px}
  .bar{height:4px;width:180px;border-radius:3px;background:var(--panel2);overflow:hidden;position:relative}
  .bar::after{content:'';position:absolute;top:0;left:-40%;width:40%;height:100%;background:var(--accent);border-radius:3px;animation:slide 1.05s ease-in-out infinite}
  @keyframes slide{0%{left:-40%}100%{left:100%}}
  .caret{display:inline-block;width:7px;height:1em;background:var(--accent);margin-left:3px;vertical-align:text-bottom;border-radius:1px;animation:blink .9s steps(2,start) infinite}
  @keyframes blink{to{opacity:0}}
  /* overlay d'avvio: copre la UI finché /api/health non dice model_ok (il modello sale in RAM) */
  #bootov{position:fixed;inset:0;z-index:200;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;text-align:center;padding:40px;transition:opacity .4s}
  #bootov.gone{opacity:0;pointer-events:none}
  #bootov .bt{font-size:1.3rem;font-weight:600;color:var(--text)}
  #bootov .bm{color:var(--dim);max-width:520px;line-height:1.6;font-size:.9rem}
  #bootov .bsp{width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:bspin 1s linear infinite}
  @keyframes bspin{to{transform:rotate(360deg)}}
  .katex{font-size:1.04em}.katex-display{overflow-x:auto;overflow-y:hidden;padding:2px 0}
  .compactsug{align-self:center;font-size:.82rem;color:var(--dim);background:var(--panel2);border:1px dashed var(--border);border-radius:11px;padding:8px 14px;margin-top:2px;text-align:center}
  .compactsug a{color:var(--accent-text);font-weight:600;cursor:pointer}.compactsug a:hover{text-decoration:underline}
  .assistant p{margin:.5em 0}.assistant p:first-child{margin-top:0}.assistant p:last-child{margin-bottom:0}
  .assistant ul,.assistant ol{margin:.5em 0;padding-left:1.4em}.assistant li{margin:.2em 0}
  .assistant h1,.assistant h2,.assistant h3{margin:.6em 0 .3em;font-size:1.08em}
  .assistant a{color:var(--accent-text)}.assistant strong{font-weight:700}
  code,pre{background:var(--bg);border:1px solid var(--border);border-radius:6px;font-family:'SF Mono',monospace;font-size:.88em}
  code{padding:1px 5px}pre{padding:12px;overflow-x:auto}pre code{border:0;padding:0}
  footer{border-top:1px solid var(--border);background:var(--panel);padding:11px 18px}
  .composer{max-width:min(1100px,92vw);margin:0 auto;position:relative}
  .inputwrap{position:relative}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
  .chip{display:flex;align-items:center;gap:6px;background:var(--panel2);border:1px solid var(--border);border-radius:9px;padding:4px 8px;font-size:.75rem;color:var(--text);max-width:260px}
  .chip img{width:26px;height:26px;object-fit:cover;border-radius:5px;flex:none}
  .chip .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .chip .tk{color:var(--dim);flex:none}
  .chip .x{cursor:pointer;color:var(--dim);font-weight:700;flex:none}.chip .x:hover{color:var(--accent)}
  /* stati allegato: caricamento (spinner + "Leggo… (Ns)") -> pronto (pop + ✓ + token) */
  @keyframes chpop{0%{transform:scale(.92)}55%{transform:scale(1.05)}100%{transform:scale(1)}}
  .chip .spin{width:11px;height:11px;border-radius:50%;border:2px solid var(--accent);border-top-color:transparent;animation:bspin .7s linear infinite;flex:none}
  .chip.loading{border-color:var(--accent)}
  .chip.loading .nm{color:var(--accent-text)}
  .chip .tk.load{color:var(--accent-text)}
  .chip .ok{color:var(--accent-text);font-weight:700;flex:none}
  .chip.ready{animation:chpop .3s ease-out}
  .attrow{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
  .attchip{display:flex;align-items:center;gap:5px;background:rgba(255,255,255,.2);border-radius:8px;padding:3px 8px;font-size:.74rem}
  .attchip img{width:24px;height:24px;object-fit:cover;border-radius:4px}
  #inp{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:14px;color:var(--text);padding:13px 46px 13px 82px;font-size:1rem;resize:none;font-family:inherit;line-height:1.4;max-height:170px;overflow-y:auto}
  #inp:focus{outline:none;border-color:var(--accent)}
  .cbtn{position:absolute;bottom:8px;width:30px;height:30px;background:transparent;border:1px solid var(--border);color:var(--dim);border-radius:9px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
  .cbtn:hover{color:var(--accent);border-color:var(--accent)}
  .cbtn svg{width:16px;height:16px}
  #attach{left:8px}#mic{left:44px;display:none}
  #mic.rec{color:#fff;background:#e0245e;border-color:#e0245e}
  #send{position:absolute;right:8px;bottom:8px;width:30px;height:30px;background:var(--accent);color:var(--accent-ink);border:1px solid var(--accent);border-radius:9px;font-size:1rem;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:1;transition:opacity .15s}
  #send:disabled{opacity:.35;cursor:not-allowed}
  #send svg{width:16px;height:16px;display:block}
  /* mentre legge il documento: il bottone invia diventa uno spinner (stato di lavoro) */
  #send.loading{opacity:1;cursor:default;color:transparent}
  #send.loading::after{content:'';position:absolute;left:50%;top:50%;width:15px;height:15px;margin:-7.5px 0 0 -7.5px;border-radius:50%;border:2px solid var(--accent-ink);border-top-color:transparent;animation:bspin .7s linear infinite}
  /* a una riga: pulsanti centrati verticalmente; quando la textarea cresce: ancorati in basso */
  .cbtn,#send{top:50%;bottom:auto;transform:translateY(-50%)}
  .composer.grown .cbtn,.composer.grown #send{top:auto;bottom:8px;transform:none}
  /* modal impostazioni */
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;align-items:center;justify-content:center;z-index:10}
  .overlay.on{display:flex}
  .modal{background:var(--panel);border:1px solid var(--border);border-radius:16px;width:min(560px,92vw);max-height:88vh;overflow-y:auto;box-shadow:0 20px 60px var(--shadow)}
  .modal header{border-radius:16px 16px 0 0}
  .modal .body{padding:18px 22px}
  .modal h3{margin:18px 0 8px;font-size:.82rem;text-transform:uppercase;letter-spacing:.5px;color:var(--dim)}
  .modal h3:first-child{margin-top:0}
  .seg{display:flex;gap:6px}
  .seg button{flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:9px;border-radius:10px;cursor:pointer;font-size:.9rem}
  .seg button.active{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:600}
  .row{display:flex;align-items:center;gap:10px;margin:8px 0}
  .row label{font-size:.85rem;min-width:130px;color:var(--dim)}
  .row input[type=text],.row input[type=number],.row select{flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 10px;font-family:inherit}
  .row select{cursor:pointer}
  .stepper{display:inline-flex;align-items:center;border:1px solid var(--border);border-radius:10px;overflow:hidden}
  .stepper button{background:var(--bg);border:none;color:var(--text);width:42px;height:38px;font-size:1.4rem;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center}
  .stepper button:hover{background:var(--panel2);color:var(--accent)}
  .stepper .sval{min-width:72px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums;padding:0 6px}
  .adv{margin:6px 0}
  .adv summary{cursor:pointer;font-size:.78rem;color:var(--accent-text);list-style:none;user-select:none}
  .adv summary::-webkit-details-marker{display:none}
  .adv summary::before{content:"▸ "}.adv[open] summary::before{content:"▾ "}
  .paths{font-size:.74rem;color:var(--dim);background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:10px 12px;line-height:1.7;word-break:break-all}
  .paths b{color:var(--text)}
  .hint{font-size:.76rem;color:var(--dim);line-height:1.5;margin:0 0 8px;overflow-wrap:normal;word-break:normal}
  .savebtn{background:var(--accent);color:var(--accent-ink);border:none;border-radius:10px;padding:10px 16px;font-weight:700;cursor:pointer;margin-top:6px}
  .inlinebtn{display:inline-block;margin-top:10px;background:var(--accent);color:var(--accent-ink);border:none;border-radius:9px;padding:7px 13px;font-size:.82rem;font-weight:600;cursor:pointer;font-family:inherit}
  .inlinebtn:disabled{opacity:.6;cursor:default}
  .note{font-size:.78rem;color:var(--accent-text);margin-top:8px;display:none}
  .row{flex-wrap:wrap}
  /* area cliccabile più comoda per la × delle chip (senza ingrandirne il glifo) */
  .chip .x{padding:2px 4px;margin:-2px -2px -2px 0}
  /* --- rifiniture UI/UX (review) --- */
  *:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  #chat{overflow-x:hidden}
  .msg{overflow-wrap:anywhere}
  .assistant table{display:block;max-width:100%;overflow-x:auto;border-collapse:collapse;margin:.5em 0}
  .assistant th,.assistant td{border:1px solid var(--border);padding:6px 10px}
  .user .msgactions{justify-content:flex-end}
  .attchip{background:rgba(0,0,0,.26)}
  .errbubble{align-self:center;background:transparent;border:1px solid var(--border);color:var(--dim);font-size:.85rem;max-width:min(82%,640px);padding:10px 14px;border-radius:11px}
  header h1{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
  header .badge,header .txtbtn,header .iconbtn{flex:none}
  .stepper button:active{background:var(--panel2)}
  .stepper button:disabled{opacity:.4;cursor:default}
  @media (prefers-reduced-motion: reduce){ .bar::after,.caret,.sp,.chip .spin,#send.loading::after,.chip.ready{animation:none} .caret{opacity:.6} }
</style></head>
<body>
  <header>
    <span class="logo">__LOGO__</span>
    <h1>Gephid</h1><span class="badge">offline · MLX</span>
    <span class="sp"></span>
    <button class="txtbtn" id="newchat" title="Nuova chat" aria-label="Nuova chat">Nuova chat</button>
    <button class="txtbtn" id="export" title="Esporta tutta la chat" aria-label="Esporta la chat">Esporta</button>
    <button class="txtbtn" id="gear" title="Impostazioni" aria-label="Impostazioni">Impostazioni</button>
  </header>

  <div id="bootov">
    <span class="logo">__LOGO__</span>
    <div class="bt">Carico il modello…</div>
    <div class="bsp"></div>
    <div class="bm" id="bootmsg">Primo avvio: il modello a diffusione sale in memoria. Ci vuole qualche secondo.</div>
  </div>

  <div id="chat">
    <div class="msg assistant">Ciao! Sono <b>Gephid</b>, giro 100% offline sul tuo Mac.
Genero il testo "a blocchi" via diffusione. Chiedimi qualcosa!</div>
  </div>

  <footer>
    <div class="composer">
      <div id="chips" class="chips"></div>
      <div class="inputwrap">
        <textarea id="inp" rows="1" placeholder="Carico il modello…" disabled autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"></textarea>
        <button id="attach" class="cbtn" title="Allega immagini o documenti" aria-label="Allega immagini o documenti"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7.07-7.07l8.49-8.49a3.5 3.5 0 0 1 4.95 4.95l-8.49 8.49a1.5 1.5 0 0 1-2.12-2.12l7.78-7.78"/></svg></button>
        <button id="mic" class="cbtn" title="Dettatura (macOS): premi per avviare, ripremi per fermare" aria-label="Dettatura vocale" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2.5" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>
        <button id="send" title="Invia" aria-label="Invia messaggio"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button>
      </div>
      <input type="file" id="fileinput" multiple style="display:none" accept="image/*,.txt,.md,.markdown,.csv,.json,.log,.pdf,.docx,.xlsx,.xlsm,.py,.js,.ts,.tsx,.html,.css,.java,.c,.cpp,.h,.go,.rs,.sh,.yaml,.yml,.xml">
    </div>
  </footer>

  <div class="exportmenu" id="expmenu">
    <button data-f="copy">Copia testo</button>
    <button data-f="md">Markdown (.md)</button>
    <button data-f="txt">Testo (.txt)</button>
    <button data-f="html">HTML (.html)</button>
    <button data-f="pdf">PDF (.pdf)</button>
    <button data-f="compact">Compatta in 1 prompt</button>
  </div>

  <!-- IMPOSTAZIONI -->
  <div class="overlay" id="ov">
    <div class="modal">
      <header><span class="logo">__LOGO__</span><h1>Impostazioni</h1><span class="sp"></span>
        <button class="iconbtn" id="closeset" title="Chiudi" aria-label="Chiudi impostazioni">&times;</button></header>
      <div class="body">
        <h3>Aspetto</h3>
        <div class="seg" id="themeseg">
          <button data-t="system">Sistema</button>
          <button data-t="light">Chiaro</button>
          <button data-t="dark">Scuro</button>
        </div>

        <h3>Dettatura vocale</h3>
        <div class="seg" id="dictseg">
          <button data-d="off">Disattivata</button>
          <button data-d="on">Microfono</button>
        </div>
        <div class="hint">Se attiva, compare il microfono nel campo per dettare (offline). Al primo uso macOS chiede i permessi.</div>

        <h3>Generazione</h3>
        <div class="row"><label>Step di denoising</label><div class="stepper" id="stStep"></div></div>
        <div class="hint">Più step = testo più pulito ma più lento. Consigliato <b>32</b> (64 per codice/documenti).</div>
        <div class="row"><label>Max token risposta</label><div class="stepper" id="stTok"></div></div>
        <div class="hint">Lunghezza massima della risposta (1 token ≈ 0,75 parole). Il modello si ferma comunque da solo a fine risposta: un valore alto serve solo a non troncare.</div>

        <h3>OCR documenti scansionati</h3>
        <div class="seg" id="ocrseg">
          <button data-o="apple">Apple Vision</button>
          <button data-o="local">GLM locale</button>
          <button data-o="omlx">Router oMLX</button>
        </div>
        <div class="hint"><b>GLM locale</b> (consigliato): potente e tutto dentro Gephid, non impalla.<br><b>Apple Vision</b>: leggero e integrato.<br><b>Router oMLX</b>: massima resa, ma richiede il server attivo.</div>

        <h3>Modello</h3>
        <div class="row"><label>Sul tuo Mac</label><select id="modelsel" style="flex:1;min-width:0"></select></div>
        <details class="adv"><summary>Avanzato: HF id o cartella</summary>
          <div class="hint" style="margin-top:6px">Incolla un HF id (già in cache) o il percorso di una cartella-modello locale.</div>
          <div class="row"><input type="text" id="modelin" placeholder="HF id o percorso cartella" style="min-width:0"></div>
        </details>
        <button class="savebtn" id="savemodel" style="margin-top:10px">Salva e carica</button>
        <div class="note" id="restartnote"></div>
      </div>
    </div>
  </div>

<script>
  const $=id=>document.getElementById(id);
  const chat=$('chat'),inp=$('inp'),send=$('send');
  // stick-to-bottom: si auto-scrolla solo se sei già in fondo (così puoi rileggere su mentre genera)
  let stick=true;
  chat.addEventListener('scroll',()=>{stick=(chat.scrollHeight-chat.scrollTop-chat.clientHeight)<80;});
  function scrollDown(){if(stick)chat.scrollTo(0,chat.scrollHeight);}
  let history=[];
  let attachments=[]; // allegati in attesa di invio: {id,kind,name,tokens,thumb}
  let curSteps=32,curMaxTok=32768; // valori effettivi (modificabili solo da Impostazioni)
  let busy=false; // anti doppio-invio (fix: Enter mentre una richiesta è in corso)
  let modelReady=false; // false finché /api/health non dice model_ok: composer disabilitato + overlay
  let recording=false,dictBase='',dictTimer=null; // dettatura vocale
  let chatId=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():('c'+Date.now()+Math.round(Math.random()*1e6));
  function newChat(){
    if(busy)return;
    history=[];attachments=[];renderChips();
    if(compactSuggest){compactSuggest.remove();compactSuggest=null;}
    chatId=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():('c'+Date.now());
    chat.innerHTML='<div class="msg assistant">Ciao! Sono <b>Gephid</b>, giro 100% offline sul tuo Mac. Genero il testo "a blocchi" via diffusione. Chiedimi qualcosa!</div>';
    inp.value='';inp.style.height='auto';inp.focus();stick=true;updateSendState();
  }
  function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  // Renderizza markdown solo se marked+DOMPurify sono entrambi presenti; altrimenti testo grezzo (fail-safe).
  function safeHtml(text){return (window.marked&&window.DOMPurify)?DOMPurify.sanitize(marked.parse(text)):null;}

  // ---- TEMA: system/light/dark, default system ----
  const mq=window.matchMedia('(prefers-color-scheme: dark)');
  function effective(t){return t==='system' ? (mq.matches?'dark':'light') : t;}
  function applyTheme(){const t=localStorage.getItem('diffuchat-theme')||'system';
    document.documentElement.dataset.theme=effective(t);
    document.querySelectorAll('#themeseg button').forEach(b=>b.classList.toggle('active',b.dataset.t===t));}
  mq.addEventListener('change',()=>{ if((localStorage.getItem('diffuchat-theme')||'system')==='system') applyTheme(); });
  document.querySelectorAll('#themeseg button').forEach(b=>b.onclick=()=>{localStorage.setItem('diffuchat-theme',b.dataset.t);applyTheme();});
  applyTheme();

  // ---- DETTATURA opt-in: il microfono compare solo se abilitato in Impostazioni ----
  function applyDict(){const on=localStorage.getItem('gephid-dictation')==='1';
    $('mic').style.display=on?'flex':'none';$('inp').style.paddingLeft=on?'':'46px';
    document.querySelectorAll('#dictseg button').forEach(b=>b.classList.toggle('active',(b.dataset.d==='on')===on));}
  document.querySelectorAll('#dictseg button').forEach(b=>b.onclick=async()=>{
    const on=b.dataset.d==='on';localStorage.setItem('gephid-dictation',on?'1':'0');
    if(!on&&recording){await stopDict();}applyDict();});

  // ---- OCR documenti: motore selezionabile (apple | omlx | paranoid) ----
  function applyOcr(eng){document.querySelectorAll('#ocrseg button').forEach(b=>b.classList.toggle('active',b.dataset.o===eng));}
  document.querySelectorAll('#ocrseg button').forEach(b=>b.onclick=async()=>{
    applyOcr(b.dataset.o);
    try{await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ocr_engine:b.dataset.o})});}catch(e){}
  });

  // ---- config / impostazioni ----
  $('newchat').onclick=newChat;
  $('gear').onclick=()=>{$('ov').classList.add('on');loadModels();}; // ricarica la lista modelli all'apertura
  $('closeset').onclick=()=>$('ov').classList.remove('on');
  $('ov').onclick=e=>{if(e.target===$('ov'))$('ov').classList.remove('on');};
  // stepper -/+ chiaro; onChange applica subito (curSteps/curMaxTok) e salva
  function makeStepper(el,min,max,step,onChange){
    let v=min;
    const dec=document.createElement('button');dec.textContent='−';
    const val=document.createElement('span');val.className='sval';
    const inc=document.createElement('button');inc.textContent='+';
    function render(){val.textContent=v;dec.disabled=(v<=min);inc.disabled=(v>=max);}
    function setv(nv){v=Math.max(min,Math.min(max,nv));render();onChange(v);}
    dec.onclick=()=>setv(v-step);inc.onclick=()=>setv(v+step);
    el.appendChild(dec);el.appendChild(val);el.appendChild(inc);render();
    return {get:()=>v,set:(nv)=>{v=Math.max(min,Math.min(max,nv));render();}};
  }
  let cfgReady=false;
  const stStep=makeStepper($('stStep'),16,64,4,v=>{curSteps=v;if(cfgReady)saveCfg();});
  const stTok=makeStepper($('stTok'),2048,32768,2048,v=>{curMaxTok=v;if(cfgReady)saveCfg();});
  async function loadConfig(){
    try{const c=await(await fetch('/api/config')).json();
      curSteps=c.default_steps;curMaxTok=c.default_max_tokens;
      stStep.set(c.default_steps);stTok.set(c.default_max_tokens);$('modelin').value=c.model;
      applyOcr(c.ocr_engine||'apple');
    }catch(e){}
    cfgReady=true;
  }
  async function loadModels(){
    try{const d=await(await fetch('/api/models')).json();const sel=$('modelsel');sel.innerHTML='';
      let has=false;
      (d.models||[]).forEach(m=>{const o=document.createElement('option');o.value=m.id;o.textContent=m.label;if(m.id===d.current){o.selected=true;has=true;}sel.appendChild(o);});
      if(!has&&d.current){const o=document.createElement('option');o.value=d.current;o.textContent=d.current+' (attuale)';o.selected=true;sel.insertBefore(o,sel.firstChild);}
      $('modelin').value=d.current; // allinea il campo al modello effettivamente caricato
      sel.onchange=()=>{$('modelin').value=sel.value;};
    }catch(e){}
  }
  async function saveCfg(){
    try{await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({default_steps:curSteps,default_max_tokens:curMaxTok})});}catch(e){}
  }
  $('savemodel').onclick=async()=>{
    const model=$('modelin').value.trim();if(!model)return;
    const note=$('restartnote');note.style.display='block';note.textContent='Carico il modello…';
    $('savemodel').disabled=true;
    try{
      const resp=await fetch('/api/reload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model})});
      const reader=resp.body.getReader(),dec=new TextDecoder();let buf='',err=null,okk=false;
      while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});let nl;
        while((nl=buf.indexOf('\n'))>=0){const line=buf.slice(0,nl);buf=buf.slice(nl+1);if(line.trim()){try{const o=JSON.parse(line);if(o.status)note.textContent=o.status;if(o.error)err=o.error;if(o.done)okk=true;}catch(e){}}}}
      note.textContent=err?('Errore: '+err):(okk?'Modello caricato e pronto.':'Fatto.');
      if(okk&&!err){markModelReady();setTimeout(()=>{note.style.display='none';},2500);}
    }catch(e){note.textContent='Errore: '+e;}
    $('savemodel').disabled=false;
  };

  // ---- chat ----
  // Renderizza il contenuto: markdown sanificato + formule LaTeX (KaTeX), o testo grezzo (fail-safe).
  function renderInto(d,role,text,skipMath){
    let h=null;if(role==='assistant')h=safeHtml(text);
    if(h!==null){d.innerHTML=h; if(!skipMath&&window.renderMathInElement){try{renderMathInElement(d,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false},{left:'$',right:'$',display:false}],ignoredTags:['script','noscript','style','textarea','pre','code'],throwOnError:false});}catch(e){}}}
    else d.textContent=text;
  }
  // bolla di errore/sistema distinta dalle risposte (niente avatar, niente pulsanti copia/scarica)
  function addError(text){const d=document.createElement('div');d.className='msg errbubble';d.textContent=text;chat.appendChild(d);scrollDown();return d;}
  // Effetto "macchina da scrivere" stile ChatGPT: il modello genera a blocchi, li riveliamo
  // gradualmente con requestAnimationFrame (testo semplice durante; markdown+KaTeX a fine).
  function makeTyper(bubble){
    let target='',shown=0,raf=null,done=false,last=0,lastPaint=0,caretOn=false;
    // Renderizza markdown live del testo già rivelato (senza KaTeX: le formule si "katexano" a finish,
    // così niente flicker su $…$ incompleti). Fail-safe a testo grezzo se marked/DOMPurify mancano.
    // Posiziona il caret a fine dell'ultimo elemento testuale (p/li/heading) così sta a fine riga;
    // se l'ultimo blocco è pre/tabella/citazione lo mette dopo il blocco, mai dentro (no caret nel codice).
    function placeCaret(){
      const c=document.createElement('span');c.className='caret';
      let host=bubble,el=bubble.lastElementChild;
      while(el){
        const t=el.tagName;
        if(t==='PRE'||t==='TABLE'||t==='BLOCKQUOTE'||t==='HR'){host=bubble;break;}
        if((t==='UL'||t==='OL'||t==='DL')&&el.lastElementChild){el=el.lastElementChild;continue;} // entra nell'ultima voce
        host=el;break; // P, LI, H1..H6, ecc.: caret a fine di questo elemento
      }
      host.appendChild(c);
    }
    function paint(ts,withCaret){
      renderInto(bubble,'assistant',target.slice(0,shown),true);
      if(withCaret)placeCaret();
      lastPaint=ts;caretOn=withCaret;scrollDown();
    }
    function frame(ts){
      raf=null;if(done)return;
      const dt=last?Math.min(ts-last,100):16;last=ts;
      if(shown<target.length){
        const step=Math.max(Math.ceil((target.length-shown)/12),Math.ceil(dt*0.6)); // ~600 char/s, accelera se resta indietro
        shown=Math.min(target.length,shown+step);
        // throttle del re-parse markdown (~12 render/s): fluido e con costo trascurabile (delta rari)
        if(ts-lastPaint>=80||shown===target.length)paint(ts,false);else scrollDown();
      }else if(!caretOn){
        // raggiunto il testo ricevuto ma la generazione continua: cursore lampeggiante
        // (il modello sta denoisando il prossimo blocco da 256 token: non è bloccato)
        paint(ts,true);
      }
      raf=requestAnimationFrame(frame);
    }
    return {
      push(t){target=t;if(raf==null&&!done){last=0;raf=requestAnimationFrame(frame);}},
      finish(){done=true;if(raf){cancelAnimationFrame(raf);raf=null;}renderInto(bubble,'assistant',target,false);scrollDown();return Promise.resolve();}
    };
  }
  const SVG_COPY='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
  const SVG_DL='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M5 21h14"/></svg>';
  function copyBtnFor(text){
    const b=document.createElement('button');b.className='actbtn';b.dataset.exp='1';b.title='Copia testo';b.setAttribute('aria-label','Copia testo');b.innerHTML=SVG_COPY+'Copia';
    b.onclick=ev=>{ev.stopPropagation();if(navigator.clipboard)navigator.clipboard.writeText(text).then(()=>{b.innerHTML='✓ Copiato';setTimeout(()=>{b.innerHTML=SVG_COPY+'Copia';},900);}).catch(()=>{});};
    return b;
  }
  function exportBtnFor(role,text){
    const b=document.createElement('button');b.className='actbtn';b.dataset.exp='1';b.title='Esporta messaggio';b.setAttribute('aria-label','Scarica messaggio');b.innerHTML=SVG_DL+'Scarica';
    b.onclick=ev=>{ev.stopPropagation();const r=b.getBoundingClientRect();openExportMenu(r.left,r.bottom+4,[{role:role,content:text}],true);};
    return b;
  }
  function msgButtons(d,role,text){const row=document.createElement('div');row.className='msgactions';row.appendChild(copyBtnFor(text));if(role!=='user')row.appendChild(exportBtnFor(role,text));d.appendChild(row);}
  function add(role,text,tps){
    const d=document.createElement('div');d.className='msg '+role;
    if(role==='thinking'){const sp=document.createElement('span');d.appendChild(sp);const bar=document.createElement('div');bar.className='bar';d.appendChild(bar);
      // contatore secondi + etichetta aggiornabile (d._label): mostra gli stati di avanzamento del
      // backend (es. "comprimo parte 3/21…" durante il map-reduce di un documento grande)
      d._label=text;const t0=Date.now();const upd=()=>{sp.textContent=d._label+' ('+Math.floor((Date.now()-t0)/1000)+'s)';};upd();
      const iv=setInterval(()=>{if(!d.isConnected){clearInterval(iv);return;}upd();},1000);}
    else{
      renderInto(d,role,text);
      if(tps){const s=document.createElement('span');s.className='tps';s.textContent=tps+' tok/s · '+curSteps+' step';d.appendChild(s);}
      if(text!=='')msgButtons(d,role,text); // i pulsanti solo se c'è testo (il placeholder in streaming li riceve a fine)
    }
    chat.appendChild(d);scrollDown();return d;
  }

  // Legge una risposta NDJSON in streaming. onDelta(testoCumulativo) ad ogni blocco. Ritorna {acc,tps,err}.
  async function streamNDJSON(url,body,onDelta,signal,onStatus){
    const resp=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
    let acc='',tps=null,err=null;
    function handle(o){if(o.error)err=o.error;else if(o.delta!==undefined){acc+=o.delta;onDelta(acc);}else if(o.status!==undefined){if(onStatus)onStatus(o.status);}else if(o.done)tps=o.tps;}
    if(resp.body&&resp.body.getReader){
      const reader=resp.body.getReader(),dec=new TextDecoder();let buf='';
      while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});
        let nl;while((nl=buf.indexOf('\n'))>=0){const line=buf.slice(0,nl);buf=buf.slice(nl+1);if(line.trim()){try{handle(JSON.parse(line));}catch(e){}}}}
      if(buf.trim()){try{handle(JSON.parse(buf));}catch(e){}}
    }else{const t=await resp.text();t.split('\n').forEach(l=>{if(l.trim()){try{handle(JSON.parse(l));}catch(e){}}});}
    return {acc,tps,err};
  }

  let aborter=null;
  // "invia" disabilitato quando non c'è nulla da inviare (ma sempre attivo come "ferma" durante la generazione)
  function updateSendState(){
    const loading=attachments.some(a=>a.loading);
    send.classList.toggle('loading', loading && !busy);   // spinner sul bottone mentre legge
    send.disabled=(!busy)&&(!modelReady||loading||(!inp.value.trim()&&!attachments.some(a=>a.id)));
    if(!busy) send.title=loading?'Sto leggendo il documento…':'Invia';
  }
  const ICON_SEND='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  const ICON_STOP='<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6.5" y="6.5" width="11" height="11" rx="2"/></svg>';
  function setStopMode(on){send.innerHTML=on?ICON_STOP:ICON_SEND;send.title=on?'Ferma':'Invia';send.setAttribute('aria-label',on?'Ferma generazione':'Invia messaggio');updateSendState();}
  function stopGen(){if(aborter)try{aborter.abort();}catch(e){}}
  async function ask(){
    if(busy||!modelReady)return;
    if(attachments.some(a=>!a.id)){return;} // allegati ancora in caricamento: aspetta
    const m=inp.value.trim();
    const atts=attachments.filter(a=>a.id);
    if(!m&&!atts.length)return;
    if(compactSuggest){compactSuggest.remove();compactSuggest=null;}
    busy=true;inp.value='';inp.style.height='auto';setStopMode(true);
    if(recording){dictBase='';if(window.gephidDictReset)gephidDictReset();} // svuota la trascrizione (mic resta attivo per il prossimo)
    const userMsg={role:'user',content:m||'(vedi allegati)'};
    const ud=add('user',m||(atts.length?'':'(allegato)'));history.push(userMsg);
    if(atts.length){ // mostra gli allegati dentro il messaggio inviato
      const ar=document.createElement('div');ar.className='attrow';
      atts.forEach(a=>{const c=document.createElement('span');c.className='attchip';
        if(a.thumb){const im=document.createElement('img');im.src=a.thumb;c.appendChild(im);}
        c.appendChild(document.createTextNode(a.name+(a.kind==='doc'?(' ('+a.tokens+' tok)'):'')));ar.appendChild(c);});
      ud.appendChild(ar);scrollDown();
    }
    attachments=[];renderChips(); // consumati da questo turno
    const th=add('thinking','Denoising primo blocco…');
    let acc='',dmsg=null,typer=null,tps=null,err=null,aborted=false;
    aborter=new AbortController();
    const popUser=()=>{const i=history.indexOf(userMsg);if(i>=0)history.splice(i,1);}; // rimuovi per identità
    const onDelta=a=>{acc=a;if(!dmsg){th.remove();dmsg=add('assistant','');typer=makeTyper(dmsg);}typer.push(acc);};
    try{
      try{
        const onStatus=s=>{if(th&&th.isConnected&&th._label!==undefined)th._label=s;}; // avanzamento map-reduce nella bolla "thinking"
        const r=await streamNDJSON('/api/chat',{chat_id:chatId,messages:history,steps:curSteps,max_tokens:curMaxTok,attach:atts.map(a=>a.id)},onDelta,aborter.signal,onStatus);
        tps=r.tps;err=r.err;
      }catch(e){if(e&&e.name==='AbortError')aborted=true;else err=String(e);}
      if(th.parentNode)th.remove();
      if(err){
        if(typer)await typer.finish();
        if(dmsg)dmsg.remove();
        popUser(); // turno utente fallito: non lasciarlo in cronologia (no duplicati al retry)
        if(m){inp.value=m;grow();} // ripristina il testo digitato così puoi ritentare
        addError('Errore: '+err);
      }else if(!acc&&aborted){
        popUser(); // fermato senza output
      }else if(!acc.trim()){
        if(typer)await typer.finish();
        if(dmsg)dmsg.remove(); // risposta vuota: niente bolla/caret orfano
        addError('(nessuna risposta dal modello — riprova, o alza step/token)');
      }else{
        if(!dmsg)dmsg=add('assistant',acc);
        else{await typer.finish();if(tps){const s=document.createElement('span');s.className='tps';s.textContent=tps+' tok/s · '+curSteps+' step';dmsg.appendChild(s);}msgButtons(dmsg,'assistant',acc);}
        history.push({role:'assistant',content:acc});addCompactSuggest();
      }
    }finally{
      busy=false;aborter=null;setStopMode(false);inp.focus();
    }
  }
  send.onclick=()=>{if(busy){stopGen();return;}if(attachments.some(a=>a.loading))return;ask();};
  // textarea si ingrandisce con le righe (fino a max, poi scroll)
  const composerEl=document.querySelector('.composer');
  function grow(){inp.style.height='auto';const sh=inp.scrollHeight;inp.style.height=Math.min(sh,170)+'px';
    composerEl.classList.toggle('grown',sh>54);} // >1 riga -> pulsanti in basso, altrimenti centrati
  inp.addEventListener('input',grow);
  inp.addEventListener('input',updateSendState);
  // se durante la dettatura modifichi/svuoti a mano la casella, quella diventa la nuova base
  // (il polling riparte da lì) -> cancellando resta cancellato, e puoi correggere a mano.
  inp.addEventListener('input',()=>{ if(recording){ dictBase=inp.value; if(window.gephidDictReset)gephidDictReset(); } });
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(!busy)ask();}
    else if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='a'){e.preventDefault();inp.select();} // Cmd+A (webview non lo fa di default)
  });

  // ---- ALLEGATI: immagini (vision) e documenti (estrazione + token) ----
  function fileToB64(file){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res((r.result+'').split(',')[1]||'');r.onerror=rej;r.readAsDataURL(file);});}
  function renderChips(){
    const c=$('chips');c.textContent='';
    attachments.forEach(a=>{
      const ch=document.createElement('div');
      ch.className='chip'+(a.loading?' loading':'')+(a._justReady?' ready':'');
      if(a._justReady)a._justReady=false;
      if(a.loading){const sp=document.createElement('span');sp.className='spin';ch.appendChild(sp);}
      else if(a.kind==='image'&&a.thumb){const im=document.createElement('img');im.src=a.thumb;ch.appendChild(im);}
      const nm=document.createElement('span');nm.className='nm';nm.textContent=a.name;ch.appendChild(nm);
      if(a.loading){
        const t=document.createElement('span');t.className='tk load';ch.appendChild(t);
        const t0=a.t0||Date.now();
        const upd=()=>{t.textContent='Leggo… ('+Math.floor((Date.now()-t0)/1000)+'s)';};upd();
        const iv=setInterval(()=>{if(!t.isConnected||!a.loading){clearInterval(iv);return;}upd();},1000);
      }else if(a.kind==='doc'){
        const ok=document.createElement('span');ok.className='ok';ok.textContent='✓';ch.appendChild(ok);
        const t=document.createElement('span');t.className='tk';t.textContent=a.tokens+' tok';ch.appendChild(t);
      }
      const x=document.createElement('span');x.className='x';x.textContent='×';x.title=a.loading?'Annulla lettura':'Rimuovi';
      x.onclick=()=>{if(a.loading&&a._ctrl){try{a._ctrl.abort();}catch(e){}}attachments=attachments.filter(z=>z!==a);renderChips();};ch.appendChild(x);
      c.appendChild(ch);
    });
    updateSendState();
  }
  async function ingestPath(path){
    const name=path.split('/').pop();
    const isImg=/\.(png|jpe?g|gif|webp|bmp|heic|tiff)$/i.test(name);
    const ph={id:null,kind:isImg?'image':'doc',name:name,tokens:0,loading:true,thumb:null,t0:Date.now(),_ctrl:null};
    try{ph._ctrl=new AbortController();}catch(e){}
    attachments.push(ph);renderChips();
    try{
      const r=await(await fetch('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:path}),signal:ph._ctrl&&ph._ctrl.signal})).json();
      if(r.error){attachments=attachments.filter(z=>z!==ph);addError('Errore allegato "'+name+'": '+r.error);}
      else{ph.id=r.id;ph.kind=r.kind;ph.tokens=r.tokens||0;ph.loading=false;ph._justReady=true;}
      renderChips();
    }catch(err){attachments=attachments.filter(z=>z!==ph);renderChips();}
  }
  $('attach').onclick=async()=>{
    if(window.gephidOpenFiles){ // pannello file nativo (WKWebView non apre <input type=file>)
      let s='';try{s=await gephidOpenFiles();}catch(e){}
      for(const p of (s||'').split('\n').filter(Boolean)) await ingestPath(p);
      inp.focus(); // il pannello nativo ruba il focus: riportalo sull'input (altrimenti tastiera/Tab morti)
    }else{$('fileinput').click();} // fallback
  };
  $('fileinput').onchange=async e=>{
    const files=[...e.target.files];e.target.value='';
    for(const f of files){
      const isImg=(f.type||'').startsWith('image/');
      let b64;try{b64=await fileToB64(f);}catch(err){continue;}
      const ph={id:null,kind:isImg?'image':'doc',name:f.name,tokens:0,loading:true,thumb:isImg?('data:'+(f.type||'image/png')+';base64,'+b64):null,t0:Date.now(),_ctrl:null};
      try{ph._ctrl=new AbortController();}catch(e){}
      attachments.push(ph);renderChips();
      try{
        const r=await(await fetch('/api/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:f.name,content:b64}),signal:ph._ctrl&&ph._ctrl.signal})).json();
        if(r.error){attachments=attachments.filter(z=>z!==ph);addError('Errore allegato "'+f.name+'": '+r.error);}
        else{ph.id=r.id;ph.kind=r.kind;ph.tokens=r.tokens||0;ph.loading=false;ph._justReady=true;}
        renderChips();
      }catch(err){attachments=attachments.filter(z=>z!==ph);renderChips();}
    }
    inp.focus();
  };

  // ---- DETTATURA: usa la dettatura nativa di macOS (offline). Click avvia, ri-click ferma. ----
  async function stopDict(){
    recording=false;$('mic').classList.remove('rec');$('mic').setAttribute('aria-pressed','false');
    if(dictTimer){clearInterval(dictTimer);dictTimer=null;}
    if(window.gephidDictStop)gephidDictStop();
    if(window.gephidDictText){try{const t=await gephidDictText();inp.value=dictBase+t;grow();}catch(e){}}
    inp.focus();
  }
  $('mic').onclick=async()=>{
    if(!window.gephidDictStart){addError('Dettatura non disponibile in questa finestra.');return;}
    if(recording){await stopDict();return;}
    inp.focus();
    let r;try{r=await gephidDictStart();}catch(e){r=-1;}
    if(r<0){add('assistant','Dettatura on-device non disponibile. Attiva la Dettatura italiana (anche "on device") in Impostazioni di Sistema → Tastiera → Dettatura, e concedi Microfono e Riconoscimento vocale a Gephid.');return;}
    recording=true;$('mic').classList.add('rec');$('mic').setAttribute('aria-pressed','true');
    dictBase=inp.value?(inp.value.replace(/\s*$/,'')+' '):'';
    dictTimer=setInterval(async()=>{try{const t=await gephidDictText();inp.value=dictBase+t;grow();updateSendState();scrollDown();}catch(e){}},300);
  };

  // ---- EXPORT: chat intera (header ⬇) o singolo messaggio (⬇ sulla bolla) in MD/TXT/HTML/PDF ----
  let exportTarget=[];
  function renderMsgHtml(m){const h=safeHtml(m.content);const safe=h!==null?h:('<pre style="white-space:pre-wrap;font-family:inherit;margin:0">'+escapeHtml(m.content)+'</pre>');const who=m.role==='user'?'Tu':'Gephid';const bg=m.role==='user'?'#eef1f6':'#f4f7ff';return '<div style="margin:14px 0;padding:12px 16px;border-radius:12px;background:'+bg+';border:1px solid #e1e7f2"><div style="color:#4169e1;font-weight:700;font-size:.82em;margin-bottom:6px">'+who+'</div>'+safe+'</div>';}
  function fullHtml(msgs){return '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Chat Gephid</title></head><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:760px;margin:30px auto;padding:0 16px;color:#1a1f29"><h2 style="color:#4169e1">Chat — Gephid</h2>'+msgs.map(renderMsgHtml).join('')+'</body></html>';}
  function mdOf(msgs){return msgs.map(m=>(m.role==='user'?'**Tu:** ':'**Gephid:**\n\n')+m.content).join('\n\n---\n\n');}
  function txtOf(msgs){return msgs.map(m=>(m.role==='user'?'Tu: ':'Gephid:\n')+m.content).join('\n\n');}
  // Il download del browser non funziona in WKWebView: salva lato server in ~/Downloads.
  async function saveToDownloads(name,content,b64){
    try{return await(await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:name,content:content,b64:!!b64})})).json();}
    catch(e){return {ok:false,error:String(e)};}
  }
  // Salva chiedendo dove (pannello di salvataggio nativo macOS); fallback a ~/Downloads.
  async function saveAsFile(defName,content,b64){
    if(window.gephidSaveFile){
      let path='';try{path=await gephidSaveFile(defName);}catch(e){}
      if(!path)return {cancelled:true};
      try{return await(await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:path,content:content,b64:!!b64})})).json();}
      catch(e){return {ok:false,error:String(e)};}
    }
    return await saveToDownloads(defName,content,b64);
  }
  async function doExport(msgs,fmt){
    if(!msgs||!msgs.length)return;
    const ts=new Date().toISOString().slice(0,16).replace(/[:T]/g,'-');const base='gephid-'+ts;
    let name,content,b64=false;
    if(fmt==='md'){name=base+'.md';content=mdOf(msgs);}
    else if(fmt==='txt'){name=base+'.txt';content=txtOf(msgs);}
    else if(fmt==='html'){name=base+'.html';content=fullHtml(msgs);}
    else if(fmt==='pdf'){
      if(!window.html2pdf){addError('PDF non disponibile: libreria non caricata.');return;}
      const el=document.createElement('div');el.style.color='#1a1f29';el.innerHTML='<h2 style="color:#4169e1;font-family:sans-serif">Chat - Gephid</h2>'+msgs.map(renderMsgHtml).join('');
      const uri=await html2pdf().set({margin:10,html2canvas:{scale:2},jsPDF:{unit:'mm',format:'a4',orientation:'portrait'}}).from(el).outputPdf('datauristring');
      name=base+'.pdf';content=(uri.split(',')[1]||'');b64=true;
    } else return;
    const r=await saveToDownloads(name,content,b64);
    if(r&&r.ok)add('assistant','Salvato in '+r.path+' (aperto nel Finder).');
    else addError('Salvataggio non riuscito'+(r&&r.error?': '+r.error:'')+'.');
  }
  function openExportMenu(x,y,msgs,single){exportTarget=msgs;const m=$('expmenu');
    // per-messaggio (single): solo formati; intestazione: anche Copia/Compatta di tutta la chat
    m.querySelectorAll('[data-f="copy"],[data-f="compact"]').forEach(b=>b.style.display=single?'none':'block');
    m.classList.add('on');
    const w=m.offsetWidth||160,h=m.offsetHeight||220;
    m.style.left=Math.max(8,Math.min(x,innerWidth-w-8))+'px';
    m.style.top=Math.max(8,Math.min(y,innerHeight-h-8))+'px';}
  $('export').onclick=e=>{e.stopPropagation();const r=e.target.getBoundingClientRect();openExportMenu(r.right-150,r.bottom+6,history.slice(),false);};
  document.querySelectorAll('#expmenu button').forEach(b=>b.onclick=()=>{
    if(b.dataset.f==='copy'){const txt=exportTarget.length===1?exportTarget[0].content:txtOf(exportTarget);if(navigator.clipboard)navigator.clipboard.writeText(txt).catch(()=>{});}
    else if(b.dataset.f==='compact')compactChat();
    else doExport(exportTarget,b.dataset.f);
    $('expmenu').classList.remove('on');});
  // chiudi il menu cliccando fuori (gli apri-menu fanno stopPropagation), con Escape o allo scroll
  function closeExportMenu(){$('expmenu').classList.remove('on');}
  document.addEventListener('click',e=>{if(!e.target.closest('#expmenu'))closeExportMenu();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeExportMenu();$('ov').classList.remove('on');}});
  chat.addEventListener('scroll',closeExportMenu);
  window.addEventListener('scroll',closeExportMenu,true);
  window.addEventListener('resize',closeExportMenu);

  // ---- COMPATTA chat in 1 prompt (per riprenderla altrove / con un altro LLM) ----
  let compactSuggest=null;
  function addCompactSuggest(){
    if(compactSuggest)compactSuggest.remove();
    if(history.length<2)return;
    compactSuggest=document.createElement('div');compactSuggest.className='compactsug';
    compactSuggest.innerHTML='<a id="csg">Compatta in 1 prompt</a> — riassume la chat in un unico prompt per continuarla altrove';
    compactSuggest.querySelector('#csg').onclick=()=>compactChat();
    chat.appendChild(compactSuggest);scrollDown();
  }
  async function compactChat(){
    if(busy||!history.length)return;
    if(compactSuggest){compactSuggest.remove();compactSuggest=null;}
    busy=true;setStopMode(true);
    const th=add('thinking','comprimo la conversazione...');
    let acc='',dmsg=null,typer=null,err=null,aborted=false;
    aborter=new AbortController();
    const onDelta=a=>{acc=a;if(!dmsg){th.remove();dmsg=add('assistant','');typer=makeTyper(dmsg);}typer.push(acc);};
    try{
      try{const r=await streamNDJSON('/api/compact',{messages:history},onDelta,aborter.signal);err=r.err;}
      catch(e){if(e&&e.name==='AbortError')aborted=true;else err=String(e);}
      if(th.parentNode)th.remove();
      if(typer)await typer.finish();
      if(dmsg)dmsg.remove(); // lo rimostro formattato col prefisso e i pulsanti
      if(err){addError('Errore: '+err);}
      else if(acc){
        const ts=new Date().toISOString().slice(0,16).replace(/[:T]/g,'-');
        let copied=false;
        if(navigator.clipboard){try{await navigator.clipboard.writeText(acc);copied=true;}catch(e){}}
        const d=add('assistant','**Chat compattata**'+(copied?' — copiata negli appunti':'')+'. Incollala in un altro LLM (o qui) per riprendere:\n\n---\n\n'+acc);
        const btn=document.createElement('button');btn.className='inlinebtn';btn.textContent='Salva come file…';
        btn.onclick=async()=>{
          btn.disabled=true;btn.textContent='salvataggio…';
          const r=await saveAsFile('gephid-compact-'+ts+'.txt',acc,false);
          if(r&&r.cancelled){btn.disabled=false;btn.textContent='Salva come file…';}
          else if(r&&r.ok){btn.textContent='Salvato ✓';setTimeout(()=>{btn.textContent='Salva come file…';btn.disabled=false;},2200);}
          else{btn.disabled=false;btn.textContent='Riprova salvataggio';}
        };
        d.appendChild(btn);scrollDown();
      }
    }finally{
      busy=false;aborter=null;setStopMode(false);
    }
  }

  // Sblocca la UI quando il modello è pronto: dissolve l'overlay, riabilita il composer.
  function markModelReady(){
    if(modelReady)return;
    modelReady=true;
    const ov=$('bootov');if(ov){ov.classList.add('gone');setTimeout(()=>{if(ov.parentNode)ov.remove();},450);}
    inp.disabled=false;inp.placeholder='Scrivi un messaggio...';updateSendState();
    if(!$('ov').classList.contains('on'))inp.focus(); // non rubare il focus se le Impostazioni sono aperte (reload a caldo)
  }
  // Overlay d'avvio: il server risponde subito (model_ok=false) mentre i pesi salgono in RAM sul main
  // thread. Facciamo polling finché model_ok=true (sblocca) o model_err (mostra l'errore in overlay).
  async function bootGate(){
    const ov=$('bootov');if(!ov){markModelReady();return;}
    const bt=ov.querySelector('.bt'),bm=$('bootmsg'),t0=Date.now();
    // mostra uno stato terminale nell'overlay con un pulsante d'azione (l'overlay copre tutto, quindi
    // i controlli sotto — es. Impostazioni — sono irraggiungibili: serve un pulsante qui dentro)
    function bootFail(title,html,btnLabel,btnFn){
      if(bt)bt.textContent=title;
      const sp=ov.querySelector('.bsp');if(sp)sp.remove();
      if(bm)bm.innerHTML=html;
      const b=document.createElement('button');b.className='inlinebtn';b.textContent=btnLabel;b.onclick=btnFn;ov.appendChild(b);
    }
    const iv=setInterval(()=>{if(bt&&!modelReady)bt.textContent='Carico il modello… ('+Math.floor((Date.now()-t0)/1000)+'s)';},1000);
    let fails=0;
    while(!modelReady){
      try{
        const h=await(await fetch('/api/health')).json();
        fails=0;
        if(h.model_ok){clearInterval(iv);markModelReady();return;}
        if(h.model_err){clearInterval(iv);
          bootFail('Modello non caricato',
            'Impossibile caricare <b>'+escapeHtml(h.model||'')+'</b>.<br>'+escapeHtml(h.model_err)+'<br><br>Cambia modello dalle Impostazioni e ricaricalo.',
            'Apri Impostazioni',()=>{ov.classList.add('gone');setTimeout(()=>{if(ov.parentNode)ov.remove();},450);$('gear').click();});
          return;}
      }catch(e){
        // backend irraggiungibile (morto dopo l'apertura della finestra): dopo ~12s offri di ricaricare
        if(++fails>=20){clearInterval(iv);
          bootFail('Backend non raggiungibile',
            'Gephid non riesce a contattare il backend. Potrebbe essersi chiuso: controlla i log o riprova.',
            'Ricarica',()=>location.reload());
          return;}
      }
      await new Promise(r=>setTimeout(r,600));
    }
  }

  applyDict();
  updateSendState();
  loadConfig();
  loadModels();
  bootGate();
</script>
</body></html>"""

LOGO_SVG = '''<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%">
<rect x="40" y="40" width="432" height="432" rx="104" fill="#4169E1"/>
<g transform="rotate(13.37 256 256)" fill="#fff">
<ellipse cx="254" cy="210" rx="58" ry="52"/>
<path d="M247 250 L266 250 L302 372 Q307 391 287 388 L227 378 Q213 376 219 359 Z"/></g></svg>'''

FULL_PAGE = PAGE.replace("__LOGO__", LOGO_SVG)  # precompilata una volta (il logo è costante)

# Redesign "Terminale × Cifra": la nuova UI vive in page.html accanto a questo file.
# Servita su /new finché non è completa; poi diventerà la "/" di default. Caricata a ogni
# richiesta in dev (così posso iterare senza riavviare); in bundle è statica.
_PAGE_CACHE = {"mtime": None, "html": None}
def _load_new_page():
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html")
        m = os.path.getmtime(p)  # cache in memoria: rilegge solo se il file cambia (hot-reload in dev, zero I/O in prod)
        if _PAGE_CACHE["mtime"] != m:
            with open(p, encoding="utf-8") as f:
                _PAGE_CACHE["html"] = f.read()
            _PAGE_CACHE["mtime"] = m
        return _PAGE_CACHE["html"]
    except Exception as e:
        return "<!doctype html><meta charset=utf-8><body style='font-family:monospace;padding:40px'>page.html non trovata: " + str(e) + "</body>"

class H(http.server.BaseHTTPRequestHandler):
    timeout = 120  # un client lento/bloccato non tiene occupato il thread per sempre
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json", extra=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(b))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/" or self.path == "/new":  # nuova UI "Terminale × Cifra" (default)
            self._send(200, _load_new_page(), "text/html; charset=utf-8")
        elif self.path == "/old":  # vecchia UI, fallback durante la transizione
            self._send(200, FULL_PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._send(200, json.dumps(config_payload()))
        elif self.path == "/api/health":
            global _NEEDS_DL
            if _NEEDS_DL is None and not MODEL_OK and not MODEL_ERR:
                _NEEDS_DL = not model_cached(MODEL)
            self._send(200, json.dumps({"model_ok": MODEL_OK, "model_err": MODEL_ERR[:300], "model": MODEL,
                                        "needs_download": bool(_NEEDS_DL) and not MODEL_OK}))
        elif self.path == "/api/models":
            self._send(200, json.dumps({"models": list_local_models(), "current": MODEL}))
        elif self.path.startswith("/static/"):
            self._serve_static(self.path[len("/static/"):])
        else:
            self._send(404, "not found", "text/plain")
    def _serve_static(self, name):
        # serve file da STATIC_DIR e dalla sola sottocartella fonts/ (KaTeX); niente path traversal
        parts = name.split("/")
        ok = (len(parts) == 1) or (len(parts) == 2 and parts[0] == "fonts")
        if not ok or any(p in ("", ".", "..") for p in parts):
            self._send(404, "not found", "text/plain"); return
        path = os.path.join(STATIC_DIR, *parts)
        if not os.path.isfile(path):
            self._send(404, "not found", "text/plain"); return
        ext = os.path.splitext(path)[1].lower()
        ctype = {".js": "application/javascript", ".css": "text/css",
                 ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf"}.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as f: self._send(200, f.read(), ctype, {"Cache-Control": "public, max-age=31536000"})
        except Exception:
            self._send(404, "not found", "text/plain")
    def do_POST(self):
        try: n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError): n = 0
        if n > 80 * 1024 * 1024:  # limite 80MB (immagini/documenti grandi inclusi)
            self._send(413, json.dumps({"error": "Richiesta troppo grande."})); return
        # Anti-CSRF/DNS-rebinding: una pagina web esterna non può pilotare l'API locale.
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
            self._send(403, json.dumps({"error": "Origin non consentita."})); return
        # anti DNS-rebinding: l'Host deve essere locale (blocca un dominio esterno rimappato su 127.0.0.1).
        # Copre anche il caso di POST senza header Origin (client browser fanno comunque richieste con Host).
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("localhost", "127.0.0.1"):
            self._send(403, json.dumps({"error": "Host non consentito."})); return
        try: req = json.loads(self.rfile.read(n)) if n else {}
        except Exception: req = {}
        if self.path == "/api/chat":
            # Risposta in streaming (NDJSON): una riga JSON per blocco generato
            # ({"delta": "..."}), poi {"done":true,"tps":..,"secs":..} o {"error":".."}.
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            def emit(obj):
                try:
                    self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush(); return True
                except Exception:
                    return False
            if not MODEL_OK:
                if MODEL_ERR:
                    emit({"error": "Modello non trovato: " + MODEL +
                          ". Scaricalo da HuggingFace o cambia il path in Impostazioni > Modello, poi riavvia l'app. (" + MODEL_ERR[:120] + ")"})
                else:
                    emit({"error": "Il modello si sta ancora caricando, attendi qualche secondo e riprova."})
                return
            try:
                chat_id = req.get("chat_id") or "default"
                steps = _coerce_int(req.get("steps"), STEP_MIN, STEP_MAX, CFG["default_steps"])
                mtok = _coerce_int(req.get("max_tokens"), TOK_MIN, TOK_MAX, CFG["default_max_tokens"])
                reveal = bool(req.get("reveal", False))  # "formazione dal rumore" (unmasking-draft)
                cont = bool(req.get("cont", False))      # continuazione di un parziale interrotto
                attach = req.get("attach") or []
                img_paths = []
                for i in attach:
                    e = INGEST.get(i)
                    if e and e["kind"] == "image": img_paths.extend(e.get("paths") or [])
                doc_ids = [i for i in attach if i in INGEST and INGEST[i]["kind"] == "doc"]
                raw_msgs = req.get("messages", [])
                def work(job):  # gira sul thread-worker del modello
                    msgs = fit_context(raw_msgs, chat_id, on_status=lambda s: job.q.put(("status", s)))
                    # in continuazione l'ultimo messaggio è l'assistant parziale: non toccarlo col contesto-documenti
                    if doc_ids and not (cont and msgs and msgs[-1].get("role") == "assistant"):
                        doc_ctx = build_doc_context(doc_ids, lambda s: job.q.put(("status", s)), job.cancel)
                        if doc_ctx and msgs:
                            msgs = msgs[:-1] + [{"role": msgs[-1]["role"],
                                                 "content": "Contesto dai documenti allegati:\n" + doc_ctx + "\n\n---\n\n" + msgs[-1]["content"]}]
                    # Guard memoria GPU: attenzione ~seq^2, quindi prompt+output deve stare in SAFE_SEQ.
                    # Tieni il prompt entro un tetto (riducendo i documenti) e clampa i max token di output.
                    # Nota: usa una variabile nuova (eff_mtok), non riassegnare 'mtok' del closure (UnboundLocalError).
                    eff_mtok = mtok
                    if not img_paths:  # con immagini il conteggio token non è affidabile: salta il guard
                        ptok = _ntok(msgs)
                        cap = SAFE_SEQ - 256
                        if ptok > cap:
                            job.q.put(("status", "contesto troppo grande per la GPU: uso le porzioni principali..."))
                            msgs = _fit_prompt(msgs, cap)
                            ptok = _ntok(msgs)
                        eff_mtok = max(TOK_MIN, min(mtok, SAFE_SEQ - ptok))  # prompt+output entro il buffer
                    if doc_ids:
                        job.q.put(("status", "Ho letto tutto il documento, scrivo la risposta…"))
                    def on_delta(d):
                        if job.cancel.is_set(): return False
                        job.q.put(("delta", d)); return True
                    def on_event(ev):
                        if not job.cancel.is_set(): job.q.put(("diff", ev))
                    text, tps, dt = genera_stream(msgs, steps, eff_mtok, on_delta, images=img_paths or None, on_event=on_event, reveal=reveal, cont=cont)
                    job.q.put(("done", tps, dt))
                stream_job(Job(work), emit)
            except Exception as e:
                emit({"error": str(e)[:300]})
        elif self.path == "/api/compact":
            # Anche la compattazione è in streaming (stesso protocollo NDJSON di /api/chat).
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            def emitc(obj):
                try:
                    self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")); self.wfile.flush(); return True
                except Exception:
                    return False
            if not MODEL_OK:
                emitc({"error": "Modello non caricato."}); return
            instr = {"role": "user", "content":
                     "Comprimi la conversazione precedente in UN UNICO PROMPT denso e telegrafico, in italiano, "
                     "da incollare in un altro assistente (o in te stessa) per RIPRENDERE da dove eravamo. "
                     "REGOLE FERREE per non sprecare token:\n"
                     "- NON descrivere cosa sei tu né cosa è il modello/Gemma/DeepMind.\n"
                     "- NIENTE preamboli, cortesie o frasi generiche ('Continua la conversazione...', 'Finora abbiamo...').\n"
                     "- Vai DRITTO ai contenuti: solo fatti concreti, dati/numeri, decisioni prese, stato attuale e prossimo passo.\n"
                     "- Usa elenchi puntati brevi se utile. Massima densità, minimo testo.\n"
                     "Restituisci solo il prompt pronto da incollare."}
            cmsgs = req.get("messages", []) + [instr]
            def cwork(job):
                def on_delta(d):
                    if job.cancel.is_set(): return False
                    job.q.put(("delta", d)); return True
                text, tps, dt = genera_stream(cmsgs, 28, 2000, on_delta)
                job.q.put(("done", tps, dt))
            stream_job(Job(cwork), emitc)
        elif self.path == "/api/ingest":
            # Riceve un file via path (file picker nativo) o base64 (fallback) -> immagine/documento.
            if not MODEL_OK:  # senza tokenizer il conteggio token sarebbe solo una stima caratteri/4
                self._send(200, json.dumps({"error": "Il modello si sta ancora caricando, attendi qualche secondo e riprova."})); return
            try:
                p = req.get("path")
                if p:
                    if not os.path.isfile(p): raise ValueError("File non trovato.")
                    if os.path.getsize(p) > 80 * 1024 * 1024: raise ValueError("File troppo grande (>80MB).")
                    with open(p, "rb") as f: data = f.read()
                    fname = os.path.basename(p)
                else:
                    fname = os.path.basename(str(req.get("filename") or "file"))
                    data = base64.b64decode(req.get("content") or "")
                self._send(200, json.dumps(ingest_file(fname, data)))
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)[:200]}))
        elif self.path == "/api/save":
            content = req.get("content") or ""
            # WKWebView non sa scaricare via <a download>/blob: salva lato server in ~/Downloads
            # e rivela il file nel Finder (open -R). Nessuna scrittura su path arbitrari: solo ~/Downloads.
            name = os.path.basename(str(req.get("filename") or "gephid.txt")).lstrip(".") or "gephid.txt"
            try:
                os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                path = os.path.join(DOWNLOADS_DIR, name)
                # difesa extra: il path finale deve restare dentro ~/Downloads
                if os.path.dirname(os.path.realpath(path)) != os.path.realpath(DOWNLOADS_DIR):
                    self._send(200, json.dumps({"ok": False, "error": "Nome file non valido."})); return
                if os.path.exists(path):  # non sovrascrivere: aggiungi suffisso
                    base, ex = os.path.splitext(name)
                    path = os.path.join(DOWNLOADS_DIR, base + "-" + uuid.uuid4().hex[:6] + ex)
                if req.get("pdf"):
                    with open(path, "wb") as f: f.write(_html_to_pdf(content, req.get("footer") or ""))
                elif req.get("b64"):
                    with open(path, "wb") as f: f.write(base64.b64decode(content))
                else:
                    with open(path, "w", encoding="utf-8") as f: f.write(content)
                try: subprocess.Popen(["open", "-R", path])  # mostra il file nel Finder
                except Exception: pass
                self._send(200, json.dumps({"ok": True, "path": path}))
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)[:200]}))
        elif self.path == "/api/reload":
            # Ricarica il modello a caldo (sul thread-worker), senza riavviare l'app.
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            def emitR(obj):
                try: self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")); self.wfile.flush(); return True
                except Exception: return False
            new_model = (req.get("model") or "").strip()
            if not new_model:
                emitR({"error": "Modello non valido."}); return
            def rwork(job):
                global MODELO, PROC, TOK, MODEL, MODEL_OK, MODEL_ERR
                job.q.put(("status", "Carico il modello " + new_model + "…"))
                m, p = load(new_model)  # se fallisce, l'eccezione lascia intatto il modello attuale
                MODELO, PROC = m, p
                TOK = p.tokenizer if hasattr(p, "tokenizer") else p
                MODEL, MODEL_OK, MODEL_ERR = new_model, True, ""
                CFG["model"] = new_model; save_config(CFG)
                SESSIONS.clear(); SUMMARY_CACHE.clear()  # contesto/cache non validi col nuovo modello
                job.q.put(("done", 0, 0))
            stream_job(Job(rwork), emitR)
        elif self.path == "/api/config":
            CFG["default_steps"] = _coerce_int(req.get("default_steps"), STEP_MIN, STEP_MAX, CFG["default_steps"])
            CFG["default_max_tokens"] = _coerce_int(req.get("default_max_tokens"), TOK_MIN, TOK_MAX, CFG["default_max_tokens"])
            oe = str(req.get("ocr_engine", CFG.get("ocr_engine", "apple"))).lower()
            if oe in ("apple", "local", "omlx", "paranoid"):
                CFG["ocr_engine"] = oe
                globals()["OCR_ENGINE"] = oe   # effetto immediato sui prossimi ingest, senza riavvio
            save_config(CFG)
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/api/download":
            # Scarica il modello (primo avvio) in streaming NDJSON. Gira su un thread dedicato:
            # è I/O di rete, non tocca la GPU né il worker del modello.
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            def emitD(obj):
                try: self.wfile.write((json.dumps(obj) + "\n").encode()); self.wfile.flush(); return True
                except Exception: return False
            with _DL_LOCK:
                already = _DL["active"]
                if not already: _DL["active"] = True
            try:
                if already:
                    emitD({"error": "download già in corso"})
                else:
                    download_model_stream(emitD)
            except Exception as e:
                emitD({"error": str(e)[:200]})
            finally:
                if not already:  # se l'ho attivato io, garantisco il reset anche se download_model_stream è esploso prima del suo finally
                    with _DL_LOCK: _DL["active"] = False
            global _NEEDS_DL; _NEEDS_DL = not model_cached(MODEL)
        elif self.path == "/api/download/pause":
            _DL["cancel"] = True
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, "{}")

class GephidServer(http.server.ThreadingHTTPServer):
    # HTTP concorrente (static/health/ingest restano reattivi durante lo streaming di una
    # risposta). Le ops del modello restano su un solo thread, il worker.
    daemon_threads = True
    request_queue_size = 128
    allow_reuse_address = True  # esplicito: al restart (supervisione del launcher) il bind sulla porta non deve fallire

IS_BUNDLED = ".app/Contents/Resources" in os.path.realpath(__file__)  # True solo dentro la .app
BUILD = "2026-06-25b"  # marker di build: compare in ~/gephid-backend.log per verificare la versione in uso

def _launcher_watchdog():
    """Spegne il backend SOLO quando nessun launcher Gephid è più vivo (tutte le finestre chiuse).
    Si basa sulla PRESENZA del processo launcher, non sull'heartbeat della pagina: così il backend
    resta vivo finché c'è almeno una finestra aperta, anche in background quando macOS rallenta i
    timer JS (era questa la causa del 'Backend non raggiungibile dopo un po'). Per i dev (script
    fuori dalla .app) il watchdog non parte affatto."""
    import subprocess
    grace = time.time() + 30   # margine all'avvio: lascia comparire il launcher
    misses = 0
    while True:
        time.sleep(5)
        try:
            out = subprocess.run(["pgrep", "-f", "Gephid.app/Contents/MacOS/Gephid"],
                                 capture_output=True, text=True, timeout=4).stdout
            if any(x.strip() for x in out.split()):
                misses = 0
            elif time.time() > grace:
                misses += 1
                if misses >= 2:  # due check a vuoto consecutivi (~10s) per evitare falsi positivi
                    print("nessun launcher Gephid vivo → spengo il backend", flush=True)
                    os._exit(0)
        except Exception:
            misses = 0  # nel dubbio non spegnere

if __name__ == "__main__":
    srv = GephidServer(("127.0.0.1", PORT), H)  # solo loopback
    # Server HTTP su thread daemon; il main thread carica il modello e poi fa da worker.
    # MLX richiede che le ops del modello girino sul thread che ha caricato i pesi.
    threading.Thread(target=srv.serve_forever, daemon=True, name="gephid-http").start()
    if IS_BUNDLED:  # nel bundle: spegniti quando l'ultima finestra si chiude (non quando è solo idle)
        threading.Thread(target=_launcher_watchdog, daemon=True, name="gephid-watchdog").start()
    print(f"diffuchat build {BUILD} attivo su http://localhost:{PORT} (carico il modello…)", flush=True)
    load_model()  # sul main thread, mentre il server già risponde /api/health (model_ok=false)
    try:
        _model_worker()  # processa i job del modello sul thread principale
    except KeyboardInterrupt:
        print("\nchiudo")
