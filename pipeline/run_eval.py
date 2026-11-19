#!/usr/bin/env python3
"""run_eval.py - batch runner for the eval corpus.

Walks a documents folder (default eval/docs/), runs the full pipeline
(classify -> map-select -> extract -> validate) on every page of every
file, and writes one JSON result per page into the results folder
(default eval/results/). Existing results are skipped unless --force,
so you can grow the corpus and re-run cheaply.

Gold sheets are NOT read here; that is score.py's job. This only produces
the pipeline half of the comparison.

Usage:
  python pipeline/run_eval.py                    # eval/docs -> eval/results
  python pipeline/run_eval.py --force             # re-run everything
  python pipeline/run_eval.py --docs C:\sample_forms --out C:\runs
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import run_page as rp  # reuse the proven plumbing: call_model, MAP_FOR_CATEGORY, validators

DOCS_DEFAULT = REPO / "eval" / "docs"
OUT_DEFAULT = REPO / "eval" / "results"
FILE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}


def iter_documents(docs: Path):
    """Yield (set_id, path, page_count) for every eval document."""
    import pymupdf

    for path in sorted(docs.rglob("*")):
        if path.suffix.lower() not in FILE_SUFFIXES or path.name.startswith("."):
            continue
        if path.name.upper().startswith("MANIFEST"):
            continue
        set_id = path.relative_to(docs).parts[0] if len(path.relative_to(docs).parts) > 1 else "_root"
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            pages = 1
        else:
            doc = pymupdf.open(str(path))
            pages = doc.page_count
            doc.close()
        yield set_id, path, pages


def run_one_page(set_id: str, path: Path, page_no: int, args, started: float) -> dict:
    img, total = rp.page_to_b64(path, page_no, args.dpi)
    classification = rp.call_model(
        rp.VISION_MODEL,
        [
            {"role": "system", "content": rp.CLASSIFY_PROMPT.read_text()},
            {"role": "user", "content": "Classify this document.", "images": [img]},
        ],
    )
    category = str(classification.get("category", "other")).strip()
    confidence = float(classification.get("confidence", 0) or 0)

    record = {
        "setId": set_id,
        "file": str(path),
        "page": page_no,
        "totalPages": total,
        "runAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsedSec": round(time.time() - started, 1),
        "classification": classification,
        "extraction": None,
        "validationIssues": [],
        "status": "classified_only",
    }

    stem = rp.MAP_FOR_CATEGORY.get(category)
    if category not in rp.MAP_FOR_CATEGORY:
        record["status"] = f"no_map:{category}"
        return record
    if category == "other" or confidence < rp.MIN_CONFIDENCE:
        record["status"] = "low_confidence:refused_extraction"
        return record

    import yaml

    field_map = yaml.safe_load((REPO / "field_maps" / f"{stem}.yaml").read_text())
    schema_hint = {f: (s or {}).get("from") or f for f, s in field_map["fields"].items()}
    user_content = (
        f"Extract the {category} fields from this image. "
        "Return JSON with exactly these keys (values or null): "
        + json.dumps(schema_hint)
        + '. Additionally include "unresolvedFields": {name: partial reading} '
        "for anything visible but illegible."
    )
    extraction = rp.call_model(
        rp.VISION_MODEL,
        [
            {"role": "system", "content": rp.EXTRACT_PROMPT.read_text()},
            {"role": "user", "content": user_content, "images": [img]},
        ],
    )
    unresolved = extraction.pop("unresolvedFields", {})
    clean, issues = rp.validate_fragment(extraction, field_map)
    record["extraction"] = {**clean, "unresolvedFields": unresolved}
    record["validationIssues"] = issues
    record["status"] = "extracted"
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default=str(DOCS_DEFAULT))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--force", action="store_true", help="re-run pages that already have results")
    args = ap.parse_args()

    docs, out = Path(args.docs), Path(args.out)
    if not docs.exists():
        print(f"docs folder missing: {docs}")
        return 2

    jobs = []
    for set_id, path, pages in iter_documents(docs):
        for p in range(1, pages + 1):
            result_path = out / set_id / f"{path.stem}__p{p}.json"
            jobs.append((set_id, path, p, result_path))

    todo = [j for j in jobs if args.force or not j[3].exists()]
    print(f"[run_eval] {len(jobs)} page(s) across {docs}; {len(jobs) - len(todo)} already done, {len(todo)} to run")
    if not todo:
        print("Nothing to do. Use --force to re-run, or add documents.")
        return 0

    summary = {}
    t0 = time.time()
    for i, (set_id, path, p, result_path) in enumerate(todo, 1):
        started = time.time()
        status = "?"
        try:
            record = run_one_page(set_id, path, p, args, started)
            status = record["status"].split(":")[0]
        except SystemExit as e:
            record = {"setId": set_id, "file": str(path), "page": p, "status": "error", "error": str(e)}
            status = "error"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(record, indent=2))
        summary[status] = summary.get(status, 0) + 1
        print(f"  [{i}/{len(todo)}] {set_id}/{path.name} p{p} -> {status} ({record.get('elapsedSec', '?')}s)")

    print(f"\n[run_eval] done in {round(time.time() - t0, 1)}s: {json.dumps(summary)}")
    print(f"[run_eval] next: python pipeline/score.py (once gold sheets exist for these sets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
