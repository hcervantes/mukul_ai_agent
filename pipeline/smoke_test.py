#!/usr/bin/env python3
"""Phase 0 smoke test: document -> classify via local Ollama -> JSON.

Handles two input kinds:
- PDF / TXT: extract the text layer, classify with the text model (qwen3:14b)
- PNG / JPG / JPEG: image-only documents, classify with a VISION model
  (e.g. qwen2.5vl or qwen3-vl; must be pulled separately via ollama pull)

Proves the harness runs end to end on day 1 so Ollama/driver issues
surface now, not in week 3. Not production code.

Usage: python pipeline/smoke_test.py <pdf|png|jpg|txt-file> [--model MODEL]
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
TEXT_MODEL = "qwen3:14b"
VISION_MODEL = "qwen2.5vl:7b"  # change to your pulled vision model if different
MAX_CHARS = 6000

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

CLASSIFY_PROMPT = (
    Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"
)


def extract_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text[:MAX_CHARS]


def classify(model: str, user_content, images=None) -> dict:
    message = {"role": "user", "content": user_content}
    if images:
        message["images"] = images
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": CLASSIFY_PROMPT.read_text()},
                message,
            ],
            "stream": False,
            "format": "json",
        },
        timeout=600,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return json.loads(content)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--model", default=None, help="override the model choice")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"missing file: {path}")
        return 2

    suffix = path.suffix.lower()

    if suffix in IMAGE_SUFFIXES:
        model = args.model or VISION_MODEL
        print(f"[smoke_test] image input -> using vision model {model}")
        images = [base64.b64encode(path.read_bytes()).decode()]
        try:
            result = classify(model, "Classify this document.", images)
        except requests.HTTPError as e:
            print(f"ERROR: Ollama rejected the call: {e}")
            print(f"Is the vision model pulled? Try:  ollama pull {model}")
            return 1
    elif suffix == ".txt":
        model = args.model or TEXT_MODEL
        text = path.read_text(errors="replace")[:MAX_CHARS]
        result = classify(model, text)
    else:  # default: treat as PDF
        model = args.model or TEXT_MODEL
        print(f"[smoke_test] pdf input -> using text model {model}")
        text = extract_text(path)
        if not text.strip():
            print(
                "ERROR: no text layer extracted (use a PNG/JPG to test the "
                "vision path, or run through print-to-PDF first)"
            )
            return 1
        result = classify(model, text)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
