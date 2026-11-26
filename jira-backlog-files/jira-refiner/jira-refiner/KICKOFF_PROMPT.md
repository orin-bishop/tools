# Kickoff prompt for the Fed-side assistant

Paste this into the assistant on the Fed side, then paste the items it asks for from FED_SIDE_NEEDS.md.

```
You are finishing a Python and Harness project called the Jira Backlog Refinement Pipeline. It was designed and
built outside this environment on made-up data. You have no memory of that work, so everything you need is in this
repository. Read README.md, then HANDOFF.md, then FED_SIDE_NEEDS.md.

Goal: a weekly Harness pipeline (the working day before team refinement) exports Jira, checks every story and spike
against rules.yaml, and publishes a workbook, a copy-and-paste update pack, a CSV of edits, and a Confluence summary.
It never writes to Jira.

Do these in order:
1. Run the tests: python -m unittest discover -s tests -t .  Do not continue until they pass.
2. Run python -m refiner doctor. Work down FED_SIDE_NEEDS.md with me to clear every FAIL line, then the TODO lines.
   Ask me for each value. Do not guess field ids, connectors or labels.
3. Adapt pipeline/harness-pipeline.example.yaml to our existing Jira query, Confluence publisher and workbook pipelines.
4. Build a snapshot from real exports and run python -m refiner doctor --snapshot snapshot.json. Only counts are printed;
   use them to check the field mapping.
5. Run python -m refiner report on one team's board and show me the workbook and the update pack before anything is published.
6. Set the weekly trigger in pipeline/harness-trigger.example.yaml.

Rules: keep changes small and keep one job per module. Add a test for every change. Never put secrets, real Jira text
or CUI in the repo or in logs. Keep the pipeline read-only. Suggestions must not add scope. The work_patterns, hints and
themes are starter examples: extend them from our real stack and context repo, and ask me to confirm each one.
```
