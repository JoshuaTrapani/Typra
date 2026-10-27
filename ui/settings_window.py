# ui/settings_window.py
"""Typra Settings — tabbed, theme-aware, custom CheckBox, HotkeyRecorder."""
from __future__ import annotations
import html
import math
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import QObject, QProcess, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)
from audio.recorder import AudioRecorder
from config.settings import Settings
from stt.transcriber import MODEL_INFO, Transcriber, cublas_dir
from stt.llm_processor import DEFAULT_MODEL, LLM_MODELS, LLMProcessor
from stt.voice_commands import DELETE, commands_for
from ui.audio_meter import AudioMeter
from ui.widgets import CheckBox, HotkeyRecorder

_ROOT = Path(__file__).resolve().parent.parent
_GPU_LOCK = _ROOT / "requirements-gpu.lock"
_LOG_FILE = Path.home() / ".whisper_dictation" / "typra.log"
_TEST_SECONDS = 5


class _DownloadBridge(QObject):
    """Carries download progress from the worker thread to the GUI thread
    (a QTimer.singleShot issued from a plain Python thread never fires)."""
    progress = pyqtSignal(int, float, float)   # percent, MB received, MB total
    finished = pyqtSignal(bool)


class _TestBridge(QObject):
    """Mic test results from the transcription thread."""
    heard = pyqtSignal(str, float)   # text, seconds taken


def _is_dark() -> bool:
    if sys.platform != "win32": return True
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k); return v == 0
    except Exception: return True


def _qss(dark: bool) -> str:
    bg   = "#16161c" if dark else "#f5f5f7"
    bg2  = "#22222e" if dark else "#ffffff"
    bdr  = "#3a3a50" if dark else "#d0d0d8"
    txt  = "#e0e0e8" if dark else "#1a1a2e"
    sel  = "#3a3a70" if dark else "#c8d0f0"
    dim  = "#a0a0b8" if dark else "#606070"
    btn  = "#2a2a38" if dark else "#e8e8f0"
    div  = "#2a2a38" if dark else "#e8e8ee"
    ttl  = "#e8e8ff" if dark else "#1a1a2e"
    sub  = "#555568" if dark else "#808090"
    sec  = "#c8c8e0" if dark else "#2a2a3e"
    tab  = "#1e1e28" if dark else "#eaeaf0"
    return f"""
QWidget {{background:{bg};color:{txt};font-family:"Segoe UI",Arial;font-size:13px;}}
QTabWidget::pane {{background:{bg2};border:1px solid {bdr};border-radius:6px;}}
QTabBar::tab {{background:{tab};color:{dim};border:none;padding:7px 14px;
               margin-right:2px;border-radius:5px 5px 0 0;}}
QTabBar::tab:selected {{background:{bg2};color:{txt};}}
QComboBox {{background:{bg2};border:1px solid {bdr};border-radius:6px;
            padding:5px 10px;min-height:28px;color:{txt};}}
QComboBox::drop-down {{border:none;width:22px;}}
QComboBox QAbstractItemView {{background:{bg2};border:1px solid {bdr};
    selection-background-color:{sel};color:{txt};}}
QLineEdit,QTextEdit,QPlainTextEdit {{background:{bg2};border:1px solid {bdr};border-radius:6px;
    padding:5px 10px;color:{txt};}}
QFrame#Divider {{background:{div};max-height:1px;min-height:1px;}}
QLabel#AppTitle {{color:{ttl};font-size:17px;font-weight:bold;}}
QLabel#AppSub   {{color:{sub};font-size:11px;}}
QLabel#Sec      {{color:{sec};font-size:12px;font-weight:bold;}}
QLabel#Hint     {{color:{dim};font-size:10px;}}
QLabel#Info     {{color:{txt};font-size:11px;}}
QLabel#StatusOk {{background:#1a3a1a;color:#60e080;border-radius:5px;padding:5px 8px;font-size:11px;}}
QPushButton#Btn {{background:{btn};border:1px solid {bdr};border-radius:5px;
    color:{dim};font-size:11px;min-height:28px;padding:0 14px;}}
QPushButton#Btn:hover {{background:{sel};}}
QPushButton#Btn:disabled {{color:{sub};}}
QPushButton#Green {{background:#2d5a27;border:none;border-radius:5px;
    color:#e0ffe0;font-size:11px;min-height:28px;padding:0 14px;}}
QPushButton#Green:hover {{background:#3a7a30;}}
QPushButton#Green:disabled {{background:#1e2e1e;color:#406040;}}
QScrollBar:vertical {{background:{bg};width:6px;border-radius:3px;}}
QScrollBar::handle:vertical {{background:{bdr};border-radius:3px;min-height:20px;}}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
"""


LANGUAGES = [
    ("en","English"),("de","German"),("fr","French"),("es","Spanish"),
    ("it","Italian"),("pt","Portuguese"),("ja","Japanese"),("zh","Chinese"),
    ("ko","Korean"),("nl","Dutch"),("pl","Polish"),("ru","Russian"),
    ("ar","Arabic"),("tr","Turkish"),("sv","Swedish"),("da","Danish"),
    ("fi","Finnish"),("no","Norwegian"),("cs","Czech"),("hu","Hungarian"),
]


_PUNCT_NAMES = {
    ".": "period", ",": "comma", "?": "question mark", "!": "exclamation mark",
    ":": "colon", ";": "semicolon", "(": "open parenthesis", ")": "close parenthesis",
    "。": "period", "、": "enumeration comma", "，": "comma", "？": "question mark",
    "！": "exclamation mark", "：": "colon", "；": "semicolon",
    "（": "open parenthesis", "）": "close parenthesis",
    "،": "comma", "؟": "question mark", "؛": "semicolon",
}


def _command_label(out: str) -> str:
    """Human-readable result of a voice command, for the help dialog."""
    if out == DELETE:
        return "deletes the last phrase"
    if out == "\n":
        return "line break"
    if out == "\n\n":
        return "new paragraph (blank line)"
    return f"<b>{html.escape(out)}</b>&nbsp;&nbsp;{_PUNCT_NAMES.get(out, '')}"


def meter_level(rms: float) -> float:
    """RMS -> 0..1 on a decibel scale (-60 dB .. 0 dB), like a mixer meter."""
    if rms <= 1e-6:
        return 0.0
    return min(1.0, max(0.0, (20 * math.log10(rms) + 60) / 60))


def mic_verdict(levels: list[float], threshold: float) -> str:
    """Plain-language result of a microphone test (levels are block RMS values)."""
    if not levels:
        return "The microphone did not deliver any audio. Check it is connected."
    peak = max(levels)
    above = sum(1 for lv in levels if lv >= threshold) / len(levels)
    if peak < threshold:
        return ("No speech detected: everything stayed below the silence threshold. "
                "Check that this is the right microphone and that it is not muted, "
                "or raise its volume in the Windows sound settings.")
    if peak >= 0.9:
        return "Too loud: the signal clips. Lower the microphone volume in Windows."
    if above < 0.15:
        return ("Very quiet: most of your voice is close to the silence threshold, "
                "so phrases may be cut. Speak closer or raise the microphone volume.")
    return "Level OK: your voice is well above the silence threshold."


class _MicMonitor(QObject):
    """Opens the selected microphone while Settings is visible, for the level
    meter and the microphone test. Independent of dictation."""
    level = pyqtSignal(float)          # RMS of each block (any thread → GUI)
    test_finished = pyqtSignal(object) # np.ndarray with the recording

    def __init__(self, sample_rate: int) -> None:
        super().__init__()
        self._sr = sample_rate
        self._stream = None
        self._test: Optional[list] = None
        self._test_until = 0.0
        self.error = ""

    def start(self, device) -> bool:
        self.stop()
        try:
            import sounddevice as sd
            self._stream = sd.InputStream(device=device, channels=1, samplerate=self._sr,
                                          blocksize=AudioRecorder._BLOCK_SIZE,
                                          dtype=np.float32, callback=self._callback)
            self._stream.start()
            self.error = ""
            return True
        except Exception as exc:
            self._stream = None
            self.error = str(exc)
            return False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._test is not None:
            self._finish_test()

    @property
    def running(self) -> bool:
        return self._stream is not None

    def record_test(self, seconds: float) -> None:
        self._test, self._test_until = [], time.monotonic() + seconds

    def _callback(self, indata, frames, time_info, status) -> None:
        chunk = indata[:, 0].copy()
        self.level.emit(float(np.sqrt(np.mean(chunk ** 2))))
        if self._test is not None:
            self._test.append(chunk)
            if time.monotonic() >= self._test_until:
                self._finish_test()

    def _finish_test(self) -> None:
        chunks, self._test = self._test, None
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        self.test_finished.emit(audio)


class SettingsWindow(QWidget):
    language_changed  = pyqtSignal(str)
    mic_changed       = pyqtSignal(object)
    model_changed     = pyqtSignal(str)
    hotkey_changed    = pyqtSignal(str, str)
    download_started  = pyqtSignal()
    download_finished = pyqtSignal()
    mode_changed      = pyqtSignal(str)

    def __init__(self, settings: Settings, app_icon: QIcon, parent=None,
                 activity=None) -> None:
        super().__init__(parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint)
        self._settings = settings
        self._activity = activity
        # Set by the controller: transcribe a test recording -> text, and why
        # a test cannot run right now ("" when it can)
        self.transcribe_fn: Optional[Callable[[np.ndarray], str]] = None
        self.test_blocked_fn: Optional[Callable[[], str]] = None
        self._engine = ("", "")    # device label, GPU problem
        self._monitor = _MicMonitor(settings.sample_rate)
        self._monitor.level.connect(self._on_level)
        self._monitor.test_finished.connect(self._on_test_recorded)
        self._test_audio: Optional[np.ndarray] = None
        self._test_levels: list[float] = []
        self._testing = False
        self._pip: Optional[QProcess] = None
        self.setWindowTitle("Typra: Settings")
        self.setWindowIcon(app_icon)
        self.setFixedWidth(500)
        self._apply_theme()
        self._build_ui()
        # Snapshot value at open-time so the banner hides if the user reverts
        self._orig_model = self._settings.model_size
        self._orig_gpu = self._settings.gpu_enabled

    def _apply_theme(self) -> None:
        self.setStyleSheet(_qss(_is_dark()))

    def refresh_theme(self) -> None:
        self._apply_theme()

    # ── Build ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        col = QVBoxLayout(); col.setSpacing(1)
        t = QLabel("Typra"); t.setObjectName("AppTitle")
        s = QLabel("Settings"); s.setObjectName("AppSub")
        col.addWidget(t); col.addWidget(s)
        hdr.addLayout(col); hdr.addStretch()
        root.addLayout(hdr)
        root.addWidget(self._div())

        self._tabs = tabs = QTabWidget()
        tabs.addTab(self._tab_general(),       "General")
        tabs.addTab(self._tab_transcription(), "Transcription")
        tabs.addTab(self._tab_ai(),            "AI Cleanup")
        tabs.addTab(self._tab_advanced(),      "Advanced")
        tabs.addTab(self._tab_activity(),      "Activity")
        tabs.currentChanged.connect(lambda _: self._update_monitor())
        root.addWidget(tabs)

        root.addWidget(self._div())
        btn = QPushButton("Close"); btn.setObjectName("Btn")
        btn.clicked.connect(self.hide)
        root.addWidget(btn)
        self.adjustSize()

    def show_tab(self, name: str) -> None:
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == name:
                self._tabs.setCurrentIndex(i)

    # ── General tab ────────────────────────────────────────────────────

    def _tab_general(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(12,12,12,12); v.setSpacing(8)

        v.addWidget(self._sec("Microphone"))
        self._mic_combo = QComboBox()
        self._populate_mics()
        self._mic_combo.currentIndexChanged.connect(self._on_mic)
        v.addWidget(self._mic_combo)
        self._meter = AudioMeter()
        self._meter.set_threshold(meter_level(self._settings.silence_threshold))
        v.addWidget(self._meter)
        self._mic_status = self._hint(
            "Speak: the bar should go past the dashed line. Below the line Typra "
            "treats the sound as silence.")
        v.addWidget(self._mic_status)
        test_row = QHBoxLayout(); test_row.setSpacing(8)
        self._test_btn = QPushButton(f"Test microphone ({_TEST_SECONDS} s)")
        self._test_btn.setObjectName("Btn")
        self._test_btn.clicked.connect(self._start_test)
        self._play_btn = QPushButton("Play back")
        self._play_btn.setObjectName("Btn")
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._play_test)
        test_row.addWidget(self._test_btn); test_row.addWidget(self._play_btn); test_row.addStretch()
        v.addLayout(test_row)
        self._test_result = QLabel(); self._test_result.setObjectName("Info")
        self._test_result.setWordWrap(True)
        self._test_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._test_result.hide()
        v.addWidget(self._test_result)
        self._test_bridge = _TestBridge(self)
        self._test_bridge.heard.connect(self._on_test_heard)
        self._test_timer = QTimer(self); self._test_timer.setInterval(250)
        self._test_timer.timeout.connect(self._tick_test)

        v.addWidget(self._div())
        v.addWidget(self._sec("Language"))
        self._lang_combo = QComboBox()
        active = self._settings.language
        sel_i = 0
        for i,(code,name) in enumerate(LANGUAGES):
            self._lang_combo.addItem(name, code)
            if code == active: sel_i = i
        self._lang_combo.setCurrentIndex(sel_i)
        self._lang_combo.currentIndexChanged.connect(self._on_lang)
        v.addWidget(self._lang_combo)

        v.addWidget(self._div())
        v.addWidget(self._sec("Global Hotkey"))
        v.addWidget(self._hint("Click the field below and press your desired key combination."))
        self._hotkey_rec = HotkeyRecorder(
            initial=self._settings.get("hotkey", "ctrl+shift+space"))
        self._hotkey_rec.hotkey_recorded.connect(self._on_hotkey_recorded)
        v.addWidget(self._hotkey_rec)

        v.addStretch()
        return w

    # ── Transcription tab ──────────────────────────────────────────────

    def _tab_transcription(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(12,12,12,12); v.setSpacing(8)

        v.addWidget(self._sec("Dictation Mode"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Live: text is typed while you speak", "live")
        self._mode_combo.addItem("Whole text: transcribed when you stop (more accurate)", "complete")
        self._mode_combo.setCurrentIndex(0 if self._settings.dictation_mode == "live" else 1)
        self._mode_combo.currentIndexChanged.connect(self._on_mode)
        v.addWidget(self._mode_combo)
        self._mode_hint = self._hint("")
        v.addWidget(self._mode_hint)
        self._output_combo = QComboBox()
        self._output_combo.addItem("Show the text in the result panel (you choose where it goes)", "panel")
        self._output_combo.addItem("Type it into the window where I started, if still in front", "insert")
        self._output_combo.setCurrentIndex(0 if self._settings.complete_output == "panel" else 1)
        self._output_combo.currentIndexChanged.connect(
            lambda _: self._settings.set("complete_output", self._output_combo.currentData()))
        v.addWidget(self._output_combo)
        self._update_mode_hint()

        v.addWidget(self._div())
        v.addWidget(self._sec("Whisper Model"))
        self._model_combo = QComboBox()
        for mid, info in MODEL_INFO.items():
            self._model_combo.addItem(
                f"{mid}  ({info['size']})  {info['label']}", mid)
        cur = self._settings.model_size
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == cur:
                self._model_combo.setCurrentIndex(i); break
        self._model_combo.currentIndexChanged.connect(self._on_model)
        v.addWidget(self._model_combo)
        self._engine_lbl = self._hint("Model downloads automatically on first use.")
        v.addWidget(self._engine_lbl)
        self._model_restart_lbl = self._restart_notice()
        v.addWidget(self._model_restart_lbl)

        v.addWidget(self._div())
        self._vc_check = CheckBox("Enable voice commands (new line, comma, delete...)")
        self._vc_check.setChecked(self._settings.voice_commands_enabled)
        self._vc_check.stateChanged.connect(
            lambda s: self._settings.set("voice_commands_enabled", bool(s)))
        v.addWidget(self._vc_check)
        v.addWidget(self._hint(
            "Live mode only. Say a command on its own, with a short pause before "
            "and after it. Inside a sentence it is typed as a word. Punctuation "
            "is usually added automatically."))
        vc_btn = QPushButton("Show voice commands")
        vc_btn.setObjectName("Btn")
        vc_btn.clicked.connect(self._show_voice_commands)
        vc_row = QHBoxLayout(); vc_row.addWidget(vc_btn); vc_row.addStretch()
        v.addLayout(vc_row)

        v.addWidget(self._div())
        v.addWidget(self._sec("Custom Dictionary / Hotwords"))
        v.addWidget(self._hint("One word or phrase per line. Biases Whisper toward these terms."))
        self._hotwords_edit = QTextEdit()
        self._hotwords_edit.setPlaceholderText("MyBrand\nAcronym XYZ\nPerson Name")
        self._hotwords_edit.setPlainText(self._settings.custom_hotwords)
        self._hotwords_edit.setMaximumHeight(80)
        self._hotwords_edit.textChanged.connect(
            lambda: self._settings.set("custom_hotwords",
                                       self._hotwords_edit.toPlainText()))
        v.addWidget(self._hotwords_edit)
        v.addStretch()
        return w

    # ── AI Cleanup tab ─────────────────────────────────────────────────

    def _tab_ai(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(12,12,12,12); v.setSpacing(8)

        v.addWidget(self._sec("Local LLM Post-Processing"))
        v.addWidget(self._hint(
            "Uses a small local AI model to clean up transcriptions.\n"
            "Fully offline. Requires 1-3.5 GB of free disk space."))
        if not LLMProcessor.llama_cpp_available():
            missing = self._hint(
                "Needs the optional llama-cpp-python package (0.2.72 or newer), "
                "which is not installed, so this feature does nothing yet. "
                "See README > AI Cleanup.")
            missing.setStyleSheet("color: #e8a030; font-size: 11px;")
            v.addWidget(missing)

        self._llm_check = CheckBox("Enable LLM cleanup")
        self._llm_check.setChecked(self._settings.llm_enabled)
        self._llm_check.stateChanged.connect(
            lambda s: self._settings.set("llm_enabled", bool(s)))
        v.addWidget(self._llm_check)

        v.addWidget(self._div())
        v.addWidget(self._sec("LLM Model Selection"))

        self._llm_model_combo = QComboBox()
        cur_llm = self._settings.get("llm_model_id", DEFAULT_MODEL)
        for i, (mid, info) in enumerate(LLM_MODELS.items()):
            installed = " ✓" if LLMProcessor.model_downloaded_for(mid) else ""
            label = f"{info['name']}{installed}"
            tooltip = info['name'] + "\n" + info['desc']
            self._llm_model_combo.addItem(label, mid)
            self._llm_model_combo.setItemData(i, tooltip, Qt.ItemDataRole.ToolTipRole)
            if mid == cur_llm:
                self._llm_model_combo.setCurrentIndex(i)
        self._llm_model_combo.setToolTip("Hover over an item in the list to see details")
        self._llm_model_combo.currentIndexChanged.connect(self._on_llm_model_change)
        v.addWidget(self._llm_model_combo)

        # Status — only shown when installed
        self._llm_status = QLabel()
        self._llm_status.setObjectName("StatusOk")
        self._llm_status.setWordWrap(True)
        self._update_llm_status()
        v.addWidget(self._llm_status)

        self._dl_btn = QPushButton("Download selected model")
        self._dl_btn.setObjectName("Green")
        self._dl_btn.clicked.connect(self._download_llm)
        self._update_dl_btn()
        v.addWidget(self._dl_btn)

        self._dl_progress = QProgressBar()
        self._dl_progress.setRange(0, 100)
        self._dl_progress.setValue(0)
        self._dl_progress.setTextVisible(True)
        self._dl_progress.setStyleSheet(
            "QProgressBar{border:1px solid #3a3a50;border-radius:4px;height:16px;text-align:center;font-size:10px;}"
            "QProgressBar::chunk{background:#2d5a27;border-radius:3px;}")
        self._dl_progress.hide()
        v.addWidget(self._dl_progress)

        v.addWidget(self._div())
        v.addWidget(self._sec("Tone Mode"))
        v.addWidget(self._hint("How the LLM rewrites your transcription."))
        self._tone_combo = QComboBox()
        tones = [
            ("cleanup",      "Cleanup: fix grammar and remove fillers"),
            ("casual",       "Casual: friendly and conversational"),
            ("professional", "Professional: formal and polished"),
            ("concise",      "Concise: shortest version without losing meaning"),
        ]
        cur_tone = self._settings.llm_tone
        for i,(code,label) in enumerate(tones):
            self._tone_combo.addItem(label, code)
            if code == cur_tone: self._tone_combo.setCurrentIndex(i)
        self._tone_combo.currentIndexChanged.connect(self._on_tone_changed)
        v.addWidget(self._tone_combo)
        v.addStretch()
        return w

    # ── Advanced tab ───────────────────────────────────────────────────

    def _tab_advanced(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(12,12,12,12); v.setSpacing(8)

        v.addWidget(self._sec("GPU Acceleration (NVIDIA)"))
        gpu_ok = Transcriber.cuda_available()
        self._gpu_check = CheckBox(
            "Use the GPU for transcription" if gpu_ok
            else "Use the GPU: no NVIDIA GPU found")
        self._gpu_check.setChecked(self._settings.gpu_enabled and gpu_ok)
        self._gpu_check.setEnabled(gpu_ok)
        self._gpu_check.stateChanged.connect(self._on_gpu_toggled)
        v.addWidget(self._gpu_check)
        self._gpu_status = QLabel(); self._gpu_status.setObjectName("Info")
        self._gpu_status.setWordWrap(True)
        v.addWidget(self._gpu_status)
        self._gpu_btn = QPushButton("Install GPU support (about 630 MB download)")
        self._gpu_btn.setObjectName("Green")
        self._gpu_btn.clicked.connect(self._install_gpu)
        v.addWidget(self._gpu_btn)
        self._gpu_progress = QProgressBar(); self._gpu_progress.setRange(0, 0)
        self._gpu_progress.setMaximumHeight(8); self._gpu_progress.setTextVisible(False)
        self._gpu_progress.hide()
        v.addWidget(self._gpu_progress)
        self._gpu_restart_lbl = self._restart_notice()
        v.addWidget(self._gpu_restart_lbl)
        self._update_gpu_status()

        v.addWidget(self._div())
        v.addWidget(self._sec("Privacy"))
        self._history_check = CheckBox("Save dictations to History")
        self._history_check.setChecked(self._settings.save_history)
        self._history_check.stateChanged.connect(
            lambda s: self._settings.set("save_history", bool(s)))
        v.addWidget(self._history_check)
        v.addWidget(self._hint(
            "Stored only on this computer, in .whisper_dictation\\history.db "
            "inside your user folder."))

        v.addStretch()
        return w

    # ── Activity tab ───────────────────────────────────────────────────

    def _tab_activity(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(12,12,12,12); v.setSpacing(8)
        v.addWidget(self._sec("Status"))
        self._summary = QLabel(); self._summary.setObjectName("Info")
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self._summary)
        v.addWidget(self._div())
        v.addWidget(self._sec("Recent activity"))
        v.addWidget(self._hint("Timings, where text went, warnings and errors. "
                               "Dictated text is never recorded here."))
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMinimumHeight(230)
        self._log_view.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; font-size: 11px;")
        v.addWidget(self._log_view)
        row = QHBoxLayout(); row.setSpacing(8)
        for label, slot in (("Copy", self._copy_log), ("Open full log", self._open_log),
                            ("Clear", self._clear_log)):
            b = QPushButton(label); b.setObjectName("Btn"); b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        if self._activity is not None:
            for entry in self._activity.entries():
                self._log_view.appendPlainText(entry.line())
            self._activity.entry_added.connect(lambda e: self._log_view.appendPlainText(e.line()))
            self._activity.stats_changed.connect(self._update_summary)
        self._update_summary()
        return w

    # ── Engine / activity ─────────────────────────────────────────────

    def set_engine_info(self, device: str, gpu_problem: str) -> None:
        """Called by the controller once the Whisper model is loaded."""
        self._engine = (device, gpu_problem)
        on_cpu = device.startswith("CPU")
        slow = on_cpu and self._settings.model_size in ("medium", "large-v3-turbo")
        self._engine_lbl.setText(
            f"Running on: {device}."
            + (" Medium and large models are slow on a CPU: 'small' is a good "
               "compromise, or enable the GPU in Advanced." if slow else ""))
        self._update_gpu_status()
        self._update_summary()

    def _update_summary(self) -> None:
        if not hasattr(self, "_summary"):
            return
        device, gpu_problem = self._engine
        lines = [f"<b>Model:</b> {html.escape(self._settings.model_size)} on "
                 f"{html.escape(device or 'loading…')}"]
        if gpu_problem and self._settings.gpu_enabled:
            lines.append(f"<b>GPU:</b> not used, {html.escape(gpu_problem)}")
        mode = "whole text" if self._settings.dictation_mode == "complete" else "live"
        lines.append(f"<b>Dictation mode:</b> {mode}")
        if self._activity is not None:
            speed = self._activity.average_speed()
            if speed is not None:
                lines.append(f"<b>Speed:</b> {speed:.2f} s of processing per second of audio"
                             + (" (faster than real time)" if speed < 1 else ""))
            if self._activity.last_timing:
                lines.append(f"<b>Last transcription:</b> {self._activity.last_timing}")
            lines.append(f"<b>Errors this session:</b> {self._activity.errors}")
        self._summary.setText("<br>".join(lines))

    def _copy_log(self) -> None:
        from ui.clipboard import copy_private
        copy_private(self._log_view.toPlainText())

    def _open_log(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(_LOG_FILE)))

    def _clear_log(self) -> None:
        self._log_view.clear()
        if self._activity is not None:
            self._activity.clear()

    # ── GPU ───────────────────────────────────────────────────────────

    def _update_gpu_status(self) -> None:
        gpu_ok = Transcriber.cuda_available()
        has_cublas = cublas_dir() is not None
        device = self._engine[0]
        if not gpu_ok:
            text = ("No NVIDIA GPU with a CUDA driver was found, so Whisper runs on "
                    "the CPU. Smaller models (base, small) are faster there.")
        elif not has_cublas:
            text = ("An NVIDIA GPU was found, but the CUDA library Whisper needs "
                    "(cuBLAS) is not installed, so the GPU cannot be used yet.")
        elif device.startswith("GPU"):
            text = "The GPU is in use."
        elif self._settings.gpu_enabled and device:
            text = (f"GPU support is installed but the model runs on the CPU"
                    f"{': ' + self._engine[1] if self._engine[1] else ''}. "
                    "If you just installed it, quit and reopen Typra.")
        else:
            text = "GPU support is installed. Tick the box above to use it."
        self._gpu_status.setText(text)
        self._gpu_btn.setVisible(gpu_ok and not has_cublas and _GPU_LOCK.exists()
                                 and self._pip is None)

    def _on_gpu_toggled(self, state) -> None:
        self._settings.set("gpu_enabled", bool(state))
        self._gpu_restart_lbl.setVisible(bool(state) != self._orig_gpu)

    def _install_gpu(self) -> None:
        answer = QMessageBox.question(
            self, "Install GPU support",
            "Typra will download NVIDIA's cuBLAS library (about 630 MB) from the "
            "Python Package Index and install it into its own environment. Every "
            "file is checked against a SHA-256 hash pinned in requirements-gpu.lock.\n\n"
            "This takes a few minutes. Continue?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_pip(truststore=True)

    def _run_pip(self, truststore: bool) -> None:
        python = Path(sys.executable).with_name("python.exe")
        if not python.exists():
            python = Path(sys.executable)
        args = ["-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                "--require-hashes", "--only-binary=:all:", "-r", str(_GPU_LOCK)]
        if truststore:
            # use the Windows certificate store (antivirus / proxy HTTPS inspection)
            args.insert(4, "--use-feature=truststore")
        self._pip = QProcess(self)
        self._pip.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._pip.finished.connect(lambda code, _status: self._on_pip_done(code, truststore))
        self._gpu_btn.hide()
        self._gpu_progress.show()
        self._gpu_status.setText("Downloading and installing GPU support… "
                                 "you can keep using Typra meanwhile.")
        if self._activity is not None:
            self._activity.info("Installing GPU support (NVIDIA cuBLAS)")
        self._pip.start(str(python), args)

    def _on_pip_done(self, code: int, truststore: bool) -> None:
        output = bytes(self._pip.readAll()).decode("utf-8", "replace") if self._pip else ""
        self._pip = None
        if code != 0 and truststore:
            print(f"[Settings] pip with truststore failed:\n{output}")
            self._run_pip(truststore=False)   # pip without the feature: its own certificates
            return
        self._gpu_progress.hide()
        if code == 0:
            self._settings.set("gpu_enabled", True)
            self._gpu_check.setChecked(True)
            self._gpu_restart_lbl.setVisible(True)
            self._gpu_status.setText("GPU support installed. Quit and reopen Typra to use it.")
            if self._activity is not None:
                self._activity.info("GPU support installed: restart Typra to use it")
        else:
            print(f"[Settings] pip failed:\n{output}")
            tail = " ".join(output.strip().splitlines()[-1:])[:200]
            self._gpu_status.setText(f"Installation failed: {tail or 'see typra.log'}")
            self._gpu_btn.show()
            if self._activity is not None:
                self._activity.error(f"GPU support installation failed: {tail}")

    # ── LLM status helpers ─────────────────────────────────────────────

    def _update_llm_status(self) -> None:
        mid = self._llm_model_combo.currentData() if hasattr(self, "_llm_model_combo") \
              else self._settings.get("llm_model_id", DEFAULT_MODEL)
        if LLMProcessor.model_downloaded_for(mid):
            info = LLM_MODELS[mid]
            self._llm_status.setText(f"Installed: {info['name']}")
            self._llm_status.show()
        else:
            self._llm_status.hide()

    def _update_dl_btn(self) -> None:
        if not hasattr(self, "_llm_model_combo"): return
        mid = self._llm_model_combo.currentData()
        if LLMProcessor.model_downloaded_for(mid):
            self._dl_btn.setText("Model already installed")
            self._dl_btn.setEnabled(False)
        else:
            self._dl_btn.setText("Download selected model")
            self._dl_btn.setEnabled(True)

    def _on_llm_model_change(self, _) -> None:
        mid = self._llm_model_combo.currentData()
        self._settings.set("llm_model_id", mid)
        self._update_llm_status()
        self._update_dl_btn()
        # Hide progress bar and re-enable recording if we switched to installed model
        if LLMProcessor.model_downloaded_for(mid):
            self._dl_progress.hide()
            self._dl_progress.setValue(0)
            self.download_finished.emit()

    def _download_llm(self) -> None:
        mid = self._llm_model_combo.currentData()
        info = LLM_MODELS[mid]
        self._dl_btn.setEnabled(False)
        self._dl_btn.setText("Downloading...")
        self._llm_status.setText(f"Downloading {info['name']} — recording disabled until complete.")
        self._llm_status.show()
        self._dl_progress.setValue(0)
        self._dl_progress.show()
        # Notify main controller to block recording during download
        self.download_started.emit()

        bridge = _DownloadBridge(self)
        bridge.progress.connect(self._on_dl_progress)
        bridge.finished.connect(self._on_dl_done)
        bridge.finished.connect(bridge.deleteLater)
        last_pct = [-1]

        def _progress(received: int, total: int) -> None:
            pct = int(received * 100 / total) if total > 0 else 0
            if pct != last_pct[0]:
                last_pct[0] = pct
                bridge.progress.emit(pct, received / 1_048_576, total / 1_048_576)

        def _do():
            ok = False
            try:
                ok = LLMProcessor(model_id=mid).download_model(progress_cb=_progress, model_id=mid)
            except Exception as exc:
                print(f"[Settings] download error: {exc}")
            finally:
                # Always signal the end: recording stays blocked until then
                bridge.finished.emit(ok)
        threading.Thread(target=_do, daemon=True).start()

    def _on_dl_progress(self, pct: int, mb_recv: float, mb_total: float) -> None:
        self._dl_progress.setValue(pct)
        self._dl_progress.setFormat(f"{mb_recv:.0f} / {mb_total:.0f} MB  ({pct}%)")

    def _on_dl_done(self, ok: bool) -> None:
        self._dl_progress.hide()
        self._update_llm_status()
        self._update_dl_btn()
        self.download_finished.emit()
        if ok:
            self._llm_status.setText("Download complete and verified (SHA-256).")
            self._llm_status.show()
        else:
            self._llm_status.setText(
                "Download failed or the file did not pass verification. "
                "Check your internet connection and try again.")
            self._llm_status.show()

    # ── Microphone: meter and test ─────────────────────────────────────

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._update_monitor()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._monitor.stop()
        self._testing = False
        self._test_timer.stop()

    def _update_monitor(self) -> None:
        """The microphone is open only while the General tab is on screen."""
        wanted = self.isVisible() and self._tabs.currentIndex() == 0
        if wanted and not self._monitor.running:
            if not self._monitor.start(self._mic_combo.currentData()):
                self._mic_status.setText(f"This microphone cannot be opened: {self._monitor.error}")
            self._meter.set_active(self._monitor.running)
        elif not wanted and self._monitor.running and not self._testing:
            self._monitor.stop()
            self._meter.set_active(False)

    def _on_level(self, rms: float) -> None:
        self._meter.set_level(meter_level(rms))
        if self._testing:
            self._test_levels.append(rms)

    def _start_test(self) -> None:
        blocked = self.test_blocked_fn() if self.test_blocked_fn else ""
        if blocked:
            self._show_test_result(blocked)
            return
        if not self._monitor.running and not self._monitor.start(self._mic_combo.currentData()):
            self._show_test_result(f"This microphone cannot be opened: {self._monitor.error}")
            return
        self._testing, self._test_levels, self._test_audio = True, [], None
        self._test_started = time.monotonic()
        self._monitor.record_test(_TEST_SECONDS)
        self._test_btn.setEnabled(False); self._play_btn.setEnabled(False)
        self._show_test_result("Recording: say a sentence in your dictation language…")
        self._test_timer.start()

    def _tick_test(self) -> None:
        left = max(0, _TEST_SECONDS - int(time.monotonic() - self._test_started))
        self._test_btn.setText(f"Recording… {left}")

    def _on_test_recorded(self, audio) -> None:
        self._test_timer.stop()
        self._testing = False
        self._test_btn.setText(f"Test microphone ({_TEST_SECONDS} s)")
        self._test_btn.setEnabled(True)
        self._test_audio = audio
        self._play_btn.setEnabled(len(audio) > 0)
        verdict = mic_verdict(self._test_levels, self._settings.silence_threshold)
        peak = max(self._test_levels) if self._test_levels else 0.0
        db = 20 * math.log10(peak) if peak > 1e-6 else -99
        self._show_test_result(f"{verdict}\nPeak level: {db:.0f} dB "
                               f"(silence threshold {20 * math.log10(self._settings.silence_threshold):.0f} dB).")
        if self.transcribe_fn is not None and len(audio) and peak >= self._settings.silence_threshold:
            self._test_result.setText(self._test_result.text() + "\nTranscribing the test…")
            fn = self.transcribe_fn

            def _run():
                started = time.monotonic()
                try:
                    text = fn(audio)
                except Exception as exc:
                    text = f"(error: {exc})"
                self._test_bridge.heard.emit(text, time.monotonic() - started)
            threading.Thread(target=_run, daemon=True, name="MicTest").start()
        self._update_monitor()

    def _on_test_heard(self, text: str, seconds: float) -> None:
        base = self._test_result.text().replace("\nTranscribing the test…", "")
        heard = f"Whisper heard: “{text}”" if text else "Whisper did not recognise any words."
        self._show_test_result(f"{base}\n{heard} ({seconds:.1f} s)")

    def _show_test_result(self, text: str) -> None:
        self._test_result.setText(text)
        self._test_result.show()

    def _play_test(self) -> None:
        if self._test_audio is None or not len(self._test_audio):
            return
        try:
            import sounddevice as sd
            sd.play(self._test_audio, self._settings.sample_rate)
        except Exception as exc:
            self._show_test_result(f"Playback failed: {exc}")

    # ── Helpers ────────────────────────────────────────────────────────

    def _populate_mics(self) -> None:
        self._mic_combo.blockSignals(True)
        self._mic_combo.clear()
        mics = AudioRecorder.list_microphones()
        saved      = self._settings.microphone_index
        saved_name = self._settings.microphone_name
        default_name = AudioRecorder.default_microphone_name()
        self._mic_combo.addItem(
            f"Windows default ({default_name})" if default_name else "Windows default", None)
        self._mic_combo.setItemData(0, "", Qt.ItemDataRole.ToolTipRole)
        for mic in mics:
            lbl = mic.name[:52]+"..." if len(mic.name)>52 else mic.name
            self._mic_combo.addItem(lbl, mic.index)
            i = self._mic_combo.count() - 1
            self._mic_combo.setItemData(i, mic.name, Qt.ItemDataRole.ToolTipRole)
            selected = (mic.name == saved_name) if saved_name else \
                       (saved is not None and mic.index == saved)
            if selected:
                self._mic_combo.setCurrentIndex(i)
        if not mics:
            self._mic_combo.addItem("No microphones found", None)
        self._mic_combo.blockSignals(False)

    @staticmethod
    def _div() -> QFrame:
        f = QFrame(); f.setObjectName("Divider")
        f.setFrameShape(QFrame.Shape.HLine); return f

    @staticmethod
    def _sec(text: str) -> QLabel:
        l = QLabel(text); l.setObjectName("Sec"); return l

    @staticmethod
    def _hint(text: str) -> QLabel:
        l = QLabel(text); l.setObjectName("Hint")
        l.setWordWrap(True); return l

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_lang(self, _):
        code = self._lang_combo.currentData()
        self._settings.set("language", code)
        self.language_changed.emit(code)

    def _on_mic(self, i):
        self._settings.set("microphone_index", self._mic_combo.currentData())
        self._settings.set("microphone_name",
                           self._mic_combo.itemData(i, Qt.ItemDataRole.ToolTipRole) or "")
        self.mic_changed.emit(self._mic_combo.currentData())
        if self._monitor.running and not self._testing:
            self._monitor.stop()
            self._update_monitor()

    def _on_mode(self, _) -> None:
        mode = self._mode_combo.currentData()
        self._settings.set("dictation_mode", mode)
        self._update_mode_hint()
        self._update_summary()
        self.mode_changed.emit(mode)

    def set_mode(self, mode: str) -> None:
        """Mode changed elsewhere (tray menu)."""
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(0 if mode == "live" else 1)
        self._mode_combo.blockSignals(False)
        self._update_mode_hint()
        self._update_summary()

    def _update_mode_hint(self) -> None:
        complete = self._mode_combo.currentData() == "complete"
        self._output_combo.setVisible(complete)
        self._mode_hint.setText(
            "Speak freely, pauses included, up to 10 minutes. When you stop, the "
            "whole recording is transcribed at once, so punctuation and capital "
            "letters follow the full context. Voice commands are not used."
            if complete else
            "Each phrase is typed when you pause, only into the window where you "
            "started. If you switch window, the rest goes to the result panel.")

    def _on_model(self, _):
        m = self._model_combo.currentData()
        self._settings.set("model_size", m)
        self.model_changed.emit(m)
        self._model_restart_lbl.setVisible(m != self._orig_model)

    def _on_hotkey_recorded(self, combo: str) -> None:
        self._settings.set("hotkey", combo)
        self.hotkey_changed.emit(combo, "toggle")

    def _on_tone_changed(self, _) -> None:
        # Takes effect with the next dictated chunk
        self._settings.set("llm_tone", self._tone_combo.currentData())

    def _show_voice_commands(self) -> None:
        code = self._settings.language
        name = dict(LANGUAGES).get(code, code)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Voice commands - {name}")
        dlg.setFixedWidth(500)
        v = QVBoxLayout(dlg); v.setContentsMargins(16, 16, 16, 12); v.setSpacing(10)
        v.addWidget(self._sec(f"Voice commands in {name}"))
        intro = QLabel(
            "<b>Say each command on its own</b>: pause, say the command, pause. "
            "Inside a sentence it is typed as a normal word, so "
            "<i>\"hello comma how are you\"</i> is written out in full.<br><br>"
            "Whisper already adds punctuation from your intonation and pauses, "
            "so you rarely need to dictate it. Commands are most useful for new "
            "lines and for deleting the last phrase. A spoken punctuation mark "
            "replaces the one Whisper added at the end of the previous phrase.<br><br>"
            "The delete command removes the last typed phrase, but only if the "
            "same window is still in front. Commands work in live mode only.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        rows = "".join(
            f"<tr><td style='padding:3px 14px 3px 0'>{' / '.join(html.escape(p) for p in phrases)}</td>"
            f"<td style='padding:3px 0'>{_command_label(out)}</td></tr>"
            for out, phrases in commands_for(code))
        table = QLabel(f"<table><tr><td style='padding:0 14px 6px 0'><b>Say</b></td>"
                       f"<td style='padding:0 0 6px 0'><b>Result</b></td></tr>{rows}</table>")
        table.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(table)
        if not self._settings.voice_commands_enabled:
            off = self._hint("Voice commands are currently turned off.")
            off.setStyleSheet("color: #e8a030; font-size: 11px;")
            v.addWidget(off)
        close = QPushButton("Close"); close.setObjectName("Btn")
        close.clicked.connect(dlg.accept)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(close)
        v.addLayout(row)
        # Size to the wrapped text, otherwise Qt clips the end of the table
        dlg.setFixedHeight(v.totalHeightForWidth(500))
        dlg.exec()

    @staticmethod
    def _restart_notice():
        lbl = QLabel("Quit and reopen Typra for this change to take effect.")
        lbl.setObjectName("Hint")
        lbl.setStyleSheet("color: #e8a030; font-size: 11px;")
        lbl.setWordWrap(True)
        lbl.setVisible(False)
        return lbl

    def closeEvent(self, e): e.ignore(); self.hide()
