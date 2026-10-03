"""Chat salvate SU RICHIESTA dell'utente (di default Gephid non salva nulla).

Una chat salvata è un JSON in `root/<id>.json` con cronologia e testo dei documenti allegati, così
riaprendola i documenti tornano disponibili al modello anche dopo un riavvio.
"""
import json, os, re, time

_ID = re.compile(r"^[0-9a-f][0-9a-f-]{6,63}$")


def default_root():
    return os.path.expanduser("~/Library/Application Support/Gephid/chats")


class ChatStore:
    def __init__(self, root=None):
        self.root = root or default_root()

    def _path(self, cid):
        if not isinstance(cid, str) or not _ID.match(cid):
            raise ValueError("id chat non valido")
        return os.path.join(self.root, cid + ".json")

    def save(self, chat):
        path = self._path(chat.get("id"))
        os.makedirs(self.root, exist_ok=True)
        data = dict(chat, saved_at=time.time())
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)  # atomico: un crash non lascia un file a metà
        return data["saved_at"]

    def load(self, cid):
        try:
            with open(self._path(cid), encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            return None

    def list(self):
        out = []
        try:
            names = os.listdir(self.root)
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.root, n), encoding="utf-8") as f:
                    c = json.load(f)
                out.append({"id": c["id"], "title": c.get("title") or "Chat", "saved_at": c.get("saved_at", 0),
                            "messages": len(c.get("history") or [])})
            except (ValueError, OSError, KeyError, TypeError):
                continue  # file rotto o estraneo: non deve rompere l'elenco
        return sorted(out, key=lambda c: -c["saved_at"])

    def delete(self, cid):
        try:
            os.remove(self._path(cid))
        except (ValueError, OSError):
            pass
