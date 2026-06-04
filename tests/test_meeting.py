from local_stt.engine.backend import Segment, Transcript
from local_stt.meeting.recorder import slugify
from local_stt.meeting.transcribe import label, merge


def _t(segs, duration=10.0):
    return Transcript(segments=segs, language="en", duration=duration, model="tiny")


def test_slugify():
    assert slugify("Weekly Standup!") == "weekly-standup"
    assert slugify("  ") == "meeting"
    assert slugify("1:1 w/ Sam") == "1-1-w-sam"


def test_label():
    t = label(_t([Segment(0, 1, "hi")]), "Me")
    assert t.segments[0].speaker == "Me"


def test_merge_interleaves_by_timestamp():
    mine = label(_t([Segment(0.0, 2.0, "Hello"), Segment(10.0, 12.0, "Sure")]), "Me")
    theirs = label(_t([Segment(3.0, 8.0, "Hi, can you hear me?")], duration=15.0), "Them")
    merged = merge(mine, theirs)
    assert [(s.speaker, s.text) for s in merged.segments] == [
        ("Me", "Hello"),
        ("Them", "Hi, can you hear me?"),
        ("Me", "Sure"),
    ]
    assert merged.duration == 15.0


def test_merge_empty_track():
    mine = label(_t([Segment(0.0, 1.0, "Testing")]), "Me")
    theirs = label(_t([], duration=0.0), "Them")
    merged = merge(mine, theirs)
    assert len(merged.segments) == 1
    assert merged.segments[0].speaker == "Me"
