from local_stt.engine.backend import Segment
from local_stt.meeting.diarize import Turn, assign_speakers


def _segs():
    return [
        Segment(0.0, 4.0, "Hi everyone", speaker="Them"),
        Segment(5.0, 9.0, "Thanks for joining", speaker="Them"),
        Segment(10.0, 14.0, "Quick update from me", speaker="Them"),
    ]


def test_two_speakers_split():
    turns = [
        Turn(0.0, 4.5, "SPEAKER_01"),
        Turn(4.8, 9.2, "SPEAKER_00"),
        Turn(9.8, 14.5, "SPEAKER_01"),
    ]
    out = assign_speakers(_segs(), turns)
    # numbered by first appearance: SPEAKER_01 spoke first -> Them 1
    assert [s.speaker for s in out] == ["Them 1", "Them 2", "Them 1"]


def test_single_speaker_keeps_labels():
    turns = [Turn(0.0, 14.0, "SPEAKER_00")]
    out = assign_speakers(_segs(), turns)
    assert [s.speaker for s in out] == ["Them", "Them", "Them"]


def test_no_turns_keeps_labels():
    out = assign_speakers(_segs(), [])
    assert [s.speaker for s in out] == ["Them", "Them", "Them"]


def test_overlap_picks_majority():
    # segment 0-4 overlaps SPEAKER_00 for 1s and SPEAKER_01 for 3s
    turns = [Turn(0.0, 1.0, "SPEAKER_00"), Turn(1.0, 4.0, "SPEAKER_01"), Turn(5.0, 9.0, "SPEAKER_00")]
    out = assign_speakers(_segs()[:2], turns)
    assert out[0].speaker == "Them 2"  # SPEAKER_01 appears second -> Them 2
    assert out[1].speaker == "Them 1"


def test_segment_outside_turns_unchanged():
    turns = [Turn(0.0, 4.0, "SPEAKER_00"), Turn(5.0, 9.0, "SPEAKER_01")]
    out = assign_speakers(_segs(), turns)
    assert out[2].speaker == "Them"  # 10-14s has no overlap
