# Runbook: using the backlog refinement report

INTERNAL USE ONLY - Via Logic LLC.

## The weekly rhythm

The report runs **every week, the working day before team refinement**, from a scheduled Harness trigger.

| When | Who | What |
| --- | --- | --- |
| The day before refinement | The pipeline | Exports Jira, builds the report, posts the Confluence page, saves the files |
| Before refinement | Team lead | Opens the Confluence page for the counts, then the update pack for the details |
| Before refinement | Team lead and engineers | Fix the quick ones: missing epics, empty acceptance criteria, unclear titles |
| In refinement | Everyone | Use the "Ask in refinement" questions; decide duplicates and splits |
| After refinement | Team lead | Tick Done? on the workbook's Changes tab, if you use it |

Nothing in the report changes Jira. People make every change.

## Reading the report (start at the top)

1. **The Confluence page.** Counts only: by group, by epic ("No epic" should be 0), themes, labels.
2. **`update-pack.html`.** Open it in a browser. Contents, then a table per story: Field, Now, Suggested, Why.
   Click the story key (it opens in Jira in a new window), click a blue box to select it (or press Copy), paste
   into Jira, and Save. Yellow **Decide** rows are choices, such as closing a duplicate.
3. **`refinement-report.xlsx`.** For filtering and sorting: Findings (shaded weak cells; hover for why), Changes,
   Epics, Duplicates, Themes, and every Jira field on Raw Jira data.
4. **`changes.csv`.** The same edits, one per row, for anyone who prefers a spreadsheet or a bulk tool.

## Changing a rule (project leads)

1. Open `rules.yaml` in the Git web editor. Every setting has a plain comment.
2. Change a value (for example a threshold, a required label or a technology name) and raise `rules_version` by 1.
3. Commit on a branch and get a quick approval.
4. The next run checks the file first and stops with the line number if something is wrong.
   To check it yourself: `python -m refiner validate-rules --rules rules.yaml`

Common changes:

| I want to ... | Change |
| --- | --- |
| require the team label on every story | `labels.required_all: [my-team]` |
| make "Ansible" start titles | `themes.known: [terraform, ansible]` |
| flag fewer near-duplicates | raise `duplicates.duplicate_at` (0.8 now) |
| get fewer epic suggestions | raise `epics.min_match_score` (0.5 now) |
| stop the gentle "brief" nudge | `fields.description.brief_chars: 0` |
| say a different day on the reports | `schedule.note` |

## Running it by hand

    pip install -r requirements.txt
    python -m refiner doctor                                    # is this copy ready?
    python -m refiner snapshot --fields jira_fields.yaml --current current.json --future future.json \
                               --backlog backlog.json --epics epics.json --out snapshot.json
    python -m refiner doctor --snapshot snapshot.json           # counts only: did the fields map correctly?
    python -m refiner report --snapshot snapshot.json --rules rules.yaml --context context --out-dir refinement-out

Add `--intake planned.csv` to check stories that are not in Jira yet (they show as "Not in Jira yet").
Add `--today 2026-12-01` to judge epics as of another day.

## When something looks wrong

| What you see | What to check |
| --- | --- |
| The run stops at the self-check | `python -m refiner doctor` lists the FAIL lines, with file and line |
| "No story has acceptance criteria" | `story_fields.acceptance_criteria` in `jira_fields.yaml` is the wrong field id |
| Every story is in one group | An export file was passed to the wrong option (`--current`, `--future`, `--backlog`) |
| An odd epic suggestion | The epic's name is short and generic; tune `epics.min_match_score` |
| Two different stories marked duplicate | Their titles share most words; tune `duplicates.duplicate_at`, or reword a title |
| A rule change "did nothing" | The run uses the committed `rules.yaml`; check the version printed on the report |
