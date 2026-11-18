# Phase 0 checklist

## Step 1 - Harness (day 1-2)
- [ ] Repo cloned, venv, `pip install -r requirements.txt`
- [ ] Ollama installed, `qwen3:14b` pulled
- [ ] `python pipeline/smoke_test.py <file>` returns classified JSON

## Step 2 - Schema (day 2-4)
- [ ] `schema/facts_sheet.v1.json` reviewed by preparer
- [ ] Decision: cents confirmed for all money fields
- [ ] Decision: multi-state withholding shape (state field present) - confirm BGC's states

## Step 3 - Field maps (day 4-6)
- [ ] w2.yaml reviewed against a real W-2
- [ ] 1099_nec.yaml, 1099_int.yaml, ssa_1099.yaml reviewed
- [ ] Add 1098.yaml and 1099_div.yaml when sample docs exist
- [ ] sanity rules reviewed by preparer (60% withholding cap, medicare >= ss)

## Step 4 - Eval set (day 6-9)
- [ ] 20-30 sets collected from personal/family returns, NO BGC client data
- [ ] Every SSN sanitized to last-4; dependent SSNs removed entirely
- [ ] Mix: ~15 clean PDFs, ~5 phone photos/scans, ~2 partially illegible, >=3 multi-employer
- [ ] Kept OUT of git (gitignored); stored locally only
- [ ] Sets labeled by difficulty: clean vs photo

## Step 5 - Gold sheets (day 10-13)
- [ ] Per-set gold facts sheet written with citations for every figure
- [ ] Intended unresolved/missing items recorded in gold

## Step 6 - Scoring harness (day 13-14)
- [ ] `eval/score.py` runs end to end
- [ ] Invention rate metric wired (any invented value = run failure)

## Step 7 - Baseline + write-up (day 14)
- [ ] Baseline run with qwen3:14b recorded
- [ ] `eval/PHASE0_RESULTS.md` written: clean-set accuracy, photo-set accuracy, latency
- [ ] Go/no-go decision for Phase 1 recorded
