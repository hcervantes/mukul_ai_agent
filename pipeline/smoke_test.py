#!/usr/bin/env python3
"""Phase 0 smoke test: document -> classify via local Ollama -> JSON.

Inputs and behavior:
- PDF with text layer -> text model classifies the whole file
- PDF scan with ONE page -> vision model on that page
- PDF scan with MULTIPLE pages -> vision model classifies EACH page
  separately and reports per-page results. Clients upload packages,
  not clean single-form PDFs, so classification is per page.
- PNG / JPG -> vision model directly; TXT -> text model.

Usage: python pipeline/smoke_test.py <file> [--model MODEL] [--dpi N]
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
TEXT_MODEL = "qwen3:14b"
VISION_MODEL = "qwen2.5vl:7b"
MAX_CHARS = 6000
DEFAULT_DPI = 150
NUM_CTX = 8192  # per-page classification needs far less than multi-page

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

CLASSIFY_PROMPT = (
    Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"
)
MIN_TEXT_WORDS = 50


def extract_text(path: Path) -> str:
    import pymupdf

    doc = pymupdf.open(str(path))
    text = "\n".join(page.get_text() or "" for page in doc)
    doc.close()
    return text


def rasterize_pages(path: Path, dpi: int) -> list[str]:
    import pymupdf

    doc = pymupdf.open(str(path))
    images = [
        base64.b64encode(page.get_pixmap(dpi=dpi).tobytes("png")).decode()
        for page in doc
    ]
    doc.close()
    return images


def list_local_models() -> set[str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return set()


def classify(model: str, user_content, images=None, label: str = "") -> dict:
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
            "options": {"num_ctx": NUM_CTX},
        },
        timeout=600,
    )
    if not resp.ok:
        installed = list_local_models()
        print(f"ERROR: Ollama returned {resp.status_code}: {resp.text[:300]}")
        print(f"Installed models: {sorted(installed) or '(none)'}")
        raise SystemExit(1)
    result = json.loads(resp.json()["message"]["content"])
    if label:
        print(f"  {label}: {json.dumps(result)}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--model", default=None)
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"missing file: {path}")
        return 2

    suffix = path.suffix.lower()

    if suffix in IMAGE_SUFFIXES:
        model = args.model or VISION_MODEL
        print(f"[smoke_test] image -> {model}")
        images = [base64.b64encode(path.read_bytes()).decode()]
        result = classify(model, "Classify this document.", images)
        print(json.dumps(result, indent=2))
        return 0

    if suffix == ".txt":
        model = args.model or TEXT_MODEL
        print(f"[smoke_test] txt -> {model}")
        result = classify(model, path.read_text(errors="replace")[:MAX_CHARS])
        print(json.dumps(result, indent=2))
        return 0

    # PDF
    text = extract_text(path)
    word_count = len(text.split())
    if word_count >= MIN_TEXT_WORDS:
        model = args.model or TEXT_MODEL
        print(f"[smoke_test] pdf text layer ({word_count} words) -> {model}")
        result = classify(model, text[:MAX_CHARS])
        print(json.dumps(result, indent=2))
        return 0

    model = args.model or VISION_MODEL
    images = rasterize_pages(path, args.dpi)
    print(f"[smoke_test] pdf scan; classifying each of {len(images)} page(s) with {model} (dpi {args.dpi}, ctx {NUM_CTX})")
    results = []
    for i, img in enumerate(images, 1):
        result = classify(
            model,
            f"Classify this document. It is page {i} of a multi-page scan.",
            images=[img],
            label=f"page {i}",
        )
        results.append({"page": i, **result})
    cats = [r.get("category") for r in results]
    print("\nSummary:", json.dumps(cats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
