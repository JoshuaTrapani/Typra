# stt/worker.py
"""
TranscriptionWorker: QThread consuming audio, applying voice commands
and optional LLM post-processing, emitting final text.

Two dictation modes, chosen per session:
- live: audio is cut at pauses (or after live_max_seconds) and each phrase
  is transcribed and typed while the user keeps talking. The text already
  dictated in the session is passed to Whisper as context, so phrases
  continue each other instead of each looking like a new sentence.
- complete: the whole recording is transcribed once, when the user stops,
  with beam search and voice activity detection (slower, more accurate).

Dictated text is never written to the log, only its length.
"""
from __future__ import annotations
import collections, queue, re, time, traceback
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from audio.recorder import AudioRecorder
from config.settings import HALLUCINATION_PHRASES, Settings
from stt.transcriber import Transcriber
from stt.voice_commands import process_commands, CommandResult

# Audio kept from just before speech starts, so the first syllable survives
_PRE_ROLL_SECONDS = 0.3
# Ask to stop listening after this long without speech (mic not left on by mistake)
_AUTO_STOP_SECONDS = 300
# After stop: how long to wait for audio the recorder captured but we have not read
_DRAIN_SECONDS = 0.15
# Longest recording in complete mode
COMPLETE_MAX_SECONDS = 600
# Text of the session given to Whisper as context in live mode
_CONTEXT_CHARS = 200

_EDGE_ELLIPSIS = re.compile(r"^\s*(?:\.\.\.|…)\s*|\s*(?:\.\.\.|…)\s*$")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def _is_prompt_echo(text: str, hotwords: str) -> bool:
    """On near-silent audio Whisper can repeat its initial prompt, i.e. the
    custom dictionary (names, clients...). Output made only of two or more
    dictionary entries is treated as such an echo; a single dictated term is not."""
    entries = sorted({_norm(w) for w in hotwords.splitlines() if _norm(w)}, key=len, reverse=True)
    rest, hits = _norm(text), 0
    for entry in entries:
        rest, n = re.subn(rf"\b{re.escape(entry)}\b", " ", rest)
        hits += n
    return hits >= 2 and not rest.strip()


def _is_context_echo(text: str, context: str) -> bool:
    """Whisper repeating the previous phrases it was given as context."""
    t = _norm(text)
    return len(t) >= 12 and t in _norm(context)


def build_prompt(hotwords: str, context: str) -> str:
    """Initial prompt: dictionary terms, then the end of what was already said."""
    terms = ", ".join(w.strip() for w in hotwords.splitlines() if w.strip())
    parts = [f"{terms}." if terms else "", context.strip()]
    return " ".join(p for p in parts if p)


class TranscriptionWorker(QThread):
    """Each recording session has an id. start_transcribing() puts the new id
    into the audio queue as a marker, so audio captured before it is still
    processed for (and attributed to) the earlier session."""
    text_ready      = pyqtSignal(str, int)   # text, session id
    command_delete  = pyqtSignal(int)        # session id
    status_changed  = pyqtSignal(str)        # listening | processing | recording | transcribing | idle
    session_done    = pyqtSignal(int)        # all audio of that session processed
    error_occurred  = pyqtSignal(str)
    silence_timeout = pyqtSignal()
    transcribed     = pyqtSignal(int, dict)  # session, timings (no text)
    progress        = pyqtSignal(int, float) # session, fraction done (complete mode)
    limit_reached   = pyqtSignal(int)        # complete mode: maximum length recorded
    event           = pyqtSignal(str, str)   # level, message for the Activity log

    def __init__(self, recorder: AudioRecorder, transcriber: Transcriber,
                 settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._recorder    = recorder
        self._transcriber = transcriber
        self._settings    = settings
        self._active      = False
        self._session     = 0
        self._modes: dict[int, str] = {}
        self._context = ""
        self._llm         = None
        self._llm_id      = None
        self._error_shown = False

    def start_transcribing(self, mode: str = "live") -> int:
        """Begin a new session (call before starting the recorder); returns its id."""
        self._session += 1
        self._modes[self._session] = mode
        print(f"[Worker] start_transcribing() session={self._session} mode={mode}")
        self._recorder.audio_queue.put(self._session)   # session boundary marker
        self._active = True
        return self._session

    def stop_transcribing(self) -> None:
        print("[Worker] stop_transcribing()")
        self._active = False

    def shutdown_llm(self) -> None:
        """Stop the LLM worker process (also unblocks a request in progress)."""
        if self._llm is not None:
            self._llm.shutdown()

    def run(self) -> None:
        print("[Worker] Thread started")
        sr = self._settings.sample_rate
        next_session = None

        while not self.isInterruptionRequested():
            if not self._active and next_session is None:
                try: self._recorder.audio_queue.get(timeout=0.05)
                except queue.Empty: pass
                continue

            session = next_session if next_session is not None else self._session
            next_session = None
            complete = self._modes.pop(session, "live") == "complete"
            self._context = ""
            self.status_changed.emit("recording" if complete else "listening")
            buf:        list[np.ndarray] = []
            buffered    = 0
            silence_n   = 0
            last_voice  = time.monotonic()
            max_samples = int((COMPLETE_MAX_SECONDS if complete
                               else self._settings.live_max_seconds) * sr)
            sil_thresh  = int(self._settings.silence_seconds * sr)
            rms_thresh  = self._settings.silence_threshold
            limit_hit   = False
            # Silence before speech is not buffered (it used to pile up without
            # limit and force a flush on the first word), only a short pre-roll.
            pre_roll = collections.deque(
                maxlen=max(1, int(_PRE_ROLL_SECONDS * sr / AudioRecorder._BLOCK_SIZE)))

            print(f"[Worker] Listening — mode={'complete' if complete else 'live'} "
                  f"max={max_samples / sr:.0f}s rms_thresh={rms_thresh} "
                  f"sil_sec={self._settings.silence_seconds}s")

            while not self.isInterruptionRequested():
                # After stop, still process what the recorder already captured
                # (it piles up while a chunk is being transcribed)
                try:
                    item = self._recorder.audio_queue.get(
                        timeout=0.05 if self._active else _DRAIN_SECONDS)
                except queue.Empty:
                    if self._active:
                        continue
                    break
                if isinstance(item, int):          # session marker
                    if item <= session:
                        continue                   # this session's own start
                    next_session = item            # a newer session started:
                    break                          # finish this one first
                chunk = item
                silent = float(np.sqrt(np.mean(chunk ** 2))) < rms_thresh
                if not silent:
                    last_voice = time.monotonic()
                elif self._active and time.monotonic() - last_voice > _AUTO_STOP_SECONDS:
                    print("[Worker] No speech for a while — requesting stop")
                    self.silence_timeout.emit()
                    last_voice = time.monotonic()
                if not buf:
                    if silent:
                        pre_roll.append(chunk)
                        continue
                    buf = list(pre_roll)
                    buffered = sum(c.shape[0] for c in buf)
                    pre_roll.clear()
                if complete:
                    # Keep everything, pauses included: Whisper needs them to
                    # place punctuation. Stop collecting at the length limit.
                    if buffered >= max_samples:
                        if not limit_hit:
                            limit_hit = True
                            self.limit_reached.emit(session)
                        continue
                    buf.append(chunk)
                    buffered += chunk.shape[0]
                    continue
                buf.append(chunk)
                buffered += chunk.shape[0]
                silence_n = silence_n + chunk.shape[0] if silent else 0
                if silence_n >= sil_thresh or buffered >= max_samples:
                    print(f"[Worker] Flushing {buffered} samples")
                    self._flush(buf, sr, session, complete=False)
                    buf = []; buffered = 0; silence_n = 0

            if buf:
                self._flush(buf, sr, session, complete=complete)
            self.status_changed.emit("idle")
            self.session_done.emit(session)

        if self._llm is not None:
            self._llm.shutdown()
        print("[Worker] Thread exiting")

    def _flush(self, buf: list[np.ndarray], sr: int, session: int, complete: bool) -> None:
        # An unexpected error must not end the thread (dictation would stop)
        try:
            self._process(np.concatenate(buf), sr, session, complete)
        except Exception:
            print(f"[Worker] Error while processing audio:\n{traceback.format_exc()}")
            self.event.emit("error", "Unexpected error while processing audio (details in typra.log)")
            self.status_changed.emit("listening")

    def _process(self, audio: np.ndarray, sr: int, session: int, complete: bool) -> None:
        duration = len(audio) / sr
        print(f"[Worker] _flush: {duration:.2f}s lang={self._settings.language}")
        self.status_changed.emit("transcribing" if complete else "processing")
        after = "listening" if self._active and not complete else "processing"

        if not self._transcriber.is_loaded:
            print("[Worker] Transcriber not loaded — skipping")
            self.status_changed.emit(after); return

        hotwords = self._settings.custom_hotwords.strip()
        context = "" if complete else self._context[-_CONTEXT_CHARS:]
        started = time.monotonic()
        raw = self._transcriber.transcribe(
            audio,
            language=self._settings.language,
            initial_prompt=build_prompt(hotwords, context),
            best=complete,
            progress_cb=(lambda f: self.progress.emit(session, f)) if complete else None,
        )
        stt_s = time.monotonic() - started
        print(f"[Worker] Transcriber returned {len(raw)} chars in {stt_s:.2f}s")

        if self._transcriber.worker_failed:
            if not self._error_shown:   # tell the user once, not on every chunk
                self._error_shown = True
                self.error_occurred.emit("The speech model stopped working. "
                                         "Quit and reopen Typra (details in typra.log).")
        else:
            self._error_shown = False

        metrics = {"mode": "complete" if complete else "live", "audio_s": duration,
                   "stt_s": stt_s, "llm_s": 0.0, "chars": 0,
                   "device": self._transcriber.device_label}

        if not raw:
            self.transcribed.emit(session, metrics)
            self.status_changed.emit(after); return

        if self._settings.filter_hallucinations:
            if raw.strip().lower() in HALLUCINATION_PHRASES or (
                    hotwords and _is_prompt_echo(raw, hotwords)) or (
                    context and _is_context_echo(raw, context)):
                print("[Worker] Hallucination filtered")
                self.event.emit("info", f"Ignored {duration:.1f} s of audio: Whisper "
                                        "returned a typical phrase for silence or noise")
                self.status_changed.emit(after); return

        raw = re.sub(r"  +", " ", raw.strip())
        if not complete:
            # A phrase cut at a pause often ends (or starts) with "...":
            # the next phrase continues it
            raw = _EDGE_ELLIPSIS.sub("", raw).strip()

        if self._settings.voice_commands_enabled and not complete:
            result: CommandResult = process_commands(raw, self._settings.language)
            if result.delete_last:
                self.event.emit("info", "Voice command: delete the last phrase")
                self.command_delete.emit(session)
                self.status_changed.emit(after); return
            text = result.text
            if text != raw:
                self.event.emit("info", "Voice command recognised")
        else:
            text = raw

        if not text:
            self.status_changed.emit(after); return

        if self._settings.llm_enabled and self._settings.llm_tone != "none":
            from stt.llm_processor import MAX_LLM_CHARS
            if len(text) > MAX_LLM_CHARS:
                self.event.emit("warning", "AI Cleanup skipped: the text is too long "
                                           f"({len(text)} characters, limit {MAX_LLM_CHARS})")
            else:
                llm_started = time.monotonic()
                text = self._apply_llm(text)
                metrics["llm_s"] = time.monotonic() - llm_started
        elif self._llm is not None:
            # AI Cleanup turned off: release the model's memory
            self._llm.shutdown()
            self._llm = self._llm_id = None

        if text:
            if not complete:
                self._context = (self._context + " " + text)[-_CONTEXT_CHARS * 2:]
            metrics["chars"] = len(text)
            print(f"[Worker] Emitting {len(text)} chars")
            self.transcribed.emit(session, metrics)
            self.text_ready.emit(text, session)
        self.status_changed.emit(after)

    def _apply_llm(self, text: str) -> str:
        model_id = self._settings.get("llm_model_id")
        if self._llm is None or self._llm_id != model_id:
            if self._llm is not None:
                self._llm.shutdown()
            from stt.llm_processor import LLMProcessor
            self._llm, self._llm_id = LLMProcessor(model_id=model_id), model_id
        if not self._llm.is_ready():
            return text
        return self._llm.process(text, tone=self._settings.llm_tone)
