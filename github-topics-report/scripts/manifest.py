"""Stage 1b - manifest sync.

The "download every repo, team by team" repo keeps a JSON manifest of the program's
repos and their topics. This stage pulls that JSON, normalises it, and compares it with
what GitHub actually says (inventory.json):

  * not_on_github    repos in the manifest that the scan can't find (renamed / deleted)
  * topic_drift      per repo: topics on GitHub but not in the manifest, and vice versa
  * vocabulary       the manifest's master topic list vs topics really in use on GitHub
  * multi_team       repos listed under more than one team

Convention: GitHub is the source of truth for *topics* (so drift means "update the manifest");
the manifest is a source of truth for *team membership* (its repos are merged into each
team's registry, so a manifest repo missing its team topic shows up as "needs topic").

The JSON layout is auto-detected (see extract_entries) and every key can be overridden under
`settings.manifest` in config/teams.yml.

Writes out/manifest.json, out/manifest_topic_drift.csv, out/manifest_proposed.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from ghclient import GitHubClient, GitHubError
from reportlib import iso, load_config, log, now_utc, out_dir, read_json, write_json

NAME_KEYS = ("full_name", "nameWithOwner", "repo", "repository", "html_url", "clone_url", "ssh_url",
             "url", "name", "slug")
OWNER_KEYS = ("owner", "org", "organization")
TOPIC_KEYS = ("topics", "github_topics", "tags")
VOCAB_KEYS = ("topic_list", "topic_vocabulary", "available_topics", "allowed_topics", "topics")
REPO_LIST_KEYS = ("repos", "repositories")
TEAM_NAME_KEYS = ("name", "team", "id", "slug")
TEAM_FIELD_KEYS = ("team", "team_name", "group", "owner_team")


class ManifestError(ValueError):
    pass


# --------------------------------------------------------------- parsing

def dig(data, dotted: str):
    for part in filter(None, dotted.split(".")):
        if not (isinstance(data, dict) and part in data):
            raise ManifestError(f"path '{dotted}' not found in manifest (no '{part}')")
        data = data[part]
    return data


def repo_from_text(value: str, default_org: str) -> str:
    """'org/repo', 'repo', 'https://github.com/org/repo', 'git@github.com:org/repo.git' -> 'org/repo'."""
    value = value.strip()
    match = re.search(r"([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", value)
    if match:
        return f"{match.group(1)}/{match.group(2)}".lower()
    return f"{default_org}/{value.removesuffix('.git')}".lower()


def parse_topics(raw) -> list[str]:
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return []
    names = [(t.get("name") if isinstance(t, dict) else t) for t in raw]
    return sorted({str(n).strip().lower() for n in names if n and str(n).strip()})


def _first(raw: dict, keys, want=str):
    for key in keys:
        if isinstance(raw.get(key), want) and raw[key] not in ("", None):
            return key, raw[key]
    return None, None


def parse_entry(raw, team: str | None, mf: dict, default_org: str) -> dict | None:
    """One repo record (string or dict) -> {full_name, team, topics|None}."""
    if isinstance(raw, str):
        return {"full_name": repo_from_text(raw, default_org), "team": team or "", "topics": None}
    if not isinstance(raw, dict):
        return None
    name_keys = ([mf["name_key"]] if mf["name_key"] else []) + list(NAME_KEYS)
    _, name = _first(raw, name_keys)
    if not name:
        return None
    if "/" not in name:
        for key in OWNER_KEYS:
            owner = raw.get(key)
            owner = owner.get("login") or owner.get("name") if isinstance(owner, dict) else owner
            if isinstance(owner, str) and owner:
                name = f"{owner}/{name}"
                break
    topic_keys = ([mf["topics_key"]] if mf["topics_key"] else []) + list(TOPIC_KEYS)
    topics = next((parse_topics(raw[k]) for k in topic_keys if k in raw), None)
    if team is None:
        team_keys = ([mf["team_key"]] if mf["team_key"] else []) + list(TEAM_FIELD_KEYS)
        _, found = _first(raw, team_keys, (str, dict))
        team = (found.get("name") if isinstance(found, dict) else found) or ""
    return {"full_name": repo_from_text(name, default_org), "team": str(team).strip().lower(), "topics": topics}


def repo_container(obj, mf: dict):
    if not isinstance(obj, dict):
        return None
    for key in ([mf["repos_key"]] if mf["repos_key"] else []) + list(REPO_LIST_KEYS):
        if isinstance(obj.get(key), (list, dict)):
            return obj[key]
    return None


def entries_from_repos(container, team: str | None, mf: dict, default_org: str) -> list[dict]:
    if isinstance(container, dict):    # {repo_name: {topics: [...]}}
        items = [({"name": k, **v} if isinstance(v, dict) else k) for k, v in container.items()]
    else:
        items = container
    parsed = (parse_entry(raw, team, mf, default_org) for raw in items)
    return [e for e in parsed if e]


def extract_entries(data, mf: dict, default_org: str) -> tuple[list[dict], list[str]]:
    """Normalise the supported layouts into a flat list of repo entries.

    1. {"pet": ["org/a", ...], "viz": [...]}                         team -> list of repos
    2. {"pet": {"repos": [{"name": "a", "topics": [...]}]}}          team -> object with repos
    3. {"pet": {"a": {"topics": [...]}}}                             team -> {repo: meta}
    4. [{"name": "pet", "repos": [...]}, ...]                        list of team objects
    5. [{"full_name": "org/a", "team": "pet", "topics": [...]}]      flat list, team on each repo
    6. any of the above nested under "teams" or `teams_path`
    """
    root = dig(data, mf["teams_path"]) if mf["teams_path"] else data
    if not mf["teams_path"] and isinstance(root, dict) and isinstance(root.get("teams"), (dict, list)):
        root = root["teams"]
    entries: list[dict] = []
    skipped: list[str] = []
    if isinstance(root, list):
        name_keys = ([mf["team_name_key"]] if mf["team_name_key"] else []) + list(TEAM_NAME_KEYS)
        for item in root:
            container = repo_container(item, mf)
            if container is not None:                                   # layout 4
                _, team = _first(item, name_keys)
                entries += entries_from_repos(container, str(team or "").strip().lower(), mf, default_org)
            else:                                                       # layout 5
                entries += entries_from_repos([item], None, mf, default_org)
    elif isinstance(root, dict):
        flat = repo_container(root, mf)
        if flat is not None:                                            # {"repos": [...]} flat
            entries += entries_from_repos(flat, None, mf, default_org)
        else:
            for team, value in root.items():
                container = repo_container(value, mf)
                if container is None and isinstance(value, list):
                    container = value
                if container is None and isinstance(value, dict) and value and all(
                        isinstance(v, dict) for v in value.values()):
                    container = value                                   # layout 3
                if container is None:
                    skipped.append(str(team))
                    continue
                entries += entries_from_repos(container, str(team).strip().lower(), mf, default_org)
    else:
        raise ManifestError("manifest JSON must be an object or a list")
    return entries, skipped


def extract_vocabulary(data, mf: dict) -> list[str] | None:
    """The manifest's master topic list, if it has one."""
    candidates = [dig(data, mf["topic_list_path"])] if mf["topic_list_path"] else []
    if not candidates and isinstance(data, dict):
        candidates = [data[k] for k in VOCAB_KEYS if k in data and not isinstance(data[k], str)][:1]
    for value in candidates:
        if isinstance(value, dict):
            value = list(value)
        if isinstance(value, list):
            return parse_topics(value)
    return None


# ------------------------------------------------------------- comparison

def compare(entries: list[dict], vocabulary, repos: list[dict], orgs: list[str], team_topics: dict) -> dict:
    by_name = {r["nameWithOwner"].lower(): r for r in repos}
    scanned = {o.lower() for o in orgs}
    not_found, outside, drift, used = [], [], [], set()
    teams_of: dict[str, set] = {}
    for e in entries:
        teams_of.setdefault(e["full_name"], set()).add(e["team"])
        gh = by_name.get(e["full_name"])
        if gh is None:
            bucket = not_found if e["full_name"].split("/")[0] in scanned else outside
            bucket.append({"full_name": e["full_name"], "team": e["team"]})
            continue
        used |= set(gh["topics"])
        if e["topics"] is None:
            continue
        github_only = sorted(set(gh["topics"]) - set(e["topics"]))
        manifest_only = sorted(set(e["topics"]) - set(gh["topics"]))
        team_topic = team_topics.get(e["team"])
        if team_topic in manifest_only:
            manifest_only.remove(team_topic)   # already reported as "registry repo missing the topic"
        if github_only or manifest_only:
            drift.append({"full_name": e["full_name"], "team": e["team"], "url": gh["url"],
                          "github_topics": gh["topics"], "manifest_topics": e["topics"],
                          "github_only": github_only, "manifest_only": manifest_only})
    vocab = {"present": vocabulary is not None, "github_not_in_vocab": [], "vocab_unused": []}
    if vocabulary is not None:
        vocab["github_not_in_vocab"] = sorted(used - set(vocabulary))
        vocab["vocab_unused"] = sorted(set(vocabulary) - used)
    return {
        "not_on_github": not_found,
        "outside_scanned_orgs": outside,
        "topic_drift": drift,
        "vocabulary": vocab,
        "multi_team": sorted(({"repo": n, "teams": sorted(t)} for n, t in teams_of.items() if len(t) > 1),
                             key=lambda x: x["repo"]),
        "repos_with_topic_data": sum(1 for e in entries if e["topics"] is not None),
    }


def build_manifest(data, source: str, settings: dict, teams: dict, inventory: dict) -> dict:
    mf = settings["manifest"]
    team_map = {str(k).lower(): str(v).lower() for k, v in (mf["team_map"] or {}).items()}
    entries, skipped = extract_entries(data, mf, settings["orgs"][0].lower())
    if not entries:
        raise ManifestError("parsed 0 repos from the manifest - check settings.manifest key mappings "
                            f"(top-level keys: {sorted(data)[:10] if isinstance(data, dict) else 'list'})")
    for e in entries:
        e["manifest_team"] = e["team"]
        e["team"] = team_map.get(e["team"], e["team"])
    scanned = {o.lower() for o in settings["orgs"]}
    registry: dict[str, list] = {}
    for e in entries:   # repos in orgs we don't scan are reported separately, not merged as "not found"
        if e["team"] in teams and e["full_name"].split("/")[0] in scanned:
            registry.setdefault(e["team"], []).append(e["full_name"])
    team_topics = {key: t["topic"] for key, t in teams.items()}
    cmp = compare(entries, extract_vocabulary(data, mf), inventory["repos"], settings["orgs"], team_topics)
    all_teams = sorted({e["team"] for e in entries})
    return {
        "enabled": True,
        "source": source,
        "fetched_at": iso(now_utc()),
        "entries": entries,
        "teams": {k: sorted(set(v)) for k, v in registry.items()},
        "unmapped_teams": [t for t in all_teams if t not in teams],
        "skipped_keys": skipped,
        "stats": {"repos": len({e["full_name"] for e in entries}), "teams": len(all_teams),
                  "with_topic_data": cmp["repos_with_topic_data"]},
        "compare": cmp,
    }


# -------------------------------------------------------------------- I/O

def load_manifest_data(mf: dict, client) -> tuple[object, str]:
    if mf["source"] == "file" or mf["file"]:
        path = Path(mf["file"])
        return json.loads(path.read_text(encoding="utf-8")), f"file:{path}"
    if not mf["repo"]:
        raise ManifestError("settings.manifest.repo (or MANIFEST_REPO) is not set")
    data = client.get_file_json(mf["repo"], mf["path"], mf["ref"])
    return data, f"{mf['repo']}@{mf['ref']}:{mf['path']}"


def write_outputs(manifest: dict) -> None:
    write_json("manifest.json", manifest)
    if manifest.get("error") or not manifest.get("enabled"):
        return
    drift = manifest["compare"]["topic_drift"]
    with open(out_dir() / "manifest_topic_drift.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["repo", "team", "on_github_not_in_manifest", "in_manifest_not_on_github", "url"])
        for d in drift:
            w.writerow([d["full_name"], d["team"], " ".join(d["github_only"]), " ".join(d["manifest_only"]), d["url"]])
    vocab = manifest["compare"]["vocabulary"]
    proposed = {
        "convention": "GitHub is the source of truth for topics: set manifest topics to topics_by_repo.",
        "generated_at": manifest["fetched_at"],
        "topics_by_repo": {d["full_name"]: d["github_topics"] for d in drift},
        "vocabulary_additions": vocab["github_not_in_vocab"],
        "vocabulary_unused": vocab["vocab_unused"],
    }
    write_json("manifest_proposed.json", proposed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="path to teams.yml")
    args = parser.parse_args(argv)
    settings, teams = load_config(args.config)
    mf = settings["manifest"]
    if not mf["enabled"]:
        log("Manifest sync disabled (settings.manifest.enabled is false)")
        write_json("manifest.json", {"enabled": False})
        return 0
    try:
        use_file = mf["source"] == "file" or bool(mf["file"])
        data, source = load_manifest_data(mf, None if use_file else GitHubClient())
        manifest = build_manifest(data, source, settings, teams, read_json("inventory.json"))
    except (GitHubError, ManifestError, OSError, ValueError) as err:
        if mf["required"]:
            raise SystemExit(f"Manifest sync failed: {err}")
        log(f"WARNING: manifest sync failed, continuing without it: {err}")
        manifest = {"enabled": True, "error": str(err), "source": mf["repo"] or mf["file"]}
    write_outputs(manifest)
    if not manifest.get("error"):
        c = manifest["compare"]
        log(f"Manifest {manifest['source']}: {manifest['stats']['repos']} repos in "
            f"{manifest['stats']['teams']} teams; {len(c['topic_drift'])} topic drifts, "
            f"{len(c['not_on_github'])} not on GitHub; unmapped teams: {manifest['unmapped_teams'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
