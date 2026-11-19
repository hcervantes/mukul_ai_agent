#!/usr/bin/env python3
"""run_page.py - the seed of the Phase 1 worker.

One command: rasterize a page -> classify it -> pick the field map FROM
THE CLASSIFICATION OUTPUT -> extract -> mechanically validate -> print
an assembled fragment. No form type is ever assumed (finding F5).

Behavior notes:
- Categories with no field map yet (receipt, brokerage-statement, ...) are
  classified but skipped for extraction, reported as "no map - fine".
- Categories 'other' and low-confidence classifications produce NO
  extraction at all: a mis-extraction is worse than no extraction.
- The model never computes anything; this script converts to cents and
  runs every check from the field map + schema.

Usage:
  python pipeline/run_page.py <pdf-or-png> [--page N] [--dpi N] [--json OUT]
"""

import argparse
import base64
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

REPO = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434/api/chat"
TEXT_MODEL = "qwen3:14b"
VISION_MODEL = "qwen2.5vl:7b"
NUM_CTX = 8192
DEFAULT_DPI = 150
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MIN_CONFIDENCE = 0.7

CLASSIFY_PROMPT = REPO / "prompts" / "classify.txt"
EXTRACT_PROMPT = REPO / "prompts" / "extract.txt"

EIN_RE = re.compile(r"^[0-9]{2}-[0-9]{7}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")

# classified category -> field-map file stem; categories absent here = no map (by design)
MAP_FOR_CATEGORY = {
    "W-2": "w2",
    "1099-NEC": "1099_nec",
    "1099-INT": "1099_int",
    "SSA-1099": "ssa_1099",
}


def call_model(model: str, messages: list[dict]) -> dict:
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"num_ctx": NUM_CTX},
        },
        timeout=600,
    )
    if not resp.ok:
        print(f"ERROR: Ollama {resp.status_code}: {resp.text[:300]}")
        raise SystemExit(1)
    return json.loads(resp.json()["message"]["content"])


def page_to_b64(path: Path, page_no: int | None, dpi: int):
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return base64.b64encode(path.read_bytes()).decode(), 1
    import pymupdf

    doc = pymupdf.open(str(path))
    total = doc.page_count
    idx = (page_no - 1) if page_no else 0
    if idx >= total:
        raise SystemExit(f"ERROR: --page {page_no} but file has {total} pages")
    img = base64.b64encode(doc[idx].get_pixmap(dpi=dpi).tobytes("png")).decode()
    doc.close()
    return img, total


def to_cents(v):
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v * 100
    s = str(v).replace(",", "").replace("$", "").strip()
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def validate_fragment(fragment: dict, field_map: dict):
    issues = []
    clean = {}
    validators = {
        "ein": lambda v: bool(EIN_RE.match(v)) if v else True,
        "state_code": lambda v: bool(STATE_RE.match(v)) if v else True,
    }
    for field, spec in field_map.get("fields", {}).items():
        v = fragment.get(field)
        vtype = (spec or {}).get("validate", {}).get("type")
        if vtype == "cents":
            cents = to_cents(v)
            if cents is None and v not in (None, ""):
                issues.append(f"{field}: unreadable {v!r} -> unresolved")
            elif cents is not None:
                clean[field] = cents
        elif vtype in validators:
            if v and not validators[vtype](v):
                issues.append(f"{field}: failed {vtype} ({v!r})")
            elif v:
                clean[field] = v
        elif v:
            clean[field] = v

    wages = clean.get("wages") or clean.get("amount")
    fw = clean.get("federalWithholding")
    if wages and fw and fw > 0.6 * wages:
        issues.append(f"SANITY: federalWithholding {fw} > 60% of {wages} -> unresolved (WARN)")
    state = clean.get("state")
    stw = clean.get("stateWithholding")
    if stw and not state:
        issues.append("SANITY: stateWithholding without state code -> unresolved (BLOCK)")
    stwg = clean.get("stateWages")
    if wages and stwg and stwg != wages and abs(stwg - wages) > 0.01 * wages:
        issues.append(f"SANITY: stateWages {stwg} differs from wages {wages} by >1% (misread or box substitution) -> unresolved (WARN)")
    trio = [state, stwg, stw]
    if any(trio) and not all(trio):
        issues.append("SANITY: state trio incomplete (state/stateWages/stateWithholding should be all present or all empty) -> unresolved (WARN)")
    return clean, issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--page", type=int, default=None)
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--json", default=None, help="also write the result to this path")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"missing file: {path}")
        return 2

    img, total = page_to_b64(path, args.page, args.dpi)
    where = f"page {args.page}" if args.page else path.name
    print(f"[run_page] {where} ({total} page file) | model {VISION_MODEL} | dpi {args.dpi}")

    # 1. classify
    classification = call_model(
        VISION_MODEL,
        [
            {"role": "system", "content": CLASSIFY_PROMPT.read_text()},
            {"role": "user", "content": "Classify this document.", "images": [img]},
        ],
    )
    category = str(classification.get("category", "other")).strip()
    confidence = float(classification.get("confidence", 0) or 0)
    print(f"[classify] {category} @ {confidence}")

    result = {
        "file": str(path),
        "page": args.page,
        "classifiedAt": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "extraction": None,
        "validationIssues": [],
        "status": "classified_only",
    }

    gate = None
    if category not in MAP_FOR_CATEGORY:
        gate = f"no field map for {category!r} (fine)"
    elif category == "other" or confidence < MIN_CONFIDENCE:
        gate = "low confidence or 'other': refusing to extract (no extraction beats a wrong one)"
    if gate:
        print(f"[extract] SKIPPED - {gate}")
        result["status"] = "skipped_extraction: " + gate
        print(json.dumps(result, indent=2))
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=2))
        return 0

    # 2. extract with the map chosen BY the classification
    stem = MAP_FOR_CATEGORY[category]
    field_map = yaml.safe_load((REPO / "field_maps" / f"{stem}.yaml").read_text())
    schema_hint = {f: (s or {}).get("from") or f for f, s in field_map["fields"].items()}

    user_content = (
        f"Extract the {category} fields from this image. "
        "Return JSON with exactly these keys (values or null): "
        + json.dumps(schema_hint)
        + '. Additionally include "unresolvedFields": {name: partial reading} '
        "for anything visible but illegible."
    )
    extraction = call_model(
        VISION_MODEL,
        [
            {"role": "system", "content": EXTRACT_PROMPT.read_text()},
            {"role": "user", "content": user_content, "images": [img]},
        ],
    )
    unresolved = extraction.pop("unresolvedFields", {})
    clean, issues = validate_fragment(extraction, field_map)

    result["extraction"] = {**clean, "unresolvedFields": unresolved}
    result["validationIssues"] = issues
    result["status"] = "extracted"

    print("\n--- extracted fragment (validated, cents) ---")
    print(json.dumps(result["extraction"], indent=2))
    if issues:
        print("\n--- validation issues ---")
        for line in issues:
            print(" ", line)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"\n[run_page] wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
