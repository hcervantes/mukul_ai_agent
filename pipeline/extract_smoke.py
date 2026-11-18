#!/usr/bin/env python3
"""Extraction smoke test: one classified document page -> facts-sheet fragment.

Pipeline: load field map (YAML) -> build fill-in schema for the model ->
vision model extracts a single page -> mechanical validation (cents
conversion, EIN regex, sanity rules) -> print fragment + validation report.

The model NEVER does arithmetic or validation. It fills the schema;
this script converts, checks, and flags. Anything the model cannot read
must land in unresolvedFields.

Usage:
  python pipeline/extract_smoke.py <pdf-or-png> [--page N] [--form W-2] [--dpi N]
"""

import argparse
import base64
import json
import re
import sys
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

EXTRACT_PROMPT = REPO / "prompts" / "extract.txt"

EIN_RE = re.compile(r"^[0-9]{2}-[0-9]{7}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")


def check_ein(v):
    return bool(EIN_RE.match(v)) if v else True


def check_state_code(v):
    return bool(STATE_RE.match(v)) if v else True


FORM_ALIASES = {
    # --form value (lowercased) -> field-map file stem
    "w-2": "w2",
    "w2": "w2",
    "1099-nec": "1099_nec",
    "1099nec": "1099_nec",
    "1099-int": "1099_int",
    "1099int": "1099_int",
    "ssa-1099": "ssa_1099",
    "ssa1099": "ssa_1099",
}


def load_field_map(form: str) -> dict:
    key = form.lower().strip()
    stem = FORM_ALIASES.get(key, key.replace(" ", "_").replace("-", "_"))
    path = REPO / "field_maps" / f"{stem}.yaml"
    if not path.exists():
        forms = sorted(p.stem for p in (REPO / "field_maps").glob("*.yaml"))
        raise SystemExit(f"ERROR: no field map for {form!r}. Available: {forms}")
    return yaml.safe_load(path.read_text())


def page_to_b64(path: Path, page_no: int | None, dpi: int) -> tuple[str, int]:
    """Return (base64 image, total pages). page_no is 1-based."""
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return base64.b64encode(path.read_bytes()).decode(), 1
    import pymupdf

    doc = pymupdf.open(str(path))
    total = doc.page_count
    idx = (page_no - 1) if page_no else 0
    if idx >= total:
        raise SystemExit(f"ERROR: --page {page_no} but the file has {total} pages")
    img = base64.b64encode(doc[idx].get_pixmap(dpi=dpi).tobytes("png")).decode()
    doc.close()
    return img, total


def to_cents(v):
    """Model returns dollars ('43500.00' or 43500.0). Convert to integer cents."""
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v * 100
    s = str(v).replace(",", "").replace("$", "").strip()
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None  # unreadable -> unresolved, never guessed


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


def validate_fragment(fragment: dict, field_map: dict) -> tuple[dict, list[str]]:
    """Convert + mechanically validate. Returns (clean fragment, issues)."""
    issues = []
    clean = {}
    validators = {"ein": check_ein, "state_code": check_state_code}

    for field, spec in field_map.get("fields", {}).items():
        v = fragment.get(field)
        vtype = (spec or {}).get("validate", {}).get("type")
        if vtype == "cents":
            cents = to_cents(v)
            if cents is None and v not in (None, ""):
                issues.append(f"{field}: unreadable value {v!r} -> unresolved")
            elif cents is not None:
                clean[field] = cents
        elif vtype in validators:
            if v and not validators[vtype](v):
                issues.append(f"{field}: failed {vtype} validation ({v!r})")
            elif v:
                clean[field] = v
        elif v:
            clean[field] = v

    # sanity rules wired in the field map
    wages = clean.get("wages")
    fw = clean.get("federalWithholding")
    if wages and fw and fw > 0.6 * wages:
        issues.append(f"SANITY: federalWithholding {fw} cents > 60% of wages {wages} -> unresolved (WARN)")
    mw = clean.get("medicareWages")
    sw = clean.get("ssWages")
    if mw is not None and sw is not None and mw < sw:
        issues.append(f"SANITY: medicareWages {mw} < ssWages {sw} -> unresolved (WARN)")
    state = clean.get("state")
    stw = clean.get("stateWithholding")
    if stw and not state:
        issues.append("SANITY: stateWithholding present but no state code -> unresolved (BLOCK)")
    return clean, issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--page", type=int, default=None, help="1-based page number in a scanned PDF")
    ap.add_argument("--form", default="W-2")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"missing file: {path}")
        return 2

    field_map = load_field_map(args.form)
    schema_for_model = {
        field: (spec or {}).get("from") or field
        for field, spec in field_map.get("fields", {}).items()
    }

    img, total = page_to_b64(path, args.page, args.dpi)
    page_desc = f"page {args.page} of {total}" if args.page or total > 1 else "single page"

    print(f"[extract] {args.form} from {page_desc} | model {VISION_MODEL} | ctx {NUM_CTX}")

    user_content = (
        f"Extract the {args.form} fields from this image. "
        "Return JSON with exactly these keys (values or null): "
        + json.dumps(schema_for_model)
        + '. Additionally include "unresolvedFields": {name: partial reading} '
        "for anything visible but illegible."
    )
    result = call_model(
        VISION_MODEL,
        [
            {"role": "system", "content": EXTRACT_PROMPT.read_text()},
            {"role": "user", "content": user_content, "images": [img]},
        ],
    )

    unresolved = result.pop("unresolvedFields", {})
    clean, issues = validate_fragment(result, field_map)

    print("\n--- extracted fragment (validated, cents) ---")
    print(json.dumps({**clean, "unresolvedFields": unresolved}, indent=2))
    if issues:
        print("\n--- validation issues ---")
        for line in issues:
            print(" ", line)
    if unresolved:
        print("\n(illegible fields went to unresolved, as designed - never guessed)")
    print("\n--- acceptance check ---")
    print("Compare wages + federalWithholding against the paper/scan BY EYE before trusting this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
