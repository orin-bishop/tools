"""The counts shown in the workbook Summary tab and (later) on the Confluence page.

Defined once, here, so both always mean the same thing.
"""
from collections import Counter

from .verdict import MISSING_INFO, NEEDS_REVIEW, LOOKS_GOOD, SUGGEST_SPLIT

POINTS_CODES = frozenset({"points_missing"})
DESCRIPTION_CODES = frozenset({"description_missing", "description_short", "description_format"})
CRITERIA_CODES = frozenset({"ac_missing", "ac_short", "ac_vague"})

# (column title, finding codes that make a story count). Used for the "Yes / No" columns.
MEASURES = (
    ("Not pointed", POINTS_CODES),
    ("Description needs update", DESCRIPTION_CODES),
    ("Acceptance criteria needs update", CRITERIA_CODES),
)
VERDICT_COLUMNS = (SUGGEST_SPLIT, MISSING_INFO, NEEDS_REVIEW, LOOKS_GOOD)

GROUP_TITLES = {
    "current_sprint": "Current sprint",
    "future_sprints": "Upcoming sprints",
    "backlog": "Backlog",
}
NO_LABEL = "No label"


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


def count_by_group(results, include_groups):
    """{group title: count row} in the order of the rules file's scope."""
    return {
        GROUP_TITLES[group]: count_row([r for r in results if r.story.group == group])
        for group in include_groups
    }


def count_by_label(results):
    """{label: count row}. A story with several labels counts once under each; none counts under 'No label'."""
    by_label = {}
    for result in results:
        for label in [x for x in result.story.labels if x] or [NO_LABEL]:
            by_label.setdefault(label, []).append(result)
    return {label: count_row(by_label[label]) for label in sorted(by_label, key=lambda x: (x == NO_LABEL, x.lower()))}
