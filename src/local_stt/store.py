"""Dictation history and the personal dictionary in one SQLite file. A row's clip,
if kept, is audio/<id>.wav next to it (16 kHz mono, 16-bit)."""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import wave
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

DATA_DIR = Path.home() / ".local" / "share" / "local-stt"
DB_PATH = DATA_DIR / "history.db"

# words per minute of an average typist, for the "saved vs typing" figure
TYPING_WPM = 40

DICTIONARY_KINDS = ("words", "replacements", "snippets")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    text TEXT NOT NULL,
    words INTEGER NOT NULL,
    audio_ms INTEGER NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    app_id TEXT,
    app_name TEXT,
    has_audio INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS dictations_created ON dictations (created_at);
CREATE TABLE IF NOT EXISTS dictionary (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    phrase TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    UNIQUE (kind, phrase COLLATE NOCASE)
);
"""


def count_words(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class FrontApp:
    bundle_id: str | None
    name: str | None


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self.audio_dir = self.path.parent / "audio"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _write(self, sql: str, args: tuple = ()) -> int:
        with self._lock, self._db:
            return self._db.execute(sql, args).lastrowid

    def add_dictation(
        self,
        text: str,
        audio_ms: int,
        elapsed_ms: int,
        app: FrontApp | None = None,
        pcm: np.ndarray | None = None,
        created_at: float | None = None,
    ) -> dict:
        text = text.strip()
        row_id = self._write(
            "INSERT INTO dictations (created_at, text, words, audio_ms, elapsed_ms,"
            " app_id, app_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                created_at or time.time(), text, count_words(text), audio_ms, elapsed_ms,
                app.bundle_id if app else None, app.name if app else None,
            ),
        )
        if pcm is not None and len(pcm):
            self._save_audio(row_id, pcm)
            self._write("UPDATE dictations SET has_audio = 1 WHERE id = ?", (row_id,))
        return self.dictation(row_id)

    def _save_audio(self, row_id: int, pcm: np.ndarray) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        samples = (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(str(self.audio_path(row_id)), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(samples.tobytes())

    def audio_path(self, row_id: int) -> Path:
        return self.audio_dir / f"{int(row_id)}.wav"

    def dictation(self, row_id: int) -> dict | None:
        rows = self._query("SELECT * FROM dictations WHERE id = ?", (row_id,))
        return dict(rows[0]) if rows else None

    def history(self, query: str = "", before: int | None = None, limit: int = 50) -> dict:
        """Newest first. `before` is the last id of the previous page."""
        sql, args = "SELECT * FROM dictations WHERE 1 = 1", []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND (text LIKE ? ESCAPE '\\' OR app_name LIKE ? ESCAPE '\\')"
            args += [f"%{escaped}%"] * 2
        if before is not None:
            sql += " AND id < ?"
            args.append(before)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit + 1)
        rows = [dict(r) for r in self._query(sql, tuple(args))]
        return {"items": rows[:limit], "has_more": len(rows) > limit}

    def delete_dictation(self, row_id: int) -> bool:
        with self._lock, self._db:
            deleted = self._db.execute("DELETE FROM dictations WHERE id = ?", (row_id,)).rowcount
        self.audio_path(row_id).unlink(missing_ok=True)
        return bool(deleted)

    def _days(self, since: float | None = None) -> dict[date, dict]:
        """Per local day: words and audio milliseconds."""
        sql = "SELECT created_at, words, audio_ms FROM dictations"
        args: tuple = ()
        if since is not None:
            sql += " WHERE created_at >= ?"
            args = (since,)
        days: dict[date, dict] = {}
        for r in self._query(sql, args):
            day = datetime.fromtimestamp(r["created_at"]).date()
            d = days.setdefault(day, {"words": 0, "audio_ms": 0})
            d["words"] += r["words"]
            d["audio_ms"] += r["audio_ms"]
        return days

    @staticmethod
    def _wpm(words: int, audio_ms: int) -> int:
        return round(words / (audio_ms / 60000)) if audio_ms else 0

    @staticmethod
    def _streaks(days: set[date], today: date) -> tuple[int, int]:
        """(current, longest). The current streak survives a today with no
        dictation yet, so it counts back from yesterday then."""
        current = 0
        day = today if today in days else today - timedelta(days=1)
        while day in days:
            current += 1
            day -= timedelta(days=1)
        longest = run = 0
        previous = None
        for day in sorted(days):
            run = run + 1 if previous == day - timedelta(days=1) else 1
            longest = max(longest, run)
            previous = day
        return current, longest

    def home_stats(self, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        days = self._days()
        week = [d for day, d in days.items() if day >= week_start]
        words = sum(d["words"] for d in week)
        audio_ms = sum(d["audio_ms"] for d in week)
        saved_min = max(0, round(words / TYPING_WPM - audio_ms / 60000))
        current, _ = self._streaks(set(days), today)
        return {
            "week_words": words,
            "week_wpm": self._wpm(words, audio_ms),
            "streak_days": current,
            "week_saved_min": saved_min,
            "day_words": {
                day.isoformat(): d["words"] for day, d in days.items()
                if day >= today - timedelta(days=1)
            },
        }

    def insights(self, span: str = "month", now: datetime | None = None) -> dict:
        now = now or datetime.now()
        today = now.date()
        starts = {
            "week": today - timedelta(days=6),
            "month": today - timedelta(days=29),
            "all": None,
        }
        if span not in starts:
            raise ValueError(f"unknown range {span!r}")
        start = starts[span]
        days = self._days()
        in_span = {day: d for day, d in days.items() if start is None or day >= start}
        words = sum(d["words"] for d in in_span.values())
        audio_ms = sum(d["audio_ms"] for d in in_span.values())
        current, longest = self._streaks(set(days), today)

        # 26 week columns ending with the current week, Monday on top
        first = today - timedelta(days=today.weekday() + 25 * 7)
        heatmap = []
        for i in range(26 * 7):
            day = first + timedelta(days=i)
            heatmap.append({
                "date": day.isoformat(),
                "words": days.get(day, {}).get("words", 0),
                "future": day > today,
            })

        wpm_days = []
        for i in range(29, -1, -1):
            day = today - timedelta(days=i)
            d = days.get(day)
            wpm_days.append({
                "date": day.isoformat(),
                "wpm": self._wpm(d["words"], d["audio_ms"]) if d else 0,
            })

        app_sql = (
            "SELECT COALESCE(app_name, 'Other') AS name, SUM(words) AS words"
            " FROM dictations"
        )
        app_args: tuple = ()
        if start is not None:
            app_sql += " WHERE created_at >= ?"
            app_args = (datetime.combine(start, datetime.min.time()).timestamp(),)
        app_sql += " GROUP BY name ORDER BY words DESC"
        app_rows = self._query(app_sql, app_args)
        total = sum(r["words"] for r in app_rows) or 1
        apps = [
            {"name": r["name"], "words": r["words"], "share": r["words"] / total}
            for r in app_rows[:5]
        ]
        return {
            "range": span,
            "words": words,
            "wpm": self._wpm(words, audio_ms),
            "streak_days": current,
            "longest_streak_days": longest,
            "heatmap": heatmap,
            "wpm_days": wpm_days,
            "apps": apps,
        }

    def dictionary(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {kind: [] for kind in DICTIONARY_KINDS}
        for r in self._query("SELECT * FROM dictionary ORDER BY created_at, id"):
            out[r["kind"]].append(dict(r))
        return out

    def add_entry(self, kind: str, phrase: str, value: str = "") -> dict:
        phrase = " ".join(phrase.split())
        if kind not in DICTIONARY_KINDS:
            raise ValueError(f"unknown dictionary kind {kind!r}")
        if not phrase:
            raise ValueError("the word or phrase is empty")
        if kind != "words" and not value.strip():
            raise ValueError("say what it should become")
        try:
            row_id = self._write(
                "INSERT INTO dictionary (kind, phrase, value, created_at) VALUES (?, ?, ?, ?)",
                (kind, phrase, value if kind != "words" else "", time.time()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"{phrase!r} is already in the dictionary") from None
        return dict(self._query("SELECT * FROM dictionary WHERE id = ?", (row_id,))[0])

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock, self._db:
            return bool(
                self._db.execute("DELETE FROM dictionary WHERE id = ?", (entry_id,)).rowcount
            )

    def apply_dictionary(self, text: str) -> str:
        return apply_dictionary(text, self.dictionary())


_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[^\W\d_]+")


def _phrase_pattern(phrase: str) -> str:
    """Matches the phrase however the model spaced or cased it: "local-stt"
    also matches "local stt" and "LocalSTT", "WKWebView" matches "WK web view"."""
    tokens = _TOKEN.findall(phrase) or [phrase]
    body = r"[\s\-_.]*".join(re.escape(t) for t in tokens)
    return rf"(?<!\w){body}(?!\w)"


def _expand(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\t", "\t")


def apply_dictionary(text: str, entries: dict[str, list[dict]]) -> str:
    """Snippets, then replacements, then word spellings. A snippet also eats
    the punctuation the model put after its trigger."""
    for e in entries.get("snippets", []):
        value = _expand(e["value"])
        text = re.sub(
            _phrase_pattern(e["phrase"]) + r"[.,!?]?", lambda _m, v=value: v, text,
            flags=re.IGNORECASE,
        )
    for e in entries.get("replacements", []):
        value = _expand(e["value"])
        text = re.sub(
            _phrase_pattern(e["phrase"]), lambda _m, v=value: v, text, flags=re.IGNORECASE
        )
    for e in entries.get("words", []):
        word = e["phrase"]
        text = re.sub(_phrase_pattern(word), lambda _m, w=word: w, text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text)
