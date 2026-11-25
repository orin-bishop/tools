"""The one shape every check works with.

A "snapshot" is a JSON file with a list of stories already turned into this shape.
(Turning raw Jira JSON into this shape is the job of the snapshot step, P1-2. Keeping
that step separate means the checks never need to know Jira field IDs.)
"""
import json
from dataclasses import dataclass, field

GROUPS = ("current_sprint", "future_sprints", "backlog")


@dataclass
class Story:
    key: str
    summary: str = ""
    description: str = ""
    acceptance_criteria: str = ""
    story_points: float = None      # None means "not pointed"
    issue_type: str = "Story"
    status: str = ""
    group: str = "backlog"          # current_sprint, future_sprints or backlog
    sprint: str = ""
    epic: str = ""
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


def load_snapshot(path):
    """Read a snapshot file. It may be a list of stories or {"stories": [...]}."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    items = data.get("stories") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a list of stories or an object with a 'stories' list.")
    return [Story.from_dict(item) for item in items]
