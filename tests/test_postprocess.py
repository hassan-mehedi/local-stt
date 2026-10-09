import pytest

from local_stt.dictation.postprocess import drop_fillers, postprocess


def test_strips_and_collapses_whitespace():
    assert postprocess("  hello   world \n", append_space=False) == "hello world"


def test_append_space():
    assert postprocess("hello", append_space=True) == "hello "


def test_empty_stays_empty():
    assert postprocess("   ", append_space=True) == ""


@pytest.mark.parametrize("heard, expected", [
    ("Um pull Pro 1285 from plane.", "Pull Pro 1285 from plane."),
    ("check uh wo like in the portal, uh like what is the scope", "check wo like in the portal, like what is the scope"),
    ("So, um, I think it works.", "So, I think it works."),
    ("I uhh need the the report.", "I need the report."),
    ("Hmm. Okay, ship it.", "Okay, ship it."),
    ("I know that that is wrong and it had had issues.", "I know that that is wrong and it had had issues."),
    ("The umbrella is under the erm table.", "The umbrella is under the table."),
    ("Uh-oh, the build broke.", "Uh-oh, the build broke."),
    ("Okay. Uh, so we go.", "Okay. So we go."),
    ("um uh", ""),
])
def test_drop_fillers_removes_sounds_and_stutters(heard, expected):
    assert drop_fillers(heard) == expected
