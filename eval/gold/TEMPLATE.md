# Gold Facts Sheet Template

Copy this file per eval set as `eval/gold/<set_id>.json` (or draft in this
markdown and convert). The gold sheet is the FLOOR TRUTH: what a careful
human preparer would key into TaxAct, with citations, BEFORE the pipeline
ever sees the documents. It is written by hand from the source documents.

## Rules for filling
- Money: **integer cents** ($12,345.67 -> 1234567). Same convention as the schema.
- `null` means "not present on any document" (e.g., blank state boxes).
- Gold `expectedWarnings` / `expectedBlocks` describe what a CORRECT
  pipeline should flag - the harness scores unresolved-precision too.
- If a value is genuinely illegible in the source, gold records `unresolved`
  with the partial reading. The pipeline matching that is a PASS.
- Difficulty tags feed the clean/photo/illegible split in scoring.

## JSON skeleton

```json
{
  "setId": "family_01",
  "difficulty": "clean | photo | illegible",
  "source": "real-family | synthetic",
  "taxYear": 2026,
  "wageIncome": [
    {
      "employerName": "DFAS INDIANAPOLIS",
      "ein": "35-1819323",
      "wages": 3249583,
      "federalWithholding": 492833,
      "ssWages": 3249583,
      "medicareWages": 106375,
      "state": "OH",
      "stateWages": 3249583,
      "stateWithholding": 106375,
      "citations": ["w2_page_2 box 1", "w2_page_2 box 15-17"]
    }
  ],
  "otherIncome": [
    {
      "payer": "SAMPLE BLUE SKY CONSULTING INC",
      "form": "1099-NEC",
      "amount": 1480000,
      "federalWithholding": 0,
      "citations": ["nec_page_1 box 1"]
    }
  ],
  "unresolved": [
    {
      "field": "stateWages",
      "reason": "blank box 16; pipeline must NOT substitute box 12a DD",
      "expectedInRunPage": "WARN or null extraction"
    }
  ],
  "expectedWarnings": [
    "stateWages null while stateWithholding present -> trio WARN expected"
  ],
  "expectedBlocks": [],
  "notes": "Adversarial sample: DD amount $6,800 sits where models hunt."
}
```

## Which sets get a gold sheet?

Every set in `eval/docs/` once its documents are final. A set without gold
is unmeasured; scoring skips it with a warning rather than guessing.
