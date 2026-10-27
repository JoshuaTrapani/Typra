# stt/llm_worker.py
"""
LLM worker subprocess: loads a GGUF model once, then rewrites text on request.
Protocol: one JSON object per line.
  -> {"model_path": "...", "n_gpu_layers": 0}   first line: load the model
  <- {"ok": true}  |  {"error": "..."}
  -> {"system": "...", "text": "...", "max_tokens": 256}   rewrite request
  <- {"text": "..."}  |  {"error": "..."}
Text only travels through the pipe; nothing is written to disk.
"""
import json
import sys

_N_CTX = 4096   # room for a whole-text dictation and its rewrite


def _complete(model, system: str, text: str, max_tokens: int) -> str:
    try:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": text}]
        reply = model.create_chat_completion(messages=messages,
                                             max_tokens=max_tokens, temperature=0.1)
    except Exception:
        # Some chat templates (e.g. Gemma's) reject the system role
        messages = [{"role": "user", "content": f"{system}\n\n{text}"}]
        reply = model.create_chat_completion(messages=messages,
                                             max_tokens=max_tokens, temperature=0.1)
    choice = reply["choices"][0]
    if choice.get("finish_reason") == "length":
        # A cut-off rewrite would silently drop the end of the dictation
        raise ValueError("the rewrite was cut off")
    return choice["message"]["content"].strip()


def main() -> None:
    # Only protocol replies may reach stdout: send library output to stderr.
    out = sys.stdout
    sys.stdout = sys.stderr

    def send(obj: dict) -> None:
        out.write(json.dumps(obj) + "\n")
        out.flush()

    try:
        cfg = json.loads(sys.stdin.readline())
        from llama_cpp import Llama
        model = Llama(model_path=cfg["model_path"], n_ctx=_N_CTX, n_threads=2,
                      n_gpu_layers=int(cfg.get("n_gpu_layers", 0)), verbose=False)
    except Exception as exc:
        send({"error": f"{type(exc).__name__}: {exc}"})
        return
    send({"ok": True})

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            send({"text": _complete(model, req["system"], req["text"],
                                    int(req.get("max_tokens", 256)))})
        except Exception as exc:
            send({"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
