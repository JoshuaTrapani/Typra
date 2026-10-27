# stt/transcriber.py
"""
Transcriber: runs faster-whisper in a subprocess (stt/subprocess_worker.py).
- Models come from pinned Hugging Face commits and are stored under
  ~/.whisper_dictation/whisper_models, next to the rest of the user data.
- Loading doubles as the compatibility probe: every attempt (GPU float16
  first if enabled, then CPU compute types) runs in a fresh worker and ends
  with a test transcription, so a native crash only costs that attempt.
- One reader thread per worker feeds a queue. A request that times out kills
  the worker, so a late answer can never be paired with the next request.
  Long recordings report progress, and the timeout counts from the last
  sign of progress, so a 10-minute dictation is not cut off.
- subprocess stderr is drained continuously so it never blocks.
"""
from __future__ import annotations
import base64, json, os, queue, subprocess, sys, sysconfig, threading, time
from pathlib import Path
from typing import Callable, Optional
import numpy as np


def _get_worker_script() -> list:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    # -I: ignore PYTHONPATH/PYTHONHOME and the user site (the worker only
    # imports installed packages)
    return [sys.executable, "-I", str(Path(__file__).parent / "subprocess_worker.py")]


MODELS_DIR = Path.home() / ".whisper_dictation" / "whisper_models"


def worker_env() -> dict:
    """Environment for model workers: Hugging Face caches and logs go into
    Typra's data folder (removed with it), not ~/.cache/huggingface."""
    env = dict(os.environ)
    env["HF_HOME"] = str(Path.home() / ".whisper_dictation" / "hf_home")
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    return env

# faster-whisper (CTranslate2) model repositories, pinned to reviewed commits.
MODEL_INFO = {
    "tiny":           {"size": "~75 MB",  "label": "Fastest · Lower accuracy",
                       "repo": "Systran/faster-whisper-tiny",
                       "revision": "d90ca5fe260221311c53c58e660288d3deb8d356"},
    "base":           {"size": "~145 MB", "label": "Fast · Good accuracy",
                       "repo": "Systran/faster-whisper-base",
                       "revision": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"},
    "small":          {"size": "~465 MB", "label": "Balanced · Better accuracy",
                       "repo": "Systran/faster-whisper-small",
                       "revision": "536b0662742c02347bc0e980a01041f333bce120"},
    "medium":         {"size": "~1.5 GB", "label": "Slow · High accuracy",
                       "repo": "Systran/faster-whisper-medium",
                       "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f"},
    "large-v3-turbo": {"size": "~1.6 GB", "label": "Best quality · Requires patience",
                       "repo": "dropbox-dash/faster-whisper-large-v3-turbo",
                       "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"},
}

_LOAD_TIMEOUT       = 1800   # first use downloads the model (up to ~1.6 GB)
_RESTART_TIMEOUT    = 300    # model already on disk
_IDLE_TIMEOUT       = 180    # longest wait for the next sign of progress
_RETRY_BACKOFF      = 60     # after a failed restart, don't retry on every chunk
_CREATE_NO_WINDOW   = 0x08000000
_CUBLAS_DLL         = "cublas64_12.dll"


def _transcribe_budget(seconds: float) -> float:
    """Upper bound for one request: generous even for medium on a slow CPU."""
    return 120.0 + 4.0 * seconds


def _cpu_threads() -> int:
    # Half the logical processors (≈ physical cores), at least 2, at most 8
    return max(2, min(8, (os.cpu_count() or 4) // 2))


def cublas_dir() -> Optional[Path]:
    """Folder of cuBLAS for CUDA 12, if installed (Typra's optional NVIDIA
    package, or a CUDA Toolkit on PATH)."""
    pip_dir = Path(sysconfig.get_paths()["purelib"]) / "nvidia" / "cublas" / "bin"
    if (pip_dir / _CUBLAS_DLL).exists():
        return pip_dir
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and (Path(entry) / _CUBLAS_DLL).exists():
            return Path(entry)
    return None


class Transcriber:
    def __init__(self, model_size: str = "base", gpu: bool = False) -> None:
        self.model_size    = model_size if model_size in MODEL_INFO else "base"
        self.gpu           = gpu
        self._proc: Optional[subprocess.Popen] = None
        self._lines: queue.Queue = queue.Queue()
        self._loaded       = False
        self._compute_type = "auto"
        self._closing      = False   # set by shutdown(): never start new workers
        self._retry_after  = 0.0
        self._io_lock      = threading.Lock()   # dictation and the mic test share the worker
        self._last_error   = ""
        self.worker_failed = False   # the worker could not be (re)started
        self.gpu_problem   = ""      # why the GPU is not used, if it was requested
        self.load_seconds  = 0.0
        self.cpu_threads   = _cpu_threads()
        # Called as on_event(level, message) for the Activity log (any thread)
        self.on_event: Optional[Callable[[str, str], None]] = None

    def _event(self, level: str, message: str) -> None:
        print(f"[Transcriber] {message}")
        if self.on_event:
            try: self.on_event(level, message)
            except Exception: pass

    @property
    def device_label(self) -> str:
        """e.g. 'GPU (CUDA, float16)' or 'CPU (int8, 8 threads)'."""
        if not self._loaded:
            return "not loaded"
        if self.gpu:
            return f"GPU (CUDA, {self._compute_type})"
        return f"CPU ({self._compute_type}, {self.cpu_threads} threads)"

    @staticmethod
    def faster_whisper_available() -> bool:
        try:
            import ctranslate2, faster_whisper  # noqa
            return True
        except Exception:
            return False

    @staticmethod
    def cuda_available() -> bool:
        """An NVIDIA GPU and driver are present (cuBLAS may still be missing)."""
        try:
            import ctranslate2
            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    def load(self, status_cb: Optional[Callable[[str], None]] = None) -> None:
        attempts = [("cpu", ct) for ct in ("auto", "float32", "int8")]
        self.gpu_problem = ""
        if self.gpu:
            if not self.cuda_available():
                self.gpu_problem = "no NVIDIA GPU with a CUDA driver was found"
            elif cublas_dir() is None:
                self.gpu_problem = ("the NVIDIA cuBLAS library is not installed "
                                    "(Settings > Advanced > Install GPU support)")
            else:
                attempts.insert(0, ("cuda", "float16"))
        if status_cb:
            status_cb(f"Loading '{self.model_size}' model "
                      f"({MODEL_INFO[self.model_size]['size']} download on first use)…")
        started = time.monotonic()
        for device, compute_type in attempts:
            if self._closing:
                raise RuntimeError("Typra is closing")
            print(f"[Transcriber] Starting worker (model={self.model_size}, "
                  f"device={device}, compute={compute_type})")
            if self._start(device, compute_type, _LOAD_TIMEOUT):
                self.gpu, self._compute_type = device == "cuda", compute_type
                self._loaded = True
                self.load_seconds = time.monotonic() - started
                self._event("info", f"Model '{self.model_size}' ready on {self.device_label} "
                                    f"in {self.load_seconds:.1f} s")
                if self.gpu_problem:
                    self._event("warning", f"GPU not used: {self.gpu_problem}")
                if status_cb:
                    status_cb("Model ready — start speaking!")
                return
            if device == "cuda":
                self.gpu_problem = self._last_error or "the GPU could not run the model"
        raise RuntimeError(f"Could not load the '{self.model_size}' Whisper model "
                           "with any device/compute type (see typra.log).")

    def shutdown(self) -> None:
        self._closing = True
        if self._proc:
            try: self._send("QUIT")
            except Exception: pass
            try: self._proc.wait(timeout=3)
            except Exception: pass
            self._kill_worker()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def transcribe(self, audio: np.ndarray, language: str = "en",
                   initial_prompt: str = "", best: bool = False,
                   progress_cb: Optional[Callable[[float], None]] = None) -> str:
        """best=True: beam search and VAD, for a whole recording (slower,
        more accurate). progress_cb receives the fraction of audio done."""
        if not self._loaded or audio is None or len(audio) == 0:
            return ""
        opts = {"language": language, "prompt": initial_prompt,
                "beam_size": 5 if best else 1, "vad": best}
        with self._io_lock:
            return self._subprocess_transcribe(audio, opts, progress_cb)

    # ── Subprocess communication ──────────────────────────────────────

    def _start(self, device: str, compute_type: str, timeout: float) -> bool:
        """Start a fresh worker, load the model and run a test transcription."""
        self._kill_worker()
        if self._closing:
            return False
        info = MODEL_INFO[self.model_size]
        params = {"model": info["repo"], "revision": info["revision"],
                  "download_root": str(MODELS_DIR),
                  "device": device, "compute_type": compute_type,
                  "cpu_threads": self.cpu_threads}
        try:
            self._start_worker()
            if self._closing:   # shutdown() ran while the process was starting
                self._kill_worker()
                return False
            self._send("LOAD " + base64.b64encode(json.dumps(params).encode()).decode("ascii"))
        except OSError as e:
            print(f"[Transcriber] Could not start worker: {e}")
            self._kill_worker()
            return False
        response = self._readline(timeout)
        if response != "READY":
            print(f"[Transcriber] Load failed ({device}/{compute_type}): {response}")
            self._last_error = response[6:] if response.startswith("ERROR ") else response
            self._kill_worker()
            return False
        # Some compute types only crash at inference time
        if self._do_transcribe(np.zeros(16000, dtype=np.float32),
                               {"language": "en", "beam_size": 1}) is None:
            print(f"[Transcriber] Test transcription failed ({device}/{compute_type})")
            self._kill_worker()
            return False
        return True

    def _start_worker(self) -> None:
        self._lines = queue.Queue()
        self._proc = subprocess.Popen(
            _get_worker_script(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
            # the worker switches its pipes to UTF-8; "replace" keeps a stray
            # byte from killing the reader threads
            bufsize=1, encoding="utf-8", errors="replace",
            env=worker_env(),
            creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        proc, lines = self._proc, self._lines

        def _read_stdout():
            try:
                for line in proc.stdout:
                    lines.put(line.strip())
            except Exception:
                pass
            lines.put(None)   # EOF: the worker exited

        # Drain stderr continuously — prevents pipe buffer filling and blocking
        def _drain_stderr():
            try:
                for line in proc.stderr:
                    print(f"[Worker-stderr] {line.rstrip()}")
            except Exception:
                pass

        threading.Thread(target=_read_stdout, daemon=True, name="WorkerStdout").start()
        threading.Thread(target=_drain_stderr, daemon=True, name="WorkerStderr").start()

    def _kill_worker(self) -> None:
        if self._proc:
            try: self._proc.kill()
            except Exception: pass
            self._proc = None

    def _send(self, line: str) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()

    def _readline(self, timeout: float = 30.0) -> str:
        if not self._proc: return "ERROR no process"
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            # Never leave a request in flight: its late answer would be read
            # as the answer to the next one.
            print(f"[Transcriber] No answer within {timeout:.0f}s — stopping worker")
            self._kill_worker()
            return "ERROR timeout"
        return "ERROR worker exited" if line is None else line

    def _ensure_worker(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if time.monotonic() < self._retry_after:
            return False
        self._event("warning", "The speech model process stopped: restarting it")
        device = "cuda" if self.gpu else "cpu"
        ok = self._start(device, self._compute_type, _RESTART_TIMEOUT)
        if not ok and (device, self._compute_type) != ("cpu", "float32") and \
                self._start("cpu", "float32", _RESTART_TIMEOUT):
            self.gpu, self._compute_type = False, "float32"
            ok = True
        self.worker_failed = not ok
        if not ok:
            self._event("error", "The speech model could not be restarted")
            self._retry_after = time.monotonic() + _RETRY_BACKOFF
        return ok

    def _subprocess_transcribe(self, audio: np.ndarray, opts: dict,
                                progress_cb: Optional[Callable[[float], None]]) -> str:
        if not self._ensure_worker():
            return ""
        result = self._do_transcribe(audio, opts, progress_cb)
        # If GPU transcription errored, fall back to CPU and retry once
        if result is None and self.gpu:
            self._event("warning", f"GPU transcription failed ({self._last_error}): "
                                   "switching to the CPU")
            if self._start("cpu", "float32", _RESTART_TIMEOUT):
                self.gpu, self._compute_type = False, "float32"
                result = self._do_transcribe(audio, opts, progress_cb)
        return result or ""

    def _do_transcribe(self, audio: np.ndarray, opts: dict,
                       progress_cb: Optional[Callable[[float], None]] = None) -> Optional[str]:
        """Send TRANSCRIBE, return text or None on error."""
        if not str(opts.get("language", "")).isalpha():
            opts = {**opts, "language": "en"}
        seconds = len(audio) / 16000
        try:
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            b64 = base64.b64encode(pcm.tobytes()).decode("ascii")
            opts_b64 = base64.b64encode(json.dumps(opts).encode()).decode("ascii")
            self._send(f"TRANSCRIBE {opts_b64} {b64}")
            deadline = time.monotonic() + _transcribe_budget(seconds)
            while True:
                wait = min(_IDLE_TIMEOUT, max(1.0, deadline - time.monotonic()))
                resp = self._readline(wait)
                if resp.startswith("PROGRESS "):
                    if progress_cb and seconds > 0:
                        try: progress_cb(min(1.0, float(resp[9:]) / seconds))
                        except ValueError: pass
                    if time.monotonic() > deadline:
                        print("[Transcriber] Transcription is taking too long — stopping worker")
                        self._kill_worker()
                        self._last_error = "timeout"
                        return None
                    continue
                if resp.startswith("TEXT "):
                    return base64.b64decode(resp[5:]).decode("utf-8")
                if resp == "EMPTY":
                    return ""
                if resp.startswith("ERROR"):
                    self._last_error = resp[6:]
                    print(f"[Transcriber] Subprocess error: {resp[6:]}")
                    return None   # signals "error occurred, consider fallback"
                print(f"[Transcriber] Unexpected response: {resp[:100]}")
                return ""
        except Exception as e:
            print(f"[Transcriber] _do_transcribe exception: {e}")
            self._kill_worker()
            return None
