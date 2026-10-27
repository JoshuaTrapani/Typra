# ui/main_window.py
"""
AppController: Typra v2 invisible coordinator.
Wires: recorder, transcriber, worker, LLM, history, hotkey,
       overlay, result panel, settings, tray, activity log, voice commands.

Where text goes: the window in front when dictation starts is its target.
Text is typed only into that window; if it is no longer in front (or the
dictation was started from the tray), the text goes to the result panel,
where the user can insert it into the target window or copy it.
"""
from __future__ import annotations
import sys, os, time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QSystemTrayIcon as _QSTray

from audio.recorder import AudioRecorder
from config.settings import Settings
from db.history import HistoryStore
from input.hotkey import DEFAULT_HOTKEY, HotkeyManager, is_safe_hotkey
from input.typer import TextTyper
from stt.transcriber import Transcriber
from stt.voice_commands import command_spacing, ends_with_punct, join_phrases
from stt.worker import COMPLETE_MAX_SECONDS, TranscriptionWorker
from ui import winutil
from ui.activity import ActivityLog
from ui.clipboard import copy_private
from ui.overlay import RecordingOverlay
from ui.result_panel import ResultPanel
from ui.settings_window import SettingsWindow
from ui.history_window import HistoryWindow
from ui.tray import SystemTray

_ASSETS         = Path(__file__).parent.parent / "assets"
_ICO_DARK       = _ASSETS / "typra_dark.ico"
_ICO_LIGHT      = _ASSETS / "typra_light.ico"


def _is_dark() -> bool:
    if sys.platform != "win32": return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k); return v == 0
    except Exception: return True


# Module-level wrappers (the tests replace them)
def _foreground_window() -> int:
    return winutil.foreground_window()


def _foreground_is_ours() -> bool:
    return winutil.is_own_window(_foreground_window())


def _is_taskbar(hwnd: int) -> bool:
    return winutil.is_taskbar(hwnd)


def _describe(hwnd: int) -> str:
    return winutil.describe(hwnd)


def _app_name(hwnd: int) -> str:
    return winutil.app_name(hwnd) or "that window"


@dataclass
class _Session:
    buf:      list = field(default_factory=list)   # everything dictated (history)
    target:   int  = 0         # window the text belongs in (0: none)
    target_desc: str = ""
    mode:     str  = "live"    # live | complete
    started:  float = field(default_factory=time.monotonic)
    audio_s:  float = 0.0      # totals, for the result panel and the log
    proc_s:   float = 0.0
    typed:    int  = 0         # characters typed into the target
    paneled:  int  = 0         # characters sent to the result panel
    diverted: bool = False     # live: the rest of the session goes to the panel
    outcome:  str  = ""        # final message for the overlay


def make_app_icon() -> QIcon:
    ico = _ICO_DARK if _is_dark() else _ICO_LIGHT
    if ico.exists():
        icon = QIcon(str(ico))
        if not icon.isNull(): return icon
    icon = QIcon()
    for size in (16, 32, 48):
        px = QPixmap(size, size); px.fill(QColor(0,0,0,0))
        p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(46,213,115)); p.setPen(QColor(0,0,0,0))
        m = size//8; p.drawEllipse(m,m,size-2*m,size-2*m); p.end()
        icon.addPixmap(px)
    return icon


def _make_logo_pixmap(square_size: int = 40) -> QPixmap:
    ico = _ICO_DARK if _is_dark() else _ICO_LIGHT
    px = QPixmap(square_size, square_size); px.fill(QColor(0,0,0,0))
    if ico.exists():
        loaded = QPixmap(str(ico))
        if not loaded.isNull():
            scaled = loaded.scaled(square_size, square_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            x=(square_size-scaled.width())//2; y=(square_size-scaled.height())//2
            p=QPainter(px); p.drawPixmap(x,y,scaled); p.end()
    return px


class ModelLoader(QThread):
    status_update = pyqtSignal(str)
    finished_ok   = pyqtSignal()
    finished_err  = pyqtSignal(str)

    def __init__(self, transcriber: Transcriber, parent=None):
        super().__init__(parent); self._t = transcriber

    def run(self):
        import traceback
        try:
            self._t.load(status_cb=self.status_update.emit)
            self.finished_ok.emit()
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")


class AppController(QObject):

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings    = settings
        self._recording   = False
        self._model_ready = False
        self._downloading = False
        # Recording sessions by id. The worker may still deliver text for a
        # session after it stopped (or after a new one started).
        self._sessions: dict[int, _Session] = {}
        self._session_id  = 0      # the session being recorded
        self._last_text   = ""     # for "delete that"
        self._last_hwnd   = 0      # window that received _last_text
        self._last_sid    = 0      # session of _last_text
        self._last_trailing = False  # a space was typed after _last_text
        self._last_removed  = ""     # text _last_text replaced (". " before a spoken "?")
        self._quitting    = False
        self._last_dark   = _is_dark()

        # Hotkeys saved by older versions were not validated
        hotkey = settings.get("hotkey", DEFAULT_HOTKEY)
        self._hotkey_was_reset = not is_safe_hotkey(hotkey)
        if self._hotkey_was_reset:
            settings.set("hotkey", DEFAULT_HOTKEY)

        self._app_icon = make_app_icon()
        QApplication.instance().setWindowIcon(self._app_icon)

        self._activity    = ActivityLog()
        self._recorder    = AudioRecorder(sample_rate=settings.sample_rate)
        self._transcriber = Transcriber(
            model_size=settings.model_size,
            gpu=settings.gpu_enabled,
        )
        self._transcriber.on_event = self._activity.add
        self._typer   = TextTyper()
        self._hotkey  = HotkeyManager(
            hotkey_str=settings.get("hotkey", DEFAULT_HOTKEY),
        )
        self._worker  = TranscriptionWorker(
            recorder=self._recorder,
            transcriber=self._transcriber,
            settings=settings,
        )
        self._history = HistoryStore()
        self._overlay = RecordingOverlay()
        self._panel   = ResultPanel(self._app_icon)
        self._settings_win = SettingsWindow(settings, self._app_icon, activity=self._activity)
        self._settings_win.transcribe_fn = self._transcribe_test
        self._settings_win.test_blocked_fn = self._test_blocked_reason
        self._history_win  = HistoryWindow(self._history, self._app_icon)
        self._tray    = SystemTray(app_icon=self._app_icon)
        self._tray.set_active_mode(settings.dictation_mode)
        self._tray.set_hotkey_label(settings.get("hotkey", DEFAULT_HOTKEY))

        # Warns in the overlay as soon as the user leaves the target window
        self._watch = QTimer(self)
        self._watch.setInterval(400)
        self._watch.timeout.connect(self._watch_target)

        self._wire()

    # ── Start ──────────────────────────────────────────────────────────

    def start(self) -> None:
        self._tray.show()
        self._tray.set_active_tone(self._settings.get('llm_tone', 'none'))
        self._worker.start()
        self._hotkey.start()
        self._typer.start_tracking(0)
        self._activity.info(f"Typra started. Loading the '{self._settings.model_size}' model…")

        self._model_loader = ModelLoader(self._transcriber)
        self._model_loader.status_update.connect(self._on_loader_status)
        self._model_loader.finished_ok.connect(self._on_model_loaded)
        self._model_loader.finished_err.connect(self._on_model_error)
        self._model_loader.start()

        # Theme watcher
        self._theme_timer = QTimer()
        self._theme_timer.setInterval(3000)
        self._theme_timer.timeout.connect(self._check_theme)
        self._theme_timer.start()

        QTimer.singleShot(300, self._apply_taskbar_icon)
        if self._hotkey_was_reset:
            self._tray.showMessage(
                "Typra", "Your saved hotkey could be triggered while typing, so it was "
                "reset to Ctrl+Shift+Space. You can change it in Settings.",
                self._app_icon, 6000)

    # ── Wire ───────────────────────────────────────────────────────────

    def _wire(self) -> None:
        # Tray
        self._tray.toggle_recording.connect(self._toggle_recording)
        self._tray.open_settings.connect(self._open_settings)
        self._tray.open_history.connect(self._open_history)
        self._tray.open_activity.connect(self._open_activity)
        self._tray.open_result.connect(self._open_result)
        self._tray.quit_app.connect(self._quit)
        self._tray.tone_selected.connect(self._on_tone)
        self._tray.mode_selected.connect(self._on_mode_selected)

        # Overlay
        self._overlay.stop_requested.connect(self._stop_recording)

        # Result panel
        self._panel.insert_requested.connect(self._insert_from_panel)

        # Hotkey
        self._hotkey.activated.connect(self._toggle_recording)

        # Audio level
        self._recorder.set_level_callback(self._overlay.set_level)

        # Worker
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.command_delete.connect(self._on_command_delete)
        self._worker.status_changed.connect(self._on_worker_status)
        self._worker.session_done.connect(self._on_session_done)
        self._worker.silence_timeout.connect(self._on_silence_timeout)
        self._worker.transcribed.connect(self._on_transcribed)
        self._worker.progress.connect(self._on_progress)
        self._worker.limit_reached.connect(self._on_limit_reached)
        self._worker.event.connect(self._activity.add)
        self._worker.error_occurred.connect(self._on_worker_error)

        # Settings signals
        self._settings_win.language_changed.connect(lambda _: None)
        self._settings_win.mic_changed.connect(self._on_mic_changed)
        self._settings_win.model_changed.connect(self._on_model_changed)
        self._settings_win.hotkey_changed.connect(self._on_hotkey_changed)
        self._settings_win.download_started.connect(self._on_download_started)
        self._settings_win.download_finished.connect(self._on_download_finished)
        self._settings_win.mode_changed.connect(self._tray.set_active_mode)

        # History re-paste
        self._history_win.paste_requested.connect(self._retype)

    # ── Recording ──────────────────────────────────────────────────────

    @pyqtSlot()
    def _toggle_recording(self) -> None:
        if not self._model_ready: return
        if self._recording: self._stop_recording()
        else: self._start_recording()

    @pyqtSlot()
    def _start_recording(self) -> None:
        if not self._model_ready or self._recording or self._downloading: return
        device = self._settings.microphone_index
        mic_name = self._settings.microphone_name
        if mic_name:
            device = AudioRecorder.find_microphone(mic_name)
            if device is None:
                self._tray.showMessage(
                    "Typra", f"Microphone \"{mic_name}\" not found: using the default microphone.",
                    self._app_icon, 3000)
                self._activity.warning(f"Microphone \"{mic_name}\" not found: using the default one")
        # The window in front now is where the text belongs
        fg = _foreground_window()
        target = 0 if (_foreground_is_ours() or _is_taskbar(fg)) else fg
        mode = self._settings.dictation_mode
        self._recording = True
        # Before the recorder starts: marks where this session's audio begins
        self._session_id = self._worker.start_transcribing(mode)
        session = _Session(target=target, target_desc=_describe(target) if target else "",
                           mode=mode)
        self._sessions[self._session_id] = session
        try:
            self._recorder.start(device_index=device)
        except Exception as e:
            self._recording = False
            self._worker.stop_transcribing()
            self._activity.error(f"The microphone could not be opened: {e}")
            self._tray.showMessage("Typra: Mic Error", str(e), _QSTray.MessageIcon.Warning, 3000); return
        if mode == "complete":
            self._overlay.set_status("recording", "Recording · press the hotkey to stop")
            self._overlay.start_clock(COMPLETE_MAX_SECONDS)
        else:
            self._overlay.set_status("listening", "Listening · text is typed as you speak")
            self._overlay.stop_clock()
        self._show_target(session)
        self._overlay.show_overlay()
        self._tray.update_recording_state(True)
        self._watch.start()
        where = session.target_desc or "the result panel (no window was in front)"
        self._activity.info(f"Dictation started ({'whole text' if mode == 'complete' else 'live'}) → {where}")

    def _show_target(self, session: _Session, switched: bool = False) -> None:
        if session.mode == "complete" and self._settings.complete_output == "panel":
            self._overlay.set_target("→ Result panel: you choose where the text goes")
        elif not session.target:
            self._overlay.set_target("→ Result panel (no window was in front when you started)",
                                     warn=True)
        elif switched or session.diverted:
            back = f"Go back to {_app_name(session.target)}" if session.mode == "complete" \
                else "Window changed"
            self._overlay.set_target(f"⚠ {back}: the text goes to the result panel", warn=True)
        else:
            self._overlay.set_target(f"→ {session.target_desc}")

    @pyqtSlot()
    def _watch_target(self) -> None:
        session = self._sessions.get(self._session_id)
        if session is None or not self._recording or not session.target:
            return
        fg = _foreground_window()
        if _foreground_is_ours() or _is_taskbar(fg):
            return   # the overlay, the tray menu or a Typra window
        self._show_target(session, switched=fg != session.target)

    @pyqtSlot()
    def _stop_recording(self) -> None:
        if not self._recording: return
        self._recording = False
        self._worker.stop_transcribing()
        self._recorder.stop()
        self._watch.stop()
        self._tray.update_recording_state(False)
        session = self._sessions.get(self._session_id)
        if session is None:
            self._overlay.hide_overlay(); return
        self._overlay.stop_clock()
        seconds = time.monotonic() - session.started
        if session.mode == "complete":
            self._overlay.set_status("transcribing", f"Transcribing {seconds:.0f} s of audio…")
            self._overlay.set_progress(0.0)
        else:
            self._overlay.set_status("processing", "Finishing the last phrase…")
        self._activity.info(f"Dictation stopped after {seconds:.0f} s")

    @pyqtSlot(int)
    def _on_session_done(self, sid: int) -> None:
        session = self._sessions.pop(sid, None)
        if session is None:
            return
        self._save_history(join_phrases(session.buf))
        parts = []
        if session.typed:
            parts.append(f"{session.typed} characters typed into {_app_name(session.target)}")
        if session.paneled:
            parts.append(f"{session.paneled} to the result panel")
        self._activity.info("Dictation finished: " + (", ".join(parts) if parts
                                                      else "no speech recognised"))
        if self._recording:
            return   # a new dictation is already on screen
        if session.outcome:
            status, text = session.outcome.split("|", 1)
        elif not session.buf:
            status, text = "warning", "No speech recognised"
        elif session.paneled:
            status, text = "warning", "Part of the text is in the result panel"
        else:
            status, text = "done", f"Typed into {_app_name(session.target)}"
        self._overlay.set_target("")
        self._overlay.flash(status, text, 2200 if status == "done" else 3500)

    def _save_history(self, text: str) -> None:
        """Store a finished session as one history entry (if enabled)."""
        full = text.strip()
        if not full or not self._settings.save_history:
            return
        self._history.add(
            text=full,
            language=self._settings.language,
            tone=self._settings.llm_tone if self._settings.llm_enabled else "none",
        )
        if self._history_win.isVisible():
            self._history_win.refresh()

    # ── Text handling ──────────────────────────────────────────────────

    def _copy_instead(self, text: str, reason: str) -> None:
        copy_private(text)
        self._tray.showMessage("Typra", f"{reason} The text was copied to the clipboard.",
                               self._app_icon, 4000)

    def _to_panel(self, session: _Session, sid: int, text: str, reason: str = "") -> None:
        """Show text in the result panel instead of typing it."""
        session.paneled += len(text)
        if session.mode == "live":
            session.diverted = True
            info = "Live dictation"
        else:
            info = (f"{session.audio_s:.0f} s of audio, transcribed in {session.proc_s:.1f} s "
                    f"on {self._transcriber.device_label}")
        self._panel.show_result(sid, text, session.target, info=info, reason=reason)
        self._last_text = ""
        if reason:
            self._activity.warning(f"{len(text)} characters sent to the result panel: {reason}")
        else:
            self._activity.info(f"{len(text)} characters shown in the result panel")

    def _blocked_reason(self, session: _Session) -> str:
        """Why text cannot be typed now ("" if it can), after modifier keys are up."""
        if not self._typer.wait_for_modifiers_release():
            return "Typing was skipped because keys were held down."
        if not session.target:
            return "Dictation was started without a window in front."
        if _foreground_is_ours():
            return "Typra does not type into its own windows."
        if _foreground_window() != session.target:
            return (f"You switched away from {_app_name(session.target)} during "
                    "dictation, so the text was kept here.")
        return ""

    @pyqtSlot(str, int)
    def _on_text_ready(self, text: str, sid: int) -> None:
        if not text: return
        session = self._sessions.setdefault(sid, _Session(mode="live"))
        # Accumulate in the session — saved to history when the session ends
        session.buf.append(text)

        if session.mode == "complete":
            if self._settings.complete_output == "panel":
                self._to_panel(session, sid, text)
                session.outcome = "done|Text ready in the result panel"
                return
            reason = self._blocked_reason(session)
            if reason:
                self._to_panel(session, sid, text, reason)
                session.outcome = "warning|The window changed: text is in the result panel"
                return
            if self._typer.type_text(text, trailing_space=self._settings.add_trailing_space,
                                     restore_focus=True):
                session.typed += len(text)
                session.outcome = f"done|Typed into {_app_name(session.target)}"
            else:
                self._to_panel(session, sid, text, "Typing was skipped because keys were held down.")
            return

        # Live: once text went to the panel, the rest of the session follows it
        reason = "The rest of this dictation is collected here." if session.diverted \
            else self._blocked_reason(session)
        if reason:
            self._to_panel(session, sid, text, reason if not session.paneled else "")
            if self._recording and sid == self._session_id:
                self._show_target(session)
            return
        fg = session.target
        trailing = self._settings.add_trailing_space
        removed = ""   # replaced by this command; "delete that" puts it back
        rule = command_spacing(text)
        if rule is not None:
            # A spoken "comma" or "new line" joins the previous phrase:
            # "Hello, " instead of "Hello , ", "Hello?" instead of "Hello.?"
            trailing = trailing and rule.space_after
            if rule.attach and self._last_text and fg == self._last_hwnd \
                    and sid == self._last_sid:
                back = 1 if self._last_trailing else 0
                if rule.replaces_punct and ends_with_punct(self._last_text):
                    back += 1
                if back:
                    typed = self._last_text + (" " if self._last_trailing else "")
                    removed = typed[-back:]
                    self._typer.backspace(back)
        if not self._typer.type_text(text, trailing_space=trailing, restore_focus=True):
            if removed:
                self._typer.type_text(removed, trailing_space=False)
            self._to_panel(session, sid, text, "Typing was skipped because keys were held down.")
            return
        session.typed += len(text)
        self._last_text, self._last_hwnd, self._last_sid = text, fg, sid
        self._last_trailing = trailing and not text.endswith(" ")
        self._last_removed = removed

    @pyqtSlot(int)
    def _on_command_delete(self, sid: int) -> None:
        """Delete the last typed text segment using backspace — only in the
        window that received it: anywhere else the backspaces would destroy
        unrelated content."""
        if not self._last_text or sid != self._last_sid:
            return
        # Wait for modifiers first (Ctrl+Backspace deletes words, and the
        # window can change while they are released), then check the window.
        if not self._typer.wait_for_modifiers_release():
            print("[AppController] delete skipped: modifier keys held")
            self._last_text = ""
            return
        if _foreground_window() != self._last_hwnd or _foreground_is_ours():
            print("[AppController] delete skipped: the foreground window changed")
            self._activity.warning("\"Delete that\" was skipped: the window changed")
            self._tray.showMessage("Typra", "\"Delete that\" was skipped: the window changed.",
                                   self._app_icon, 3000)
            self._last_text = ""
            return
        session = self._sessions.get(sid)
        if session and session.buf and session.buf[-1] == self._last_text:
            session.buf.pop()   # keep deleted text out of the history
            session.typed = max(0, session.typed - len(self._last_text))
        self._typer.backspace(len(self._last_text) + (1 if self._last_trailing else 0))
        if self._last_removed:
            # Undo a spoken punctuation mark: restore what it replaced
            self._typer.type_text(self._last_removed, trailing_space=False)
        self._last_text = ""

    @pyqtSlot(str, int)
    def _insert_from_panel(self, text: str, hwnd: int) -> None:
        """Result panel → the window where the dictation started."""
        self._panel.hide()
        QTimer.singleShot(120, lambda: self._do_insert(text, hwnd))

    def _do_insert(self, text: str, hwnd: int) -> None:
        app = _app_name(hwnd)
        if not winutil.activate(hwnd) or not self._typer.wait_for_modifiers_release() \
                or _foreground_is_ours():
            self._panel.show()
            self._panel.set_status(f"Could not switch to {app}. Click where the text "
                                   "should go, then use Copy and Ctrl+V.")
            self._activity.warning(f"Insert into {app} failed: the window could not be activated")
            return
        if self._typer.type_text(text, trailing_space=False, restore_focus=True):
            self._activity.info(f"Inserted {len(text)} characters into {app}")
            self._overlay.set_target("")
            self._overlay.flash("done", f"Inserted into {app}", 2000)
        else:
            self._panel.show()
            self._panel.set_status("Typing was skipped because keys were held down.")

    @pyqtSlot(str)
    def _retype(self, text: str) -> None:
        self._typer.wait_for_modifiers_release()
        if _foreground_is_ours():
            # Never type into Typra's own windows
            self._copy_instead(text, "Click where the text should go and press Ctrl+V.")
            return
        if not self._typer.type_text(text, trailing_space=True, restore_focus=True):
            self._copy_instead(text, "Typing was skipped because keys were held down.")

    # ── Worker feedback ────────────────────────────────────────────────

    @pyqtSlot(int, dict)
    def _on_transcribed(self, sid: int, m: dict) -> None:
        session = self._sessions.get(sid)
        total = m["stt_s"] + m["llm_s"]
        if session is not None:
            session.audio_s += m["audio_s"]
            session.proc_s += total
        self._activity.record_timing(m["audio_s"], total)
        llm = f" + AI Cleanup {m['llm_s']:.1f} s" if m["llm_s"] else ""
        if m["chars"]:
            self._activity.info(f"Transcribed {m['audio_s']:.1f} s of audio in {m['stt_s']:.1f} s"
                                f"{llm} → {m['chars']} characters")
        else:
            self._activity.info(f"No words in {m['audio_s']:.1f} s of audio "
                                f"(checked in {m['stt_s']:.1f} s)")

    @pyqtSlot(int, float)
    def _on_progress(self, sid: int, fraction: float) -> None:
        if not self._recording:
            self._overlay.set_progress(fraction)

    @pyqtSlot(int)
    def _on_limit_reached(self, sid: int) -> None:
        if self._recording and sid == self._session_id:
            self._stop_recording()
            minutes = COMPLETE_MAX_SECONDS // 60
            self._activity.warning(f"Reached the {minutes}-minute limit: recording stopped")
            self._tray.showMessage("Typra", f"Reached the {minutes}-minute limit: "
                                   "transcribing what you said.", self._app_icon, 4000)

    @pyqtSlot(str)
    def _on_worker_error(self, msg: str) -> None:
        self._activity.error(msg)
        self._tray.showMessage("Typra", msg, _QSTray.MessageIcon.Warning, 6000)

    @pyqtSlot(str)
    def _on_worker_status(self, status: str) -> None:
        session = self._sessions.get(self._session_id)
        if not self._recording or session is None or session.mode != "live":
            return
        if status == "processing":
            self._overlay.set_status("processing", "Listening · transcribing the last phrase…")
        elif status == "listening":
            self._overlay.set_status("listening", "Listening · text is typed as you speak")

    # ── Mic test (Settings) ────────────────────────────────────────────

    def _transcribe_test(self, audio) -> str:
        return self._transcriber.transcribe(audio, language=self._settings.language)

    def _test_blocked_reason(self) -> str:
        if self._recording:
            return "Stop the dictation first, then test the microphone."
        if not self._model_ready:
            return "The speech model is still loading: try again in a moment."
        return ""

    # ── Slots ──────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_loader_status(self, msg: str) -> None:
        self._tray.setToolTip(f"Typra: {msg}")

    @pyqtSlot()
    def _on_model_loaded(self) -> None:
        self._model_ready = True
        self._tray.set_model_ready()
        self._settings_win.set_engine_info(self._transcriber.device_label,
                                           self._transcriber.gpu_problem)
        print("[Typra] Model ready.")

    @pyqtSlot(str)
    def _on_model_error(self, err: str) -> None:
        print(f"\n{'='*60}\nMODEL ERROR:\n{err}\n{'='*60}\n")
        if self._quitting: return
        self._activity.error("The speech model failed to load (details in typra.log)")
        self._tray.setToolTip("Typra: Model error")
        box = QMessageBox()
        box.setWindowTitle("Typra: Model Error")
        box.setWindowIcon(self._app_icon)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setWindowFlags(box.windowFlags()|Qt.WindowType.WindowStaysOnTopHint)
        box.setText(
            "<b>The speech model failed to load.</b><br><br>"
            "On first launch the model is downloaded once: check your internet connection.<br><br>"
            "Otherwise install <b>Microsoft Visual C++ Redistributable 2022 (x64)</b>:<br>"
            "<code>https://aka.ms/vs/17/release/vc_redist.x64.exe</code><br><br>"
            "Click <b>Show Details</b> for the full error.")
        box.setDetailedText(err); box.exec()

    @pyqtSlot()
    def _on_silence_timeout(self) -> None:
        if not self._recording: return
        self._stop_recording()
        self._activity.info("Dictation stopped after 5 minutes without speech")
        self._tray.showMessage("Typra", "Dictation stopped after 5 minutes without speech.",
                               self._app_icon, 4000)

    @pyqtSlot(object)
    def _on_mic_changed(self, _) -> None:
        if self._recording: self._stop_recording()

    @pyqtSlot(str)
    def _on_model_changed(self, model: str) -> None:
        pass  # setting already saved; user restarts via tray

    @pyqtSlot(str, str)
    def _on_hotkey_changed(self, hotkey: str, mode: str) -> None:
        self._hotkey.update(hotkey)
        self._tray.set_hotkey_label(hotkey)

    @pyqtSlot(str)
    def _on_tone(self, tone: str) -> None:
        # Takes effect with the next dictated chunk
        self._settings.set("llm_tone", tone)
        self._tray.set_active_tone(tone)
        if tone != "none" and not self._settings.llm_enabled:
            self._tray.showMessage(
                "Typra: AI Cleanup is off",
                "Enable it in Settings > AI Cleanup to apply this tone.",
                self._app_icon, 4000)

    @pyqtSlot(str)
    def _on_mode_selected(self, mode: str) -> None:
        self._settings.set("dictation_mode", mode)
        self._settings_win.set_mode(mode)
        self._tray.set_active_mode(mode)
        label = "whole text" if mode == "complete" else "live"
        self._activity.info(f"Dictation mode: {label}"
                            + (" (from the next dictation)" if self._recording else ""))

    # ── Settings / History ─────────────────────────────────────────────

    @pyqtSlot()
    def _on_download_started(self) -> None:
        self._downloading = True
        if self._recording:
            self._stop_recording()
        self._tray.setToolTip("Typra: Downloading model — recording disabled")
        print("[Typra] Download started — recording blocked")

    @pyqtSlot()
    def _on_download_finished(self) -> None:
        self._downloading = False
        self._tray.update_recording_state(self._recording)
        print("[Typra] Download finished — recording re-enabled")

    def _open_settings(self) -> None:
        self._settings_win.show()
        self._settings_win.raise_()
        self._settings_win.activateWindow()

    def _open_activity(self) -> None:
        self._settings_win.show_tab("Activity")
        self._open_settings()

    def _open_result(self) -> None:
        if self._panel.isVisible() or self._panel.has_text():
            self._panel.show(); self._panel.raise_(); self._panel.activateWindow()
        else:
            self._tray.showMessage("Typra", "No dictation result to show yet.",
                                   self._app_icon, 3000)

    def _open_history(self) -> None:
        self._history_win.refresh()
        self._history_win.show()
        self._history_win.raise_()
        self._history_win.activateWindow()

    # ── Theme ──────────────────────────────────────────────────────────

    @pyqtSlot()
    def _check_theme(self) -> None:
        dark = _is_dark()
        if dark != self._last_dark:
            self._last_dark = dark
            self._app_icon  = make_app_icon()
            QApplication.instance().setWindowIcon(self._app_icon)
            self._tray.setIcon(self._app_icon)
            self._settings_win.setWindowIcon(self._app_icon)
            self._history_win.setWindowIcon(self._app_icon)
            self._panel.setWindowIcon(self._app_icon)
            self._settings_win.refresh_theme()
            self._panel.refresh_theme()
            self._overlay.refresh_theme()
            QTimer.singleShot(100, self._apply_taskbar_icon)

    def _apply_taskbar_icon(self) -> None:
        if sys.platform != "win32": return
        try:
            import ctypes, tempfile, os
            ico = _ICO_DARK if _is_dark() else _ICO_LIGHT
            if not ico.exists(): return
            tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
            tmp.write(ico.read_bytes()); tmp.close()
            IMAGE_ICON=1; LR_LOADFROMFILE=0x10; WM_SETICON=0x80
            h32=ctypes.windll.user32.LoadImageW(None,tmp.name,IMAGE_ICON,32,32,LR_LOADFROMFILE)
            h16=ctypes.windll.user32.LoadImageW(None,tmp.name,IMAGE_ICON,16,16,LR_LOADFROMFILE)
            for win in [self._settings_win, self._overlay, self._history_win, self._panel]:
                try:
                    hwnd=int(win.winId())
                    if h32: ctypes.windll.user32.SendMessageW(hwnd,WM_SETICON,1,h32)
                    if h16: ctypes.windll.user32.SendMessageW(hwnd,WM_SETICON,0,h16)
                except Exception: pass
            os.unlink(tmp.name)
        except Exception as e: print(f"[Icon] {e}")

    # ── Quit ───────────────────────────────────────────────────────────

    def _quit(self) -> None:
        self._quitting = True
        if self._recording: self._stop_recording()
        for fn in [
            lambda: (self._worker.stop_transcribing(),
                     self._worker.requestInterruption(),
                     self._worker.quit(), self._worker.wait(5000)),
            # Unblock the worker if it is waiting for the LLM or Whisper process
            lambda: self._worker.shutdown_llm(),
            lambda: self._transcriber.shutdown(),
            lambda: self._worker.wait(3000),
            # shutdown() makes a model load in progress give up quickly
            lambda: self._model_loader.wait(5000),
            lambda: self._hotkey.stop(),
            lambda: self._typer.stop_tracking(),
            lambda: self._theme_timer.stop(),
            lambda: self._settings_win.hide(),
            lambda: self._panel.hide(),
        ]:
            try: fn()
            except Exception: pass
        # Deliver what the worker emitted while stopping, then save the sessions
        QApplication.processEvents()
        for sid in list(self._sessions):
            self._on_session_done(sid)
        QApplication.quit()


MainWindow = AppController
