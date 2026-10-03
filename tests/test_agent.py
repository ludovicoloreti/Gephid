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
    assert "e+" in A.calc("exp(100000)")  # numeri enormi in notazione scientifica
    for bad in ["__import__('os')", "open('x')", "9**9**9", "a.b", "[1]*10", "1,000*3", "exp(10**7)"]:
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


def test_sandbox_non_raggiunge_localhost_ne_dns():
    """Il codice NON deve poter parlare col backend di Gephid (127.0.0.1:8890 -> /api/save scrive ovunque)."""
    import socket, threading
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1); port = srv.getsockname()[1]
    try:
        r = A.run_code("python", f"import socket\nsocket.create_connection(('127.0.0.1', {port}), timeout=3)", timeout=20)
        assert r["exit"] != 0, r
    finally:
        srv.close()
    r = A.run_code("python", "import socket\nsocket.getaddrinfo('example.com', 443)", timeout=20)
    assert r["exit"] != 0 and "gaierror" in r["output"]
    r = A.run_code("python", "print(open(%r).read(5))" % os.path.expanduser("~/.config/diffuchat/config.json"), timeout=20)
    assert r["exit"] != 0  # segreti/config di Gephid non leggibili


def test_server_figlio_su_tutte_le_interfacce_viene_fermato():
    code = ("import os, http.server as h\n"
            "if os.fork() == 0:\n"
            "    h.HTTPServer(('0.0.0.0', 8099), h.SimpleHTTPRequestHandler).serve_forever()\n"
            "else:\n"
            "    import time; time.sleep(60)\n")
    r = A.run_code("python", code, background=True)
    import time; time.sleep(0.5)
    assert not r["running"] or not A.procs_status(), r
    import subprocess
    assert not subprocess.run(["lsof", "-nP", "-iTCP:8099", "-sTCP:LISTEN"], capture_output=True, text=True).stdout


def test_timeout_uccide_anche_i_figli():
    code = "import os, time\nif os.fork() == 0:\n    time.sleep(120)\nelse:\n    time.sleep(120)\n"
    r = A.run_code("python", code, timeout=2)
    assert r["timeout"]
    import subprocess, time; time.sleep(0.5)
    # pattern stretto: il processo eseguito è <tmp>/gephid-run-XXXX/main.py
    assert not subprocess.run(["pgrep", "-f", r"gephid-run-[A-Za-z0-9_]+/main\.py"], capture_output=True, text=True).stdout
