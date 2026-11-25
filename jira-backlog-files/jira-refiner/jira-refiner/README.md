# Jira Backlog Refiner

INTERNAL USE ONLY - Via Logic LLC. Not for distribution outside the organization.

Checks Jira stories and spikes against rules a project lead can edit, and says which ones are
thin, unpointed, or bigger than their points suggest. **Nothing in this project writes to Jira.**

## Status

| Story | What | State |
| --- | --- | --- |
| P1-3 | Rules file and validator (`rules.yaml`, `refiner/rules.py`) | Built, tested |
| P1-4 | Quality checks (`refiner/checks.py`) | Built, tested |
| P1-5 | Sizing and split check (`refiner/sizing.py`) | Built, tested |
| P1-7 | Suggestions, template mode (`refiner/suggest.py`, `refiner/context.py`) | Built, tested |
| P1-8 | Excel workbook (`refiner/workbook.py`, `refiner/measures.py`) | Built, tested |
| P1-9 | Confluence report as HTML body sections (`refiner/confluence.py`) | Built, tested. Publishing is the existing publisher's job |
| P1-13 | Handoff package (see HANDOFF.md, started) | Next |

## Try it

    python3 -m refiner validate-rules --rules rules.yaml
    python3 -m refiner check --snapshot fixtures/snapshot.json --rules rules.yaml --details
    python3 -m refiner suggest --snapshot fixtures/snapshot.json --rules rules.yaml --context context
    python3 -m refiner workbook --snapshot fixtures/snapshot.json --rules rules.yaml --context context --out report.xlsx
    python3 -m refiner confluence --snapshot fixtures/snapshot.json --rules rules.yaml --out-dir confluence-out
    python3 -m unittest discover -s tests -t .

Needs Python 3.9 or newer (tested on 3.12). Outside libraries: PyYAML, and openpyxl for the workbook.

## What it checks

Each finding has a severity (set in `rules.yaml`) and each story gets one verdict:
**Looks good**, **Needs review**, **Missing info** or **Suggest split**.

| Finding | Meaning |
| --- | --- |
| `summary_missing`, `summary_short` | The Summary (Jira's title) is empty or short |
| `summary_mismatch` | Few words of the summary appear in the description or criteria |
| `description_missing`, `description_short` | Description is empty, or 20 characters or fewer |
| `description_format` | Not in "As a ..., I want ..., so that ..." form, or the role is not allowed |
| `ac_missing`, `ac_short`, `ac_vague` | Acceptance criteria empty, 20 characters or fewer, or only "TBD / works as expected" |
| `points_missing` | Story has no points |
| `other_required_missing` | A field you marked required in `fields.other_required` is empty |
| `large_and_thin` | 5+ points (1 point = 1 day) with a thin description or criteria |
| `possibly_undersized` | 3 points or fewer, but the text matches a **work pattern**: a kind of work that sounds small but usually is not (for example encrypting an existing database). The patterns live in `rules.yaml` and are starter examples to extend with the real tech stack |

## How suggestions work (template mode, no AI)

For every story that is not "Looks good", `suggest` drafts: a description in story form, acceptance criteria,
"Ask in refinement" questions, a split suggestion, and pointers to similar well-written stories and to related
context sections. Every draft is labelled **SUGGESTED - review before use** and lists where it came from.

| Part | Where it comes from |
| --- | --- |
| Description | The story's own summary and any "I want" / "so that" it already has. The role defaults to `suggestions.default_role`. If the reason is unknown the draft says `[reason to confirm in refinement]` and asks a question. Brief old text is kept as "Existing notes" |
| Acceptance criteria | **Only** a confirmed hint in `context/hints.yaml`. With no hint, nothing is invented: it becomes a question |
| Split titles and reason | The matching work pattern in `rules.yaml` |
| Questions | Built from the findings, plus any questions on a matching hint |
| Similar stories | Well-written stories in the same epic that share topic words (role words and everyday words are ignored) |
| Context pointers | Headings in the context folder's markdown files that share topic words. Pointers only, never copied text |

`context/` here is a made-up sample. On the Fed side the context repo is the program metrics repo, and the
Fed-side assistant drafts `hints.yaml` from it. **A person must confirm every hint.**

## The workbook

`workbook` writes one Excel file with these tabs: **Table of Contents**, **Summary**, **Findings**, **Suggestions**,
**Raw Jira data** and **Rules in effect**. Every tab carries the internal-use banner and uses Arial.

- **Summary** numbers are **formulas** (`COUNTIFS`) that read the Findings tab, so they never drift from it. By group and by label
  (a story with several labels counts under each; none counts under "No label"). The same counts exist in
  `refiner/measures.py` for the Confluence page, so the two always agree.
- **Findings** has one row per checked story. Weak or missing cells are shaded by severity using the colors in `rules.yaml`
  (high amber, medium light yellow, low paler), and hovering a shaded cell shows why. It shows plain text, shortened to 300 characters.
- **Suggestions** has the drafts, each labelled, plus an **Approved?** column (a Y/N dropdown, light blue) for later use.
- **Raw Jira data** has every story in the snapshot, including ones that were not checked (the `Checked` column says why),
  every Jira field as a column, and the original text. Column order comes from `workbook.raw_column_order` in `rules.yaml`;
  anything not listed is added at the end, so nothing is dropped.
- Text that starts with `=` stays text, control characters are removed, and text over Excel's cell limit is cut with a note.
- Excel works the formulas out when the file opens. To fill in the cached values too (for previewers), recalculate with LibreOffice.

## The Confluence report

`confluence` writes the report as HTML **body** sections for the existing publisher, which replaces whatever sits between a
start marker and an end marker. A page can hold several sections, so the report is three separate ones:

| Section id (from `rules.yaml`) | Holds |
| --- | --- |
| `refiner-summary` | Banner, title, generated time, rules version, "at a glance", the by-group table, what each column means |
| `refiner-labels` | The by-label table |
| `refiner-not-checked` | What was in the snapshot but outside the scope |

It writes `section-<id>.html` for each, `manifest.json` (each section's file and its start and end markers) and `preview.html`
(all sections together, for looking at in a browser; **never publish it**).

- **Counts only.** No story keys, titles, people or text appear. The numbers come from `refiner/measures.py`, the same definitions the
  workbook formulas are checked against, so the page and the workbook always agree.
- **Storage format.** Body only: no `html`, `head`, `body`, `style` or `script`; every tag closed; all text escaped; colors inline on a
  `span` as `rgb(...)`. A test fails if any other tag or attribute appears.
- **Markers.** How they are written is in `rules.yaml` (`confluence.marker_start`, `marker_end`, with `{id}` replaced by the section id).
  The default is an HTML comment, which is only a starting guess: match what the existing publisher expects.
  `include_markers` (or `--include-markers`) writes them around the body in each file; leave it off if the publisher adds them.

## Layout

    rules.yaml          the rules, edited by project leads (comments explain every setting)
    refiner/rules.py    loads and checks rules.yaml; errors name the line and the fix
    refiner/model.py    the Story shape and the snapshot loader
    refiner/checks.py   quality checks        refiner/sizing.py   sizing checks
    refiner/verdict.py  one verdict per story  refiner/runner.py   scope and running everything
    refiner/cli.py      the command line      refiner/text.py     Jira wiki markup -> plain words
    refiner/confluence.py  the Confluence HTML sections
    refiner/workbook.py  the Excel workbook   refiner/measures.py  the counts shared with the Confluence page
    refiner/suggest.py  suggestions        refiner/context.py  hints file and context folder
    refiner/storyform.py  pulls role / want / reason out of a story    refiner/yamlcheck.py  shared YAML checking
    context/            made-up sample context (hints.yaml plus a markdown file)
    fixtures/           made-up stories and spikes (each says the verdict it should get)
    tests/              unittest tests, no Jira needed

## Design rules (so another person or assistant can keep going)

- Plain Python, small modules, one job each, comments in simple words.
- Every setting a lead might change is in `rules.yaml`, not in code.
- Environment-specific values (anything from the Fed side) are marked `REPLACE_` and listed in HANDOFF.md.
- Every change gets a test. Run the tests before and after.
