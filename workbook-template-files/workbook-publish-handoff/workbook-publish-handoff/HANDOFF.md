# HANDOFF: "workbook-publish" Harness step template (v1.1.0)

**Internal use only: Via Logic LLC.** Written 2026-11-25 for the AI taking over. Assume you remember nothing from the
previous conversation. Everything you need is here or in the files next to this one.

## 0. State in five lines
- Deliverable = **two Harness step templates**, one YAML each: `templates/workbook-publish-template-cd-custom.yaml`
  (ShellScript step for CD/Custom stages) and `templates/workbook-publish-template-ci-build.yaml` (Run step for CI stages).
- They turn files the pipeline already produced (CSV, TSV, TXT, HTML, or `s3://`) into one Excel workbook:
  **Overview** tab, **Table of Contents** tab (clickable), then one tab per input table. Tab name = file name minus extension.
- All the logic is an inline bash + Python block inside each YAML. The two blocks are byte-identical. No other runtime files.
- Everything the user asked for is implemented and passes `maintainer/verify_templates.py` (96/96 checks) **in a sandbox**.
- **Never run inside real Harness yet.** First job for you or the user: import both templates and run one pipeline (section 9).

## 1. The user, and how to read their messages
- Messages are **dictated** (speech-to-text): typos and slips are normal. "harness" = **Harness.io** (the CI/CD platform), not
  a test harness. "You don't know your own system" meant *our* system: don't assume how their pipeline works.
- They want the AI to "think hard" and not produce "slop". They **dislike heavy footprints** (many scripts/files spread around).
  My first attempt (a Python engine + manifest + tests + zip) was rejected for exactly that. Do not rebuild it.
- They like **sensible defaults** and do not want to be prompted for every option.
- Earlier work for them (same conventions, reuse them): a send-email step-template pair (CD ShellScript + CI Run), a New Relic
  deployment-marker template, and a "harness-audit" scanner. Chats: claude.ai/chat/736e39f0-d2ed-43cb-be6a-b701e260dd75 (send-email),
  claude.ai/chat/96eb4680-0dbf-4edf-aae4-9eab28e7ceb6 (template inventory). Conventions seen there: account-scope templates,
  `type: Step`, inputs as `<+input>` / `<+input>.default("...")`, auto-filled pipeline metadata (`<+pipeline.name>`,
  `<+pipeline.sequenceId>`, `<+pipeline.executionUrl>`, `<+pipeline.triggeredBy.name>`), a header comment with a usage example.

## 2. Org rules that apply (from Via Logic admin instructions)
Connected accounts must be `vialogicllc.com` corporate accounts. Artifacts/documents are internal only, never public. No
third-party sites/services beyond what the admin approved. The templates add an "INTERNAL USE ONLY: Via Logic LLC" banner and make
no network calls except the `s3://` reads the user lists. Never put credentials in inputs.

## 3. Requirements, in the user's words, and where each lives
| # | Ask | Status | Where |
|---|---|---|---|
| R1 | Combine artifacts from S3 / pipeline CSVs into an Excel-compatible `.xlsx` | Done | whole script; S3 via `aws s3 cp` |
| R2 | Tab names = file names without extension | Done | `tab_for()`; `.csv .tsv .txt .html .htm` |
| R3 | Table of contents tab: generated date stamp, purpose, "any HTML", every page with links + what it is for; manual additions possible | Done | Overview + TOC; `WB_NOTES` (text/HTML/`@file`); `manual:` lines in `WB_FILES` |
| R4 | "Give the latest proper MCP server, latest capabilities, the right version" | **Unresolved**. My reading was "keep versions visible and pinned". The first design had a preflight and `min_versions`; the lean rewrite dropped them. Overview now prints template version, Python and openpyxl versions only | ask the user what they meant |
| R5 | Light footprint: one YAML step with bash/python sections, inputs direct, don't assume their system | Done | two YAMLs, inputs are step env vars |
| R6 | Overview tab that explains things + TOC tab with hyperlinks and short explanations | Done | `Overview`, `Table of Contents` |
| R7 | Accept CSV, HTML, possibly TXT | Done | HTML tables -> tabs; table-less HTML or plain TXT -> one tab of lines; tab-delimited TXT -> columns |
| R8 | Frozen top row, sortable + filterable columns, distinct heading (dark blue, bold white) | Done, defaults ON | `freeze_rows`, `filter`, `header_*` |
| R9 | Adjustable with defaults, not prompted for all the goodies, a "switch" | Done | one optional input `WB_OPTIONS`; empty = defaults |
| R10 | Highlight cells by value: greater, less, equal to a number or string, with examples built in | Done | `highlight:` lines; examples in each header comment |
| R11 | Keep script minimal, inside the harness YAML | Mostly: ~390 lines of Python inside each YAML. Tell the user honestly if they ask | see section 7 |

## 4. Files
```
HANDOFF.md                         this file
templates/                         THE DELIVERABLES (also copied to /mnt/user-data/outputs in the original chat)
  workbook-publish-template-cd-custom.yaml    Harness ShellScript step (Bash, runs on delegate)
  workbook-publish-template-ci-build.yaml     Harness Run step (Sh = POSIX, CI stage)
maintainer/                        tooling for you, NOT part of what gets deployed
  body.sh                          SINGLE SOURCE OF TRUTH for the script (bash wrapper + inline Python)
  build_yaml.py                    regenerates both YAMLs from body.sh (header docs + input list live here)
  verify_templates.py              regression suite (96 checks, no Harness/network needed)
```
Old files from the first, rejected design may still sit in the user's outputs folder (`workbook-publish.zip`,
`publish_workbook.py`, `SKILL.md`, `manifest.example.yaml`). They are **superseded**. Ignore them.

## 5. Contract
Inputs (Harness step env vars). Required runtime inputs `<+input>`: `WB_TITLE`, `WB_PURPOSE`, `WB_FILES`. Optional (default
`""` unless noted): `WB_NOTES` (text/HTML, or `@path` to a file), `WB_OPTIONS`, `WB_OUTPUT` (`workbook.xlsx`), `WB_TZ` (`UTC`).
Auto-filled: `PIPELINE_NAME`, `PIPELINE_BUILD_NUMBER`, `PIPELINE_EXECUTION_URL`, `TRIGGERED_BY`. Note: the script also reads
`WB_CLASSIFICATION` (banner text) if set, but **neither template declares it as an input**, so Harness cannot set it until someone
adds it to the env list (and to `INPUTS` in `build_yaml.py`).

`WB_FILES`, one per line: `path-or-s3-uri | what the tab is used for`. `manual: Tab name | description` lists a tab a person
adds later (linked once it exists). Lines starting `#` are ignored.

`WB_OPTIONS`, one per line, `#` comments. Keys (defaults): `font=Arial`, `font_size=10`, `header_fill=1F3864`, `header_font=FFFFFF`,
`header_bold=on`, `freeze_rows=1`, `freeze_cols=0`, `filter=on`, `max_col_width=60`, `date_format=yyyy-mm-dd`.
Highlight: `highlight: tab | column | operator | value | colour`. Operators `> < >= <= = != contains`; colour = `red yellow
green blue orange gray` or a 6-digit hex; tab may be `*`; column = heading name or letter. Bad lines **warn and continue**.

Output: step output variable `WORKBOOK_PATH` (absolute path). CD: `outputVariables: [{name,type,value: WORKBOOK_PATH}]`, read as
`<+execution.steps.STEP_ID.output.outputVariables.WORKBOOK_PATH>`. CI: `outputVariables: [{name: WORKBOOK_PATH}]`, read as
`<+steps.STEP_ID.output.outputVariables.WORKBOOK_PATH>` (both forms confirmed in Harness docs). Exit non-zero with `ERROR: ...` on bad input.

## 6. Design decisions (and why)
- **Inputs are the step's own env vars; no manifest file.** Matches the user's existing templates and the "inputs almost directly" ask.
- **It only publishes.** No fetching beyond `s3://`, no transforms. Their earlier pipeline steps already produce files. A transform
  belongs in a step before this one.
- **One optional `WB_OPTIONS` box is the "switch".** Empty = defaults and no extra prompt. Harness has no native "show advanced inputs"
  toggle for step templates, so this is the closest honest equivalent. Tip in the header: keep a house style in a pipeline variable
  and pass `<+pipeline.variables.WB_STYLE>`.
- **Same script in both YAMLs**, because Harness splits step types by stage kind (ShellScript for CD/Custom, Run for CI). The script is
  POSIX-sh compatible so it can run under `shell: Sh`; the Python sits in a quoted heredoc (`<<'PY'`) so the shell never expands it.
- **Highlights are native Excel conditional formatting** (live, survive edits), built as formulas: numbers use `AND(ISNUMBER(x), x>n)`
  so blanks and text never match by accident (in Excel text sorts above numbers and blank counts as 0, a classic trap).
- **Overview is tab 1, Table of Contents tab 2.** The user first said "table of contents as the first tab", later asked for both.
  Confirm the order if it matters to them.
- TOC row/column counts are a **snapshot** (static values), deliberately: formulas would need a recalculation pass.

## 7. Where the size is, if the user wants less script
383 Python lines (plus ~10 lines of bash wrapper), measured: Overview + Table of Contents build 115; per-tab loop (styling, freeze,
filter, applying highlights) 70; options/defaults/rule parsing and validation 42; HTML table parser 35; file loading + notes
flattening + rule formulas 31; value conversion 19; saving + self-check 14; the rest is inputs and small helpers.
Highlight rules cost about 35 lines spread over three places; HTML support about 45. Cheapest cuts, in that order: highlight rules,
HTML support, the Overview "how to use" tips.

## 8. Verification status (2026-11-25, sandbox: Python 3.12.3, openpyxl 3.1.5, PyYAML 6.0.3, LibreOffice render)
**Verified**
- Both YAMLs parse; embedded scripts identical; no `<+` inside the script; `sh -n`/`dash -n`/`bash -n` clean.
- Ran the CD script under bash and the CI script under dash against fixtures: defaults, options/rules, TSV/TXT/HTML (multi-table and
  table-less), S3 via a fake `aws`, manual rows, name clashes with the front tabs, 8 failure paths (all exit non-zero with a clear message).
- The usage example inside each header comment parses as YAML and runs as written; the documented option block pastes back with no warnings.
- Workbooks rendered through LibreOffice and inspected by eye (front tabs, heading style, highlight colours, one-page-wide print).
- The regression suite catches real breakage: 13 deliberate sabotages (frozen header removed, filter removed, numeric guard dropped,
  `=` text turned into a formula, version drift, header typo, ...) were each caught by the expected check.
- Speed/memory (this script): 300,000 rows x 8 columns ~ 30 s, ~975 MB RAM, 14 MB file.

**NOT verified. Do not claim these**
- Importing/running in **real Harness** (template schema acceptance, `executionTarget: {}`, multi-line runtime inputs in the UI,
  `.default("")` behaviour, output-variable hand-off to the next step).
- **Real S3**: only a stub `aws` was used. The `aws` CLI and read access must exist where the step runs.
- Opening in **desktop Excel** (checked in LibreOffice only; the features used are standard OOXML).
- The auto `pip install openpyxl` fallback (no network in the sandbox). Real HTML/TXT files from the user's actual sources.
- Inputs above ~1M rows are rejected by design (Excel limit); 300k was the largest tested.

## 9. Do these next (priority order)
1. Ask the user which stage types they use (CD/Custom, CI, or both); delete the unused template.
2. Import the template into Harness (account scope; adjust `templateRef` prefix), run once with the header's usage example against
   a real pipeline's files. Check: step passes, `WORKBOOK_PATH` reaches a later step (e.g. their send-email template's attachment input).
3. Open the result in Excel: filters, frozen header, highlights, links, print preview.
4. Resolve **R4** (the "latest MCP server / capabilities / right version" ask) by asking, not guessing.
5. Confirm the Overview-before-Table-of-Contents order and that "limit in columns" meant filter arrows (my reading).
6. Ideas the user has NOT asked for, offer only if wanted: per-tab options, whole-row highlighting, `between` operator, XLSX/Parquet
   inputs, back-links on each tab, per-column number formats, an upload/publish step.

## 10. How to change anything safely
```bash
cd maintainer
# 1. edit body.sh (script) and/or build_yaml.py (header docs, inputs). Bump VER in build_yaml.py AND VERSION at top of body.sh for a release.
python build_yaml.py          # regenerates both YAMLs (refuses if the two version strings differ)
python verify_templates.py    # must end with "N/N checks passed"; add a check for every new feature
python verify_templates.py --keep   # optional: keeps the temp folder with generated .xlsx files to open and eyeball
```
Visual check: `soffice --headless --convert-to pdf file.xlsx` then `pdftoppm -r 80 -png file.pdf page`.
Needs only PyYAML, openpyxl, bash, dash/sh.

## 11. Gotchas (all learned the hard way)
- **Harness resolves `<+...>` anywhere in script text.** Keep that sequence out of the script (checked automatically).
- CI `Run` with `shell: Sh` is POSIX sh: no bash-only syntax in the wrapper. Output vars need `export NAME=...` plus a declared output.
- Files only exist where the step ran: the next step must share the CI workspace or the same delegate (add a delegate selector).
- openpyxl traps handled in the script: strings starting `=` become formulas (forced to text), NaN/inf/control characters corrupt
  files, tab names (31 chars, `[]:*?/\`, unique, not "History"), date cells need an explicit format, dxf fills need start+end colour.
- The script sets `wb._fonts` (openpyxl **private API**, works on 3.1.5) to make Arial the workbook default. If a future openpyxl
  breaks it, switch to per-cell fonts; the verify suite will fail on the heading-font check.
- HTML numbers like `1,200` are converted; `02134` and ids over 15 digits stay text; `<br>` inside a cell becomes a space.
- Row heights on wrapped Overview/TOC text are estimated (`fit()`); extreme text lengths may clip slightly.
- Sandbox notes: no network (cannot `pip install`), files outside `/mnt/user-data/outputs` can vanish between turns.

## 12. Please don't
Re-introduce a manifest/engine/package; claim Harness or Excel testing that did not happen; add prompts for every option;
publish the workbook or templates anywhere public; use a non-corporate account.
