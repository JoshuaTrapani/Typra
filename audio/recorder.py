# audio/recorder.py
"""
Microphone capture using sounddevice.

- Enumerates all available input devices.
- Opens a non-blocking InputStream that pushes float32 mono audio
  into a thread-safe queue consumed by the transcription worker.
- Computes RMS for the live level meter.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np
import sounddevice as sd


@dataclass
class MicrophoneInfo:
    index: int
    name: str
    max_channels: int
    default_sample_rate: float

    def __str__(self) -> str:
        return f"{self.name} (#{self.index})"


class AudioRecorder:
    """Capture audio from a microphone into a queue."""

    # Internal chunk size fed by sounddevice callback (samples)
    _BLOCK_SIZE: int = 1024

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate

        # Public queue: consumers read np.ndarray chunks from here
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue()

        self._stream: Optional[sd.InputStream] = None
        self._is_recording: bool = False
        self._lock = threading.Lock()

        # Optional callback invoked with RMS value on every block
        self._level_cb: Optional[Callable[[float], None]] = None

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def list_microphones() -> List[MicrophoneInfo]:
        """Return the input devices of the default host API (Windows lists
        every microphone once per host API: MME, DirectSound, WASAPI...)."""
        devices: List[MicrophoneInfo] = []
        default_api: List[MicrophoneInfo] = []
        try:
            hostapi = sd.default.hostapi
            for idx, dev in enumerate(sd.query_devices()):
                # The "Sound Mapper" is the Windows default, listed separately
                if dev["max_input_channels"] > 0 and "Sound Mapper" not in dev["name"]:
                    mic = MicrophoneInfo(
                        index=idx,
                        name=dev["name"],
                        max_channels=dev["max_input_channels"],
                        default_sample_rate=dev["default_samplerate"],
                    )
                    devices.append(mic)
                    if dev["hostapi"] == hostapi:
                        default_api.append(mic)
        except Exception as exc:
            print(f"[AudioRecorder] Error listing devices: {exc}")
        return default_api or devices

    @staticmethod
    def default_microphone_name() -> str:
        """Name of the input device Windows currently uses by default. MME
        calls it "Microsoft Sound Mapper": WASAPI knows the real device."""
        try:
            for api in sd.query_hostapis():
                if "WASAPI" in api["name"] and api["default_input_device"] >= 0:
                    return str(sd.query_devices(api["default_input_device"])["name"])
            return str(sd.query_devices(kind="input")["name"])
        except Exception:
            return ""

    @staticmethod
    def find_microphone(name: str) -> Optional[int]:
        """Current index of the input device called `name` (indexes change
        when devices are added or removed), or None if it is gone."""
        for mic in AudioRecorder.list_microphones():
            if mic.name == name:
                return mic.index
        return None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_level_callback(self, cb: Callable[[float], None]) -> None:
        """Register a callback that receives RMS (0.0–1.0) per block."""
        self._level_cb = cb

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start(self, device_index: Optional[int] = None) -> None:
        """Open the microphone stream and begin capturing."""
        with self._lock:
            if self._is_recording:
                return

            # Not flushed: audio of the previous session still waiting in the
            # queue belongs to it (the worker separates sessions with markers).
            try:
                self._stream = sd.InputStream(
                    device=device_index,
                    channels=1,
                    samplerate=self.sample_rate,
                    blocksize=self._BLOCK_SIZE,
                    dtype=np.float32,
                    callback=self._callback,
                )
                self._stream.start()
                self._is_recording = True
                print(
                    f"[AudioRecorder] Started on device "
                    f"{'default' if device_index is None else device_index} "
                    f"@ {self.sample_rate} Hz"
                )
            except Exception as exc:
                print(f"[AudioRecorder] Failed to start stream: {exc}")
                raise

    def stop(self) -> None:
        """Stop capturing and close the stream."""
        with self._lock:
            if not self._is_recording:
                return
            self._is_recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as exc:
                    print(f"[AudioRecorder] Error stopping stream: {exc}")
                finally:
                    self._stream = None
            print("[AudioRecorder] Stopped.")

    # ------------------------------------------------------------------
    # Internal sounddevice callback (called from C thread)
    # ------------------------------------------------------------------

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(f"[AudioRecorder] Stream status: {status}")

        # Extract mono channel, make a copy so sounddevice can reuse the buffer
        chunk: np.ndarray = indata[:, 0].copy()  # shape: (frames,)

        # Push to queue (non-blocking; drop if consumer is too slow)
        try:
            self.audio_queue.put_nowait(chunk)
        except queue.Full:
            pass  # Drop oldest? For now just drop new chunk

        # RMS level for visualization (clamped to 0–1)
        if self._level_cb is not None:
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            # Scale: typical speech RMS ~0.02–0.1, map to 0–1 with ×8 gain
            level = min(1.0, rms * 8.0)
            self._level_cb(level)
