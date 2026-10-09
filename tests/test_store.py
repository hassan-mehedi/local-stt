from datetime import datetime

import numpy as np
import pytest

from local_stt.store import FrontApp, Store, apply_dictionary


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "history.db")
    yield s
    s.close()


def _at(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


def test_add_and_page_history(store):
    for i in range(5):
        store.add_dictation(f"note number {i}", audio_ms=1000, elapsed_ms=100)
    first = store.history(limit=2)
    assert [r["text"] for r in first["items"]] == ["note number 4", "note number 3"]
    assert first["has_more"]
    rest = store.history(before=first["items"][-1]["id"], limit=10)
    assert [r["text"] for r in rest["items"]] == ["note number 2", "note number 1", "note number 0"]
    assert not rest["has_more"]


def test_search_matches_text_and_app(store):
    store.add_dictation("ship the build", 1000, 100, app=FrontApp("com.tinyspeck.slackmacgap", "Slack"))
    store.add_dictation("buy 100% coffee", 1000, 100)
    assert [r["text"] for r in store.history(query="slack")["items"]] == ["ship the build"]
    assert [r["text"] for r in store.history(query="100%")["items"]] == ["buy 100% coffee"]
    assert store.history(query="_")["items"] == []


def test_audio_saved_and_deleted_with_row(store):
    row = store.add_dictation("hello", 500, 50, pcm=np.zeros(8000, dtype=np.float32))
    assert row["has_audio"] == 1
    assert store.audio_path(row["id"]).exists()
    assert store.delete_dictation(row["id"])
    assert not store.audio_path(row["id"]).exists()
    assert store.dictation(row["id"]) is None


def test_home_stats_week_and_streak(store):
    # Wednesday 2026-10-07; the week starts Monday the 5th
    store.add_dictation("one two three four", 6000, 100, created_at=_at("2026-10-07T09:00"))
    store.add_dictation("five six", 6000, 100, created_at=_at("2026-10-06T09:00"))
    store.add_dictation("old words here", 6000, 100, created_at=_at("2026-10-04T09:00"))
    stats = store.home_stats(now=datetime(2026, 10, 7, 12))
    assert stats["week_words"] == 6
    assert stats["week_wpm"] == 30  # 6 words in 12 seconds
    assert stats["streak_days"] == 2


def test_streak_counts_from_yesterday_before_first_dictation_today(store):
    store.add_dictation("a", 1000, 1, created_at=_at("2026-10-05T09:00"))
    store.add_dictation("b", 1000, 1, created_at=_at("2026-10-06T09:00"))
    assert store.home_stats(now=datetime(2026, 10, 7, 8))["streak_days"] == 2


def test_insights_ranges_apps_and_heatmap(store):
    slack = FrontApp("com.tinyspeck.slackmacgap", "Slack")
    store.add_dictation("a b c", 3000, 1, app=slack, created_at=_at("2026-10-07T09:00"))
    store.add_dictation("d", 1000, 1, created_at=_at("2026-09-01T09:00"))
    store.add_dictation("e", 1000, 1, created_at=_at("2026-09-02T09:00"))
    week = store.insights("week", now=datetime(2026, 10, 7, 12))
    assert week["words"] == 3
    assert week["apps"] == [{"name": "Slack", "words": 3, "share": 1.0}]
    everything = store.insights("all", now=datetime(2026, 10, 7, 12))
    assert everything["words"] == 5
    assert everything["longest_streak_days"] == 2
    assert len(everything["heatmap"]) == 182
    assert everything["heatmap"][0]["date"] == "2026-04-13"  # a Monday, 25 weeks back
    assert len(everything["wpm_days"]) == 30
    with pytest.raises(ValueError):
        store.insights("year")


def test_dictionary_entries_validate(store):
    store.add_entry("words", "  Parakeet  ")
    with pytest.raises(ValueError):
        store.add_entry("words", "parakeet ")
    with pytest.raises(ValueError):
        store.add_entry("replacements", "gonna", "")
    with pytest.raises(ValueError):
        store.add_entry("colours", "x", "y")
    assert [e["phrase"] for e in store.dictionary()["words"]] == ["Parakeet"]


@pytest.mark.parametrize("heard, expected", [
    ("we use parakeet on mlx", "we use Parakeet on MLX"),
    ("try local stt today", "try local-stt today"),
    ("the wk web view crashed", "the WKWebView crashed"),
    ("I'm gonna go", "I'm going to go"),
    ("first line new paragraph. Second", "first line\n\nSecond"),
    ("parakeets are birds", "parakeets are birds"),
])
def test_apply_dictionary(heard, expected):
    entries = {
        "words": [{"phrase": "Parakeet"}, {"phrase": "MLX"}, {"phrase": "local-stt"}, {"phrase": "WKWebView"}],
        "replacements": [{"phrase": "gonna", "value": "going to"}],
        "snippets": [{"phrase": "new paragraph", "value": "\\n\\n"}],
    }
    assert apply_dictionary(heard, entries) == expected


def test_store_keeps_raw_text_when_cleanup_changed_it(store):
    cleaned = store.add_dictation("Pull PRO-1285.", 1000, 100, raw_text="Um pull Pro 1285.")
    same = store.add_dictation("Ship it.", 1000, 100, raw_text="Ship it.")
    assert cleaned["raw_text"] == "Um pull Pro 1285."
    assert same["raw_text"] is None
    assert [r["text"] for r in store.history(query="pro 1285")["items"]] == ["Pull PRO-1285."]


def test_store_upgrades_a_file_from_before_raw_text(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE dictations (id INTEGER PRIMARY KEY, created_at REAL NOT NULL,"
        " text TEXT NOT NULL, words INTEGER NOT NULL, audio_ms INTEGER NOT NULL,"
        " elapsed_ms INTEGER NOT NULL, app_id TEXT, app_name TEXT,"
        " has_audio INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO dictations (created_at, text, words, audio_ms, elapsed_ms)"
        " VALUES (1, 'old note', 2, 1000, 100);"
    )
    db.close()
    s = Store(path)
    try:
        assert s.history()["items"][0]["raw_text"] is None
        assert s.add_dictation("new", 1, 1, raw_text="nu")["raw_text"] == "nu"
    finally:
        s.close()
    s = Store(path)  # opening again must not repeat the upgrade
    s.close()
