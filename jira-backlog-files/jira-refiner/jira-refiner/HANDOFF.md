# HANDOFF

INTERNAL USE ONLY - Via Logic LLC.

This file is for whoever finishes the project on the Fed side. You have no memory of how it was built, so everything
you need is meant to be in this repository. Read README.md first for what the tool does.

**Start here:** run `python -m refiner doctor`, then work down `FED_SIDE_NEEDS.md` with a person until doctor shows no
FAIL or TODO lines. `KICKOFF_PROMPT.md` is the prompt to give the assistant; `RUNBOOK.md` is for the people using the reports.
**The report should run every week, the working day before team refinement.**

## What works today (tested on made-up data, 515 tests, none need Jira, Confluence or Harness)

- The rules file and its validator: every setting checked, every problem reported with its line number.
- Per-story checks: titles, descriptions, acceptance criteria (with a "brief" tier), points, epics, labels, sizing.
- Cross-story analysis: duplicates and related stories, finished or ended epics, best-fit epics, new-epic ideas, themes.
- Stories planned for upload (not in Jira yet) from the snapshot's `intake` list or a CSV (`--intake`).
- Suggestions in template mode (no AI), the change list, `changes.csv`, the HTML update pack, the workbook
  (formulas checked against an independent count with LibreOffice), and the Confluence sections.
- One command for a pipeline: `python -m refiner report ... --out-dir <folder>`.
- `python -m refiner snapshot`: saved Jira exports (one file each for current sprint, upcoming sprints, backlog, epics)
  -> the snapshot, through `jira_fields.yaml`. Handles old and new sprint formats and Agile API epic objects.
- `python -m refiner doctor`: fails while any `REPLACE_` value is left, lists starter examples still in use, and prints a
  counts-only snapshot shape with warnings for likely field-mapping mistakes.
- `pipeline/`: a Harness pipeline sketch and a weekly trigger sketch, with `REPLACE_` values to align with the real examples.

## What is NOT built yet

| Story | What | Why not |
| --- | --- | --- |
| P1-1 | Probe of Jira access and the field list | Needs the real Jira |
| P1-2 | The Jira EXPORT steps in the pipeline (the converter from export to snapshot is built) | Needs the real Jira, field IDs and the existing query pipeline |
| P1-6 | Cloning the context repo (the program metrics repo) in the pipeline | Needs the Harness connector |
| P1-9 | Publishing the Confluence sections | The existing publisher does this; wire it to `manifest.json` |
| P1-10 | Turning `pipeline/*.example.yaml` into the real pipeline and weekly trigger | Needs the Fed-side pipeline examples |
| P2-4 | A Jira-importable CSV for bulk create (dry run) | Phase 2; intake checks and duplicates are already done |
| P3-x | The GitHub repo topic audit | Phase 3, planned in the epic doc |

## Values the Fed side supplies

| Item | Goes in | Supplied by |
| --- | --- | --- |
| Jira base URL, auth, Harness connector | Pipeline YAML (P1-2, P1-10) | The example Jira query pipeline |
| Jira address, so story keys become links | `rules.yaml` -> `workbook.jira_base_url` | The Fed-side Jira setup |
| Field IDs: Acceptance Criteria, Story Points, Epic Link, Sprint, epic dates | `jira_fields.yaml` | `/rest/api/2/field` output |
| Connectors, image, infrastructure, org and project | `pipeline/harness-pipeline.example.yaml` | The existing pipelines |
| Refinement day, and the time zone of Harness cron | `pipeline/harness-trigger.example.yaml` | The teams and the pipeline owner |
| The team's epics (key, name, status, start and end dates) | The snapshot's `epics` list (P1-2) | Jira, by epic query or the Agile API |
| Issue type names for stories, spikes and others | `rules.yaml` -> `scope.issue_types` | The Fed-side mapping |
| Projects, boards and sprints in scope | Pipeline config (P1-2) | The team |
| The team's labels: required, allowed, suggested by words | `rules.yaml` -> `labels` | Team leads |
| Technology names that should start titles | `rules.yaml` -> `themes.known` (starter: terraform) | Team leads |
| Tech-stack work patterns for sizing | `rules.yaml` -> `sizing.work_patterns` | Stack owners, drafted then confirmed |
| Allowed roles in "As a ..." | `rules.yaml` -> `allowed_roles` (empty = any) | Project leads |
| Story-writing hints from the context repo | `context/hints.yaml` | Drafted from the program metrics repo, each confirmed by a person |
| Confluence marker syntax and how the publisher takes the body | `rules.yaml` -> `confluence` | The existing publisher |
| Phase 3: GitHub orgs, program topic, team topics and name patterns | `repo_rules.yaml` (not built yet) | Project leads and team leads |

## The snapshot shape (what P1-2 must produce)

A JSON file. See `fixtures/program.json` for a full made-up example.

    {
      "stories": [ {key, summary, description, acceptance_criteria, story_points, issue_type, status,
                    group, sprint, epic, labels, assignee, extra} ],
      "epics":   [ {key, name, status, start_date, end_date} ],
      "intake":  [ stories planned for upload, same fields, no key needed ]
    }

- `group` is `current_sprint`, `future_sprints` or `backlog`. Take it from which Agile API call returned the story,
  not from parsing sprint text.
- `epic` is the epic KEY. Copy the Acceptance Criteria custom field into `acceptance_criteria`.
- `extra` is every other Jira field as name -> text, for the Raw Jira data tab.
- Dates are `YYYY-MM-DD`. Keep the snapshot's text as Jira gives it (wiki markup is handled).

## Tuning the cross-story rules (expect to do this on the first real run)

- **Epic matching** uses only the epic's NAME. One shared word of a two-word name scores 50%, which is the default
  `epics.min_match_score`. Raise it if suggestions are too eager; give epics short, clear names for better matches.
- **Duplicates**: `duplicate_at` (0.8) and `related_at` (0.5). Look at the Duplicates tab and adjust.
- **Themes**: only `themes.known` rewrite titles. Counted words are listed, never applied. Add a word to `known`
  once a person agrees it should start titles.
- **Word matching** is deliberately simple (it cuts common word endings). It is the same everywhere, which is what matters.
- **Everyday words** in `suggestions.ignore_when_matching` are ignored when comparing stories. Do not add topic words
  like "encrypt" or "migrate" there.

## About the work patterns (important)

`sizing.work_patterns` in `rules.yaml` is a **starter list of examples, not a rule**. The four starters come from
general AWS knowledge only. Draft patterns from the real stack, show each to a person to confirm, and never present a
pattern as fact. A pattern only prompts a second look.

## About suggestions and hints (important)

- Suggestions are drafts. They must never add scope: words come from the story, a confirmed hint, or a work pattern.
- Acceptance criteria are suggested **only** from `hints.yaml`. A missing hint is safe (it becomes a question); a wrong one is not.
- A suggested title uses only words from the story's own description.
- Template mode is the only mode. An AI-assisted mode needs an approved endpoint (not known yet) and a data-handling check first.

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
- Keep one job per module. A new kind of check goes in its own module, is called from `checks.py` (one story) or
  `analysis.py` (across stories), and gets its own test file.
- Add a test for every change. Run: `python3 -m unittest discover -s tests -t .`
- Write workbook cell text through `_text()` in `workbook.py`, and HTML text through `esc()`.
