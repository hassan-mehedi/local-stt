"""Cleanup through any OpenAI-compatible chat API: DeepSeek, OpenAI, Gemini, Groq, Ollama..."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import keychain

TIMEOUT_S = 10

# These think before they answer unless told not to: seconds of delay for a cleanup.
# Gemini 3 can't turn it off, so it gets the least.
NO_THINKING = {
    "api.deepseek.com": {"thinking": {"type": "disabled"}},
    "openrouter.ai": {"reasoning": {"enabled": False}},
    "api.openai.com": {"reasoning_effort": "none"},
    "generativelanguage.googleapis.com": {"reasoning_effort": "low"},
}


class ApiError(RuntimeError):
    pass


class ApiCleaner:
    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model

    def complete(self, messages: list[dict]) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            **NO_THINKING.get(urlparse(self.url).hostname, {}),
        }
        headers = {"Content-Type": "application/json"}
        # Ollama on this machine needs no key
        if key := keychain.get_key(self.url):
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            f"{self.url}/chat/completions", data=json.dumps(body).encode(), headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                reply = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ApiError(f"{self.url} answered {e.code}: {_error_text(e)}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise ApiError(f"{self.url} did not answer: {getattr(e, 'reason', e)}") from None
        try:
            return reply["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ApiError(f"{self.url} sent a reply without a message") from None


def _error_text(e: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(e.read())
    except (ValueError, OSError):
        return e.reason
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or e.reason)
    return str(error or e.reason)


def check(url: str, model: str) -> dict:
    """One cleanup through the API, so Settings can show whether the URL,
    model and key work before a real dictation depends on them."""
    from .rewrite import CleanupError, rewrite

    try:
        text = rewrite(ApiCleaner(url, model), "um so this is uh a test of the the cleanup")
    except (ApiError, CleanupError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": text}
