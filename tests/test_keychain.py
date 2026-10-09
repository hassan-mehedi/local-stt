import pytest

from local_stt.cleanup import keychain


def test_keychain_keeps_one_key_per_api_host(memory_keyring):
    keychain.set_key("https://api.deepseek.com/v1", " sk-deep ")
    keychain.set_key("https://openrouter.ai/api/v1", "sk-or")
    assert keychain.get_key("https://api.deepseek.com") == "sk-deep"
    assert memory_keyring.items[("local-stt", "openrouter.ai")] == "sk-or"


def test_keychain_delete_forgets_the_key_and_ignores_a_missing_one(memory_keyring):
    keychain.set_key("https://api.deepseek.com/v1", "sk-deep")
    keychain.delete_key("https://api.deepseek.com/v1")
    keychain.delete_key("https://api.deepseek.com/v1")
    assert keychain.get_key("https://api.deepseek.com/v1") is None


@pytest.mark.parametrize("url, key", [("", "sk"), ("https://api.deepseek.com", "  ")])
def test_keychain_set_rejects_a_missing_url_or_key(memory_keyring, url, key):
    with pytest.raises(ValueError):
        keychain.set_key(url, key)
