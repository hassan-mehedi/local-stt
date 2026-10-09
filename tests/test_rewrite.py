import pytest

from local_stt.cleanup.rewrite import CleanupError, messages, rewrite


class FakeCleaner:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, msgs, max_tokens):
        self.calls.append((msgs, max_tokens))
        return self.reply


def test_rewrite_returns_the_cleaned_text():
    cleaner = FakeCleaner("Pull PRO-1285 from Plane.\n")
    assert rewrite(cleaner, "um pull pro 1285 from plane", "cmux") == "Pull PRO-1285 from Plane."


@pytest.mark.parametrize("reply, expected", [
    ("<transcript>\nShip it.\n</transcript>", "Ship it."),
    ('"Ship it."', "Ship it."),
    ("<think>the user wants</think>\nShip it.", "Ship it."),
])
def test_rewrite_strips_wrappers_the_model_added(reply, expected):
    assert rewrite(FakeCleaner(reply), "ship it") == expected


@pytest.mark.parametrize("reply, error", [
    ("", "nothing"),
    ("Paris is the capital of France. It has been the capital since the year 987 and it"
     " is home to about two million people, the Louvre and the Eiffel Tower.", "answered"),
])
def test_rewrite_rejects_empty_or_answering_replies(reply, error):
    with pytest.raises(CleanupError, match=error):
        rewrite(FakeCleaner(reply), "what's the capital of France")


def test_rewrite_skips_the_model_for_empty_text():
    cleaner = FakeCleaner("anything")
    assert rewrite(cleaner, "  ") == "  "
    assert cleaner.calls == []


def test_messages_name_the_app_and_the_dictionary_words():
    system, user = messages("check local stt", "Slack", ["local-stt", "WKWebView"])
    assert system["role"] == "system"
    assert "Slack" in user["content"]
    assert "local-stt, WKWebView" in user["content"]
    assert "<transcript>\ncheck local stt\n</transcript>" in user["content"]
