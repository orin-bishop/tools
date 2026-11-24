"""Stage 3 - classify (pure logic, no network).

For every team in config/teams.yml this compares three views of the world:

  tagged      repos that carry the team's GitHub topic
  registry    repos listed under `repos:` in teams.yml (what we believe)
  candidates  untagged, unregistered, unexcluded repos scored on explainable signals

and produces the diff (needs topic / not in registry / not found) plus a ranked
candidate list. Outputs: results.json, needs_action.txt, registry_suggestions.yml,
<team>_repos.csv and candidates.csv.
"""
from __future__ import annotations

import argparse
import csv
import sys

from reportlib import (
    apply_manifest_registry, is_candidate_for, iso, load_config, log, months_ago, now_utc, out_dir,
    parse_ts, read_json, read_json_optional, short_date, write_json,
)


# ------------------------------------------------------------------ scoring

def bucket_for(score: int, thresholds: dict) -> str | None:
    if score >= thresholds["high"]:
        return "high"
    if score >= thresholds["medium"]:
        return "medium"
    if score >= thresholds["low"]:
        return "low"
    return None


def activity_signal(members: set, enrich: dict | None, weights: dict):
    """Weigh recent commits by team members. Uses *share* of commits, not mere presence,
    so a broad shared library that one member touched once doesn't light up."""
    if not enrich or not enrich.get("sampled"):
        return None
    authors = enrich["authors"]
    member_authors = {a: n for a, n in authors.items() if a in members}
    member_commits = sum(member_authors.values())
    if not member_commits:
        return None
    sampled = enrich["sampled"]
    share = member_commits / sampled
    distinct = len(member_authors)
    if share >= 0.50:
        points = weights["activity_strong"]
    elif share >= 0.25:
        points = weights["activity_medium"]
    elif distinct >= 2 and share >= 0.10:
        points = weights["activity_weak"]
    else:
        points = weights["activity_any"]
    who = f"{distinct} team member{'s' if distinct != 1 else ''}"
    reason = f"{who} authored {member_commits} of the last {sampled} commits ({share:.0%})"
    return points, reason


def score_repo(repo: dict, team: dict, members: set, team_access: dict,
               enrich: dict | None, settings: dict, cutoff) -> dict:
    w = settings["weights"]
    name = repo["nameWithOwner"].lower()
    signals: list[tuple[str, int, str]] = []  # (signal, points, human reason)

    role = team_access.get(name)
    if role in ("admin", "maintain"):
        signals.append(("team_access", w["team_admin"], f"{team['github_team']} has {role} access"))
    elif role in ("push", "write"):
        signals.append(("team_access", w["team_push"], f"{team['github_team']} has write access"))

    codeowners = (repo.get("codeowners") or "").lower()
    for handle in team["codeowners_handles"]:
        if handle in codeowners:
            signals.append(("codeowners", w["codeowners"], f"CODEOWNERS references {handle}"))
            break

    if any(rx.search(repo["name"]) for rx in team["name_regexes"]):
        signals.append(("name_match", w["name_match"], "repo name matches team pattern"))

    for topic in repo["topics"]:
        if team["near_miss_regex"].search(topic):
            signals.append(("near_miss_topic", w["near_miss_topic"], f"has similar topic '{topic}'"))
            break

    match = team["keyword_regex"].search(repo["description"] or "")
    if match:
        signals.append(("desc_keyword", w["desc_keyword"], f"description mentions '{match.group(0).lower()}'"))

    if enrich:
        readme_hits = len(team["keyword_regex"].findall(enrich.get("readme_head") or ""))
        if readme_hits >= 2:
            signals.append(("readme_keyword", w["readme_keyword"], f"README mentions team keyword {readme_hits}x"))

    activity = activity_signal(members, enrich, settings["weights"])
    if activity:
        signals.append(("member_activity", activity[0], activity[1]))
        if repo.get("createdAt") and parse_ts(repo["createdAt"]) >= cutoff:
            signals.append(("new_repo", w["new_repo_bonus"], "created inside the lookback window"))

    score = sum(points for _, points, _ in signals)
    stale = not repo.get("pushedAt") or parse_ts(repo["pushedAt"]) < cutoff
    return {
        "score": score,
        "bucket": bucket_for(score, settings["thresholds"]),
        "signals": [s for s, _, _ in signals],
        "reasons": [r for _, _, r in signals],
        "stale": stale,
    }


# ----------------------------------------------------------- per-team logic

def repo_row(repo: dict) -> dict:
    return {
        "full_name": repo["nameWithOwner"],
        "url": repo["url"],
        "description": repo["description"],
        "pushed_at": repo.get("pushedAt"),
        "archived": repo["isArchived"],
        "fork": repo["isFork"],
        "topics": repo["topics"],
    }


def classify_team(team: dict, repos: list[dict], inv_team: dict, enrichment: dict,
                  settings: dict, cutoff) -> dict:
    topic = team["topic"]
    by_name = {r["nameWithOwner"].lower(): r for r in repos}
    members = set(team["members"]) | set(inv_team.get("members", []))
    access = inv_team.get("repos", {})

    tagged = [r for r in repos if topic in r["topics"]]
    tagged_names = {r["nameWithOwner"].lower() for r in tagged}

    def live(repo):  # archived repos aren't worth nagging about unless configured otherwise
        return not (settings["skip_archived"] and repo["isArchived"])

    unregistered = [r for r in tagged if r["nameWithOwner"].lower() not in team["repos"] and live(r)]
    missing_topic = [
        by_name[n] for n in sorted(team["repos"])
        if n in by_name and n not in tagged_names and live(by_name[n])
    ]
    not_found = sorted(n for n in team["repos"] if n not in by_name)

    candidates = []
    for repo in repos:
        if not is_candidate_for(repo, team, settings):
            continue
        result = score_repo(repo, team, members, access, enrichment.get(repo["nameWithOwner"].lower()),
                            settings, cutoff)
        if result["stale"] and not settings["include_stale"]:
            continue
        if result["bucket"]:
            candidates.append({**repo_row(repo), **result})
    candidates.sort(key=lambda c: c["pushed_at"] or "", reverse=True)  # newest push first...
    candidates.sort(key=lambda c: -c["score"])                          # ...then stable sort by score

    known_names = sorted(tagged_names | {n for n in team["repos"] if n in by_name})
    known = [
        {**repo_row(by_name[n]), "tagged": n in tagged_names, "in_registry": n in team["repos"]}
        for n in known_names
    ]

    return {
        "display_name": team["display_name"],
        "topic": topic,
        "members": sorted(members),
        "github_team": team["github_team"],
        "team_error": inv_team.get("error"),
        "known_repos": known,
        "unregistered": [repo_row(r) for r in unregistered],
        "missing_topic": [repo_row(r) for r in missing_topic],
        "registry_not_found": not_found,
        "candidates": candidates,
    }


def action_count(team_result: dict) -> int:
    hot = sum(1 for c in team_result["candidates"] if c["bucket"] in ("high", "medium"))
    return (len(team_result["unregistered"]) + len(team_result["missing_topic"])
            + len(team_result["registry_not_found"]) + hot)


def manifest_summary(manifest: dict | None, team_keys) -> dict:
    """What the report needs from manifest.json (entries stay in manifest.json)."""
    if not manifest or not manifest.get("enabled"):
        return {"enabled": False}
    if manifest.get("error"):
        return {"enabled": True, "error": manifest["error"], "source": manifest.get("source")}
    cmp = manifest["compare"]
    # not_on_github for configured teams is already counted as "registry not found" per team
    unmapped_missing = [e for e in cmp["not_on_github"] if e["team"] not in team_keys]
    actions = len(cmp["topic_drift"]) + len(unmapped_missing) + len(cmp["vocabulary"]["github_not_in_vocab"])
    return {"enabled": True, "source": manifest["source"], "stats": manifest["stats"],
            "unmapped_teams": manifest["unmapped_teams"], "skipped_keys": manifest.get("skipped_keys", []),
            "compare": cmp, "actions": actions}


def build_results(settings: dict, teams: dict, inventory: dict, enrichment: dict, now=None,
                  manifest: dict | None = None) -> dict:
    now = now or now_utc()
    cutoff = months_ago(now, settings["lookback_months"])
    repos = inventory["repos"]
    team_results = {
        key: classify_team(team, repos, inventory.get("teams", {}).get(key, {}),
                           enrichment.get("repos", {}), settings, cutoff)
        for key, team in teams.items()
    }
    manifest_info = manifest_summary(manifest, set(teams))
    total_actions = sum(action_count(t) for t in team_results.values()) + manifest_info.get("actions", 0)
    return {
        "generated_at": iso(now),
        "inventory_generated_at": inventory.get("generated_at"),
        "orgs": settings["orgs"],
        "lookback_months": settings["lookback_months"],
        "cutoff": iso(cutoff),
        "repos_scanned": len(repos),
        "repos_enriched": len(enrichment.get("repos", {})),
        "teams": team_results,
        "manifest": manifest_info,
        "total_actions": total_actions,
        "needs_action": total_actions > 0,
    }


# ------------------------------------------------------------------ outputs

def registry_suggestions(results: dict) -> str:
    """A reviewable YAML doc (one mapping per team) to paste from into config/teams.yml."""
    lines = ["# Suggested changes to config/teams.yml - review before merging.",
             "# add_to_repos -> paste under the team's `repos:`;  needs_topic -> add the GitHub topic;",
             "# review_candidates -> tag + add to `repos:`, or add to `exclude:` if not ours.", ""]
    for key, t in results["teams"].items():
        review = [c for c in t["candidates"] if c["bucket"] in ("high", "medium")]
        sections = [
            ("add_to_repos", [(r["full_name"], "tagged with the topic, not in registry") for r in t["unregistered"]]),
            ("needs_topic", [(r["full_name"], "in registry, topic missing on GitHub") for r in t["missing_topic"]]),
            ("remove_or_fix", [(n, "in registry, not found in scan") for n in t["registry_not_found"]]),
            ("review_candidates", [(c["full_name"], f"{c['bucket']} ({c['score']}): {'; '.join(c['reasons'])}")
                                   for c in review]),
        ]
        sections = [(name, items) for name, items in sections if items]
        if not sections:
            lines += [f"{key}: {{}}  # no changes suggested", ""]
            continue
        lines.append(f"{key}:")
        for name, items in sections:
            lines.append(f"  {name}:")
            lines.extend(f"    - {full_name}  # {note}" for full_name, note in items)
        lines.append("")
    return "\n".join(lines)


def write_outputs(results: dict) -> None:
    write_json("results.json", results)
    directory = out_dir()
    (directory / "needs_action.txt").write_text(str(results["needs_action"]).lower(), encoding="utf-8")
    (directory / "registry_suggestions.yml").write_text(registry_suggestions(results), encoding="utf-8")

    for key, t in results["teams"].items():
        with open(directory / f"{key}_repos.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["repo", "url", "tagged", "in_registry", "archived", "pushed_at", "description"])
            for r in t["known_repos"]:
                w.writerow([r["full_name"], r["url"], r["tagged"], r["in_registry"], r["archived"],
                            short_date(r["pushed_at"]), r["description"]])

    with open(directory / "candidates.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "repo", "url", "bucket", "score", "reasons", "pushed_at", "description"])
        for key, t in results["teams"].items():
            for c in t["candidates"]:
                w.writerow([key, c["full_name"], c["url"], c["bucket"], c["score"],
                            "; ".join(c["reasons"]), short_date(c["pushed_at"]), c["description"]])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="path to teams.yml")
    args = parser.parse_args(argv)
    settings, teams = load_config(args.config)
    manifest = read_json_optional("manifest.json")
    apply_manifest_registry(teams, manifest)   # manifest repos count as registered for their team
    results = build_results(settings, teams, read_json("inventory.json"), read_json("enrichment.json"),
                            manifest=manifest)
    write_outputs(results)
    log(f"needs_action={results['needs_action']} ({results['total_actions']} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
