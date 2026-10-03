"""Separa lo stream del modello in canali: testo della risposta, pensiero, chiamate a strumenti.

Il template di DiffusionGemma avvolge il ragionamento in `<|channel>thought\\n … <channel|>` e le
chiamate a strumenti in `<|tool_call> … <tool_call|>`. Con il pensiero spento il modello apre e chiude
comunque un canale vuoto: senza questo filtro la UI stampava `<|channel>thought` in testa a OGNI
risposta. I marcatori possono arrivare spezzati tra due chunk dello stream, quindi la coda che
potrebbe essere l'inizio di un marcatore viene trattenuta finché non si sa cos'è.
"""

_OPEN = {"<|channel>": "thought", "<|tool_call>": "tool_call"}
_CLOSE = {"thought": "<channel|>", "tool_call": "<tool_call|>"}
# marcatori di struttura che non devono mai finire nel testo mostrato
_DROP = ("<|turn>", "<turn|>", '<|"|>', "<eos>", "<bos>", "<pad>", "<end_of_turn>", "<start_of_turn>",
         "<|tool_response>", "<tool_response|>", "<|tool>", "<tool|>", "<|think|>")
_ALL = tuple(_OPEN) + tuple(_CLOSE.values()) + _DROP


def _held_prefix(buf):
    """Lunghezza della coda di buf che potrebbe essere l'inizio di un marcatore (da trattenere)."""
    i = buf.rfind("<")
    if i < 0:
        return 0
    tail = buf[i:]
    return len(tail) if any(m.startswith(tail) for m in _ALL) else 0


class ChannelSplitter:
    """feed(chunk) -> [(kind, testo)] con kind in {"text", "thought", "tool_call"}."""

    def __init__(self):
        self.mode = "text"
        self.buf = ""
        self.need_name = False  # dopo <|channel> la prima riga è il nome del canale ("thought")
        self.pending_ws = ""    # a-capo in coda al pensiero: si emettono solo se segue altro pensiero

    def _emit(self, out, kind, s):
        if not s:
            return
        if kind == "thought":
            s = self.pending_ws + s
            stripped = s.rstrip("\n ")
            self.pending_ws = s[len(stripped):]
            s = stripped
            if not s:
                return
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + s)
        else:
            out.append((kind, s))

    def feed(self, chunk):
        self.buf += chunk or ""
        out = []
        while self.buf:
            if self.need_name:
                nl = self.buf.find("\n")
                if nl < 0:
                    close = self.buf.find(_CLOSE["thought"])
                    if close < 0:
                        return out  # nome del canale non ancora completo
                    nl = close - 1  # canale chiuso senza a-capo: nessun contenuto
                self.buf = self.buf[nl + 1:]
                self.need_name = False
                continue
            if self.mode == "text":
                cands = [(self.buf.find(m), m) for m in tuple(_OPEN) + _DROP + tuple(_CLOSE.values())]
                cands = [(i, m) for i, m in cands if i >= 0]
                if cands:
                    i, m = min(cands)
                    self._emit(out, "text", self.buf[:i])
                    self.buf = self.buf[i + len(m):]
                    if m in _OPEN:
                        self.mode = _OPEN[m]
                        self.need_name = (self.mode == "thought")
                        self.pending_ws = ""
                    continue
            else:
                end = _CLOSE[self.mode]
                i = self.buf.find(end)
                if i >= 0:
                    body = self.buf[:i]
                    self._emit(out, self.mode, body)
                    self.pending_ws = ""
                    self.buf = self.buf[i + len(end):]
                    self.mode = "text"
                    continue
            if self.mode == "tool_call":
                return out  # una chiamata esce intera, solo quando è chiusa (va interpretata, non mostrata)
            # nessun marcatore completo: emetti tutto tranne la coda ambigua
            h = _held_prefix(self.buf)
            emit, self.buf = (self.buf[:-h], self.buf[-h:]) if h else (self.buf, "")
            self._emit(out, self.mode, emit)
            return out
        return out

    def flush(self):
        """Fine stream: svuota ciò che era trattenuto (un canale non chiuso resta del suo tipo)."""
        out = []
        if not self.need_name:
            # in modalità testo la coda trattenuta è solo l'inizio incompleto di un marcatore: è testo
            self._emit(out, self.mode, self.buf)
        self.buf = ""
        return out


def strip_markers(text):
    """Difesa finale su un testo intero: toglie canali di pensiero/strumenti e marcatori residui."""
    sp = ChannelSplitter()
    parts = sp.feed(text or "") + sp.flush()
    out = "".join(t for k, t in parts if k == "text")
    for m in _ALL:
        out = out.replace(m, "")
    return out
