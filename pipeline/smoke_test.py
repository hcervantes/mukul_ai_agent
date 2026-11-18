#!/usr/bin/env python3
"""Phase 0 smoke test: document -> classify via local Ollama -> JSON.

Handling by input:
- PDF with a text layer -> classify text with the text model (qwen3:14b)
- PDF with NO text layer (a scan) -> rasterize pages with PyMuPDF,
  classify with the vision model. This mirrors the real pipeline:
  text first, vision only when text is absent.
- PNG / JPG -> vision model directly
- TXT -> text model

Usage: python pipeline/smoke_test.py <file> [--model MODEL]
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
TEXT_MODEL = "qwen3:14b"
VISION_MODEL = "qwen2.5vl:7b"  # change to a vision model from 'ollama list'
MAX_CHARS = 6000
RASTER_DPI = 150
MAX_PAGES = 4  # classification never needs more than the first pages
NUM_CTX = 16384  # rasterized pages (~3000 tokens/page) blow past the 4096 default

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

CLASSIFY_PROMPT = (
    Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"
)
MIN_TEXT_WORDS = 50  # fewer words than this in a PDF = treat as a scan


def extract_text(path: Path) -> str:
    import pymupdf

    doc = pymupdf.open(str(path))
    text = "\n".join(page.get_text() or "" for page in doc)
    doc.close()
    return text


def rasterize_pdf(path: Path) -> tuple[list[str], int]:
    """Render the first MAX_PAGES PDF pages to PNG; return (base64 list, page count)."""
    import pymupdf

    doc = pymupdf.open(str(path))
    images = []
    for page in doc[:MAX_PAGES]:
        pix = page.get_pixmap(dpi=RASTER_DPI)
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    pages = doc.page_count
    doc.close()
    return images, pages


def list_local_models() -> set[str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return set()


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
            "options": {"num_ctx": NUM_CTX},
        },
        timeout=600,
    )
    if not resp.ok:
        installed = list_local_models()
        vision_like = sorted(m for m in installed if "vl" in m or "vision" in m)
        print(f"ERROR: Ollama returned {resp.status_code}: {resp.text.strip()[:300]}")
        print(f"Installed models: {sorted(installed) or '(none)'}")
        if vision_like:
            print(f"Vision-capable candidates: {vision_like}")
            print(f"Retry with: python pipeline/smoke_test.py <file> --model {vision_like[0]}")
        raise SystemExit(1)
    return json.loads(resp.json()["message"]["content"])


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
        print(f"[smoke_test] image input -> vision model {model}")
        images = [base64.b64encode(path.read_bytes()).decode()]
        result = classify(model, "Classify this document.", images)
    elif suffix == ".txt":
        model = args.model or TEXT_MODEL
        text = path.read_text(errors="replace")[:MAX_CHARS]
        result = classify(model, text)
    else:  # PDF path
        text = extract_text(path)
        word_count = len(text.split())
        if word_count >= MIN_TEXT_WORDS:
            model = args.model or TEXT_MODEL
            print(f"[smoke_test] pdf with text layer ({word_count} words) -> text model {model}")
            result = classify(model, text[:MAX_CHARS])
        else:
            model = args.model or VISION_MODEL
            images, pages = rasterize_pdf(path)
            print(f"[smoke_test] pdf is a scan ({word_count} words, {pages} pages, sending first {len(images)}) -> vision model {model} (ctx {NUM_CTX})")
            result = classify(model, "Classify this document.", images=images)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
