"""The self-check: is this copy ready for a real run?  python -m refiner doctor

Three kinds of line:
  FAIL  must be fixed before a real run (a placeholder REPLACE_... is still there, or a file is broken)
  TODO  works, but still uses a starter example or an empty setting your team should fill in
  OK    done

With --snapshot it also prints the snapshot's SHAPE: counts and percentages only, never any story text, so it is
safe to paste into a chat to check that the Jira fields were mapped correctly.
Exit code 1 if any FAIL (with --strict, also if any TODO). Nothing here talks to Jira.
"""
import re
from dataclasses import dataclass
from pathlib import Path

from .jira_import import load_field_map
from .model import load_data
from .rules import load_rules
from .yamlcheck import SettingsError

STARTER_PATTERNS = {"Encrypt an existing database", "Upgrade a database or its engine", "Upgrade a cluster", "Migrate data or a workload"}
DEFAULT_MARKER = "<!-- {id} START -->"
_PLACEHOLDER = re.compile(r"REPLACE_[A-Z0-9_]+")


@dataclass(frozen=True)
class Check:
    status: str      # FAIL, TODO or OK
    topic: str
    message: str


def find_placeholders(path):
    """[(placeholder, line number)] in a file, skipping comment lines."""
    found = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        found += [(match, number) for match in _PLACEHOLDER.findall(code)]
    return found


def run_checks(rules_path="rules.yaml", fields_path="jira_fields.yaml", context_dir="context", pipeline_dir="pipeline"):
    checks = []
    add = lambda status, topic, message: checks.append(Check(status, topic, message))   # noqa: E731

    # 1. placeholders anywhere they can live
    files = [Path(rules_path), Path(fields_path), Path(context_dir) / "hints.yaml"] + sorted(Path(pipeline_dir).glob("*.yaml"))
    for path in files:
        if not path.is_file():
            continue
        found = find_placeholders(path)
        if found:
            shown = ", ".join(f"{name} (line {line})" for name, line in found[:4]) + (" ..." if len(found) > 4 else "")
            add("FAIL", "placeholders", f"{path} still has {len(found)} REPLACE_ value(s): {shown}")
        else:
            add("OK", "placeholders", f"{path} has no placeholders.")

    # 2. the rules file
    try:
        rules = load_rules(rules_path)
        add("OK", "rules", f"{rules_path} is valid (version {rules.version}).")
    except SettingsError as err:
        add("FAIL", "rules", f"{rules_path} has {len(err.problems)} problem(s). Run: python -m refiner validate-rules")
        rules = None

    # 3. the Jira field map
    if Path(fields_path).is_file():
        try:
            load_field_map(fields_path)
            add("OK", "jira fields", f"{fields_path} is filled in.")
        except SettingsError as err:
            if not any("placeholder" in p for p in err.problems):
                add("FAIL", "jira fields", f"{fields_path}: " + err.problems[0])
    else:
        add("TODO", "jira fields", f"{fields_path} is missing. Copy it from the repository and fill it in.")

    # 4. starter examples and empty settings
    if rules is not None:
        todo = [
            (not rules.jira_base_url, "jira link", "workbook.jira_base_url is empty, so story keys are not links."),
            (not rules.labels_required and not rules.labels_allowed and not rules.label_rules, "labels",
             "The label rules are empty. Add the team's required labels (labels.required_all)."),
            (not rules.allowed_roles, "roles", 'fields.description.story_format.allowed_roles is empty, so any "As a ..." role is accepted.'),
            ([w.lower() for w in rules.themes_known] == ["terraform"], "themes", "themes.known is still the starter example [terraform]. Add your technology names."),
            ({p.name for p in rules.work_patterns} == STARTER_PATTERNS, "work patterns",
             "sizing.work_patterns is still the four starter examples. Add your tech stack and have a person confirm each."),
            (rules.confluence_marker_start == DEFAULT_MARKER, "confluence markers",
             "confluence.marker_start is still the default guess. Match it to the existing publisher."),
            (not rules.schedule_note, "schedule", "schedule.note is empty. Say when the report runs (weekly, before refinement)."),
        ]
        for needed, topic, message in todo:
            add("TODO" if needed else "OK", topic, message if needed else f"{topic}: set.")

    hints = Path(context_dir) / "hints.yaml"
    if hints.is_file() and "MADE-UP SAMPLE" in hints.read_text(encoding="utf-8"):
        add("TODO", "hints", f"{hints} is the made-up sample. Draft real hints from the context repo and have a person confirm each.")
    elif hints.is_file():
        add("OK", "hints", f"{hints} is in place.")
    else:
        add("TODO", "hints", f"No {hints}: acceptance criteria will only ever be asked about, never suggested.")
    return checks


def shape(snapshot_path, intake_csv=None):
    """Counts and percentages only. Returns (lines, warnings)."""
    data = load_data(snapshot_path, intake_csv)
    stories, epics = data.stories, data.epics
    lines, warnings = [], []
    total = len(stories)
    groups = {g: sum(1 for s in stories if s.group == g) for g in ("current_sprint", "future_sprints", "backlog", "intake")}
    lines.append(f"Stories: {total} (current sprint {groups['current_sprint']}, upcoming {groups['future_sprints']}, "
                 f"backlog {groups['backlog']}, not in Jira yet {groups['intake']})")
    types = {}
    for story in stories:
        types[story.issue_type] = types.get(story.issue_type, 0) + 1
    lines.append("Issue types: " + (", ".join(f"{t} {n}" for t, n in sorted(types.items())) or "none"))

    def share(test):
        return round(100 * sum(1 for s in stories if test(s)) / total) if total else 0
    filled = {"summary": share(lambda s: s.summary.strip()), "description": share(lambda s: s.description.strip()),
              "acceptance criteria": share(lambda s: s.acceptance_criteria.strip()), "points": share(lambda s: s.story_points is not None),
              "epic": share(lambda s: s.epic.strip()), "labels": share(lambda s: s.labels), "sprint": share(lambda s: s.sprint.strip())}
    lines.append("Filled in: " + ", ".join(f"{name} {pct}%" for name, pct in filled.items()))
    lines.append(f"Epics: {len(epics)} (with an end date: {sum(1 for e in epics if e.end_date)})")
    lines.append(f"Other Jira fields kept: {len({name for s in stories for name in s.extra})} (names not shown)")

    if total and filled["acceptance criteria"] == 0:
        warnings.append("No story has acceptance criteria. Check story_fields.acceptance_criteria in jira_fields.yaml.")
    if total and filled["points"] == 0:
        warnings.append("No story has points. Check story_fields.story_points in jira_fields.yaml.")
    if total and filled["epic"] == 0:
        warnings.append("No story has an epic. Check story_fields.epic_link in jira_fields.yaml.")
    if total and max(groups.values()) == total and groups["intake"] != total:
        warnings.append("Every story is in one group. Check each export file was passed to the right option (--current, --future, --backlog).")
    if not epics:
        warnings.append("The snapshot has no epics, so finished epics and epic suggestions cannot be checked.")
    return lines, warnings
