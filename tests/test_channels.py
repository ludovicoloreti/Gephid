import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))
from channels import ChannelSplitter, strip_markers


def run(chunks):
    sp = ChannelSplitter()
    out = []
    for c in chunks:
        out += sp.feed(c)
    out += sp.flush()
    # unisce i pezzi consecutivi dello stesso tipo
    merged = []
    for k, t in out:
        if merged and merged[-1][0] == k:
            merged[-1] = (k, merged[-1][1] + t)
        else:
            merged.append((k, t))
    return merged


def test_canale_vuoto_sparisce():
    assert run(["<|channel>thought\n<channel|>17 per 3 fa 51."]) == [("text", "17 per 3 fa 51.")]


def test_pensiero_separato_dal_testo():
    r = run(["<|channel>thought\nCalcolo 17*3.\n<channel|>Fa 51."])
    assert r == [("thought", "Calcolo 17*3."), ("text", "Fa 51.")]


def test_marcatori_spezzati_in_ogni_punto():
    s = "<|channel>thought\nPenso.\n<channel|>Risposta."
    for i in range(1, len(s)):
        assert run([s[:i], s[i:]]) == [("thought", "Penso."), ("text", "Risposta.")], i


def test_un_carattere_alla_volta():
    s = "<|channel>thought\nA b\n<channel|>Ciao <b>x</b>"
    assert run(list(s)) == [("thought", "A b"), ("text", "Ciao <b>x</b>")]


def test_testo_senza_canali_e_minore_legittimo():
    assert run(["a < b e ", "c <| d"]) == [("text", "a < b e c <| d")]


def test_marcatori_residui_rimossi():
    assert run(["Ciao<turn|>"]) == [("text", "Ciao")]
    assert strip_markers('x <|channel>thought\n<channel|>y<turn|><|"|>') == "x y"


def test_tool_call_separata():
    r = run(['Leggo.<|tool_call>call:leggi{path:<|"|>a.md<|"|>}<tool_call|>'])
    assert r == [("text", "Leggo."), ("tool_call", 'call:leggi{path:<|"|>a.md<|"|>}')]


def test_flush_di_canale_non_chiuso():
    # stop a metà pensiero: quello che c'è resta pensiero, mai testo
    assert run(["<|channel>thought\nmeta"]) == [("thought", "meta")]


def test_tool_call_un_carattere_alla_volta_esce_intera():
    sp = ChannelSplitter(); out = []
    for ch in 'Ok.<|tool_call>call:calcola{espressione:<|"|>2+2<|"|>}<tool_call|>':
        out += sp.feed(ch)
    calls = [t for k, t in out if k == "tool_call"]
    assert calls == ['call:calcola{espressione:<|"|>2+2<|"|>}']
