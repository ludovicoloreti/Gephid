import os, time
import pytest
import agent as A


# ---- parsing delle chiamate native del template ----
def test_parse_call_stringhe_numeri_annidati():
    name, args = A.parse_call('call:scrivi_file{contenuto:<|"|>riga 1, con {graffe} e: due punti<|"|>,path:<|"|>a.md<|"|>}')
    assert name == "scrivi_file" and args == {"contenuto": "riga 1, con {graffe} e: due punti", "path": "a.md"}
    name, args = A.parse_call('call:x{n:3,f:2.5,b:true,l:[<|"|>a<|"|>,1],o:{k:<|"|>v<|"|>}}')
    assert args == {"n": 3, "f": 2.5, "b": True, "l": ["a", 1], "o": {"k": "v"}}
    assert A.parse_call("call:data_ora{}") == ("data_ora", {})


def test_parse_call_malformata():
    with pytest.raises(ValueError):
        A.parse_call("non una chiamata")


# ---- calcolatrice esatta senza eval ----
def test_calc():
    assert A.calc("2+3*4") == "14"
    assert A.calc("1234.5 * 87 - 19/7").startswith("107398.78571428")
    assert A.calc("2**10") == "1024"
    assert A.calc("sqrt(16) + 1") == "5"
    assert A.calc("1/3") .startswith("0.33333")
    assert A.calc("0.1 + 0.2") == "0.3"  # decimali esatti, niente 0.30000000000000004
    for bad in ["__import__('os')", "open('x')", "9**9**9", "a.b", "[1]*10"]:
        with pytest.raises(ValueError):
            A.calc(bad)


# ---- ricerca nei documenti della chat ----
def test_search_docs_trova_il_passaggio_giusto():
    docs = [{"name": "contratto.txt", "text": ("clausola generica di riempimento. " * 80) +
             "\n\nLa penale per recesso anticipato è pari al 15% del valore residuo.\n\n" + ("altro testo. " * 80)},
            {"name": "note.txt", "text": "appunti sulla riunione di lunedì"}]
    hits = A.search_docs(docs, "penale recesso")
    assert hits and hits[0]["doc"] == "contratto.txt" and "15%" in hits[0]["text"]
    assert A.search_docs(docs, "zzzz") == []


# ---- confinamento nella cartella di lavoro ----
def test_safe_path(tmp_path):
    root = tmp_path / "lavoro"; (root / "sub").mkdir(parents=True)
    assert A.safe_path(str(root), "sub/a.md") == str((root / "sub" / "a.md").resolve())
    for bad in ["../x", "/etc/passwd", "sub/../../x", ""]:
        with pytest.raises(ValueError):
            A.safe_path(str(root), bad) if bad else A.safe_path(str(root), "..")
    os.symlink("/tmp", root / "esce")
    with pytest.raises(ValueError):
        A.safe_path(str(root), "esce/x")
    with pytest.raises(ValueError):
        A.safe_path("", "a.md")  # nessuna cartella autorizzata


def test_file_tools(tmp_path):
    root = str(tmp_path)
    (tmp_path / "a.md").write_text("ciao mondo\nseconda riga con PENALE\n")
    (tmp_path / "d").mkdir(); (tmp_path / "d" / "b.txt").write_text("niente")
    ws = A.Workspace(root, extract=lambda name, data: data.decode())
    assert "a.md" in ws.list_files(".") and "d/" in ws.list_files(".")
    assert "seconda riga" in ws.read_file("a.md")
    assert "a.md:2" in ws.grep("penale")
    prev = ws.write_preview("nuovo/c.md", "# Titolo\ntesto")
    assert "nuovo/c.md" in prev and "Titolo" in prev
    out = ws.write_file("nuovo/c.md", "# Titolo\ntesto")
    assert os.path.exists(tmp_path / "nuovo" / "c.md") and "scritto" in out.lower()
    ws.write_file("doc.docx", "# Titolo\n\nParagrafo uno.\n\n- punto")
    import docx
    d = docx.Document(str(tmp_path / "doc.docx"))
    assert [p.text for p in d.paragraphs if p.text] == ["Titolo", "Paragrafo uno.", "punto"]


# ---- esecuzione codice in sandbox ----
def test_run_code_sandbox(tmp_path):
    r = A.run_code("python", "print(6*7)", timeout=20)
    assert "42" in r["output"] and r["exit"] == 0
    r = A.run_code("python", "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=3)", timeout=20)
    assert r["exit"] != 0  # rete esterna bloccata
    home_file = os.path.expanduser("~/gephid_sandbox_should_not_exist.txt")
    r = A.run_code("python", f"open({home_file!r},'w').write('x')", timeout=20)
    assert r["exit"] != 0 and not os.path.exists(home_file)
    r = A.run_code("python", "while True: pass", timeout=2)
    assert r["timeout"]


def test_processo_in_background_solo_loopback():
    r = A.run_code("python", "import http.server as h\nh.HTTPServer(('127.0.0.1', 8097), h.SimpleHTTPRequestHandler).serve_forever()",
                   background=True)
    try:
        assert r["running"] and r["id"] in A.PROCS
    finally:
        A.stop_proc(r["id"])
    r = A.run_code("python", "import http.server as h\nh.HTTPServer(('0.0.0.0', 8098), h.SimpleHTTPRequestHandler).serve_forever()",
                   background=True)
    assert not r["running"] and "127.0.0.1" in r["output"]  # in ascolto su tutte le interfacce: fermato
