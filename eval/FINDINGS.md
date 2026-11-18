# FINDINGS.md - pipeline behavior log

Dated log of what we fed the pipeline, what came back, and the root cause.
Two lines per finding is enough; this file becomes the Phase 0 write-up
and the "we test our own pipeline" demo material.

## 2026-11-18 - first end-to-end run (Windows machine, CPU, qwen2.5vl:7b)

**F1 - Multi-page scan classified as one blob -> confident "other" (0.85).**
Root cause: classification unit was the file, but a 4-page scanned package is
not a single form. Fix: classify per page. Per-page run returned 4x W-2 at
0.95. Lesson: the unit of classification is the PAGE, not the file.

**F2 - Ollama default context (4096) too small for rasterized pages
(4 pages ~= 11k tokens).** Fix: pass num_ctx explicitly. Lesson: the context
window is a production cost that Ollama will not raise on its own. Per-page
classification works comfortably at num_ctx 8192.

**F3 - Instructions page: model echoed field-map hint text back as values.**
All echoed text was rejected by validators (EIN regex, cents conversion) so
nothing entered the sheet - guardrails worked. Fix: extraction prompt rule 3
("never echo the description; if the box is absent, return null").

**F4 - Real W-2 (scan, DFAS): wages and federalWithholding extracted
correctly to the cent** (=$32,495.83 / $4,928.33; verify against paper).
State field failed validation because the model returned box 15's full
content ("OH 522886159") including the employer state ID. Fix: state hint =
two-letter code only. Note: medicareWages < ssWages is legitimate when wages
exceed the SS wage cap -> WARN, not fail.

**F5 - 1099-NEC extracted with --form W-2 produced plausible but WRONG
fields** (NEC box 1 money landed in "wages"). Not a model failure: the form
type came from the CLI flag. Lesson: in the real pipeline, classification
output feeds extraction; extraction must never assume its form type.
CLI usage until then: pass --form matching the classify step's output.

**F6 - Data hygiene reminder.** Test files contain real names/EINs/incomes.
Client data (suspected: OmniConstruction 1099-NEC package) must NOT be used
for Phase 0 per the repo rules; synthetic/generated docs replace them.
Sample docs stay in local folders, never in the repo, never in cloud agents.

**Hardware note (baseline for the box decision):** all of the above ran on
a Windows CPU machine at 7B-vision-model speed (minutes per page). The
Strix Halo rerun of this exact harness is Phase 4's headline comparison.
