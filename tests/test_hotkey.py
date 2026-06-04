import pytest

from local_stt.dictation.hotkey import parse_hotkey


def test_super_z():
    hk = parse_hotkey("<super>+z")
    assert hk.modifiers == frozenset({"super"})
    assert hk.trigger == "z"


def test_aliases_normalize():
    assert parse_hotkey("<win>+z") == parse_hotkey("<cmd>+z") == parse_hotkey("<super>+z")


def test_multiple_modifiers():
    hk = parse_hotkey("<ctrl>+<alt>+d")
    assert hk.modifiers == frozenset({"ctrl", "alt"})
    assert hk.trigger == "d"


def test_named_key_no_modifier():
    hk = parse_hotkey("<f9>")
    assert hk.modifiers == frozenset()
    assert hk.trigger == "f9"


def test_case_insensitive():
    assert parse_hotkey("<Super>+Z") == parse_hotkey("<super>+z")


def test_rejects_two_triggers():
    with pytest.raises(ValueError):
        parse_hotkey("a+b")


def test_rejects_modifier_only():
    with pytest.raises(ValueError):
        parse_hotkey("<super>")
