# ui/winutil.py
"""Windows helpers: which window is in front, what it is called, and
bringing a window back to the front. No-ops on other platforms."""
from __future__ import annotations
import os, sys, time
from pathlib import Path

_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    import ctypes
    from ctypes import wintypes
    _user32   = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _version  = ctypes.WinDLL("version", use_last_error=True)

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    _user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _user32.IsWindow.argtypes = (wintypes.HWND,)
    _user32.IsIconic.argtypes = (wintypes.HWND,)
    _user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
    _version.GetFileVersionInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
                                             wintypes.DWORD, ctypes.c_void_p)
    _version.VerQueryValueW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR,
                                        ctypes.POINTER(ctypes.c_void_p),
                                        ctypes.POINTER(wintypes.UINT))

_TASKBAR_CLASSES = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland")
_app_names: dict[str, str] = {}   # exe path -> product name (cache)


def foreground_window() -> int:
    if not _IS_WIN: return 0
    try: return _user32.GetForegroundWindow() or 0
    except Exception: return 0


def window_pid(hwnd: int) -> int:
    if not _IS_WIN or not hwnd: return 0
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_own_window(hwnd: int) -> bool:
    return bool(hwnd) and window_pid(hwnd) == os.getpid()


def is_taskbar(hwnd: int) -> bool:
    """Clicking the tray icon brings the taskbar to the foreground."""
    if not _IS_WIN or not hwnd: return False
    try:
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, buf, 64)
        return buf.value in _TASKBAR_CLASSES
    except Exception: return False


def is_window(hwnd: int) -> bool:
    return bool(_IS_WIN and hwnd and _user32.IsWindow(hwnd))


def window_title(hwnd: int) -> str:
    if not _IS_WIN or not hwnd: return ""
    try:
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception: return ""


def _exe_path(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h: return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(h)


def _product_name(exe: str) -> str:
    """FileDescription from the version resource ('Google Chrome')."""
    size = _version.GetFileVersionInfoSizeW(exe, None)
    if not size: return ""
    data = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(exe, 0, size, data): return ""
    ptr, n = ctypes.c_void_p(), wintypes.UINT()
    if not _version.VerQueryValueW(data, "\\VarFileInfo\\Translation",
                                   ctypes.byref(ptr), ctypes.byref(n)) or n.value < 4:
        return ""
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    key = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
    if not _version.VerQueryValueW(data, key, ctypes.byref(ptr), ctypes.byref(n)) or not n.value:
        return ""
    return ctypes.wstring_at(ptr.value, n.value).rstrip("\0").strip()


def app_name(hwnd: int) -> str:
    """Friendly name of the program that owns the window ('Google Chrome')."""
    if not _IS_WIN or not hwnd: return ""
    try:
        exe = _exe_path(window_pid(hwnd))
    except Exception:
        return ""
    if not exe: return ""
    if exe not in _app_names:
        try: name = _product_name(exe)
        except Exception: name = ""
        _app_names[exe] = name or Path(exe).stem
    return _app_names[exe]


def describe(hwnd: int, limit: int = 48) -> str:
    """'Google Chrome — ChatGPT' (shortened), or '' for no window."""
    if not hwnd: return ""
    app, title = app_name(hwnd), window_title(hwnd)
    if title.endswith(app) and title != app:
        title = title[: -len(app)].rstrip(" -—–|")   # 'Doc - Word' -> 'Doc'
    text = f"{app} — {title}" if app and title and title != app else (app or title or "window")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def activate(hwnd: int, timeout: float = 1.0) -> bool:
    """Bring a window to the front; True once it is the foreground window.
    Windows allows this because Typra is in front when the user clicks one
    of its buttons."""
    if not is_window(hwnd): return False
    try:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        _user32.SetForegroundWindow(hwnd)
    except Exception:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if foreground_window() == hwnd:
            return True
        time.sleep(0.03)
    return foreground_window() == hwnd
