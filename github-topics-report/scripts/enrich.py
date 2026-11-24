"""Stage 2 - enrichment of the candidate pool.

Only repos that (a) could still be an untagged repo for at least one team and
(b) were pushed inside the lookback window are enriched, to keep API cost low.
For each we fetch recent commit authors (up to `history_sample` commits inside
the window) and the head of the README, batching many repos per GraphQL query.

Set SKIP_ENRICH=true to skip (static signals only). Writes out/enrichment.json.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from ghclient import GitHubClient, GitHubError
from reportlib import (
    apply_manifest_registry, is_candidate_for, iso, load_config, log, months_ago, now_utc, parse_ts,
    read_json, read_json_optional, write_json,
)

README_CHARS = 4_000

ENRICH_QUERY = """
query($ids: [ID!]!, $since: GitTimestamp!, $sample: Int!) {
  rateLimit { cost remaining resetAt }
  nodes(ids: $ids) {
    ... on Repository {
      id
      nameWithOwner
      defaultBranchRef {
        target {
          ... on Commit {
            history(since: $since, first: $sample) {
              totalCount
              nodes { committedDate author { user { login } } }
            }
          }
        }
      }
      readme: object(expression: "HEAD:README.md") { ... on Blob { text } }
    }
  }
}
"""


def summarize(node: dict) -> dict:
    """Reduce one Repository node to what classification needs."""
    ref = node.get("defaultBranchRef") or {}
    history = (ref.get("target") or {}).get("history") or {}
    commits = history.get("nodes") or []
    authors: Counter = Counter()
    for commit in commits:
        user = (commit.get("author") or {}).get("user") or {}
        authors[(user.get("login") or "").lower()] += 1  # "" = commit not linked to a GitHub user
    readme = ((node.get("readme") or {}).get("text") or "")[:README_CHARS]
    return {
        "total_commits": history.get("totalCount", 0),
        "sampled": len(commits),
        "authors": dict(authors),
        "readme_head": readme,
    }


def candidate_pool(repos: list[dict], teams: dict, settings: dict, cutoff) -> list[dict]:
    pool = []
    for repo in repos:
        if not repo.get("pushedAt") or parse_ts(repo["pushedAt"]) < cutoff:
            continue
        if any(is_candidate_for(repo, team, settings) for team in teams.values()):
            pool.append(repo)
    pool.sort(key=lambda r: r["pushedAt"], reverse=True)
    return pool[: settings["max_enrich_repos"]]


def fetch_batch(client, ids: list[str], since: str, sample: int, out: dict, names: dict) -> None:
    """Fetch one batch; on failure split it so a single heavy repo can't sink the run."""
    try:
        data = client.graphql(ENRICH_QUERY, {"ids": ids, "since": since, "sample": sample})
    except GitHubError as err:
        if len(ids) == 1:
            log(f"  WARNING: skipping {names[ids[0]]}: {err}")
            return
        mid = len(ids) // 2
        fetch_batch(client, ids[:mid], since, sample, out, names)
        fetch_batch(client, ids[mid:], since, sample, out, names)
        return
    for node in data.get("nodes") or []:
        if node and node.get("nameWithOwner"):
            out[node["nameWithOwner"].lower()] = summarize(node)


def enrich(client, inventory: dict, teams: dict, settings: dict, now=None) -> dict:
    now = now or now_utc()
    cutoff = months_ago(now, settings["lookback_months"])
    pool = candidate_pool(inventory["repos"], teams, settings, cutoff)
    log(f"Enriching {len(pool)} repos pushed since {iso(cutoff)}")
    names = {r["id"]: r["nameWithOwner"] for r in pool}
    ids = [r["id"] for r in pool]
    size = settings["enrich_batch_size"]
    results: dict = {}
    for start in range(0, len(ids), size):
        fetch_batch(client, ids[start : start + size], iso(cutoff), settings["history_sample"], results, names)
        log(f"  {min(start + size, len(ids))}/{len(ids)}")
    return {"since": iso(cutoff), "repos": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="path to teams.yml")
    args = parser.parse_args(argv)
    if os.environ.get("SKIP_ENRICH", "").lower() == "true":
        log("SKIP_ENRICH=true - writing empty enrichment")
        write_json("enrichment.json", {"since": None, "repos": {}})
        return 0
    settings, teams = load_config(args.config)
    apply_manifest_registry(teams, read_json_optional("manifest.json"))  # known repos need no enrichment
    result = enrich(GitHubClient(), read_json("inventory.json"), teams, settings)
    path = write_json("enrichment.json", result)
    log(f"Wrote {path} ({len(result['repos'])} repos enriched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
