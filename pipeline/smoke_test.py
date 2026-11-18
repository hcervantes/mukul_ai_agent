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
VISION_MODEL = "qwen2.5vl:7b"  # change to your pulled vision model if different
MAX_CHARS = 6000
RASTER_DPI = 150

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

CLASSIFY_PROMPT = (
    Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"
)
MIN_TEXT_WORDS = 50  # fewer words than this in a PDF = treat as a scan


def extract_text(path: Path) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    text = "\n".join(page.get_text() or "" for page in doc)
    doc.close()
    return text


def rasterize_pdf(path: Path) -> list[str]:
    """Render each PDF page to a PNG, return base64 strings."""
    import fitz
    import io

    doc = fitz.open(str(path))
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=RASTER_DPI)
        png_bytes = pix.tobytes("png")
        images.append(base64.b64encode(png_bytes).decode())
    doc.close()
    return images


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

    try:
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
                pages = rasterize_pdf(path)
                print(f"[smoke_test] pdf is a scan ({word_count} words) -> rasterized {len(pages)} page(s) -> vision model {model}")
                result = classify(model, "Classify this document.", images=pages)
    except requests.HTTPError as e:
        print(f"ERROR: Ollama rejected the call: {e}")
        print("Is the model pulled? ollama pull <model>")
        return 1
    except ImportError:
        print("ERROR: PyMuPDF missing. Run: pip install pymupdf")
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
