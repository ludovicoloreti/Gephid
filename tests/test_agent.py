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


# ---- file dell'utente: percorsi, permessi per cartella, sola scrittura di file nuovi ----
@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in ["Desktop", "Downloads", "Documents", "Library/Mail", ".ssh"]:
        (h / d).mkdir(parents=True)
    (h / "Desktop" / "a.md").write_text("ciao mondo\nseconda riga con PENALE\n")
    (h / "Downloads" / "fattura.txt").write_text("totale 120 euro")
    monkeypatch.setattr(A, "_home", lambda: str(h.resolve()))
    return h.resolve()


def test_resolve_user_path(home):
    assert A.resolve_user_path("~/Desktop") == str(home / "Desktop")
    assert A.resolve_user_path("Scrivania") == str(home / "Desktop")
    assert A.resolve_user_path("scrivania/a.md") == str(home / "Desktop" / "a.md")
    assert A.resolve_user_path(str(home / "Downloads" / "fattura.txt")) == str(home / "Downloads" / "fattura.txt")
    assert A.resolve_user_path("Downloads") == str(home / "Downloads")
    for bad in ["", "~", "/etc/passwd", "~/.ssh", "~/Library/Mail", "~/Desktop/../../x", "~/.zshrc"]:
        with pytest.raises(ValueError):
            A.resolve_user_path(bad)
    os.symlink("/tmp", home / "Desktop" / "esce")
    with pytest.raises(ValueError):
        A.resolve_user_path("~/Desktop/esce/x")


def test_permesso_per_cartella(home):
    f = A.UserFiles(lambda name, data: data.decode(), set())
    assert f.need_grant("~/Desktop") == str(home / "Desktop")          # da chiedere
    assert f.need_grant("~/Desktop/a.md") == str(home / "Desktop")     # file -> la sua cartella
    with pytest.raises(ValueError):
        f.list_files("~/Desktop")                                      # senza permesso non legge
    f.grants.add(str(home / "Desktop"))
    assert f.need_grant("~/Desktop/a.md") is None
    assert "a.md" in f.list_files("Scrivania") and "1 elementi" in f.list_files("~/Desktop")
    assert "seconda riga" in f.read_file("~/Desktop/a.md")
    assert "a.md:2" in f.grep("penale", "~/Desktop")
    with pytest.raises(ValueError):
        f.read_file("~/Downloads/fattura.txt")                         # altra cartella: altro permesso
    assert "Scrivania" in A.folder_label(str(home / "Desktop"))


def test_scrittura_solo_file_nuovi(home):
    f = A.UserFiles(lambda n, d: d.decode(), set())
    with pytest.raises(ValueError):
        f.write_preview("~/Desktop/a.md", "x")                         # esiste: mai sovrascrivere
    assert (home / "Desktop" / "a.md").read_text().startswith("ciao")
    assert "nuovo file" in f.write_preview("~/Desktop/c.md", "# Titolo")
    assert "creato" in f.write_file("~/Desktop/c.md", "# Titolo\ntesto").lower()
    f.write_file("~/Desktop/doc.docx", "# Titolo\n\nParagrafo uno.\n\n- punto")
    import docx
    d = docx.Document(str(home / "Desktop" / "doc.docx"))
    assert [p.text for p in d.paragraphs if p.text] == ["Titolo", "Paragrafo uno.", "punto"]
    with pytest.raises(ValueError):
        f.write_file("~/Desktop/manca/x.md", "x")                      # cartella inesistente
    with pytest.raises(ValueError):
        f.write_file("~/.ssh/authorized_keys2", "x")                   # posizione riservata


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


def test_sandbox_niente_rm_shell_segnali(tmp_path):
    vittima = os.path.expanduser("~/Desktop/gephid-test-vittima")
    os.makedirs(vittima, exist_ok=True)
    open(os.path.join(vittima, "importante.txt"), "w").write("x")
    try:
        for code in [f"import subprocess\nsubprocess.run(['/bin/rm','-rf',{vittima!r}],check=True)",
                     "import subprocess\nsubprocess.run(['/bin/sh','-c','echo ciao'],check=True)",
                     f"import shutil\nshutil.rmtree({vittima!r})",
                     "import os, signal\nos.kill(os.getppid(), signal.SIGCONT)"]:
            r = A.run_code("python", code, timeout=20)
            assert r["exit"] != 0, (code, r)
        assert os.path.exists(os.path.join(vittima, "importante.txt"))
        assert "45" in A.run_code("python", "print(sum(range(10)))", timeout=20)["output"]
    finally:
        import shutil; shutil.rmtree(vittima, ignore_errors=True)
