# Typra Offline Speech to Text

Typra is a free, lightweight dictation app for Windows that transcribes your voice and types the result directly into any application.

Everything runs locally on your device using [OpenAI Whisper](https://github.com/openai/whisper) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No cloud, no subscription, no data leaves your machine.

---

## Features

- **Fully offline** speech never leaves your device
- **Types anywhere** works in any Windows application
- **Global hotkey** press `Ctrl + Shift + Space` (or customise it yourself) to start and stop from anywhere
- **Local AI Cleanup** after your dictation the transcribed Text gets cleanded up with local AI
- **Tone Modes** Choose between Raw, Cleanup, Casual, Professional, or Concise
- **Live waveform** small overlay shows you when Typra is listening
- **Supports 20 Languages** Dictate in 20 natively supported languages including Spanish, Italian, Japanese, Arabic and more
- **Session History** Every dictation session is saved as a complete paragraph to a searchable local database
- **Voice Commands** Say "new line", "comma", "exclamation mark", or "delete that" to format text hands-free
- **No GPU required** runs on any modern CPU (but has the option for GPU acceleration)
- **System tray** runs quietly in the background, right-click to control

---

**System requirements:**
- Windows 10 or Windows 11 (64-bit)
- ~3 GB free disk space
- Internet connection during installation only (to download the AI model ~145 MB)

---
# Download & Installation
 
**[Download the latest installer →](https://github.com/JoshuaTrapani/Typra/releases/download/v2.0.0/Typra_v2_Setup.exe)**
 
Just download `Typra_Setup.exe`, run it and follow the steps. The installer handles everything including Python and the AI model.
 
**System requirements:**
- Windows 10 or Windows 11 (64-bit)
- ~3 GB free disk space
- Internet connection during installation only (to download the AI models)

---

## How it works

1. Typra loads a local AI speech recognition model (Whisper Base, ~145 MB)
2. Press the global hotkey a small waveform overlay appears at the bottom of your screen
3. Speak naturally
4. Your words are transcribed cleanded up by an LLM of your choice and typed into whatever app you were using
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
- `faster-whisper` local Whisper inference
- `PyQt6` user interface
- `sounddevice` microphone input
- `pynput` global hotkey and keyboard simulation
- `pywin32` Windows API integration
**Optional dependency:**
- `llama-cpp-python` (>=0.3.9) is required for the local AI Cleanup feature.
---

## Project structure

```
typra/
├── assets/                 # Icons and visual assets
├── audio/                  # Microphone capture and recording logic
├── config/                 # Settings management and persistence
├── db/                     # SQLite transcription history database
├── input/                  # Hotkey listener and keyboard simulation
├── stt/                    # Whisper transcription and LLM processing
├── ui/                     # PyQt6 interface, overlay, and tray icons
├── download_models.py      # Automated model downloader
├── launch.bat              # Launcher for the setup process
├── main.py                 # Primary entry point
├── requirements.txt        # Python package dependencies
├── run.bat                 # Helper for local development
├── setup.bat               # Environment and dependency setup
├── typra.ico               # Application icon
└── Typra.vbs               # Silent launcher (no console window)
```

---

## Privacy

Typra processes all audio locally. No audio, text, or usage data is ever sent to external servers. The app requires internet access only once during installation to download the necessary AI models, including the Gemma 4 E2B model which is approximately 2.5 GB. After this initial setup, the application works completely offline.

---

## The AI models

Typra v2 utilizes two types of local AI models to provide high quality offline dictation and text refinemen

1. **Transcription Models (Whisper)**
You can select between five different Whisper model sizes in the settings to balance speed and accuracy. These models are provided via faster-whisper.

| Model          | Size    | Hardware  |
| -------------- | ------- | --------- |
| Tiny           | ~75 MB  | CPU / GPU |
| Base           | ~145 MB | CPU / GPU |
| Small          | ~465 MB | CPU / GPU |
| Medium         | ~1.5 GB | CPU / GPU |
| Large-v3-turbo | ~1.6 GB | CPU / GPU |

2. **Cleanup Models (LLM)**
These optional models are used to fix grammar, remove filler words, or rewrite text in a specific tone.

| Model        | Size    | Description                                                 |
| ------------ | ------- | ----------------------------------------------------------- |
| Gemma 4 E2B  | ~2.5 GB | Google's state of the art model for on-device use (Default) |
| Llama 3.2 1B | ~0.8 GB | Meta's lightweight model optimized for lower RAM systems    |

---

## Licence

MIT free to use, share and modify. See [LICENSE](LICENSE) for details.

---

## Acknowledgements

- [OpenAI Whisper](https://github.com/openai/whisper) speech recognition model
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) optimised Whisper inference
- [Gemma](https://ai.google.dev/gemma) on-device language models by Google
- [Llama](https://ai.meta.com/llama/) lightweight language models by Meta
- [PyQt6](https://pypi.org/project/PyQt6/) user interface framework

---

> [!WARNING]
> Typra is an early-release, vibecoded tool provided as-is. It may contain bugs or behave unexpectedly in some environments. Use at your own discretion.
