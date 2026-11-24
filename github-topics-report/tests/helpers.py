"""Test helpers: put scripts/ on sys.path and build fixture data."""
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reportlib import load_config  # noqa: E402

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)   # cutoff = 2026-03-29 with 6 months
RECENT = "2026-09-01T00:00:00Z"
OLD = "2025-11-01T00:00:00Z"

CONFIG_YAML = """
settings:
  orgs: [acme]
  lookback_months: 6
teams:
  pet:
    topic: pet
    github_team: acme/pet
    members: [alice, bob]
    repos: [acme/pet-api, acme/pet-legacy, acme/gone-repo]
    exclude: [acme/pet-excluded]
  viz:
    topic: viz
    repos: [acme/viz-dash]
"""


MANIFEST_SETTINGS = """  manifest:
    enabled: true
    repo: acme/repo-downloader
    path: repos.json
    ref: main
"""


def config_text(manifest=True, manifest_extra=""):
    if not manifest:
        return CONFIG_YAML
    return CONFIG_YAML.replace("  lookback_months: 6\n", "  lookback_months: 6\n" + MANIFEST_SETTINGS + manifest_extra)


def sample_manifest_json():
    return {
        "generated_at": "2026-09-28",
        "topic_list": ["pet", "viz", "platform", "legacy", "go"],
        "teams": {
            "pet": [
                {"name": "pet-api", "topics": ["pet"]},                      # in sync
                {"name": "pet-legacy", "topics": ["pet", "legacy"]},         # GitHub has none
                {"name": "pet-gone", "topics": ["pet"]},                     # not on GitHub
                "outside-org/their-repo",                                    # org we don't scan
            ],
            "viz": [{"name": "viz-dash", "topics": ["viz", "d3"]}],          # d3 not on GitHub
            "platform": [{"name": "shared-lib", "topics": ["platform", "go"]},
                         {"name": "pets-service", "topics": []}],            # GitHub has 'pets'
        },
    }


def make_repo(name, topics=(), desc="", archived=False, fork=False, pushed=RECENT,
              created="2024-01-01T00:00:00Z", codeowners=""):
    return {
        "id": f"ID_{name}", "nameWithOwner": f"acme/{name}", "name": name, "description": desc,
        "url": f"https://github.com/acme/{name}", "isArchived": archived, "isFork": fork,
        "isPrivate": False, "createdAt": created, "pushedAt": pushed,
        "topics": sorted(topics), "codeowners": codeowners,
    }


def write_config(text=CONFIG_YAML):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False)
    tmp.write(text)
    tmp.close()
    return load_config(tmp.name)


def sample_inventory():
    return {
        "generated_at": "2026-09-29T12:00:00Z",
        "orgs": ["acme"],
        "repos": [
            make_repo("pet-api", ["pet"]),                                   # tagged + registered
            make_repo("pet-web", ["pet"]),                                   # tagged, NOT registered
            make_repo("pet-legacy"),                                         # registered, missing topic
            make_repo("viz-dash", ["viz"]),                                  # viz tagged + registered
            make_repo("pet-tools"),                                          # name + team admin -> high
            make_repo("pets-service", ["pets"]),                             # name + near-miss topic -> high
            make_repo("petition-portal", desc="Online petition signing"),    # must NOT match
            make_repo("carpet-cleaner"),                                     # must NOT match
            make_repo("petstore-demo", desc="A pet store demo"),             # description only -> low
            make_repo("shared-lib"),                                         # broad; one member touched it
            make_repo("dash-board", codeowners="* @acme/pet"),               # CODEOWNERS -> medium
            make_repo("old-pet-thing", archived=True),                       # archived -> skipped
            make_repo("pet-fork", fork=True),                                # fork -> skipped
            make_repo("pet-excluded"),                                       # excluded -> skipped
            make_repo("new-thing", created="2026-08-01T00:00:00Z"),          # new + member activity
            make_repo("pet-ancient", pushed=OLD),                            # stale, name match only
        ],
        "teams": {"pet": {"members": ["carol"], "repos": {"acme/pet-tools": "admin", "acme/shared-lib": "pull"}}},
    }


def sample_enrichment():
    return {
        "since": "2026-03-29T12:00:00Z",
        "repos": {
            "acme/shared-lib": {"total_commits": 400, "sampled": 100,
                                "authors": {"alice": 8, "dave": 60, "erin": 32}, "readme_head": ""},
            "acme/new-thing": {"total_commits": 12, "sampled": 12,
                               "authors": {"alice": 6, "carol": 4, "dave": 2}, "readme_head": ""},
            "acme/petstore-demo": {"total_commits": 3, "sampled": 3, "authors": {"dave": 3},
                                   "readme_head": "pet pet pet store"},
        },
    }
