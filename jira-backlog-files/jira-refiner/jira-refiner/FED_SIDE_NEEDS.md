# What we need from the Fed side

INTERNAL USE ONLY - Via Logic LLC.

This is the working list for the assistant that finishes this project on the Fed side. Work down it with a person.
Everything stays on the Fed side: nothing here is copied back out. Tick each box as it is done.
`python -m refiner doctor` checks many of these for you (marked **doctor**).

**Keep it safe.** Bring field IDs, names, YAML and settings, never story text, secrets or CUI. When you need to check a
real export, run `python -m refiner doctor --snapshot snapshot.json`: it prints counts only and is safe to share.

## A. Harness pipelines (examples to copy from)

- [ ] **The existing Harness pipeline that queries Jira** (its YAML). It is the pattern for the export steps in
      `pipeline/harness-pipeline.example.yaml`: how it authenticates, which endpoints it calls, where it saves JSON.
- [ ] **The existing Confluence publisher** (its YAML and how it is given the HTML body and the start/end markers).
      Then set `confluence.marker_start` / `marker_end` in `rules.yaml`. **doctor**
- [ ] **The example pipeline that creates workbooks.** Compare it with `refiner/workbook.py` (checklist in HANDOFF.md).
- [ ] **Connector and secret NAMES** (never values): Git connector for this repo, the context repo, Jira, Confluence,
      and the image connector.
- [ ] **The infrastructure block and the Python image** the existing pipelines use (Python 3.9 or newer).
- [ ] **Fill in every `REPLACE_` value** in `pipeline/harness-pipeline.example.yaml`. **doctor**

## B. The weekly run

- [ ] **Each team's refinement day and time.** The report must run **every week, the working day before team
      refinement**, so people walk in knowing what needs work.
- [ ] **The time zone Harness uses for cron** (often UTC). Set the trigger in `pipeline/harness-trigger.example.yaml`. **doctor**
- [ ] **Who gets told** when the report is ready (the Confluence page link, and where the workbook and update pack live).
- [ ] Keep `schedule.note` in `rules.yaml` accurate, so the reports say when they run. **doctor**

## C. Jira exports

- [ ] **Jira base URL** (Data Center). Put it in `rules.yaml` -> `workbook.jira_base_url` so keys become links. **doctor**
- [ ] **The field list**: `GET /rest/api/2/field`, ids and names only. Fill in `jira_fields.yaml`:
      Acceptance Criteria, Story Points, Epic Link, Sprint. **doctor**
- [ ] **Where epic dates live.** Jira Data Center has no standard epic start date. Find the fields used (for example
      Target start / Target end, or the due date) and set `epic_fields` in `jira_fields.yaml`.
- [ ] **Boards and projects in scope**, and their board IDs (for the Agile API calls).
- [ ] **Four saved exports per run**: current sprint, upcoming sprints, backlog, and the team's epics. Then
      `python -m refiner snapshot ...` and `python -m refiner doctor --snapshot snapshot.json` to check the mapping.
- [ ] **Issue type names** (Story, Spike, others) for `scope.issue_types`, and the **status names** that mean done.

## D. Teams and how they label things

- [ ] **The team list**: each team's name, its Jira label, and (for later) its GitHub topic. The platform team's topic is `pet`.
- [ ] **Label rules**: labels every story needs (for example the team label), and any allowed list. `rules.yaml` -> `labels`. **doctor**
- [ ] **Technology names that should start titles** (for example Terraform). `rules.yaml` -> `themes.known`. **doctor**
- [ ] **Allowed roles** for "As a ..." (for example platform engineer). `rules.yaml` -> `allowed_roles`. **doctor**
- [ ] **The tech stack** (AWS services and tools) to turn into confirmed work patterns. `rules.yaml` -> `sizing.work_patterns`. **doctor**

## E. Repositories

- [ ] **The context repo** (the program metrics repo): its path, its Harness connector, and its folder names. Draft
      `context/hints.yaml` from it and have a person confirm every hint. **doctor**
- [ ] **Reference repos to point the next assistant at** (read them for patterns; do not copy content out):
  - [ ] the repo holding the existing Jira query pipeline
  - [ ] the repo holding the Confluence publisher
  - [ ] the repo holding the workbook example pipeline
  - [ ] any shared Harness templates repo
  - [ ] the program metrics repo (context)
- [ ] **Possible repos for each team**: a list of repo names and their current GitHub topics. It feeds Phase 3, the repo
      topic audit, and helps match stories to repos.
- [ ] **For a later, separate effort: a repo listing and information report on Confluence.** Start a note now of what it
      should show for each repo (for example owner team, topics, purpose, last activity, and links to its pipelines),
      so that effort can reuse the Phase 3 repo snapshot.

## F. People and approvals

- [ ] **Who approves rule changes** (project leads).
- [ ] **Who may run bulk uploads** in Jira (Jira admins only).
- [ ] **Who owns the pipeline**, and who to ask when it fails.
- [ ] **Whether an approved AI endpoint exists** for the pipeline (optional; template mode works without one).

## When the list is done

1. `python -m refiner doctor --strict` shows no FAIL and no TODO lines.
2. Run once on one team's board and review the workbook and update pack with that team (story P1-11, the pilot).
3. Turn on the weekly trigger.
