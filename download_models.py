"""
download_models.py — optional: pre-download an AI Cleanup (LLM) model.

    .venv\\Scripts\\python.exe download_models.py              (Gemma 4 E2B, 3.5 GB)
    .venv\\Scripts\\python.exe download_models.py llama32-1b-q4

Uses the same pinned URLs and SHA-256 verification as Settings > AI Cleanup.
AI Cleanup also needs llama-cpp-python (see README).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stt.llm_processor import DEFAULT_MODEL, LLM_MODELS, LLMProcessor


def main() -> int:
    model_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    if model_id not in LLM_MODELS:
        print(f"Unknown model '{model_id}'. Choose one of: {', '.join(LLM_MODELS)}")
        return 2
    info = LLM_MODELS[model_id]
    processor = LLMProcessor(model_id)
    if processor.model_downloaded():
        print(f"{info['name']} is already downloaded and verified.")
        return 0

    print(f"Downloading {info['name']} to {processor.model_path()} ...", flush=True)
    last = [-1]

    def progress(received: int, total: int) -> None:
        pct = received * 100 // total
        if pct != last[0]:
            last[0] = pct
            print(f"Progress: {received / 1_048_576:.0f} / {total / 1_048_576:.0f} MB  ({pct}%)",
                  flush=True)

    if not processor.download_model(progress_cb=progress):
        print("ERROR: download failed or the file did not pass SHA-256 verification.")
        return 1
    print("Download complete and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
