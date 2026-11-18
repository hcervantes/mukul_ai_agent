#!/usr/bin/env python3
"""Phase 0 smoke test: PDF -> text -> classify via local Ollama -> JSON.

Proves the harness runs end to end on day 1 so Ollama/driver issues
surface now, not in week 3. Not production code.

Usage: python pipeline/smoke_test.py <pdf-or-txt-file>
"""

import json
import sys
import requests
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:14b"
MAX_CHARS = 6000

CLASSIFY_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    else:
        text = path.read_text(errors="replace")
    return text[:MAX_CHARS]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_test.py <pdf-or-txt-file>")
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"missing file: {path}")
        return 2

    text = extract_text(path)
    if not text.strip():
        print("ERROR: no text layer extracted (vision model fallback not built yet)")
        return 1

    prompt = CLASSIFY_PROMPT.read_text()
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "format": "json",
        },
        timeout=300,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        print(f"MODEL DID NOT RETURN JSON:\n{content}")
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
