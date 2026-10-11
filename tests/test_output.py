import contextlib

import pytest
from pynput.keyboard import Key

from local_stt.dictation.output import MacTypeOutput


class FakeKeyboard:
    def __init__(self):
        self.events = []
        self.held = []

    def type(self, text):
        self.events.append(("type", text, tuple(self.held)))

    def tap(self, key):
        self.events.append(("tap", key, tuple(self.held)))

    @contextlib.contextmanager
    def pressed(self, *keys):
        self.held.extend(keys)
        try:
            yield
        finally:
            del self.held[-len(keys):]


def _mac_type_output() -> tuple[MacTypeOutput, FakeKeyboard]:
    output = MacTypeOutput.__new__(MacTypeOutput)
    output._keyboard = FakeKeyboard()
    return output, output._keyboard


@pytest.mark.parametrize(
    "text, events",
    [
        ("one line", [("type", "one line", ())]),
        (
            "First.\n\nSecond.",
            [
                ("type", "First.", ()),
                ("tap", Key.enter, (Key.shift,)),
                ("tap", Key.enter, (Key.shift,)),
                ("type", "Second.", ()),
            ],
        ),
        (
            "a\r\nb",
            [("type", "a", ()), ("tap", Key.enter, (Key.shift,)), ("type", "b", ())],
        ),
    ],
)
def test_mac_type_output_types_line_breaks_as_shift_enter(text, events):
    output, keyboard = _mac_type_output()
    output.emit(text)
    assert keyboard.events == events
