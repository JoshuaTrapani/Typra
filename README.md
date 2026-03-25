# Typra Offline Speech to Text

Typra is a free, lightweight dictation app for Windows that transcribes your voice and types the result directly into any application.

Everything runs locally on your device using [OpenAI Whisper](https://github.com/openai/whisper) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No cloud, no subscription, no data leaves your machine.

---

## Features

- **Fully offline** — speech never leaves your device
- **Types anywhere** — works in any Windows application
- **Global hotkey** — press `Ctrl + Shift + Space` to start and stop from anywhere
- **Live waveform** — small overlay shows you when Typra is listening
- **System tray** — runs quietly in the background, right-click to control
- **Dark & Light mode** — icon and settings window adapt to your Windows theme
- **Supports English, German and French**
- **No GPU required** — runs on any modern CPU

---

**System requirements:**
- Windows 10 or Windows 11 (64-bit)
- 500 MB free disk space
- Internet connection during installation only (to download the AI model ~145 MB)

---

## How it works

1. Typra loads a local AI speech recognition model (Whisper Base, ~145 MB)
2. Press `Ctrl + Shift + Space` — a small waveform overlay appears at the bottom of your screen
3. Speak naturally
4. Your words are transcribed and typed into whatever app you were using
5. Press the hotkey again or click the red button to stop

---

## Running from source

If you prefer to run Typra directly from the source code:

**Requirements:** Python 3.11, Windows 10/11

```bat
git clone https://github.com/JoshuaTrapani/typra.git
cd typra
run.bat
```

`run.bat` will automatically create a virtual environment and install all dependencies on first run.

**Dependencies installed automatically:**
- `faster-whisper` — local Whisper inference
- `PyQt6` — user interface
- `sounddevice` — microphone input
- `pynput` — global hotkey and keyboard simulation
- `pywin32` — Windows API integration

---

## Project structure

```
typra/
├── main.py                 # Entry point
├── run.bat                 # One-click launcher for development
├── assets/                 # App icons (dark + light mode)
├── audio/                  # Microphone capture
├── config/                 # Settings and persistence
├── input/                  # Hotkey listener and keyboard simulation
├── stt/                    # Whisper transcription (subprocess-isolated)
└── ui/                     # PyQt6 interface, tray, overlay, settings
```

---

## Privacy

Typra processes all audio locally. No audio, text or usage data is ever sent anywhere. The app requires internet access only once during installation to download the AI model. After that it works completely offline.

---

## The AI model

Typra uses **Whisper Base** by OpenAI, running locally via faster-whisper with CPU-only int8 inference.

| Property | Value |
|----------|-------|
| Model | Whisper Base |
| Size | ~145 MB |
| Languages | English, German, French (+ 96 more supported by the model) |
| Hardware | CPU only, no GPU needed |
| Latency | ~1–3 seconds per sentence |

---

## Licence

MIT — free to use, share and modify. See [LICENSE](LICENSE) for details.

---

## Acknowledgements

- [OpenAI Whisper](https://github.com/openai/whisper) — speech recognition model
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — optimised Whisper inference
- [PyQt6](https://pypi.org/project/PyQt6/) — user interface framework
