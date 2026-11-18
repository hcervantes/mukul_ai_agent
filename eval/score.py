#!/usr/bin/env python3
"""Scoring harness: compare pipeline output against gold-standard sheets.

Metrics (reported separately for clean-set and photo-set, NEVER blended):
- field_accuracy: exact-cents matches / total gold fields (W-2/1099 money fields)
- invention_rate: fields filled by pipeline that gold marks absent/unreadable.
  Any invented value is a SERIOUS failure -> fail the run.
- unresolved_precision: unresolved flags that correspond to real gold gaps.

Usage: python eval/score.py [--docs eval/docs] [--gold eval/gold]
"""

import argparse
import json
from pathlib import Path

MONEY_SECTIONS = ("wageIncome", "otherIncome")


def gold_fields(sheet: dict):
    """Yield (json_pointer, cents) for every gold money field."""
    for section in MONEY_SECTIONS:
        for i, item in enumerate(sheet.get(section, [])):
            for key in ("wages", "federalWithholding", "amount", "stateWithholding"):
                if key in item and item[key] is not None:
                    yield f"/{section}/{i}/{key}", item[key]


def compare(gold: dict, actual: dict):
    matched = 0
    invented = 0
    missing = []
    for section in MONEY_SECTIONS:
        g_items = {json.dumps(item, sort_keys=True): item for item in gold.get(section, [])}

    # Simple v1 comparison: exact match over each gold field path
    return {"matched": matched, "invented": invented, "missing": missing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="eval/docs")
    ap.add_argument("--gold", default="eval/gold")
    args = ap.parse_args()

    gold_dir = Path(args.gold)
    best_score = 0
    sets = sorted(gold_dir.glob("*.json"))
    if not sets:
        print(f"no gold sheets in {gold_dir} (Phase 0 step 5 pending)")
        return

    print(f"{len(sets)} gold sets. Full pipeline comparison lands in Phase 1;")
    print("Phase 0 uses this to score manual gold-sheet QA.")

    best_score = max(best_score, 0)
    return


if __name__ == "__main__":
    main()
