"""Shared helpers for the tests."""
import copy
from pathlib import Path

import yaml

from refiner.model import Story
from refiner.rules import parse_rules

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "rules.yaml"
SNAPSHOT_PATH = ROOT / "fixtures" / "snapshot.json"
_BASE = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def rules_with(edit=None):
    """The real rules.yaml, optionally changed by `edit(dict)` first."""
    data = copy.deepcopy(_BASE)
    if edit:
        edit(data)
    return parse_rules(yaml.safe_dump(data))


GOOD = dict(
    key="T-1",
    summary="Add health check to demo service",
    description="As a platform engineer, I want a health check endpoint on the demo service, so that the pipeline can confirm it is up.",
    acceptance_criteria="* The endpoint returns 200 when the service is up\n* The endpoint returns 503 when the database is down",
    story_points=2,
    issue_type="Story",
    status="In Progress",
    group="current_sprint",
    epic="T-100",
    labels=["platform"],
)


def make_story(**changes):
    data = dict(GOOD)
    data.update(changes)
    return Story.from_dict(data)
