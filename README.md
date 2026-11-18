# mukul_ai_agent

Local AI worker for BGC Tax Preparers: watches client documents in the portal pipeline, extracts tax facts, merges bookkeeping data, and emits a per-client **Tax Facts Sheet** the preparer keys into TaxAct.

See `Documenation/intake_facts_agent_build_guide.md` in [bgc_project](https://github.com/hcervantes/bgc_project) for the full build guide.

## Status: Phase 0 (schema + field maps + eval harness)

| Phase | Scope | Status |
|---|---|---|
| 0 | Schema, field maps, eval set, scoring harness | **in progress** |
| 1 | Extraction pipeline (poll → classify → extract → validate → store) | not started |
| 2 | Books + mileage merge via bgc-api | not started |
| 3 | Facts-sheet rendering + staff UI badge | not started |
| 4 | gpt-oss 120B review notes + full eval pass (needs Strix Halo box) | blocked on hardware |

## Repo layout

```
schema/       facts_sheet.v1.json - JSON Schema, money in integer cents
field_maps/   per-form extraction maps (box number -> schema path + validation)
prompts/      classify / extract prompts (rarely change; field maps do)
pipeline/     code: poller, extraction, validation, assembly
eval/docs/    eval document sets (LOCAL ONLY - never commit real client data)
eval/gold/    gold-standard facts sheets, built manually
eval/score.py scoring harness; any change must pass this before it is trusted
```

## Quick start (Phase 0 smoke test)

Requirements: Python 3.11+, [Ollama](https://ollama.com) with `qwen3:14b`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3:14b
python pipeline/smoke_test.py eval/docs/<some_file>.pdf
```

## Hard rules

- **No full SSNs anywhere in this repo, ever.** Eval docs are sanitized to last-4 (or 0 digits for dependents) before entering `eval/docs/`.
- **No real BGC client data in Phase 0**, even sanitized: use personal/family returns and synthetic docs only.
- The agent is a draft generator. The preparer reviews and signs; nothing writes to TaxAct.
- Every extracted figure must carry a source citation (doc id + page). If the model cannot see it, it goes to `unresolved`, never guessed.
- `eval/docs/` contents are gitignored by default; flip that consciously and never in this phase.
