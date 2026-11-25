"""The quality checks (P1-4). One story in, a list of findings ("flags") out.

A flag says WHAT is wrong, HOW serious it is, and WHICH field to highlight in the workbook.
The sizing checks live in sizing.py and are added at the end.
"""
import re
from dataclasses import dataclass

from .rules import Rules
from .sizing import check_sizing
from .storyform import role_in
from .text import plain_text, words


@dataclass(frozen=True)
class Flag:
    code: str        # one of rules.CHECK_IDS
    severity: str    # high, medium or low (from the rules file)
    field: str       # which field to highlight: summary, description, acceptance_criteria, story_points, ...
    message: str     # one plain sentence a person can act on


def run_checks(story, rules: Rules):
    """Return every finding for one story. An empty list means the story looks good."""
    skipped = rules.type_skips.get(story.issue_type.lower(), frozenset())
    flags = []

    def add(code, field, message):
        if code not in skipped:
            flags.append(Flag(code, rules.severity[code], field, message))

    summary = plain_text(story.summary)
    description = plain_text(story.description)
    criteria = plain_text(story.acceptance_criteria)

    _check_summary(summary, rules, add)
    _check_description(description, rules, add)
    _check_criteria(criteria, rules, add)

    if story.story_points is None and rules.points_required:
        add("points_missing", "story_points", "The story has no points.")

    for name in rules.other_required:
        value = getattr(story, name)
        if not value:
            add("other_required_missing", name, f"The {name} field is empty.")

    _check_summary_match(summary, description, criteria, rules, add)

    for code, message in check_sizing(story, rules, summary, description, criteria):
        add(code, "story_points", message)

    return flags


def _check_summary(summary, rules, add):
    if not summary:
        if rules.summary_required:
            add("summary_missing", "summary", "The summary is empty.")
    elif len(summary) < rules.summary_min_chars:
        add("summary_short", "summary", f"The summary is short ({len(summary)} characters; at least {rules.summary_min_chars} expected).")


def _check_description(description, rules, add):
    if not description:
        if rules.description_required:
            add("description_missing", "description", "The description is empty.")
        return

    if len(description) < rules.description_min_chars:
        add("description_short", "description", f"The description is short ({len(description)} characters; at least {rules.description_min_chars} expected).")

    if rules.story_format_enabled:
        match = re.search(rules.story_format_pattern, description, re.IGNORECASE | re.DOTALL)
        if not match:
            add("description_format", "description", "The description is not in the form 'As a ..., I want ..., so that ...'.")
        elif rules.allowed_roles:
            role = role_in(description)
            if role and role.lower() not in rules.allowed_roles:
                add("description_format", "description", f"The role '{role}' is not on the allowed list: {', '.join(rules.allowed_roles)}.")


def _check_criteria(criteria, rules, add):
    if not criteria:
        if rules.ac_required:
            add("ac_missing", "acceptance_criteria", "The acceptance criteria are empty.")
        return

    if len(criteria) < rules.ac_min_chars:
        add("ac_short", "acceptance_criteria", f"The acceptance criteria are short ({len(criteria)} characters; at least {rules.ac_min_chars} expected).")
        return

    if _left_after_vague_phrases(criteria, rules) < rules.ac_min_chars:
        add("ac_vague", "acceptance_criteria", "The acceptance criteria are vague. They say little more than 'works as expected'.")


def _left_after_vague_phrases(criteria, rules):
    """How many real characters are left once vague phrases like 'TBD' are taken out."""
    text = criteria.lower()
    for phrase in sorted(rules.vague_phrases, key=len, reverse=True):   # longest first
        text = text.replace(phrase, " ")
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return len(re.sub(r"\s+", " ", text).strip())


def _check_summary_match(summary, description, criteria, rules, add):
    if not (rules.summary_match_enabled and summary and description):
        return
    summary_words = set(words(summary))
    if len(summary_words) < rules.summary_match_min_words:
        return
    pool = set(words(description + " " + criteria))
    shared = len(summary_words & pool) / len(summary_words)
    if shared < rules.summary_match_min_overlap:
        add("summary_mismatch", "summary", f"The summary and description share few words ({round(shared * 100)}% of the summary's words appear in the description). Check they describe the same work.")
