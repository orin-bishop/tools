"""The list of changes: every concrete edit the tool suggests, one row per field, in one place.

The CSV file and the HTML update pack are both built from this list, so they always say the same thing.
Each Change says what to do (kind), where (story and field), what is there now and what to put there:

    update   replace the field with the suggested text      (title, description, acceptance criteria, epic)
    add      add to what is already there                    (labels)
    review   a decision for a person, not text to paste     (possible duplicate, split a story, new epic)

Nothing here writes to Jira.
"""
import csv
from dataclasses import dataclass

from .text import natural_key, plain_text
from .themes import prefix_title

GROUP_ORDER = ("current_sprint", "future_sprints", "backlog", "intake")
FIELD_ORDER = ("Summary", "Description", "Acceptance criteria", "Epic", "Labels", "Duplicate", "Split")
CSV_COLUMNS = ["Key", "Group", "Field", "Kind", "Current", "Suggested", "Reason", "Link"]


@dataclass(frozen=True)
class Change:
    key: str
    group: str
    field: str          # one of FIELD_ORDER
    kind: str           # update, add or review
    current: str
    suggested: str
    reason: str


def issue_url(story, rules):
    """A link to the story in Jira, or '' (no Jira address set, or the story is not in Jira yet)."""
    if rules.jira_base_url and story.group != "intake":
        return f"{rules.jira_base_url}/browse/{story.key}"
    return ""


def build_changes(summary, suggestions, rules):
    """Every suggested edit, grouped by story in report order (current sprint, upcoming, backlog, not in Jira yet)."""
    themed = _themes_by_story(summary.analysis)
    changes = []
    ordered = sorted(summary.results, key=lambda r: (GROUP_ORDER.index(r.story.group), natural_key(r.story.key)))
    for result in ordered:
        story, found = result.story, suggestions.get(result.story.key)
        why = lambda *fields, codes=(): " ".join(f.message for f in result.flags if f.field in fields or f.code in codes)  # noqa: E731

        def add(field, kind, current, suggested, reason):
            changes.append(Change(story.key, story.group, field, kind, current, suggested, reason))

        # Summary: a better title, and/or the theme prefix
        current_title = plain_text(story.summary)
        title, reasons = (found.title if found else ""), []
        if title:
            reasons.append(why("summary"))
        theme = themed.get(story.key)
        if theme:
            base = title or current_title
            prefixed = prefix_title(theme, base, rules)
            if prefixed != base:
                title = prefixed
                reasons.append(f"Theme '{theme.word}': {len(theme.starting)} of {len(theme.keys)} titles start with it, so they sort together.")
        if title and title != current_title:
            add("Summary", "update", current_title, title, " ".join(r for r in reasons if r))

        if found and found.description:
            add("Description", "update", plain_text(story.description, keep_lines=True), found.description, why("description"))
        if found and found.acceptance_criteria:
            add("Acceptance criteria", "update", plain_text(story.acceptance_criteria, keep_lines=True),
                "\n".join(f"* {line}" for line in found.acceptance_criteria), why("acceptance_criteria"))
        if found and found.epic_options:
            key, name, score = found.epic_options[0]
            others = ", ".join(f"{k} {n}" for k, n, _ in found.epic_options[1:])
            add("Epic", "update", story.epic, key,
                f"{why('epic')} Best fit: {name} ({round(score * 100)}% of its name appears in the story)." + (f" Other options: {others}." if others else ""))
        elif found and found.new_epic:
            add("Epic", "review", story.epic, found.new_epic, why("epic"))
        elif found and any(f.field == "epic" for f in result.flags):
            add("Epic", "review", story.epic, "Choose a current or future epic", why("epic") + " No existing epic fits well.")
        if found and found.labels:
            add("Labels", "add", ", ".join(story.labels), " ".join(found.labels), why("labels") + " Keep the existing labels.")
        if found and found.duplicates:
            names = ", ".join(f"{k} ('{t}')" for k, t, _ in found.duplicates[:3])
            add("Duplicate", "review", "", f"Compare with {names} and close or merge the duplicates.", why(codes=("duplicate_story",)))
        if found and found.split_reason:
            titles = "; ".join(found.split_titles) or f"Pieces of about {rules.typical_points:g} points each"
            add("Split", "review", f"{story.story_points:g} points" if story.story_points is not None else "", titles, found.split_reason)

    changes.sort(key=lambda c: (GROUP_ORDER.index(c.group), natural_key(c.key), FIELD_ORDER.index(c.field)))
    return changes


def _themes_by_story(analysis):
    """{story key: the theme its title mentions without starting with it}.

    Only KNOWN themes (listed in the rules file) rewrite titles; found-by-counting themes are only listed in the reports.
    A story that already starts with a theme word is left alone.
    """
    found = {}
    if analysis is None:
        return found
    known = [t for t in analysis.themes if t.known]
    already = {key for theme in known for key in theme.starting}
    for theme in known:                                  # in the order they are listed in the rules file
        for key in theme.keys:
            if key not in theme.starting and key not in already:
                found.setdefault(key, theme)
    return found


def _safe(text):
    """Stop spreadsheet programs from running text that starts like a formula."""
    text = str(text)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def write_changes_csv(path, changes, rules, stories_by_key):
    """One row per change. Opens cleanly in Excel (UTF-8 with a byte order mark)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for change in changes:
            link = issue_url(stories_by_key[change.key], rules) if change.key in stories_by_key else ""
            writer.writerow([_safe(x) for x in (change.key, change.group, change.field, change.kind, change.current,
                                                change.suggested, change.reason, link)])
