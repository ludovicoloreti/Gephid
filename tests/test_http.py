"""API locali reali, senza caricare il modello o modificare i dati dell'utente."""
import http.client
import json
import re
import threading

import pytest

import diffuchat as D
from store import ChatStore


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "CHATS", ChatStore(str(tmp_path / "chats")))
    monkeypatch.setattr(D, "INGEST", {})
    monkeypatch.setattr(D, "MODEL_OK", False)
    monkeypatch.setattr(D, "MODEL_ERR", "")
    monkeypatch.setattr(D, "_NEEDS_DL", False)
    server = D.GephidServer(("127.0.0.1", 0), D.H)
    monkeypatch.setattr(D, "PORT", server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    yield request
    server.shutdown()
    server.server_close()
    thread.join()


def test_health_and_offline_ui(api):
    status, _, body = api("GET", "/api/health")
    assert status == 200 and json.loads(body)["model_ok"] is False
    status, headers, body = api("GET", "/")
    assert status == 200 and b"/static/marked.min.js" in body
    assert "Content-Security-Policy" in headers


def test_static_is_revalidated_after_app_updates(api):
    status, headers, body = api("GET", "/static/marked.min.js")
    assert status == 200 and body
    assert headers["Cache-Control"] == "no-cache"


def test_ui_uses_versioned_assets_to_bypass_previous_long_lived_cache(api):
    _, _, body = api("GET", "/")
    assets = re.findall(rb'(?:src|href)="(/static/[^"?]+\?v=[a-f0-9]+)"', body)
    assert len(assets) == 7
    for asset in assets:
        assert api("GET", asset.decode())[0] == 200


@pytest.mark.parametrize("body", ["[]", "null", "42", '"text"', "{broken"])
def test_invalid_json_returns_a_client_error(api, body):
    status, _, response = api("POST", "/api/chats/get", body)
    assert status == 400 and json.loads(response)["error"]


@pytest.mark.parametrize("length", ["-1", "invalid"])
def test_invalid_content_length_is_rejected_without_waiting(api, length):
    status, _, body = api("POST", "/api/chats/get", headers={"Content-Length": length})
    assert status == 400 and json.loads(body)["error"]


def test_external_host_and_origin_are_rejected(api):
    assert api("GET", "/api/config", headers={"Host": "evil.example:8890"})[0] == 403
    assert api("POST", "/api/chats/get", "{}", {"Origin": "https://evil.example"})[0] == 403
    assert api("GET", "/static/../diffuchat.py")[0] == 404


def test_explicit_chat_save_restores_documents(api, monkeypatch):
    monkeypatch.setitem(D.INGEST, "abc12345", {"kind": "doc", "name": "note.txt", "text": "ZAFFIRO-7731", "tokens": 5})
    chat = {"id": "abcdef12", "title": "Prova", "history": [{"role": "user", "content": "ciao"}],
            "attachments": [{"id": "abc12345", "name": "note.txt"}]}
    assert json.loads(api("POST", "/api/chats/save", json.dumps({"chat": chat}))[2])["ok"]
    D.INGEST.clear()
    loaded = json.loads(api("POST", "/api/chats/get", '{"id":"abcdef12"}')[2])
    assert loaded["history"] == chat["history"]
    assert D.INGEST["abc12345"]["text"] == "ZAFFIRO-7731"
    assert json.loads(api("POST", "/api/chats/delete", '{"id":"abcdef12"}')[2])["ok"]
    assert json.loads(api("GET", "/api/chats")[2])["chats"] == []


def test_chat_reports_model_not_ready(api):
    status, _, body = api("POST", "/api/chat", '{"messages":[]}')
    assert status == 200 and json.loads(body)["error"]
