# config/settings.py
from __future__ import annotations
import json, os
from pathlib import Path

DEFAULTS: dict = {
    # ── Core ──────────────────────────────────────────────────────────
    "language":           "en",
    "model_size":         "base",
    "microphone_index":   None,
    "microphone_name":    "",            # device indexes change; the name does not
    "hotkey":             "ctrl+shift+space",
    "recording_mode":     "toggle",      # toggle only

    # ── Audio / transcription ──────────────────────────────────────────
    # live: text is typed while you speak, phrase by phrase
    # complete: the whole dictation is transcribed at once when you stop
    "dictation_mode":     "live",
    # complete mode: "panel" shows the text in the result panel,
    # "insert" types it into the window where dictation started
    "complete_output":    "panel",
    "live_max_seconds":   12.0,          # longest phrase in live mode
    "silence_threshold":  0.008,
    "silence_seconds":    0.7,
    "sample_rate":        16000,
    "add_trailing_space": True,
    "filter_hallucinations": True,

    # ── LLM post-processing ──────────────────────────────────────────
    "llm_enabled":        False,
    "llm_tone":           "cleanup",
    "llm_model_id":       "gemma4-e2b-q4",     # cleanup | casual | professional | concise

    # ── Voice commands ────────────────────────────────────────────────
    "voice_commands_enabled": True,

    # ── Custom dictionary / hotwords ──────────────────────────────────
    "custom_hotwords":    "",            # newline-separated words

    # ── GPU acceleration ──────────────────────────────────────────────
    "gpu_enabled":        False,

    # ── Privacy ───────────────────────────────────────────────────────
    "save_history":       True,          # store each session in history.db

    # ── UI ────────────────────────────────────────────────────────────
    "window_always_on_top": True,
    "start_minimized":    True,
}

HALLUCINATION_PHRASES = {
    "thank you.", "thank you", "thanks for watching.",
    "thanks for watching", "please subscribe.", ".", "...", "you",
}


_CHOICES: dict[str, set] = {
    "dictation_mode":  {"live", "complete"},
    "complete_output": {"panel", "insert"},
}


def _valid(key: str, value) -> bool:
    """A saved value must have the type of its default (ints are fine for
    floats), so a hand-edited or corrupted file cannot crash the app later."""
    if key in _CHOICES:
        return value in _CHOICES[key]
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if default is None:   # microphone_index: device number or None
        return value is None or isinstance(value, int)
    if isinstance(default, float):
        return isinstance(value, (int, float))
    return isinstance(value, type(default))


class Settings:
    def __init__(self) -> None:
        self._dir  = Path.home() / ".whisper_dictation"
        self._file = self._dir / "settings.json"
        self._data: dict = DEFAULTS.copy()
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                saved = json.loads(self._file.read_text(encoding="utf-8"))
                for k, v in saved.items():
                    if k not in DEFAULTS:
                        continue
                    if _valid(k, v):
                        self._data[k] = v
                    else:
                        print(f"[Settings] Ignoring invalid value for '{k}'")
            except Exception as exc:
                print(f"[Settings] Load error: {exc}")
        # Earlier versions saved Norwegian as "nb", which Whisper rejects
        if self._data["language"] == "nb":
            self._data["language"] = "no"

    def save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write cannot wipe the settings
        tmp = self._file.with_name(self._file.name + ".tmp")
        try:
            tmp.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self._file)
        except Exception as exc:
            print(f"[Settings] Save error: {exc}")

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        if key in DEFAULTS:
            self._data[key] = value
            self.save()

    def __getitem__(self, key): return self._data[key]
    def __setitem__(self, key, value): self.set(key, value)

    # Convenience properties
    @property
    def language(self) -> str:        return self._data["language"]
    @property
    def model_size(self) -> str:      return self._data["model_size"]
    @property
    def sample_rate(self) -> int:     return int(self._data["sample_rate"])
    @property
    def microphone_index(self):       return self._data["microphone_index"]
    @property
    def microphone_name(self) -> str: return self._data.get("microphone_name", "")
    @property
    def dictation_mode(self) -> str:  return self._data["dictation_mode"]
    @property
    def complete_output(self) -> str: return self._data["complete_output"]
    @property
    def live_max_seconds(self) -> float:
        return min(30.0, max(3.0, float(self._data["live_max_seconds"])))
    @property
    def silence_threshold(self) -> float: return float(self._data["silence_threshold"])
    @property
    def silence_seconds(self) -> float:   return float(self._data["silence_seconds"])
    @property
    def add_trailing_space(self) -> bool: return bool(self._data["add_trailing_space"])
    @property
    def filter_hallucinations(self) -> bool: return bool(self._data["filter_hallucinations"])
    @property
    def window_always_on_top(self) -> bool: return bool(self._data["window_always_on_top"])
    @property
    def recording_mode(self) -> str:  return "toggle"  # hold-to-talk removed
    @property
    def llm_enabled(self) -> bool:    return bool(self._data.get("llm_enabled", False))
    @property
    def llm_tone(self) -> str:        return self._data.get("llm_tone", "cleanup")
    @property
    def gpu_enabled(self) -> bool:    return bool(self._data.get("gpu_enabled", False))
    @property
    def voice_commands_enabled(self) -> bool:
        return bool(self._data.get("voice_commands_enabled", True))
    @property
    def custom_hotwords(self) -> str: return self._data.get("custom_hotwords", "")
    @property
    def save_history(self) -> bool:   return bool(self._data.get("save_history", True))
