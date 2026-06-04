from local_stt.engine.backend import Segment, Transcript
from local_stt.export import to_json, to_md, to_srt, to_txt, to_vtt


def _transcript(speakers=False):
    return Transcript(
        segments=[
            Segment(start=0.0, end=2.5, text="Hello there.",
                    speaker="Me" if speakers else None),
            Segment(start=72.4, end=75.913, text="We need to finish the backend.",
                    speaker="Them" if speakers else None),
        ],
        language="en",
        duration=80.0,
        model="large-v3-turbo",
    )


def test_txt():
    assert to_txt(_transcript()) == "Hello there.\nWe need to finish the backend.\n"


def test_txt_speakers():
    assert "Me: Hello there." in to_txt(_transcript(speakers=True))


def test_md():
    md = to_md(_transcript(speakers=True), title="Standup")
    assert md.startswith("# Standup\n")
    assert "[00:00:00] Me: Hello there." in md
    assert "[00:01:12] Them: We need to finish the backend." in md


def test_srt():
    srt = to_srt(_transcript())
    assert "1\n00:00:00,000 --> 00:00:02,500\nHello there." in srt
    assert "2\n00:01:12,400 --> 00:01:15,913\n" in srt


def test_vtt():
    vtt = to_vtt(_transcript())
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:02.500" in vtt


def test_json_roundtrip():
    import json

    data = json.loads(to_json(_transcript()))
    assert data["language"] == "en"
    assert data["segments"][1]["start"] == 72.4
    assert data["model"] == "large-v3-turbo"
