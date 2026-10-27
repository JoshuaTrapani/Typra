#!/usr/bin/env python3
# main.py: Typra entry point

import sys
import os
import traceback

# ── Frozen exe: dispatch sub-modes before anything else ──────────────────────
# When PyInstaller bundles the app, the worker scripts don't exist as separate
# files. Instead Typra.exe is re-invoked with --worker or --llm-worker flags.
if "--worker" in sys.argv:
    # Run as the transcription subprocess worker
    sys.argv.remove("--worker")
    from stt.subprocess_worker import main as _worker_main
    _worker_main()
    sys.exit(0)

if "--llm-worker" in sys.argv:
    # Run as the LLM post-processing subprocess worker
    sys.argv.remove("--llm-worker")
    from stt.llm_worker import main as _llm_worker_main
    _llm_worker_main()
    sys.exit(0)

# ── Single instance ──────────────────────────────────────────────────────────
# A second instance would register a second global hotkey (every dictation
# typed twice) and truncate the first instance's log. The installer checks
# the same mutex before replacing or removing files.
_SINGLE_INSTANCE_MUTEX = "Local\\Typra.OfflineDictation.SingleInstance"
_instance_mutex = None   # held until the process exits

def _acquire_single_instance() -> bool:
    global _instance_mutex
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX)
    error = ctypes.get_last_error()
    if handle and error == 183:   # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    if not handle and error == 5:  # ERROR_ACCESS_DENIED: owned by an elevated instance
        return False
    _instance_mutex = handle
    return True

if not _acquire_single_instance():
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        None, "Typra is already running.\nLook for its icon in the system tray.",
        "Typra", 0x40)   # MB_ICONINFORMATION
    sys.exit(0)

# Typra types into other programs; as administrator it would run code from
# user-writable folders with full rights, and it does not need them.
if sys.platform == "win32":
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        ctypes.windll.user32.MessageBoxW(
            None, "Typra is running as administrator, which it does not need.\n"
                  "Quit it and start it normally from the Start menu.",
            "Typra", 0x30)   # MB_ICONWARNING

# ── Redirect stdout/stderr to log file when running under pythonw ────────────
# pythonw.exe has no console at all: sys.stdout is None.
# We redirect to a log file so crashes are always visible.
_LOG_DIR = os.path.join(os.path.expanduser("~"), ".whisper_dictation")
_LOG_FILE = os.path.join(_LOG_DIR, "typra.log")

def _setup_logging() -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)
    try:
        log = open(_LOG_FILE, "w", encoding="utf-8", buffering=1)
        sys.stdout = log
        sys.stderr = log
        print(f"[Typra] Log started. Python {sys.version}")
        print(f"[Typra] Working dir: {os.getcwd()}")
    except Exception:
        pass  # If we can't even log, nothing we can do

# Only redirect if there's no real console (pythonw case)
if sys.stdout is None or not hasattr(sys.stdout, 'write'):
    _setup_logging()

# With the default hook PyQt aborts the whole app on any uncaught exception
# in a slot or thread; log it instead.
def _log_unhandled(exc_type, exc, tb) -> None:
    print("[Typra] Unhandled exception:\n"
          + "".join(traceback.format_exception(exc_type, exc, tb)))

sys.excepthook = _log_unhandled

# ── Project root ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows: set App User Model ID ───────────────────────────────────────────
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Typra.OfflineDictation.1"
        )
    except Exception as e:
        print(f"[Typra] AppUserModelID failed: {e}")

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
os.environ.setdefault("SD_ENABLE_ASIO", "0")

# ── PyQt6 ─────────────────────────────────────────────────────────────────────
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    print("[Typra] PyQt6 imported OK")
except ImportError as e:
    # Write to log and exit
    with open(_LOG_FILE, "a") as f:
        f.write(f"FATAL: PyQt6 missing: {e}\n")
    sys.exit(1)

# ── Required deps ─────────────────────────────────────────────────────────────
_REQUIRED = [
    ("numpy",       "numpy"),
    ("sounddevice", "sounddevice"),
    ("pynput",      "pynput"),
]

def check_dependencies() -> bool:
    missing = []
    for import_name, pip_name in _REQUIRED:
        try:
            __import__(import_name)
            print(f"[Typra] {import_name} OK")
        except ImportError:
            missing.append(pip_name)
        except Exception as exc:
            missing.append(f"{pip_name} (error: {exc})")
    if missing:
        print(f"[Typra] Missing deps: {missing}")
        box = QMessageBox()
        box.setWindowTitle("Typra: Missing Dependencies")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        box.setText(
            "<b>Typra cannot start: missing packages:</b><br><br>"
            + "<br>".join(f"• <code>{p}</code>" for p in missing)
            + "<br><br>Open <b>run.bat</b> to reinstall."
        )
        box.exec()
        return False
    return True

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    print("[Typra] Creating QApplication…")
    app = QApplication(sys.argv)
    app.setApplicationName("Typra")
    app.setOrganizationName("Typra")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[Typra] ERROR: No system tray available.")
        QMessageBox.critical(None, "Typra", "System tray is not available.")
        return 1

    print("[Typra] System tray available.")

    if not check_dependencies():
        return 1

    try:
        from config.settings import Settings
        from ui.main_window import AppController
        print("[Typra] Modules imported OK")
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"FATAL import:\n{tb}")
        box = QMessageBox()
        box.setWindowTitle("Typra: Import Error")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(f"<b>Failed to import modules.</b><br><br>{exc}")
        box.setDetailedText(tb)
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        box.exec()
        return 1

    try:
        settings   = Settings()
        controller = AppController(settings)
        controller.start()
        print("[Typra] Running: check tray icon.")
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"FATAL startup:\n{tb}")
        box = QMessageBox()
        box.setWindowTitle("Typra: Startup Error")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(f"<b>Typra failed to start.</b><br><br>{exc}")
        box.setDetailedText(tb)
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        box.exec()
        return 1

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
