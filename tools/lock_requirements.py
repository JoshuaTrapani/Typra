"""Regenerate requirements.lock from requirements.txt (or, with --gpu,
requirements-gpu.lock from requirements-gpu.txt).

The lock pins every package (including transitive dependencies) to an exact
version and the SHA-256 of its wheel, so installs use
`pip install --require-hashes --only-binary=:all: -r requirements.lock`.

Run it with 64-bit CPython 3.11 on Windows, the platform the lock targets:
    py -3.11 tools\\lock_requirements.py [--gpu]
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = """\
# Exact, hash-pinned dependency set used by the installer and setup.bat.
# Target: Windows x64, CPython 3.11. Wheels only (no source builds).
# Top-level requirements live in requirements.txt; regenerate this file with
#   python tools/lock_requirements.py
"""

GPU_HEADER = """\
# Optional GPU support: NVIDIA cuBLAS for CUDA 12, needed by CTranslate2 to
# run Whisper on an NVIDIA GPU (cuDNN ships with CTranslate2). Installed by
# Settings > Advanced > Install GPU support, and kept by the installer on
# updates. Exact versions, SHA-256 verified, wheels only. Regenerate with
#   python tools/lock_requirements.py --gpu
"""


def main() -> int:
    if (sys.platform != "win32" or sys.version_info[:2] != (3, 11)
            or struct.calcsize("P") != 8):
        print("Run this with 64-bit CPython 3.11 on Windows.", file=sys.stderr)
        return 1
    gpu = "--gpu" in sys.argv[1:]
    source = ROOT / ("requirements-gpu.txt" if gpu else "requirements.txt")
    out = ROOT / ("requirements-gpu.lock" if gpu else "requirements.lock")

    with tempfile.TemporaryDirectory() as tmp:
        env_dir = Path(tmp) / "venv"
        venv.create(env_dir, with_pip=True)
        report = Path(tmp) / "report.json"
        subprocess.run(
            [str(env_dir / "Scripts" / "python.exe"), "-m", "pip", "install",
             "--use-feature=truststore", "--disable-pip-version-check",
             "--dry-run", "--ignore-installed", "--only-binary=:all:",
             "--quiet", "--report", str(report),
             "-r", str(source)],
            check=True,
        )
        resolved = json.loads(report.read_text(encoding="utf-8"))["install"]

    lines = [GPU_HEADER if gpu else HEADER]
    for item in sorted(resolved, key=lambda i: i["metadata"]["name"].lower()):
        meta = item["metadata"]
        archive = item["download_info"]["archive_info"]
        sha256 = (archive.get("hashes") or {}).get("sha256") \
            or archive["hash"].split("=", 1)[1]
        lines.append(f"{meta['name']}=={meta['version']} --hash=sha256:{sha256}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {out} ({len(resolved)} packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
