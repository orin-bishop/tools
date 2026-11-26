"""The cross-story analysis: things you can only see by looking at stories TOGETHER.

The per-story checks (checks.py) look at one story at a time. This step looks across the whole set:
duplicates, epics (finished epics, best-fit epics, new epic ideas) and themes. It returns extra findings
for each story plus the lists the reports need. Nothing here changes any story.
"""
from dataclasses import dataclass, field
from datetime import date

from . import duplicates, epics as epic_rules, themes as theme_rules
from .checks import Flag

_FIELD = {"duplicate_story": "summary", "epic_inactive": "epic"}


@dataclass
class Analysis:
    today: date = None
    epics: list = field(default_factory=list)            # every epic given
    active_epics: list = field(default_factory=list)     # the current and future ones
    flags: dict = field(default_factory=dict)            # story key -> [Flag]
    pairs: list = field(default_factory=list)            # duplicates.Pair (duplicate and related)
    duplicate_groups: list = field(default_factory=list)
    epic_matches: dict = field(default_factory=dict)     # story key -> [EpicMatch] for stories that need an epic
    new_epics: list = field(default_factory=list)        # epics.NewEpic
    themes: list = field(default_factory=list)           # themes.Theme


def analyze(stories, epics, rules, today=None):
    """Run the cross-story analysis on `stories` (already limited to what is in scope)."""
    today = epic_rules.resolve_today(rules, today)
    analysis = Analysis(today=today, epics=list(epics))

    def add(found):
        for key, items in found.items():
            for code, message in items:
                analysis.flags.setdefault(key, []).append(Flag(code, rules.severity[code], _FIELD[code], message))

    analysis.pairs = duplicates.find_pairs(stories, rules)
    analysis.duplicate_groups = duplicates.duplicate_groups(analysis.pairs)
    add(duplicates.findings(analysis.pairs))

    if rules.epics_enabled and epics:
        analysis.active_epics = epic_rules.active_epics(epics, rules, today)
        add(epic_rules.inactive_findings(stories, epics, rules, today))

    if rules.epics_enabled:
        by_key = {e.key: e for e in epics}
        unmatched = []
        for story in stories:
            if story.group not in rules.epics_required_groups and not story.epic:
                continue
            if epic_rules.needs_epic(story, by_key, rules, today):
                matches = epic_rules.match_epics(story, analysis.active_epics, rules)
                if matches:
                    analysis.epic_matches[story.key] = matches
                else:
                    unmatched.append(story)
        analysis.new_epics = epic_rules.new_epic_proposals(unmatched, rules)

    analysis.themes = theme_rules.find_themes(stories, rules)
    return analysis
