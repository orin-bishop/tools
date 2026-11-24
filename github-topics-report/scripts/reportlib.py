"""Shared helpers for the GitHub topics report pipeline.

Config loading/normalisation, date math, name/keyword matching and JSON I/O.
Everything here is pure (no network) so it can be unit tested offline.
"""
from __future__ import annotations

import calendar
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "teams.yml"

DEFAULT_SETTINGS = {
    "orgs": [],
    "lookback_months": 6,
    "skip_forks": True,          # forks are never suggested as candidates
    "skip_archived": True,       # archived repos are never suggested / flagged
    "include_stale": True,       # score repos with no push inside the window (static signals only)
    "ignore_repos": [],          # fnmatch globs, e.g. "my-org/sandbox-*"
    "enrich_batch_size": 10,     # repos per GraphQL enrichment query
    "max_enrich_repos": 1500,    # safety cap on enrichment volume
    "history_sample": 100,       # commits sampled per repo (GitHub max page = 100)
    "thresholds": {"high": 7, "medium": 4, "low": 2},
    # Manifest = the JSON maintained by the "download all repos, team by team" repo.
    # Used as an extra registry source and compared topic-by-topic against GitHub.
    "manifest": {
        "enabled": False,
        "required": True,        # fail the run if the manifest can't be read/parsed
        "source": "github",      # github (contents API) | file (local path)
        "repo": "",              # org/repo that holds the JSON
        "path": "repos.json",
        "ref": "main",
        "file": "",              # local path when source=file (or env MANIFEST_FILE)
        "teams_path": "",        # dotted path to the team container (auto-detects a top-level 'teams')
        "repos_key": "",         # key holding a team's repo list (default: repos / repositories)
        "team_key": "",          # key naming the team on flat repo records (default: team)
        "team_name_key": "",     # key naming a team on team objects (default: name / team / id)
        "name_key": "",          # key naming a repo (default: full_name / repo / url / name ...)
        "topics_key": "",        # key holding a repo's topics (default: topics / github_topics / tags)
        "topic_list_path": "",   # dotted path to the master topic list (auto-detects 'topics', 'topic_list' ...)
        "team_map": {},          # manifest team name -> teams.yml key, e.g. {platform-pet: pet}
    },
    "weights": {
        "team_admin": 5,         # team has admin/maintain on the repo
        "team_push": 3,          # team has push/write on the repo
        "codeowners": 5,         # CODEOWNERS references the team
        "name_match": 4,         # repo name contains the team token
        "near_miss_topic": 4,    # repo has a topic like 'pets' / 'team-pet'
        "desc_keyword": 2,       # description mentions a team keyword
        "readme_keyword": 1,     # README mentions a keyword 2+ times
        "activity_strong": 4,    # members wrote >= 50% of recent commits
        "activity_medium": 3,    # >= 25%
        "activity_weak": 2,      # >= 10% and 2+ members
        "activity_any": 1,       # any member commit at all
        "new_repo_bonus": 1,     # created inside the window with member activity
    },
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- matching

def token_pattern(token: str) -> str:
    """Regex matching `token` (optionally plural) as a delimited word in a repo name.

    Matches pet, pets, pet-api, api-pet, my_pet_svc. Does not match petition,
    carpet, competition or petstore.
    """
    return rf"(?:^|[-_.\s]){re.escape(token)}s?(?:$|[-_.\s])"


def keyword_regex(keywords: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"\b(?:{alts})s?\b", re.IGNORECASE)


def normalize_repo(entry: str, default_org: str) -> str:
    entry = str(entry).strip().lower()
    return entry if "/" in entry else f"{default_org.lower()}/{entry}"


# ------------------------------------------------------------------ config

def _merge_settings(user: dict) -> dict:
    merged = {**DEFAULT_SETTINGS, **user}
    merged["thresholds"] = {**DEFAULT_SETTINGS["thresholds"], **(user.get("thresholds") or {})}
    merged["weights"] = {**DEFAULT_SETTINGS["weights"], **(user.get("weights") or {})}
    merged["manifest"] = {**DEFAULT_SETTINGS["manifest"], **(user.get("manifest") or {})}
    return merged


def _normalize_team(key: str, cfg: dict, default_org: str) -> dict:
    topic = str(cfg.get("topic") or key).lower()
    gh_team = cfg.get("github_team")
    handles = [h.lower() for h in cfg.get("codeowners_handles") or []]
    if gh_team:
        handles.append("@" + gh_team.lower())
    keywords = [k.lower() for k in (cfg.get("keywords") or [topic])]
    patterns = cfg.get("name_patterns") or [token_pattern(topic)]
    return {
        "key": key,
        "display_name": cfg.get("display_name") or key.upper(),
        "topic": topic,
        "github_team": gh_team,
        "members": {m.lower().lstrip("@") for m in cfg.get("members") or []},
        "repos": {normalize_repo(r, default_org) for r in cfg.get("repos") or []},
        "exclude": {normalize_repo(r, default_org) for r in cfg.get("exclude") or []},
        "name_regexes": [re.compile(p, re.IGNORECASE) for p in patterns],
        "near_miss_regex": re.compile(token_pattern(topic), re.IGNORECASE),
        "keyword_regex": keyword_regex(keywords),
        "codeowners_handles": handles,
    }


def _apply_manifest_env(mf: dict) -> None:
    """MANIFEST_FILE / MANIFEST_REPO / MANIFEST_PATH / MANIFEST_REF override the config file."""
    env = os.environ
    if env.get("MANIFEST_FILE"):
        mf.update(enabled=True, source="file", file=env["MANIFEST_FILE"])
    if env.get("MANIFEST_REPO"):
        mf.update(enabled=True, source="github", repo=env["MANIFEST_REPO"])
    if env.get("MANIFEST_PATH"):
        mf["path"] = env["MANIFEST_PATH"]
    if env.get("MANIFEST_REF"):
        mf["ref"] = env["MANIFEST_REF"]


def load_config(path: str | os.PathLike | None = None) -> tuple[dict, dict]:
    path = Path(path or os.environ.get("REPORT_CONFIG") or DEFAULT_CONFIG)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = _merge_settings(raw.get("settings") or {})
    if os.environ.get("GH_ORGS"):
        settings["orgs"] = [o.strip() for o in os.environ["GH_ORGS"].split(",") if o.strip()]
    if os.environ.get("LOOKBACK_MONTHS"):
        settings["lookback_months"] = int(os.environ["LOOKBACK_MONTHS"])
    _apply_manifest_env(settings["manifest"])
    if not settings["orgs"]:
        raise SystemExit("No GitHub orgs configured (settings.orgs in teams.yml or GH_ORGS env var).")
    default_org = settings["orgs"][0]
    teams = {
        key: _normalize_team(key, cfg or {}, default_org)
        for key, cfg in (raw.get("teams") or {}).items()
    }
    if not teams:
        raise SystemExit("No teams defined in config.")
    return settings, teams


# ------------------------------------------------------------------- dates

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def months_ago(now: datetime, months: int) -> datetime:
    year, month = now.year, now.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def short_date(value: str | None) -> str:
    return value[:10] if value else "-"


# ------------------------------------------------------------- eligibility

def is_ignored(full_name: str, settings: dict) -> bool:
    return any(fnmatch.fnmatch(full_name.lower(), g.lower()) for g in settings["ignore_repos"])


def is_candidate_for(repo: dict, team: dict, settings: dict) -> bool:
    """Could this repo belong to `team` without being tagged/registered/excluded yet?"""
    name = repo["nameWithOwner"].lower()
    if team["topic"] in repo["topics"]:
        return False
    if name in team["repos"] or name in team["exclude"] or is_ignored(name, settings):
        return False
    if settings["skip_archived"] and repo["isArchived"]:
        return False
    if settings["skip_forks"] and repo["isFork"]:
        return False
    return True


# --------------------------------------------------------------------- I/O

def out_dir() -> Path:
    path = Path(os.environ.get("OUT_DIR", "out"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(name: str, obj) -> Path:
    path = out_dir() / name
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_json(name: str):
    return json.loads((out_dir() / name).read_text(encoding="utf-8"))


def read_json_optional(name: str):
    path = out_dir() / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def apply_manifest_registry(teams: dict, manifest: dict | None) -> None:
    """Merge manifest repos into each matching team's registry (in place).

    manifest["teams"] is already keyed by teams.yml key, so this is a plain union.
    """
    if not manifest or not manifest.get("enabled") or manifest.get("error"):
        return
    for key, repos in manifest.get("teams", {}).items():
        if key in teams:
            teams[key]["repos"] = set(teams[key]["repos"]) | set(repos)
