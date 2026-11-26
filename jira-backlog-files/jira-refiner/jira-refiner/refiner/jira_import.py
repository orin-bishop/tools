"""Turn Jira Data Center exports into the snapshot this tool reads (part of P1-2).

The Fed side already has a Harness pipeline that queries Jira and saves JSON. Save one file per group:

    current sprint issues    e.g. from  /rest/agile/1.0/sprint/{active sprint id}/issue
    upcoming sprint issues   e.g. from  /rest/agile/1.0/sprint/{future sprint id}/issue
    backlog issues           e.g. from  /rest/agile/1.0/board/{board id}/backlog
    epics                    e.g. from  /rest/api/2/search with  issuetype = Epic
    (add ?expand=names to a request to get readable field names for the Raw Jira data tab)

Which file a story came from decides its group, so sprint text never has to be parsed for that.
`jira_fields.yaml` says which custom field holds acceptance criteria, story points, the epic link and the sprint.
Nothing here talks to Jira: it only reads files that were already saved.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .yamlcheck import Reader, SettingsError, load_yaml

GROUP_ORDER = ("current_sprint", "future_sprints", "backlog")      # if a story is in two files, the first group wins
_STANDARD = ("summary", "description", "status", "issuetype", "labels", "assignee")


@dataclass(frozen=True)
class FieldMap:
    acceptance_criteria: str
    story_points: str
    epic_link: str
    sprint: str
    epic_name: str
    epic_start: str
    epic_end: str
    extra: object           # "all", or a tuple of field ids (empty tuple = none)


def load_field_map(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise SettingsError([f"Cannot read the field map {path}: {err.strerror or err}."])
    return parse_field_map(text, source=path.name)


def parse_field_map(text, source="jira_fields.yaml"):
    """Check the field map. Placeholders (REPLACE_...) are reported as problems, so a half-filled map is never used."""
    data, lines = load_yaml(text, source)
    r = Reader(data, lines, source)
    r.mapping([], ("fields_version", "story_fields", "epic_fields", "extra_fields"))
    r.whole(["fields_version"], minimum=1)
    r.mapping(["story_fields"], ("acceptance_criteria", "story_points", "epic_link", "sprint"))
    story = {k: r.text(["story_fields", k]) for k in ("acceptance_criteria", "story_points", "epic_link", "sprint")}
    r.mapping(["epic_fields"], ("name", "start_date", "end_date"))
    epic = {k: r.optional_text(["epic_fields", k]) for k in ("name", "start_date", "end_date")}

    found, extra = r.find(["extra_fields"])
    if not found or extra == "all":
        extra = "all"
    elif isinstance(extra, list) and all(isinstance(x, str) for x in extra):
        extra = tuple(extra)
    else:
        r.bad(["extra_fields"], 'must be all, [] or a list of field ids.')
        extra = "all"

    for path, value in [(["story_fields", k], v) for k, v in story.items()] + [(["epic_fields", k], v) for k, v in epic.items()]:
        if value.startswith("REPLACE_"):
            r.bad(path, f"is still a placeholder ({value}). Put the real field id here, from /rest/api/2/field.")
    if r.problems:
        raise SettingsError(r.problems)
    return FieldMap(story["acceptance_criteria"], story["story_points"], story["epic_link"], story["sprint"],
                    epic["name"] or "summary", epic["start_date"], epic["end_date"], extra)


# ---------------------------------------------------------------------------------------------------
# Reading exports
# ---------------------------------------------------------------------------------------------------

def read_export(path):
    """(issues, names) from a saved Jira response. Accepts a search or Agile response ({"issues": [...]}),
    a list of such pages, or a plain list of issues. `names` maps field ids to readable names when present."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    issues, names = [], {}
    pages = data if isinstance(data, list) else [data]
    for page in pages:
        if isinstance(page, dict) and "issues" in page:
            issues.extend(page.get("issues") or [])
            names.update(page.get("names") or {})
        elif isinstance(page, dict) and "key" in page:
            issues.append(page)
        else:
            raise ValueError(f"{path}: expected a Jira search or Agile response with an 'issues' list.")
    for issue in issues:
        if not isinstance(issue, dict) or "key" not in issue:
            raise ValueError(f"{path}: an issue has no 'key'.")
    return issues, names


def text_of(value):
    """Any Jira field value as plain text: people by display name, options by name or value, lists joined."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, dict):
        for key in ("displayName", "name", "value", "key"):
            if value.get(key) not in (None, ""):
                return str(value[key])
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        return ", ".join(t for t in (text_of(v) for v in value) if t)
    return str(value)


def epic_key_of(value):
    """An epic link as a key: Jira gives either the key itself or an object with a key."""
    if isinstance(value, dict):
        return str(value.get("key") or "")
    return "" if value is None else str(value)


def sprint_name(value):
    """The sprint name. Older Jira gives text like 'com.atlassian...Sprint@1[id=3,...,name=Sprint 12,...]';
    newer exports give an object. A list means several sprints: the last one is the current."""
    if isinstance(value, list):
        return sprint_name(value[-1]) if value else ""
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, str):
        found = re.search(r"name=([^,\]]+)", value)
        return found.group(1) if found else value
    return ""


def _points(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def story_from_issue(issue, group, fmap, names=None):
    """One snapshot story (a dict) from one Jira issue."""
    fields = issue.get("fields") or {}
    epic = fields.get(fmap.epic_link)
    if epic in (None, ""):
        epic = fields.get("epic")                         # Agile API exports carry the epic as an object
    used = set(_STANDARD) | {fmap.acceptance_criteria, fmap.story_points, fmap.epic_link, fmap.sprint, "epic"}
    if fmap.extra == "all":
        wanted = [k for k in fields if k not in used]
    else:
        wanted = [k for k in fmap.extra if k not in used]
    names = names or {}
    extra = {}
    for field_id in sorted(wanted):
        text = text_of(fields.get(field_id))
        if text:
            extra[names.get(field_id, field_id)] = text
    return {
        "key": issue["key"],
        "summary": text_of(fields.get("summary")),
        "description": text_of(fields.get("description")),
        "acceptance_criteria": text_of(fields.get(fmap.acceptance_criteria)),
        "story_points": _points(fields.get(fmap.story_points)),
        "issue_type": text_of(fields.get("issuetype")) or "Story",
        "status": text_of(fields.get("status")),
        "group": group,
        "sprint": sprint_name(fields.get(fmap.sprint)) or sprint_name(fields.get("sprint")),
        "epic": epic_key_of(epic),
        "labels": [str(x) for x in (fields.get("labels") or [])],
        "assignee": text_of(fields.get("assignee")),
        "extra": extra,
    }


def epic_from_issue(issue, fmap):
    fields = issue.get("fields") or {}
    return {
        "key": issue["key"],
        "name": text_of(fields.get(fmap.epic_name)) or text_of(fields.get("summary")),
        "status": text_of(fields.get("status")),
        "start_date": text_of(fields.get(fmap.epic_start))[:10] if fmap.epic_start else "",
        "end_date": text_of(fields.get(fmap.epic_end))[:10] if fmap.epic_end else "",
    }


def build_snapshot(files_by_group, epic_files, fmap):
    """The snapshot as a dict. `files_by_group` maps a group name to a list of export files.

    Returns (snapshot, notes): notes are plain sentences about anything worth knowing (for example a story that
    was in two files)."""
    stories, seen, notes = [], {}, []
    for group in GROUP_ORDER:
        for path in files_by_group.get(group) or []:
            issues, names = read_export(path)
            for issue in issues:
                if issue["key"] in seen:
                    notes.append(f"{issue['key']} is in both {seen[issue['key']]} and {group}; kept it in {seen[issue['key']]}.")
                    continue
                seen[issue["key"]] = group
                stories.append(story_from_issue(issue, group, fmap, names))
    epics = []
    for path in epic_files or []:
        issues, _ = read_export(path)
        epics.extend(epic_from_issue(issue, fmap) for issue in issues)
    return {"note": "Built by python -m refiner snapshot from Jira exports.", "stories": stories, "epics": epics}, notes
