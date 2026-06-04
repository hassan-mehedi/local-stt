from local_stt.dictation.postprocess import postprocess


def test_strips_and_collapses_whitespace():
    assert postprocess("  hello   world \n", append_space=False) == "hello world"


def test_append_space():
    assert postprocess("hello", append_space=True) == "hello "


def test_empty_stays_empty():
    assert postprocess("   ", append_space=True) == ""
