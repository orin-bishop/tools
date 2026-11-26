"""The shapes every check works with, and how data is loaded.

A "snapshot" is a JSON file with:
    stories   Jira stories already turned into the Story shape below
    intake    optional: stories NOT in Jira yet (planned uploads). They get group "intake" and a temporary key NEW-1, NEW-2 ...
    epics     optional: the team's epics (key, name, status, start_date, end_date)
Intake stories can also come from a CSV file (see load_intake_csv). Turning raw Jira JSON into this shape is
the job of the snapshot step (P1-2), so the checks never need to know Jira field IDs.
"""
import csv
import json
from dataclasses import dataclass, field
from datetime import date

GROUPS = ("current_sprint", "future_sprints", "backlog", "intake")


def parse_date(value, label="date"):
    """A date from 'YYYY-MM-DD' (extra time text after the date is ignored). '' or None gives None."""
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValueError(f"{label}: '{value}' is not a date like 2026-12-31.")


@dataclass
class Epic:
    key: str
    name: str = ""
    status: str = ""
    start_date: date = None      # None means "no start date"
    end_date: date = None        # None means "no end date"

    @classmethod
    def from_dict(cls, data):
        if "key" not in data or not str(data["key"]).strip():
            raise ValueError("An epic in the snapshot has no 'key'.")
        key = str(data["key"]).strip()
        return cls(
            key=key,
            name=str(data.get("name") or data.get("summary") or ""),
            status=str(data.get("status") or ""),
            start_date=parse_date(data.get("start_date"), f"epic {key} start_date"),
            end_date=parse_date(data.get("end_date"), f"epic {key} end_date"),
        )

    def is_active(self, today, ignore_statuses=()):
        """Current or future: not finished (by status) and not past its end date."""
        if self.status.lower() in [s.lower() for s in ignore_statuses]:
            return False
        return self.end_date is None or self.end_date >= today


@dataclass
class Story:
    key: str
    summary: str = ""
    description: str = ""
    acceptance_criteria: str = ""
    story_points: float = None      # None means "not pointed"
    issue_type: str = "Story"
    status: str = ""
    group: str = "backlog"          # current_sprint, future_sprints, backlog, or intake (not in Jira yet)
    sprint: str = ""
    epic: str = ""                  # an epic KEY
    labels: list = field(default_factory=list)
    assignee: str = ""
    extra: dict = field(default_factory=dict)   # every other Jira field, as name -> text (for the Raw data tab)

    @classmethod
    def from_dict(cls, data):
        """Build a Story from a dictionary. Unknown keys are ignored."""
        if "key" not in data or not str(data["key"]).strip():
            raise ValueError("A story in the snapshot has no 'key'.")
        key = str(data["key"]).strip()

        def text(name, default=""):
            value = data.get(name)
            return default if value is None else str(value)

        group = text("group", "backlog")
        if group not in GROUPS:
            raise ValueError(f"{key}: group '{group}' must be one of {', '.join(GROUPS)}.")

        points = data.get("story_points")
        if points in (None, ""):
            points = None
        else:
            try:
                points = float(points)
            except (TypeError, ValueError):
                raise ValueError(f"{key}: story_points '{points}' is not a number.")

        labels = data.get("labels") or []
        if isinstance(labels, str):
            labels = [labels]

        extra = data.get("extra") or {}
        if not isinstance(extra, dict):
            raise ValueError(f"{key}: 'extra' must be a set of field names and values.")

        return cls(
            key=key,
            summary=text("summary"),
            description=text("description"),
            acceptance_criteria=text("acceptance_criteria"),
            story_points=points,
            issue_type=text("issue_type", "Story"),
            status=text("status"),
            group=group,
            sprint=text("sprint"),
            epic=text("epic"),
            labels=[str(x) for x in labels],
            assignee=text("assignee"),
            extra={str(name): "" if value is None else str(value) for name, value in extra.items()},
        )


@dataclass
class Snapshot:
    stories: list = field(default_factory=list)     # Jira stories AND intake stories (group 'intake')
    epics: list = field(default_factory=list)


def load_data(path, intake_csv=None):
    """Read a snapshot file (and optionally an intake CSV). Returns a Snapshot."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        data = {"stories": data}
    if not isinstance(data, dict) or not isinstance(data.get("stories"), list):
        raise ValueError(f"{path}: expected a list of stories or an object with a 'stories' list.")

    stories = [Story.from_dict(item) for item in data["stories"]]
    intake = data.get("intake") or []
    if not isinstance(intake, list):
        raise ValueError(f"{path}: 'intake' must be a list of stories.")
    for number, item in enumerate(intake, start=1):
        item = dict(item)
        item["group"] = "intake"
        item.setdefault("key", f"NEW-{number}")
        stories.append(Story.from_dict(item))

    epics = data.get("epics") or []
    if not isinstance(epics, list):
        raise ValueError(f"{path}: 'epics' must be a list of epics.")
    snapshot = Snapshot(stories, [Epic.from_dict(item) for item in epics])

    if intake_csv:
        snapshot.stories.extend(load_intake_csv(intake_csv, first_number=len(intake) + 1))
    return snapshot


def load_snapshot(path):
    """Just the stories (Jira and intake) from a snapshot file."""
    return load_data(path).stories


# ---------------------------------------------------------------------------------------------------
# Intake CSV: stories a project lead plans to upload but that are not in Jira yet
# ---------------------------------------------------------------------------------------------------

_CSV_COLUMNS = {
    "key": "key", "id": "key",
    "summary": "summary", "title": "summary",
    "description": "description",
    "acceptance criteria": "acceptance_criteria", "acceptance_criteria": "acceptance_criteria", "ac": "acceptance_criteria",
    "story points": "story_points", "story_points": "story_points", "points": "story_points",
    "issue type": "issue_type", "issue_type": "issue_type", "type": "issue_type",
    "labels": "labels", "label": "labels",
    "epic": "epic", "epic link": "epic",
}


def load_intake_csv(path, first_number=1):
    """Read an intake CSV. Needs a Summary (or Title) column. Labels may be separated by commas or semicolons."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path}: the intake file is empty. It needs a header row with at least a 'Summary' column.")
        mapping = {}
        for name in reader.fieldnames:
            field_name = _CSV_COLUMNS.get(str(name).strip().lower())
            if field_name and field_name not in mapping.values():
                mapping[name] = field_name
        if "summary" not in mapping.values():
            raise ValueError(f"{path}: the intake file needs a 'Summary' (or 'Title') column. Found: {', '.join(reader.fieldnames)}.")

        stories, number = [], first_number
        for line, row in enumerate(reader, start=2):          # line 1 is the header
            item = {mapping[name]: (value or "").strip() for name, value in row.items() if name in mapping}
            if not any(item.values()):
                continue                                      # a blank line
            if "labels" in item:
                item["labels"] = [x.strip() for x in item["labels"].replace(";", ",").split(",") if x.strip()]
            item["group"] = "intake"
            if not item.get("key"):
                item["key"] = f"NEW-{number}"
                number += 1
            try:
                stories.append(Story.from_dict(item))
            except ValueError as err:
                raise ValueError(f"{path}, line {line}: {err}")
    return stories
