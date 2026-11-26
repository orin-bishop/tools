"""The counts shown in the workbook Summary tab and (later) on the Confluence page.

Defined once, here, so both always mean the same thing.
"""
from collections import Counter

from .text import natural_key
from .verdict import MISSING_INFO, NEEDS_REVIEW, LOOKS_GOOD, SUGGEST_SPLIT

POINTS_CODES = frozenset({"points_missing"})
DESCRIPTION_CODES = frozenset({"description_missing", "description_short", "description_brief", "description_format"})
CRITERIA_CODES = frozenset({"ac_missing", "ac_short", "ac_brief", "ac_vague"})
EPIC_CODES = frozenset({"epic_missing", "epic_inactive"})
DUPLICATE_CODES = frozenset({"duplicate_story"})
TITLE_CODES = frozenset({"summary_missing", "summary_short", "summary_mismatch", "title_long"})
LABEL_CODES = frozenset({"labels_missing", "label_unknown", "labels_suggested"})

# (column title, finding codes that make a story count). Used for the "Yes / No" columns.
MEASURES = (
    ("Not pointed", POINTS_CODES),
    ("Description needs update", DESCRIPTION_CODES),
    ("Acceptance criteria needs update", CRITERIA_CODES),
    ("Epic needs attention", EPIC_CODES),
    ("Possible duplicate", DUPLICATE_CODES),
    ("Title needs attention", TITLE_CODES),
    ("Labels need attention", LABEL_CODES),
)
VERDICT_COLUMNS = (SUGGEST_SPLIT, MISSING_INFO, NEEDS_REVIEW, LOOKS_GOOD)

GROUP_TITLES = {
    "current_sprint": "Current sprint",
    "future_sprints": "Upcoming sprints",
    "backlog": "Backlog",
    "intake": "Not in Jira yet",
}
NO_LABEL = "No label"
NO_EPIC = "No epic"


def has_any(flags, codes):
    """True if any finding's code is in `codes`."""
    return any(flag.code in codes for flag in flags)


def label_key(story):
    """Labels as '|a|b|' so a formula can match one whole label (never part of another)."""
    labels = [label for label in story.labels if label] or [NO_LABEL]
    return "|" + "|".join(labels) + "|"


def count_row(results):
    """Counts for a set of StoryResults: stories, each measure, each verdict. Same numbers as the workbook formulas."""
    row = {"Stories": len(results)}
    for title, codes in MEASURES:
        row[title] = sum(1 for r in results if has_any(r.flags, codes))
    verdicts = Counter(r.verdict for r in results)
    for verdict in VERDICT_COLUMNS:
        row[verdict] = verdicts.get(verdict, 0)
    return row


def shown_groups(results, include_groups):
    """The groups to show as rows. 'Not in Jira yet' is shown only when there are such stories."""
    has_intake = any(r.story.group == "intake" for r in results)
    return [g for g in include_groups if g != "intake" or has_intake]


def count_by_group(results, include_groups):
    """{group title: count row} in the order of the rules file's scope."""
    return {
        GROUP_TITLES[group]: count_row([r for r in results if r.story.group == group])
        for group in shown_groups(results, include_groups)
    }


def epic_key(story):
    """The story's epic key, or 'No epic'."""
    return story.epic.strip() or NO_EPIC


def count_by_epic(results, epics=()):
    """{epic key: (epic name, count row)} for the epics stories use, in key order, with 'No epic' last.
    'No epic' is always there, because the goal is for it to be zero."""
    names = {e.key: e.name for e in epics}
    grouped = {NO_EPIC: []}
    for result in results:
        grouped.setdefault(epic_key(result.story), []).append(result)
    order = sorted((k for k in grouped if k != NO_EPIC), key=natural_key) + [NO_EPIC]
    return {key: (names.get(key, ""), count_row(grouped[key])) for key in order}


def count_by_label(results):
    """{label: count row}. A story with several labels counts once under each; none counts under 'No label'."""
    by_label = {}
    for result in results:
        for label in [x for x in result.story.labels if x] or [NO_LABEL]:
            by_label.setdefault(label, []).append(result)
    return {label: count_row(by_label[label]) for label in sorted(by_label, key=lambda x: (x == NO_LABEL, x.lower()))}
