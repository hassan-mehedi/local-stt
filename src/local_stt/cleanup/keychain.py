"""API keys in the macOS Keychain (Secret Service on Linux), one per API host,
so switching between providers keeps each key."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

log = logging.getLogger(__name__)

SERVICE = "local-stt"


def _account(url: str) -> str:
    host = urlparse(url).netloc
    if not host:
        raise ValueError("enter the API URL first")
    return host


def get_key(url: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, _account(url))
    except (KeyringError, ValueError):
        log.exception("reading the API key failed")
        return None


def set_key(url: str, key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("the key is empty")
    keyring.set_password(SERVICE, _account(url), key)


def delete_key(url: str) -> None:
    try:
        keyring.delete_password(SERVICE, _account(url))
    except PasswordDeleteError:
        pass  # there was no key
