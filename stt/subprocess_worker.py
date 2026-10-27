# stt/subprocess_worker.py
"""
Standalone transcription subprocess.
Protocol (one line per message):
  LOAD <params_b64>          base64 JSON: model, revision, download_root,
                             device, compute_type, cpu_threads
  TRANSCRIBE <opts_b64> <audio_b64>
                             opts: base64 JSON with language, prompt,
                             beam_size, vad; audio: 16 kHz mono int16
  QUIT
Replies: READY | PROGRESS <seconds> | TEXT <text_b64> | EMPTY
         | ERROR <single-line message>
PROGRESS (audio seconds done) may precede TEXT/EMPTY on long audio.
Full tracebacks go to stderr, which the parent copies into the log.
"""
import sys, base64, json, os, sysconfig, traceback
from pathlib import Path

# DLLs of the optional NVIDIA cuBLAS wheel (requirements-gpu.lock).
# CTranslate2 bundles cuDNN but loads cuBLAS from the system.
_CUDA_DLLS = ("cublasLt64_12.dll", "cublas64_12.dll")


def _load_cuda_libs() -> None:
    """Preload pip-installed cuBLAS so CTranslate2 finds it when it asks for
    it by name; a CUDA Toolkit on PATH works without this."""
    if sys.platform != "win32":
        return
    import ctypes
    bin_dir = Path(sysconfig.get_paths()["purelib"]) / "nvidia" / "cublas" / "bin"
    if not bin_dir.is_dir():
        return
    os.add_dll_directory(str(bin_dir))
    for name in _CUDA_DLLS:
        if (bin_dir / name).exists():
            ctypes.WinDLL(str(bin_dir / name))


def main():
    # Pipes default to the ANSI code page on Windows; the parent reads UTF-8.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
    # Only protocol replies may reach stdout: send library output to stderr.
    out = sys.stdout
    out.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stdout = sys.stderr

    def reply(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    def error(exc: BaseException) -> None:
        traceback.print_exc()
        reply("ERROR " + " ".join(f"{type(exc).__name__}: {exc}".split())[:500])

    model = None

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        if line == "QUIT":
            break

        elif line.startswith("LOAD "):
            try:
                params = json.loads(base64.b64decode(line[5:]).decode("utf-8"))
                if params.get("device") == "cuda":
                    _load_cuda_libs()
                from faster_whisper import WhisperModel
                kwargs = dict(
                    device=params.get("device", "cpu"),
                    compute_type=params.get("compute_type", "auto"),
                    cpu_threads=int(params.get("cpu_threads", 2)), num_workers=1,
                    download_root=params.get("download_root"),
                    revision=params.get("revision"),
                )
                # Once the pinned snapshot is on disk, load it without
                # contacting Hugging Face (works fully offline).
                cached = bool(kwargs["download_root"] and kwargs["revision"]) and (
                    Path(kwargs["download_root"])
                    / ("models--" + params["model"].replace("/", "--"))
                    / "snapshots" / kwargs["revision"]).is_dir()
                try:
                    model = WhisperModel(params["model"], local_files_only=cached, **kwargs)
                except Exception:
                    if not cached:
                        raise
                    traceback.print_exc()   # incomplete cache: fetch the missing files
                    model = WhisperModel(params["model"], **kwargs)
                reply("READY")
            except Exception as exc:
                model = None
                error(exc)

        elif line.startswith("TRANSCRIBE "):
            if model is None:
                reply("ERROR model not loaded")
                continue
            try:
                _, opts_b64, b64_data = line.split(" ", 2)
                opts = json.loads(base64.b64decode(opts_b64).decode("utf-8"))

                import numpy as np
                pcm = np.frombuffer(base64.b64decode(b64_data), dtype=np.int16)
                audio = pcm.astype(np.float32) / 32768.0

                beam = int(opts.get("beam_size", 1))
                kwargs = dict(
                    language=opts.get("language", "en"),
                    beam_size=beam,
                    best_of=beam,
                    temperature=0.0,
                    without_timestamps=True,
                    word_timestamps=False,
                )
                if opts.get("prompt"):
                    kwargs["initial_prompt"] = opts["prompt"]
                # Live phrases are already cut at pauses by the parent; long
                # recordings use Silero VAD to skip silences (fewer hallucinations)
                if opts.get("vad"):
                    kwargs["vad_filter"] = True

                segs, _ = model.transcribe(audio, **kwargs)
                parts = []
                for seg in segs:
                    parts.append(seg.text.strip())
                    reply(f"PROGRESS {seg.end:.1f}")
                text = " ".join(p for p in parts if p).strip()

                if text:
                    reply(f"TEXT {base64.b64encode(text.encode()).decode()}")
                else:
                    reply("EMPTY")

            except Exception as exc:
                error(exc)

        else:
            reply("ERROR unknown command")

if __name__ == "__main__":
    main()
