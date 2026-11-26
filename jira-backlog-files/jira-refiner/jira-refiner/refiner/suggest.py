"""Suggestions (P1-7), template mode: no AI, nothing invented.

For every story that is not "Looks good" this builds a draft a person can accept or change:
  * a suggested description in "As a ..., I want ..., so that ..." form
  * suggested acceptance criteria (only when a confirmed hint supplies them)
  * "Ask in refinement" questions
  * a split suggestion (titles only) when the story looks bigger than its points
  * pointers to well-written related stories and to related context-file sections
  * a better title (drafted from the description), a best-fit epic or a new-epic idea, labels to add,
    and the stories it may duplicate

The guardrails, in code:
  * NO ADDED SCOPE. Words come from the story itself, a confirmed hint, or a work pattern.
    Anything we do not know becomes a question, never a requirement.
  * SHORT. A description is one story line (plus the old text if it is brief). At most
    `max_acceptance_criteria` criteria and `max_questions` questions.
  * HONEST SIZING. 1 point = `points_equal_days` day(s). Splits use the work pattern's own titles.
  * LABELED. Every suggestion carries LABEL, and `basis` lists exactly where it came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .context import ContextIndex, find_hint, find_sections
from .labels import labels_to_add
from .measures import CRITERIA_CODES, DESCRIPTION_CODES, EPIC_CODES, LABEL_CODES, TITLE_CODES
from .sizing import find_work_patterns
from .storyform import reason_in, role_in, want_in, without_role
from .text import natural_key, plain_text, topic_words
from .titles import suggest_title
from .verdict import LOOKS_GOOD, SPLIT_CODES

LABEL = "SUGGESTED - review before use"
PLACEHOLDER = "[reason to confirm in refinement]"

_MAX_NOTES_CHARS = 200          # keep the old description under the new story line only if it is this brief


@dataclass
class Suggestion:
    key: str
    verdict: str
    description: str = ""                                   # '' means "no description suggestion"
    acceptance_criteria: list = field(default_factory=list)
    questions: list = field(default_factory=list)           # "Ask in refinement"
    split_titles: list = field(default_factory=list)
    split_reason: str = ""
    title: str = ""                                         # a better title, '' if the current one is fine
    epic_options: list = field(default_factory=list)        # [(epic key, epic name, score)] best first
    new_epic: str = ""                                      # "Create epic 'X' for A, B, C" when no epic fits
    labels: list = field(default_factory=list)              # labels to add
    duplicates: list = field(default_factory=list)          # [(other key, other title, score)]
    related: list = field(default_factory=list)             # [(key, summary)] of well-written stories
    references: list = field(default_factory=list)          # ["file > heading"] of context sections
    basis: list = field(default_factory=list)               # where each part came from
    needs_confirmation: bool = False                        # True if the description has a placeholder to fill in
    label: str = LABEL


def suggest_all(results, rules, context=None, analysis=None):
    """Return {story key: Suggestion} for every story whose verdict is not 'Looks good'.

    `analysis` (from analysis.analyze) supplies the cross-story facts: epic matches, new-epic ideas and duplicates.
    """
    context = context or ContextIndex()
    well_written = [r.story for r in results if r.verdict == LOOKS_GOOD]
    return {
        r.story.key: suggest_for(r, rules, context, well_written, analysis)
        for r in results
        if r.verdict != LOOKS_GOOD
    }


def suggest_for(result, rules, context, well_written=(), analysis=None):
    story = result.story
    codes = {f.code for f in result.flags}
    summary = plain_text(story.summary)
    description = plain_text(story.description)
    criteria = plain_text(story.acceptance_criteria)
    story_text = f"{summary} {description} {criteria}"

    suggestion = Suggestion(story.key, result.verdict)
    questions = []
    hint = find_hint(context, story_text)

    # --- description -----------------------------------------------------------------------------
    if codes & DESCRIPTION_CODES:
        line, placeholder = _description(summary, description, hint, rules)
        if line and _squash(line) == _squash(description):
            line = ""                                           # nothing to change: the story is already in this form
        elif line:
            suggestion.description = line
            suggestion.needs_confirmation = placeholder
            suggestion.basis.append("description: the story's own summary and description")
            if placeholder:
                questions.append("Why does this matter? The answer fills the 'so that' part of the story.")
        elif not description:
            questions.append("What is this story about? Add a short summary and a sentence or two of description.")

    # --- acceptance criteria ---------------------------------------------------------------------
    if codes & CRITERIA_CODES:
        if hint and hint.acceptance_criteria:
            suggestion.acceptance_criteria = list(hint.acceptance_criteria[: rules.suggest_max_ac])
            suggestion.basis.append(f"acceptance criteria: hint '{hint.name}'")
        else:
            questions.append("What would show that this is done? Write 2 or 3 checks anyone on the team could run.")

    if hint and codes & (DESCRIPTION_CODES | CRITERIA_CODES):
        questions.extend(hint.questions)

    # --- title -----------------------------------------------------------------------------------
    title_flagged = bool(codes & TITLE_CODES)
    if title_flagged and rules.title_suggest:
        suggestion.title = suggest_title(summary, description, rules)
        if suggestion.title:
            suggestion.basis.append("title: drafted from the description")

    # --- epic ------------------------------------------------------------------------------------
    if codes & EPIC_CODES and analysis is not None:
        _epic(suggestion, story, analysis, questions)
    elif codes & EPIC_CODES:
        questions.append("Which current or future epic does this story belong to?")

    # --- labels ----------------------------------------------------------------------------------
    if codes & LABEL_CODES:
        suggestion.labels = labels_to_add(story, rules)
        if suggestion.labels:
            suggestion.basis.append("labels: the rules file")

    # --- duplicates ------------------------------------------------------------------------------
    if "duplicate_story" in codes and analysis is not None:
        _duplicates(suggestion, story, analysis, questions)

    # --- other findings become questions ---------------------------------------------------------
    if "points_missing" in codes:
        questions.append(f"How many days of work is this? Most stories here are {rules.typical_points:g} points "
                         f"(1 point = {_days(rules.points_equal_days)}).")
    if "summary_missing" in codes and not suggestion.title:
        questions.append("What should the summary say? One short line that names the work.")
    if "summary_short" in codes and not suggestion.title:
        questions.append("Can the summary say a little more about the work?")
    if "summary_mismatch" in codes:
        questions.append("The summary and the description may describe different work. Which one is right?")
    for flag in result.flags:
        if flag.code == "other_required_missing" and not (flag.field == "epic" and suggestion.epic_options):
            questions.append(f"Which {flag.field} does this story belong to?")

    # --- split advice ----------------------------------------------------------------------------
    if codes & SPLIT_CODES:
        _split(suggestion, story, rules, summary, description, criteria, questions)

    # --- pointers --------------------------------------------------------------------------------
    topic = _topic_words(f"{summary} {without_role(description)} {criteria}", rules)
    for section in find_sections(context, topic, rules.suggest_min_shared_words, rules.suggest_max_references):
        suggestion.references.append(f"{section.file} > {section.heading}")
    suggestion.related = _related(story, summary, description, well_written, rules)

    suggestion.questions = _unique(questions)[: rules.suggest_max_questions]
    return suggestion


# ---------------------------------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------------------------------

def _description(summary, description, hint, rules):
    """Build one story line. Returns (text, used_placeholder). Text is '' if there is nothing to build from."""
    want = want_in(description)
    if not want:
        if not summary:
            return "", False
        want = _want_from_summary(summary, rules)

    role = role_in(description)
    if not role or (rules.allowed_roles and role.lower() not in rules.allowed_roles):
        role = rules.suggest_default_role

    reason = reason_in(description)
    placeholder = False
    if not reason:
        if hint and hint.so_that:
            reason = hint.so_that
        else:
            reason, placeholder = PLACEHOLDER, True

    article = "an" if role[:1].lower() in "aeiou" else "a"
    line = f"As {article} {role}, I want {want}, so that {reason}."

    # Free text that is not in story form is kept, never thrown away.
    if description and not want_in(description):
        if len(description) <= _MAX_NOTES_CHARS:
            line += f" Existing notes: {description}"
        else:
            line += " Keep the existing text below this line."
    return line, placeholder


def _squash(text):
    """Text with capitals, punctuation and spacing ignored, to tell whether two texts really differ."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _epic(suggestion, story, analysis, questions):
    matches = analysis.epic_matches.get(story.key, [])
    if matches:
        suggestion.epic_options = [(m.epic.key, m.epic.name, m.score) for m in matches]
        suggestion.basis.append("epic: how much of the epic's name appears in the story")
        return
    for proposal in analysis.new_epics:
        if story.key in proposal.keys:
            others = [k for k in proposal.keys if k != story.key]
            suggestion.new_epic = f"Create an epic \"{proposal.name}\" for this story" + (f" and {', '.join(others)}" if others else "")
            suggestion.basis.append("epic: stories that share a word and fit no current epic")
            return
    questions.append("Which current or future epic does this story belong to? No existing epic fits well.")


def _duplicates(suggestion, story, analysis, questions):
    for pair in analysis.pairs:
        if pair.kind != "duplicate" or story.key not in (pair.a.key, pair.b.key):
            continue
        other = pair.b if pair.a.key == story.key else pair.a
        suggestion.duplicates.append((other.key, plain_text(other.summary), pair.score))
    suggestion.duplicates.sort(key=lambda item: (-item[2], natural_key(item[0])))
    if suggestion.duplicates:
        suggestion.basis.append("duplicates: how alike the titles (and descriptions) are")
        questions.append(f"Is this a duplicate of {suggestion.duplicates[0][0]}? If so, close or merge one of them.")


def _want_from_summary(summary, rules):
    text = summary.strip().rstrip(".")
    first = text.split()[0] if text.split() else ""
    # Lower-case the first letter, except for an acronym such as "API" or "RDS" and for a known technology name
    # from the rules file (such as "Terraform"), which keep their capitals.
    keep = (len(first) > 1 and first[1].isupper()) or first.lower() in {w.lower() for w in rules.themes_known}
    lowered = text if keep else text[:1].lower() + text[1:]
    return f"to {lowered}" if first.lower() in rules.suggest_action_verbs else lowered


def _split(suggestion, story, rules, summary, description, criteria, questions):
    patterns = find_work_patterns(rules, summary, description, criteria)
    if patterns:
        titles = []
        for pattern in patterns:
            titles.extend(t for t in pattern.split_into if t not in titles)
        suggestion.split_titles = titles
        suggestion.split_reason = patterns[0].why_bigger
        suggestion.basis.append("split: work pattern " + " and ".join(f"'{p.name}'" for p in patterns))
        if titles:
            questions.append("Which of these pieces does the team need first?")
    elif story.story_points is not None:
        days = story.story_points * rules.points_equal_days
        suggestion.split_reason = (f"At {story.story_points:g} points the story is about {days:g} days of work "
                                   f"with little written down.")
        suggestion.basis.append("split: points and the amount of detail")
        questions.append(f"Can this be broken into pieces of about {rules.typical_points:g} points each?")


def _related(story, summary, description, well_written, rules):
    """Well-written stories in the same epic that share enough words, best first."""
    if rules.suggest_max_related == 0 or not story.epic:
        return []
    mine = _topic_words(f"{summary} {without_role(description)}", rules)
    scored = []
    for other in well_written:
        if other.key == story.key or other.epic != story.epic:
            continue
        theirs = _topic_words(f"{plain_text(other.summary)} {without_role(plain_text(other.description))}", rules)
        shared = mine & theirs
        if len(shared) >= rules.suggest_min_shared_words:
            scored.append((-len(shared), other.key, other.summary))
    scored.sort()
    return [(key, text) for _, key, text in scored[: rules.suggest_max_related]]


def _topic_words(text, rules):
    """Topic words for a story, ignoring the everyday words in the rules file (see text.topic_words)."""
    return topic_words(text, rules.suggest_ignore_words)


def _days(count):
    return f"{count:g} {'day' if count == 1 else 'days'}"


def _unique(items):
    seen, kept = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            kept.append(item)
    return kept


def to_dict(suggestion):
    """A plain dictionary, for JSON files and for the workbook."""
    return {
        "key": suggestion.key,
        "verdict": suggestion.verdict,
        "label": suggestion.label,
        "description": suggestion.description,
        "needs_confirmation": suggestion.needs_confirmation,
        "acceptance_criteria": suggestion.acceptance_criteria,
        "questions": suggestion.questions,
        "split_reason": suggestion.split_reason,
        "split_titles": suggestion.split_titles,
        "title": suggestion.title,
        "epic_options": [{"key": k, "name": n, "score": round(sc, 2)} for k, n, sc in suggestion.epic_options],
        "new_epic": suggestion.new_epic,
        "labels": suggestion.labels,
        "duplicates": [{"key": k, "title": t, "score": round(sc, 2)} for k, t, sc in suggestion.duplicates],
        "related": [{"key": k, "summary": s} for k, s in suggestion.related],
        "references": suggestion.references,
        "basis": suggestion.basis,
    }
