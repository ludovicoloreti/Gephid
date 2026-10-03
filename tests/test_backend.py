"""Funzioni pure del backend. Importare diffuchat importa mlx_vlm (venv di sviluppo) ma NON carica il
modello: load_model() parte solo da __main__."""
import os
import pytest
import diffuchat as D


def test_validate_config_limiti_e_tipi():
    c = D.validate_config({"default_steps": 3, "default_max_tokens": "x", "port": 80, "ocr_engine": "boh",
                           "system_prompt": "a" * 5000, "model": "  m/x  "})
    assert c["default_steps"] == D.STEP_MIN
    assert c["default_max_tokens"] == D.DEFAULTS["default_max_tokens"]
    assert c["port"] == 1024  # niente porte privilegiate: clamp al minimo
    assert c["ocr_engine"] == D.DEFAULTS["ocr_engine"]
    assert len(c["system_prompt"]) == 2000 and c["model"] == "m/x"


def test_strip_emoji_tiene_i_simboli_testuali():
    assert D._strip_emoji("ok ✓ fatto 🎉 ⚠ nota ✨") == "ok ✓ fatto  ⚠ nota "


def test_degenerate_solo_ripetizioni_patologiche():
    assert D._degenerate("ciao " * 60)
    assert D._degenerate("." * 30)
    assert not D._degenerate("| a | b |\n|---|---|\n" * 20 + "     ____")
    assert not D._degenerate(" ".join(f"parola{i}" for i in range(80)))


def test_system_message_prefisso_con_documenti(monkeypatch):
    monkeypatch.setitem(D.CFG, "system_prompt", "Regole.")
    m = D.system_message("===== DOCUMENTO: a.txt =====\nZAFFIRO")
    assert m["role"] == "system" and m["content"].startswith("Regole.") and "ZAFFIRO" in m["content"]
    monkeypatch.setitem(D.CFG, "system_prompt", "")
    assert D.system_message("") is None


def test_clean_toglie_marcatori_dalle_risposte_vecchie():
    out = D._clean([{"role": "assistant", "content": "<|channel>thought\n<channel|>Ciao"},
                    {"role": "system", "content": "x"}, {"role": "user", "content": 3}])
    assert out == [{"role": "assistant", "content": "Ciao"}]


def test_safe_save_target(tmp_path):
    home = tmp_path / "home"; (home / "doc").mkdir(parents=True)
    ok, err = D.safe_save_target(str(home / "doc" / "a.md"), str(home))
    assert err is None and ok.endswith("a.md")
    assert D.safe_save_target(str(home / ".." / "x.md"), str(home))[1]           # fuori dalla home
    assert D.safe_save_target(str(home), str(home))[1]                             # la home stessa
    assert D.safe_save_target(str(home / "manca" / "a.md"), str(home))[1]          # cartella inesistente
    os.symlink("/tmp", home / "link")
    assert D.safe_save_target(str(home / "link" / "a.md"), str(home))[1]           # symlink che esce


def test_touch_ingest_lru_protegge_la_chat_in_corso(monkeypatch):
    monkeypatch.setattr(D, "INGEST", {}); monkeypatch.setattr(D, "INGEST_MAX", 3)
    for i in "abcd": D.INGEST[i] = {"kind": "doc"}
    D._touch_ingest(["a"])      # "a" è della chat in corso: usato di recente
    D._evict_ingest()
    assert "a" in D.INGEST and "b" not in D.INGEST
