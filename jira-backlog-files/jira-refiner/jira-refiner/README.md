# Jira Backlog Refiner

INTERNAL USE ONLY - Via Logic LLC. Not for distribution outside the organization.

Checks Jira stories and spikes (and stories planned for upload that are not in Jira yet) against rules a project
lead can edit. It finds thin, unpointed, oversized, duplicate and epic-less stories, drafts simple fixes, and
produces a workbook, a Confluence report, a CSV of edits and a copy-and-paste HTML page. **Nothing in this project
writes to Jira.** People make the changes, with the reports to help.

## Start here

| If you are ... | Read |
| --- | --- |
| a team lead or project lead using the reports | `RUNBOOK.md` |
| finishing the setup on the Fed side | `HANDOFF.md`, then `FED_SIDE_NEEDS.md`, then `KICKOFF_PROMPT.md` for the assistant |
| changing a rule | the comments in `rules.yaml` (every setting is explained) |

**It should run every week, the working day before team refinement**, from a scheduled Harness trigger
(`pipeline/harness-trigger.example.yaml`). The reports say so (`schedule.note` in `rules.yaml`).

## Try it

    pip install -r requirements.txt
    python3 -m refiner doctor                       # is this copy ready? (fails until the placeholders are filled in)
    python3 -m refiner validate-rules --rules rules.yaml
    python3 -m refiner check  --snapshot fixtures/program.json --rules rules.yaml --today 2026-11-25
    python3 -m refiner report --snapshot fixtures/program.json --intake fixtures/intake.csv --rules rules.yaml \
                              --context context --out-dir refinement-out
    python3 -m unittest discover -s tests -t .

`report` writes everything a pipeline needs into one folder:

| File | What it is |
| --- | --- |
| `refinement-report.xlsx` | The workbook (tabs below) |
| `changes.csv` | Every suggested edit, one row per field, with a link to the story |
| `update-pack.html` | One page with a copy-and-paste table per story |
| `confluence/` | The Confluence report as HTML body sections, `manifest.json` and `preview.html` |

The other commands (`check`, `suggest`, `workbook`, `confluence`, `changes`, `update-pack`) each make one piece.
`snapshot` turns saved Jira exports into the snapshot file (using `jira_fields.yaml`), and `doctor` checks the setup
and prints a counts-only shape of a snapshot that is safe to share.
Every command takes `--snapshot`, `--intake` (optional CSV), `--rules` and `--today` (optional, to judge epics
as of another day). Needs Python 3.9 or newer (tested on 3.12). Outside libraries: PyYAML and openpyxl.

## What it checks

Each finding has a severity (set in `rules.yaml`) and each story gets one verdict:
**Looks good**, **Needs review**, **Missing info** or **Suggest split**.

**One story at a time**

| Finding | Meaning |
| --- | --- |
| `summary_missing`, `summary_short`, `title_long` | The title (Jira's Summary) is empty, short, or over 90 characters |
| `summary_mismatch` | Few words of the title appear in the description or criteria |
| `description_missing`, `description_short`, `description_brief` | Empty, 20 characters or fewer, or under 50 (a low nudge) |
| `description_format` | Not "As a ..., I want ..., so that ...", or the role is not allowed |
| `ac_missing`, `ac_short`, `ac_brief`, `ac_vague` | Acceptance criteria empty, short, brief, or only "TBD / works as expected" |
| `points_missing` | No points |
| `epic_missing` | No epic. Every story in the listed groups must have one |
| `labels_missing`, `label_unknown`, `labels_suggested` | A required label is missing, a label is not allowed, or the text suggests one |
| `large_and_thin`, `possibly_undersized` | Bigger than its points (1 point = 1 day), using the work patterns in `rules.yaml` |
| `other_required_missing` | A field you marked required is empty |

**Across stories** (`refiner/analysis.py`)

| Finding or result | Meaning |
| --- | --- |
| `epic_inactive` | The story's epic is finished (status) or past its end date |
| Epic suggestions | For stories that need an epic: the best current or future epic, by how much of the epic's name appears in the story |
| New epic ideas | Stories that fit no epic but share a word, grouped as a suggested new epic |
| `duplicate_story` | Titles (and descriptions) at or above `duplicate_at` alike. A story waiting to upload that matches one in Jira is the only one flagged |
| Related stories | Between `related_at` and `duplicate_at`: fine, listed so they can be grouped |
| Themes | Words in several titles. Only themes listed under `themes.known` (Terraform is a starter example) suggest moving the word to the front of a title |

Every threshold, list and switch is in `rules.yaml`, with a plain comment next to it.

## What it suggests (template mode, no AI)

For each story that is not "Looks good": a better title (drafted only from its own description), a description
in story form, acceptance criteria (only from a confirmed hint in `context/hints.yaml`), an epic or a new-epic
idea, labels to add, the stories it may duplicate, a split, and "Ask in refinement" questions. Anything unknown
becomes a question, never an invented requirement. Every suggestion is labelled **SUGGESTED - review before use**.

## Making the updates

`refiner/changes.py` turns everything into one list of edits. Each edit is **update** (replace or set a field),
**add** (labels) or **decide** (close a duplicate, split a story, create an epic). That one list feeds:

- **`update-pack.html`**: contents, an overview, epics, duplicates, themes, then a table per story: Field, Now,
  Suggested, Why. The story key opens the story in Jira in a new window. Click a blue box to select it (or press
  Copy), paste into Jira, and Save. Jira cannot be pre-filled from a link for an existing story, so this is the
  practical way. Set `update_pack.copy_buttons: false` to leave out the small script.
- **`changes.csv`**: the same list for anyone who prefers a spreadsheet or a bulk tool.
- **The Changes tab** in the workbook, with a Done? column to tick as you go.

## The workbook

Tabs: Table of Contents, Summary, Findings, Suggestions, Changes, Epics, Duplicates, Themes, Raw Jira data, Rules in
effect. Every tab carries the internal-use banner and uses Arial. Summary counts (by group, by epic with "No epic"
last, by label) and the Epics tab story counts are **formulas** on the Findings tab, checked against an independent
count. Weak cells on Findings are shaded by severity; hover for the reason.

## The Confluence report

Five HTML body sections (summary, by epic, themes, by label, not checked), each with its own start and end markers
for the existing publisher. Counts only: no story keys, titles or people. Body-only storage format; a test fails on
any other tag or attribute.

## How the code is organised

Each step is one module, and each module has one job. Data flows one way:

    model.py         load the snapshot (stories, epics, intake) and the intake CSV
    rules.py         load and check rules.yaml (yamlcheck.py has the shared plumbing)
    checks.py        one story at a time   (+ sizing.py, titles.py, labels.py, storyform.py, text.py)
    analysis.py      across stories        (+ epics.py, duplicates.py, themes.py)
    runner.py        scope, then checks and analysis together -> verdicts (verdict.py)
    suggest.py       drafted fixes          (+ context.py for hints and context files)
    changes.py       every edit as one list
    measures.py      the counts shared by the workbook and Confluence
    workbook.py  confluence.py  updatepack.py   the outputs
    jira_import.py   saved Jira exports -> the snapshot (with jira_fields.yaml)
    doctor.py        the self-check and the counts-only snapshot shape
    cli.py           the commands

    rules.yaml        the rules, edited by project leads
    jira_fields.yaml  which Jira custom field is which (filled in on the Fed side)
    pipeline/         Harness pipeline and weekly trigger SKETCHES, to align with the real examples
    requirements.txt  PyYAML and openpyxl
    RUNBOOK.md  HANDOFF.md  FED_SIDE_NEEDS.md  KICKOFF_PROMPT.md

    context/   made-up sample context        fixtures/   made-up stories, epics and intake
    tests/     one test file per module, no Jira needed

## Design rules (so another person or assistant can keep going)

- Plain Python, small modules, one job each, comments in simple words.
- Every setting a lead might change is in `rules.yaml`, not in code.
- Environment-specific values (anything from the Fed side) are listed in HANDOFF.md.
- Every change gets a test. Run the tests before and after.
- Nothing writes to Jira.
