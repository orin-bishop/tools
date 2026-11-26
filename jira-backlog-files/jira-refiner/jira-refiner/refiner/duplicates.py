"""Duplicate and related stories.

Two stories are compared on the topic words of their titles, and on their descriptions when both have one:
  score >= duplicate_at   "possible duplicate": flagged, so a person can close or merge one
  score >= related_at     "related": fine, and listed so similar stories can be grouped
Everything comes from the `duplicates` section of rules.yaml. Role words ("platform engineer") and everyday words
("add", "create") are ignored so unrelated stories do not look alike.
"""
from dataclasses import dataclass

from .storyform import without_role
from .text import jaccard, plain_text, topic_words

DUPLICATE, RELATED = "duplicate", "related"
_MIN_DESCRIPTION_WORDS = 3          # a description needs this many topic words before it is compared


@dataclass(frozen=True)
class Pair:
    a: object                   # Story
    b: object                   # Story
    score: float                # 0 to 1
    title_score: float
    description_score: object   # a number, or None when a description was missing
    kind: str                   # "duplicate" or "related"


def _scores(a_words, b_words, a_desc, b_desc, rules):
    title = jaccard(a_words, b_words)
    if len(a_desc) < _MIN_DESCRIPTION_WORDS or len(b_desc) < _MIN_DESCRIPTION_WORDS:
        return title, title, None
    desc = jaccard(a_desc, b_desc)
    total = rules.dup_title_weight + rules.dup_description_weight
    if total == 0:
        return title, title, desc
    return (rules.dup_title_weight * title + rules.dup_description_weight * desc) / total, title, desc


def find_pairs(stories, rules):
    """Every pair of stories alike enough to be related or duplicate, most alike first."""
    if not rules.dup_enabled:
        return []
    ignore = rules.suggest_ignore_words
    prepared = []
    for story in sorted(stories, key=lambda s: s.key):
        title_words = topic_words(plain_text(story.summary), ignore)
        if len(title_words) >= rules.dup_min_title_words:
            prepared.append((story, title_words, topic_words(without_role(plain_text(story.description)), ignore)))

    pairs = []
    for i, (a, a_title, a_desc) in enumerate(prepared):
        for b, b_title, b_desc in prepared[i + 1:]:
            score, title_score, desc_score = _scores(a_title, b_title, a_desc, b_desc, rules)
            if score >= rules.dup_duplicate_at:
                pairs.append(Pair(a, b, score, title_score, desc_score, DUPLICATE))
            elif score >= rules.dup_related_at:
                pairs.append(Pair(a, b, score, title_score, desc_score, RELATED))
    pairs.sort(key=lambda p: (-p.score, p.a.key, p.b.key))
    return pairs


def duplicate_groups(pairs):
    """Groups of stories that are duplicates of each other (chains join up). [[key, key, ...], ...]"""
    parent = {}

    def root(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for pair in pairs:
        if pair.kind == DUPLICATE:
            parent[root(pair.a.key)] = root(pair.b.key)
    groups = {}
    for key in list(parent):
        groups.setdefault(root(key), []).append(key)
    return sorted(sorted(group) for group in groups.values() if len(group) > 1)


def findings(pairs):
    """{story key: [(check id, message)]}. For a story waiting to be uploaded that matches one already in Jira,
    only the waiting story is flagged (the Jira story is not wrong)."""
    found = {}

    def add(story, other, where):
        found.setdefault(story.key, []).append((
            "duplicate_story",
            f"Possible duplicate of {other.key} ('{plain_text(other.summary)}'){where}: {round(pair.score * 100)}% alike.",
        ))

    for pair in pairs:
        if pair.kind != DUPLICATE:
            continue
        a_new, b_new = pair.a.group == "intake", pair.b.group == "intake"
        if a_new and not b_new:
            add(pair.a, pair.b, ", which is already in Jira")
        elif b_new and not a_new:
            add(pair.b, pair.a, ", which is already in Jira")
        else:
            add(pair.a, pair.b, "")
            add(pair.b, pair.a, "")
    return found
