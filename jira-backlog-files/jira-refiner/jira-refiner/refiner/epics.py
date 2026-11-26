"""Epics: which are current, which stories belong where, and where a new epic might help.

  * A story in a required group MUST have an epic (checked in checks.py: epic_missing).
  * A story whose epic has finished or ended gets epic_inactive (here).
  * For stories that need an epic we suggest the best CURRENT or FUTURE one, by how much of the epic's name
    appears in the story. Stories that fit no epic but share a word can be grouped into a suggested new epic.
Only the epic's NAME is matched, so a short, clear epic name makes for better suggestions.
"""
from dataclasses import dataclass
from datetime import date

from .model import parse_date
from .storyform import without_role
from .text import plain_text, surface_map, topic_words


@dataclass(frozen=True)
class EpicMatch:
    epic: object
    score: float            # share of the epic name's words found in the story (0 to 1)
    shared: tuple           # which words matched


@dataclass(frozen=True)
class NewEpic:
    name: str               # a suggested epic name
    keys: tuple             # the stories it would hold
    word: str


def resolve_today(rules, today=None):
    """Today's date: an explicit value, else the rules file's pretend date, else the real date."""
    if today is not None:
        return today
    return parse_date(rules.epics_today) or date.today()


def active_epics(epics, rules, today):
    """Epics that are current or in the future (not finished by status, not past their end date)."""
    return [e for e in epics if e.is_active(today, rules.epics_ignore_statuses)]


def story_topic(story, rules):
    """Words saying what a story is about: title plus description, without role boilerplate."""
    return topic_words(f"{plain_text(story.summary)} {without_role(plain_text(story.description))}", rules.suggest_ignore_words)


def inactive_findings(stories, epics, rules, today):
    """{story key: [(check id, message)]} for stories whose epic is finished or ended."""
    by_key = {e.key: e for e in epics}
    found = {}
    for story in stories:
        epic = by_key.get(story.epic.strip()) if story.epic else None
        if epic is not None and not epic.is_active(today, rules.epics_ignore_statuses):
            why = f"has status {epic.status}" if epic.status.lower() in rules.epics_ignore_statuses else f"ended on {epic.end_date}"
            found[story.key] = [("epic_inactive", f"Epic {epic.key} ({epic.name}) {why}. Move the story to a current or future epic.")]
    return found


def match_epics(story, active, rules, limit=3):
    """The best current or future epics for a story, best first. Empty if none fits well enough."""
    mine = story_topic(story, rules)
    matches = []
    for epic in active:
        name_words = topic_words(epic.name, rules.suggest_ignore_words)
        if not name_words:
            continue
        shared = mine & name_words
        score = len(shared) / len(name_words)
        if shared and score >= rules.epics_min_match_score:
            matches.append(EpicMatch(epic, score, tuple(sorted(shared))))
    matches.sort(key=lambda m: (-m.score, -len(m.shared), m.epic.key))
    return matches[:limit]


def needs_epic(story, by_key, rules, today):
    """True if the story has no epic, or its epic is finished or ended."""
    if not story.epic.strip():
        return True
    epic = by_key.get(story.epic.strip())
    return epic is not None and not epic.is_active(today, rules.epics_ignore_statuses)


def new_epic_proposals(stories, rules):
    """Group stories that fit no epic by a word they share. `stories` are the ones with no matching epic.

    A word in at least `new_epic_min_stories` of them starts a group; the biggest groups are made first and a
    story joins only one group.
    """
    if not rules.epics_suggest_new:
        return []
    topics = {s.key: story_topic(s, rules) for s in stories}
    counts = {}
    for words_in_story in topics.values():
        for word in words_in_story:
            counts[word] = counts.get(word, 0) + 1
    spelling = surface_map(plain_text(s.summary) for s in stories)

    taken, proposals = set(), []
    for word in sorted(counts, key=lambda w: (-counts[w], w)):
        if counts[word] < rules.epics_new_min_stories:
            break
        keys = sorted(k for k, t in topics.items() if word in t and k not in taken)
        if len(keys) >= rules.epics_new_min_stories:
            taken.update(keys)
            readable = spelling.get(word, word)
            proposals.append(NewEpic(readable.capitalize(), tuple(keys), readable))
    return proposals
