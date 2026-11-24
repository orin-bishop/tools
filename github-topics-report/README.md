# GitHub Topics Report

Finds every repo tagged with a team topic (`pet`, `viz`, ...), compares that to a
human-maintained registry, and hunts for repos that *look* like they belong to a team
but were never tagged. Publishes the result to Confluence and emails a summary.

```
GitHub ──► inventory ──► manifest ──► enrich ──► classify ──► render ──► Confluence page
 (GraphQL     all repos    team-by-team  commits +   registry     HTML +      + email
  + REST)     + teams      repo JSON     READMEs     diff+score   email
                           vs GitHub
```

## Layout

| Path | Purpose |
|---|---|
| `config/teams.yml` | **The registry.** Teams, topics, members, known repos, exclusions, tuning. |
| `scripts/inventory.py` | Stage 1. All repos in the org(s) via GraphQL; team members + repo access via REST. |
| `scripts/manifest.py` | Stage 1b. Pulls the team-by-team repo JSON, merges it into the registry, compares topics with GitHub. |
| `scripts/enrich.py` | Stage 2. Recent commit authors + README for repos that could still be untagged. |
| `scripts/classify.py` | Stage 3. Registry-vs-topic diff and candidate scoring (pure logic). |
| `scripts/render.py` | Stage 4. Confluence storage-format page, email HTML, subject line. |
| `scripts/run_report.sh` | Runs stages 1-4. |
| `scripts/publish_confluence.py`, `send_email.py` | Fallbacks if you don't use the Harness templates. |
| `harness/github_topics_report.yaml` | The pipeline. |
| `tests/` | 72 tests, including a full run against a mock GitHub API. |

## Run it locally

```bash
pip install -r requirements.txt
export GITHUB_TOKEN=...            # read-only: repo + read:org (or a GitHub App token)
export GH_ORGS=my-org              # or set settings.orgs in config/teams.yml
bash scripts/run_report.sh         # writes ./out
python -m unittest discover -s tests
```

First run tip: `SKIP_ENRICH=true bash scripts/run_report.sh` is fast (name, topic, CODEOWNERS and
team-access signals only) and is a good way to sanity check your config before the full run.

GitHub Enterprise Server: set `GITHUB_API_URL=https://HOST/api/v3` (GraphQL URL is derived).

Outputs in `out/`: `confluence.html`, `email.html`, `email_subject.txt`, `results.json`,
`registry_suggestions.yml`, `candidates.csv`, `<team>_repos.csv`, `needs_action.txt`, and with the
manifest on: `manifest.json`, `manifest_topic_drift.csv`, `manifest_proposed.json`.

## The registry (`config/teams.yml`)

Three views of each team are compared:

| View | Source |
|---|---|
| **Tagged** | repos carrying the team's GitHub topic |
| **Registry** | `repos:` in `teams.yml` - what we believe |
| **Candidates** | untagged, unregistered, unexcluded repos, scored |

The report flags: **in registry but missing the topic**, **tagged but not in registry**,
**registry entries not found** (renamed/deleted), and **ranked candidates**. Archived repos and
forks are skipped. Confirmed false positives go in `exclude:` so they stop reappearing.
`registry_suggestions.yml` is a paste-ready YAML of everything above.

Adding a team (e.g. another group) is a new block in `teams.yml`; no code changes.

## Manifest sync (the team-by-team repo JSON)

Your other repo keeps a JSON of every repo in the program, grouped by team, with topics. This
pipeline reads it straight from GitHub (contents API, same token), so no local clones are needed.
It does two jobs:

1. **Membership.** Manifest repos are merged into each team's registry (alongside `repos:` in
   `teams.yml`). A manifest `pet` repo without the `pet` topic shows up as "needs topic"; a
   repo tagged `pet` that the manifest doesn't list shows up as "not in registry".
2. **Topics.** Every manifest repo's topics are compared with what GitHub says.

| Finding | Meaning |
|---|---|
| Topics differ | per repo: *on GitHub, not in manifest* / *in manifest, not on GitHub* |
| Not found on GitHub | in the manifest but renamed / deleted |
| Topic list vs GitHub | topics in use on GitHub missing from the manifest's master topic list, and list entries nothing uses |
| More than one team | a repo listed under two teams |
| Unmapped teams | manifest teams with no `teams.yml` entry (topics still compared) |

**Source of truth:** GitHub for topics, the manifest for team membership. So topic drift means "update
the manifest", and `out/manifest_proposed.json` is a machine-readable patch for exactly that
(`topics_by_repo`, `vocabulary_additions`, `vocabulary_unused`) that your downloader repo can ingest.
A team's own topic is not repeated as drift, since it's already reported as "needs topic".

**Enable it** in `config/teams.yml` (`settings.manifest`): set `enabled: true`, `repo` and `path`.
The token must be able to read that repo. For a local run you can skip GitHub with
`MANIFEST_FILE=./repos.json`.

**Layout is auto-detected** (team to list of repos, team to object with `repos`, team to repo map,
list of team objects, or a flat list with a team field; optionally under a top-level `teams`). Repos may
be `org/repo`, bare names, or GitHub / SSH URLs. If detection picks the wrong keys, set the overrides
(`teams_path`, `repos_key`, `team_key`, `name_key`, `topics_key`, `topic_list_path`, `team_map`). If it
parses **zero** repos the run fails with a message listing the top-level keys, rather than quietly
reporting nothing (`required: false` downgrades that to a warning on the page).

## Candidate scoring

Every candidate lists *why*, so a human can judge. Defaults (tune under `settings.weights`):

| Signal | Points | Notes |
|---|---|---|
| Team has admin/maintain on repo | 5 | needs `github_team` + `read:org` |
| CODEOWNERS references the team | 5 | |
| Repo name contains the team token | 4 | delimited token: `pet-api` yes; `petition`, `carpet`, `petstore` no |
| Near-miss topic (`pets`, `team-pet`) | 4 | someone tried to tag it |
| Members wrote >=50% / >=25% / >=10% of recent commits | 4 / 3 / 2 | uses *share*, so busy shared libraries don't light up |
| Any member commit at all | 1 | |
| Team has write access | 3 | |
| Description mentions keyword | 2 | |
| README mentions keyword 2+ times | 1 | |
| Created inside window with member activity | 1 | |

Buckets: **high >= 7**, **medium >= 4**, **low >= 2** (`settings.thresholds`). The email shows
high + medium; Confluence shows everything (low is collapsed).

## Harness setup

1. Put this folder in the info-reports repo (the pipeline assumes `./github-topics-report`).
2. Create a secret `github_report_token` (read-only token or GitHub App installation token).
3. Import `harness/github_topics_report.yaml` and replace every `REPLACE_*`.
4. **Fill in the two template steps** (`publish_confluence`, `send_email`): set `templateRef`,
   `versionLabel`, and map `templateInputs` to your templates' schemas. The inputs they need:
   - Confluence: page id, body file `out/confluence.html` (storage format).
   - Email: recipients, subject from `out/email_subject.txt`, HTML body from `out/email.html`.
5. Run with `EMAIL_RECIPIENTS` set to your test group and `EMAIL_TEST_MODE=true`
   (adds a TEST banner and `[TEST]` subject prefix). Widen recipients when happy.

`EMAIL_MODE=on_drift` only sends when something needs action; `always` sends every run.

**No template?** Swap a template step for a Run step:

```yaml
- step:
    type: Run
    name: Publish to Confluence
    identifier: publish_confluence
    spec:
      connectorRef: REPLACE_DOCKER_CONNECTOR
      image: python:3.12-slim
      shell: Bash
      command: cd github-topics-report && python scripts/publish_confluence.py
      envVariables:
        CONFLUENCE_BASE_URL: https://yourorg.atlassian.net/wiki
        CONFLUENCE_PAGE_ID: <+pipeline.variables.CONFLUENCE_PAGE_ID>
        CONFLUENCE_EMAIL: you@yourorg.com
        CONFLUENCE_API_TOKEN: <+secrets.getValue("confluence_api_token")>
```

`send_email.py` works the same way (`SMTP_HOST`, `EMAIL_FROM`, `EMAIL_RECIPIENTS`, ...).

## Known limits

- **Creator isn't exposed by GraphQL.** "Who authored a repo recently" is approximated by commit
  authorship inside the window, plus a bonus for repos created inside it.
- **Commit sample is capped at 100 per repo** (newest first). Shares are computed over that sample.
- **Commits only count when the author email is linked to a GitHub account.** Unlinked commits
  dilute the share but can't be attributed.
- **`on_drift` repeats** until the item is tagged, registered or excluded - there is no "new since
  last run" yet.
- **Manifest layout is detected, not known.** Verify the first run's "Manifest sync" counts match your JSON.
- **Org repos only.** Personal-account repos aren't scanned.
- **Team signals need `read:org`.** Without it the report still runs and says so on the page.

## Next steps

1. Have the downloader repo apply `manifest_proposed.json` (or open a PR against it automatically).
2. Persist `results.json` between runs (artifact store) and report only what's *new* since last time.
3. Auto-open a PR against `teams.yml` from `registry_suggestions.yml`.
4. Optionally open an issue on repos asking owners to add the missing topic.
