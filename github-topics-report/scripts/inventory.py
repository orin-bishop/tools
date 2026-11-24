"""Stage 1 - inventory.

Enumerates every repository in the configured org(s) (name, description, topics,
archived/fork flags, dates, CODEOWNERS) and, for each team that has a
`github_team`, its member logins and its access level on each repo.

Writes out/inventory.json.
"""
from __future__ import annotations

import argparse
import sys

from ghclient import GitHubClient, GitHubError
from reportlib import iso, load_config, log, now_utc, write_json

CODEOWNERS_CHARS = 20_000

REPO_QUERY = """
query($org: String!, $cursor: String) {
  rateLimit { cost remaining resetAt }
  organization(login: $org) {
    repositories(first: 50, after: $cursor, orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        nameWithOwner
        name
        description
        url
        isArchived
        isFork
        isPrivate
        createdAt
        pushedAt
        repositoryTopics(first: 30) { nodes { topic { name } } }
        coA: object(expression: "HEAD:.github/CODEOWNERS") { ... on Blob { text } }
        coB: object(expression: "HEAD:CODEOWNERS") { ... on Blob { text } }
        coC: object(expression: "HEAD:docs/CODEOWNERS") { ... on Blob { text } }
      }
    }
  }
}
"""


def flatten_repo(node: dict) -> dict:
    topics = sorted(
        {(t.get("topic") or {}).get("name", "").lower() for t in (node.get("repositoryTopics") or {}).get("nodes") or []}
        - {""}
    )
    codeowners = ""
    for alias in ("coA", "coB", "coC"):
        blob = node.get(alias)
        if blob and blob.get("text"):
            codeowners = blob["text"][:CODEOWNERS_CHARS]
            break
    return {
        "id": node["id"],
        "nameWithOwner": node["nameWithOwner"],
        "name": node["name"],
        "description": node.get("description") or "",
        "url": node["url"],
        "isArchived": bool(node.get("isArchived")),
        "isFork": bool(node.get("isFork")),
        "isPrivate": bool(node.get("isPrivate")),
        "createdAt": node.get("createdAt"),
        "pushedAt": node.get("pushedAt"),
        "topics": topics,
        "codeowners": codeowners,
    }


def fetch_org_repos(client, org: str) -> list[dict]:
    repos, cursor = [], None
    while True:
        data = client.graphql(REPO_QUERY, {"org": org, "cursor": cursor})
        org_data = data.get("organization")
        if org_data is None:
            raise GitHubError(f"Organization '{org}' not found or not visible to this token")
        conn = org_data["repositories"]
        repos.extend(flatten_repo(n) for n in conn["nodes"] if n)
        log(f"  {org}: {len(repos)} repos")
        if not conn["pageInfo"]["hasNextPage"]:
            return repos
        cursor = conn["pageInfo"]["endCursor"]


def role_of(team_repo: dict) -> str:
    if team_repo.get("role_name"):
        return team_repo["role_name"].lower()
    perms = team_repo.get("permissions") or {}
    for role in ("admin", "maintain", "push", "triage", "pull"):
        if perms.get(role):
            return role
    return "none"


def fetch_team(client, org_slash_slug: str) -> dict:
    """Members and per-repo role for a GitHub team given as 'org/team-slug'."""
    org, slug = org_slash_slug.split("/", 1)
    members = client.rest_paginated(f"/orgs/{org}/teams/{slug}/members")
    repos = client.rest_paginated(f"/orgs/{org}/teams/{slug}/repos")
    return {
        "members": sorted(m["login"].lower() for m in members),
        "repos": {r["full_name"].lower(): role_of(r) for r in repos},
    }


def build_inventory(client, settings: dict, teams: dict) -> dict:
    repos = []
    for org in settings["orgs"]:
        log(f"Fetching repositories for {org}")
        repos.extend(fetch_org_repos(client, org))

    team_data = {}
    for key, team in teams.items():
        if not team["github_team"]:
            continue
        log(f"Fetching GitHub team {team['github_team']}")
        try:
            team_data[key] = fetch_team(client, team["github_team"])
        except GitHubError as err:  # e.g. token lacks read:org - degrade, don't fail the report
            log(f"  WARNING: could not read team {team['github_team']}: {err}")
            team_data[key] = {"members": [], "repos": {}, "error": str(err)}

    return {
        "generated_at": iso(now_utc()),
        "orgs": settings["orgs"],
        "repos": repos,
        "teams": team_data,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="path to teams.yml")
    args = parser.parse_args(argv)
    settings, teams = load_config(args.config)
    inventory = build_inventory(GitHubClient(), settings, teams)
    path = write_json("inventory.json", inventory)
    log(f"Wrote {path} ({len(inventory['repos'])} repos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
