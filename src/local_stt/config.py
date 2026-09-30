"""Configuration: ~/.config/local-stt/config.toml, all keys optional."""

from __future__ import annotations

import platform
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "local-stt" / "config.toml"
CACHE_DIR = Path.home() / ".cache" / "local-stt"
MODELS_DIR = CACHE_DIR / "models"


def default_model() -> str:
    # Parakeet v2 is English-only with the lowest WER here, and runs on the
    # Apple GPU; Whisper has no GPU path on a Mac
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "parakeet-tdt-0.6b-v2"
    return "large-v3-turbo"


@dataclass
class ModelConfig:
    name: str = field(default_factory=default_model)
    compute_type: str = "float16"  # fall back to int8_float16 if latency poor
    device: str = "auto"  # "auto" | "cuda" | "cpu"
    language: str = "en"  # empty string = auto-detect


@dataclass
class DictationConfig:
    hotkey: str = "<alt>+<shift>+t"
    mode: str = "toggle"  # "toggle" (press to start/stop) | "hold" (push-to-talk)
    output: str = "type"  # "type" | "clipboard"
    listener: str = "auto"  # "auto" | "pynput" (X11) | "evdev" (Wayland)
    min_duration_ms: int = 300
    # toggle-mode safety net: auto-stop a recording left running this long
    # (you pressed start and walked away). 0 disables. Ignored in hold mode.
    max_duration_ms: int = 300000  # 5 minutes
    append_space: bool = True
    notify: bool = True


@dataclass
class MeetingConfig:
    output_dir: str = "~/Documents/meetings"
    model: str = ""  # blank = the dictation model
    language: str = ""  # blank = the dictation language


@dataclass
class DiarizeConfig:
    hf_token: str = ""  # falls back to HF_TOKEN env var


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    dictation: DictationConfig = field(default_factory=DictationConfig)
    meeting: MeetingConfig = field(default_factory=MeetingConfig)
    diarize: DiarizeConfig = field(default_factory=DiarizeConfig)


def _section(cls, data: dict):
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH  # resolved at call time so tests can patch it
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Config(
        model=_section(ModelConfig, raw.get("model", {})),
        dictation=_section(DictationConfig, raw.get("dictation", {})),
        meeting=_section(MeetingConfig, raw.get("meeting", {})),
        diarize=_section(DiarizeConfig, raw.get("diarize", {})),
    )


# -- validation + save (used by the management UI) ----------------------------

# allowed enum values, validated server-side before any save
ENUMS = {
    ("model", "compute_type"): {
        "float16", "int8_float16", "int8", "float32", "default",
    },
    ("model", "device"): {"auto", "cuda", "cpu"},
    ("dictation", "mode"): {"toggle", "hold"},
    ("dictation", "output"): {"type", "clipboard"},
    ("dictation", "listener"): {"auto", "pynput", "evdev"},
}


class ConfigError(ValueError):
    """A user-supplied config value failed validation."""


def validate(cfg: Config) -> Config:
    """Raise ConfigError if any field is invalid. Returns cfg for chaining."""
    from .dictation.hotkey import parse_hotkey
    from .engine import models

    _validate_model(cfg.model.name, cfg.model.language, "[model]")
    if cfg.meeting.model:
        _validate_model(
            cfg.meeting.model, cfg.meeting.language or cfg.model.language, "[meeting]"
        )
    for (section, key), allowed in ENUMS.items():
        value = getattr(getattr(cfg, section), key)
        if value not in allowed:
            raise ConfigError(
                f"[{section}] {key} = {value!r} is invalid; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
    try:
        parse_hotkey(cfg.dictation.hotkey)
    except ValueError as e:
        raise ConfigError(str(e)) from e
    if cfg.dictation.min_duration_ms < 0:
        raise ConfigError("min_duration_ms must be >= 0")
    if cfg.dictation.max_duration_ms < 0:
        raise ConfigError("max_duration_ms must be >= 0 (0 disables the cap)")
    return cfg


def _validate_model(name: str, language: str, section: str) -> None:
    from .engine import models

    try:
        spec = models.spec(name)
    except ValueError as e:
        raise ConfigError(f"{section} {e}") from e
    if reason := models.unavailable_reason(spec.name):
        raise ConfigError(f"{section} {spec.name}: {reason}")
    if language and spec.languages and language not in spec.languages:
        raise ConfigError(
            f"{section} {spec.name} does not support language {language!r}; "
            f"supported: {', '.join(sorted(spec.languages))} (or blank for auto-detect)"
        )


def _as_tables(cfg: Config) -> dict:
    from dataclasses import asdict

    return asdict(cfg)


def save_config(cfg: Config, path: Path | None = None) -> None:
    """Validate and write config, preserving existing comments/formatting.

    Uses tomlkit so a hand-edited config.toml keeps its comments — the UI is
    just another editor of the same file.
    """
    import tomlkit

    path = path or CONFIG_PATH  # resolved at call time so tests can patch it
    validate(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        doc = tomlkit.parse(path.read_text())
    else:
        doc = tomlkit.document()

    for section, values in _as_tables(cfg).items():
        table = doc.get(section)
        if table is None:
            table = tomlkit.table()
            doc[section] = table
        for key, value in values.items():
            table[key] = value

    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(tomlkit.dumps(doc))
    tmp.replace(path)  # atomic: never leave a half-written config
