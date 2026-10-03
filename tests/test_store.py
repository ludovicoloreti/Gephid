import json
import pytest
from store import ChatStore


def test_salva_elenca_carica_elimina(tmp_path):
    st = ChatStore(str(tmp_path))
    chat = {"id": "3f2a9c1e-77aa-4b1c-9d00-aa11bb22cc33", "title": "Contratto fornitore",
            "history": [{"role": "user", "content": "ciao"}], "docs": [{"id": "e7ab919193dd", "name": "a.txt", "text": "x"}]}
    st.save(chat)
    lst = st.list()
    assert [c["id"] for c in lst] == [chat["id"]] and lst[0]["title"] == "Contratto fornitore" and "saved_at" in lst[0]
    assert st.load(chat["id"])["docs"][0]["text"] == "x"
    st.delete(chat["id"])
    assert st.list() == [] and st.load(chat["id"]) is None


@pytest.mark.parametrize("bad", ["../etc/passwd", "", "a/b", "x" * 200, "..", "ZZZ!"])
def test_id_non_validi_rifiutati(tmp_path, bad):
    st = ChatStore(str(tmp_path))
    with pytest.raises(ValueError):
        st.save({"id": bad, "history": []})
    assert st.load(bad) is None


def test_file_corrotto_non_rompe_elenco(tmp_path):
    st = ChatStore(str(tmp_path))
    (tmp_path / "abcdef12.json").write_text("{rotto")
    st.save({"id": "abcdef13", "title": "ok", "history": []})
    assert [c["id"] for c in st.list()] == ["abcdef13"]
