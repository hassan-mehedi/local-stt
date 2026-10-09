import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from local_stt.cleanup import api, keychain
from local_stt.cleanup.api import ApiCleaner, ApiError


@pytest.fixture
def chat_server():
    """A fake /v1/chat/completions on localhost that records each request."""
    seen = []
    reply = {"status": 200, "body": {"choices": [{"message": {"content": "Ship it."}}]}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            data = json.dumps(reply["body"]).encode()
            self.send_response(reply["status"])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1", seen, reply
    httpd.shutdown()


def test_api_cleaner_sends_the_key_model_and_messages(chat_server, monkeypatch):
    url, seen, _ = chat_server
    monkeypatch.setattr(keychain, "get_key", lambda u: "sk-test")
    msgs = [{"role": "user", "content": "ship it"}]
    assert ApiCleaner(url + "/", "deepseek-chat").complete(msgs, 50) == "Ship it."
    assert seen[0]["path"] == "/v1/chat/completions"
    assert seen[0]["auth"] == "Bearer sk-test"
    assert seen[0]["body"] == {"model": "deepseek-chat", "messages": msgs, "max_tokens": 50, "temperature": 0}


def test_api_cleaner_sends_no_auth_header_without_a_key(chat_server, monkeypatch):
    url, seen, _ = chat_server
    monkeypatch.setattr(keychain, "get_key", lambda u: None)
    ApiCleaner(url, "qwen3").complete([], 10)
    assert seen[0]["auth"] is None


@pytest.mark.parametrize("status, body, error", [
    (401, {"error": {"message": "Authentication Fails"}}, "401: Authentication Fails"),
    (402, {"error": "Insufficient Balance"}, "402: Insufficient Balance"),
    (200, {"choices": []}, "without a message"),
])
def test_api_cleaner_reports_the_provider_error(chat_server, monkeypatch, status, body, error):
    url, _, reply = chat_server
    monkeypatch.setattr(keychain, "get_key", lambda u: "sk-test")
    reply.update(status=status, body=body)
    with pytest.raises(ApiError, match=error):
        ApiCleaner(url, "deepseek-chat").complete([], 10)


def test_api_cleaner_gives_up_when_nothing_listens(monkeypatch):
    monkeypatch.setattr(keychain, "get_key", lambda u: None)
    monkeypatch.setattr(api, "TIMEOUT_S", 1)
    with pytest.raises(ApiError, match="did not answer"):
        ApiCleaner("http://127.0.0.1:9/v1", "m").complete([], 10)
