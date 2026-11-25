# HANDOFF (started)

INTERNAL USE ONLY - Via Logic LLC.

This file is for whoever finishes the project on the Fed side. It is completed in story P1-13.
You have no memory of how this was built, so everything you need is meant to be in this repository.

## What works today (tested on made-up data)

- `rules.yaml` and its validator
- The quality and sizing checks, verdicts, scope filtering and the command line
- Suggestions in template mode (`python -m refiner suggest ...`) with a made-up sample context folder
- The Excel workbook (`python -m refiner workbook ...`): Summary formulas checked against an independent count, shading, comments, Approved? dropdown
- The Confluence report as HTML body sections with configurable markers (`python -m refiner confluence ...`), plus a manifest and a browser preview
- 291 tests, none of which need Jira, Confluence or Harness

## What is NOT built yet

The Confluence page generator (P1-9),
the real Jira snapshot (P1-2), the context repo step (P1-6), the pipeline (P1-10).

## Values the Fed side supplies

| Item | Goes in | Supplied by |
| --- | --- | --- |
| Jira base URL, auth, Harness connector | Config and pipeline YAML (P1-2, P1-10) | The example Jira query pipeline |
| Issue type mapping for stories, spikes, others | `rules.yaml` -> `scope.issue_types` | The Fed-side mapping |
| Field names or IDs: Acceptance Criteria, Story Points, Sprint, Epic Link, labels | Snapshot step (P1-2) | `/rest/api/2/field` output |
| Projects, boards, sprints in scope | Config (P1-2) | The team |
| Context repo path and Harness connector | Pipeline YAML (P1-6) | The program metrics repo |
| Confluence template reference, version, inputs, page ID | Pipeline YAML (P1-9) | The platform team's reporting template |
| The context repo's story-writing content, as `context/hints.yaml` plus the markdown files | `context/` folder (P1-6, P1-7) | The program metrics repo. The Fed-side assistant drafts the hints, a person confirms each one |
| Jira address, so story keys become links | `rules.yaml` -> `workbook.jira_base_url` (empty = no links) | The Fed-side Jira setup |
| Confluence marker syntax, and how the existing publisher takes the HTML body | `rules.yaml` -> `confluence.marker_start`, `marker_end`, `include_markers` | The existing publisher |
| Allowed roles in "As a..." | `rules.yaml` -> `allowed_roles` (empty = any role) | Project leads |
| Tech stack knowledge for sizing: AWS services, Harness, Nexus, Vault, OpenShift and anything else the team runs | `rules.yaml` -> `sizing.work_patterns` | Stack owners, with the Fed-side assistant drafting and a person confirming |

Nothing in the code is marked `REPLACE_` yet, because the code written so far touches no real system.
The first `REPLACE_` values appear with the snapshot and pipeline steps.

## The snapshot shape

The checks read a list of stories in the shape of `refiner/model.py` (`Story`). Turning raw Jira
JSON into that shape is the job of the snapshot step (P1-2): resolve custom field IDs by name,
map `Sprint` to a group (`current_sprint`, `future_sprints`, `backlog`), and copy the Acceptance
Criteria custom field into `acceptance_criteria`. See `fixtures/snapshot.json` for the target shape.

## About the work patterns (important)

`sizing.work_patterns` in `rules.yaml` is a **starter list of examples, not a rule**. Each pattern is a kind
of work that sounds small but usually is not, with the words that trigger it, why it is bigger, and how it
usually splits. The four starters (encrypt an existing database, upgrade a database, upgrade a cluster,
migrate data or a workload) come from general AWS knowledge and nothing more. The real value is a list that
matches the team's actual stack. When you extend it: draft patterns from the real stack, show each one to a
person to confirm, and never present a pattern as fact. A pattern only prompts a second look; it does not
decide that a story is wrong. The suggestions story (P1-7) will reuse `why_bigger` and `split_into`.

## About suggestions and hints (important)

- Suggestions are drafts. They must never add scope: words come from the story, a confirmed hint, or a work pattern.
- Acceptance criteria are suggested **only** from `hints.yaml`. If you cannot confirm a hint with a person, leave it out. A missing hint is safe (it becomes a question); a wrong hint is not.
- Draft hints from the real context repo, keep each short and plain, and mark none as final until a person has read it.
- `suggestions.ignore_when_matching` in `rules.yaml` lists everyday words ignored when finding related stories. `suggestions.action_verbs` only decides how "I want to ..." is worded. Do not merge the two lists.
- Template mode is the only mode. An AI-assisted mode needs an approved endpoint (not known yet) and a data-handling check first.

## About the workbook

- The Summary tab must stay formulas. If you add a column to Findings, update `_FINDINGS_TITLES` and the widths together in `refiner/workbook.py`; the Summary formulas find their columns by name.
- The raw tab expects `Story.extra` (a name -> text dictionary of every other Jira field). The snapshot step (P1-2) must fill it, flattening each field to text. Do not put credentials or personal data in it that is not already in Jira.
- To check formulas after a change: `python3 /path/to/recalc.py report.xlsx` (LibreOffice) and compare with the Python counts in `refiner/measures.py`. LibreOffice is only needed for this check, not to build the file.
- Keep text safe: always write cell text through `_text()` in `workbook.py`. It keeps text starting with `=` as text and removes characters Excel cannot hold.

## Compare with the existing publisher and workbook pipeline (do this before wiring)

This project was built without seeing the Fed side's existing Confluence publisher or its example pipeline that creates workbooks.
Compare them against this code, adjust the settings or the code, and note every difference.

**Confluence publisher**

1. **Marker syntax.** Is it an HTML comment, a text token or a macro? Set `confluence.marker_start` and `marker_end`, and decide `include_markers`.
2. **How the body is passed in.** A file path, standard input or a pipeline variable? This project writes `section-<id>.html` and `manifest.json`; loop over the manifest.
3. **Which HTML survives.** This code uses inline `style` on `td`, `th` and `span`. If the publisher or Confluence strips it, the numbers lose color and alignment but stay readable. Say which.
4. **Several sections in one run.** Can it replace each marker pair in turn? What happens if a marker pair is missing from the page: create it or fail?
5. **Double escaping.** The sections are already escaped. The publisher must not escape them again.
6. **Page identity and the workbook link.** Space, page ID, and where the workbook ends up (attachment, artifact, storage). Update `confluence.workbook_note` to say so.

**Workbook pipeline example**

1. Compare sheet names and the table-of-contents tab with the example. This project puts the contents tab first and links to each tab.
2. Compare where the file is saved or uploaded, and its file name pattern.
3. Compare how it sets fonts, filters, frozen headers and number formats. Keep the Summary formulas either way.
4. If the example builds its workbook a different way (for example pandas), keep this project's builder and adapt only the saving step.

## Rules for working here

- The pipeline must stay read-only. Never add code that creates or edits Jira issues.
- No real Jira text, secrets or CUI in this repository, in logs, or in test fixtures.
- Add a test for every change. Run: `python3 -m unittest discover -s tests -t .`
