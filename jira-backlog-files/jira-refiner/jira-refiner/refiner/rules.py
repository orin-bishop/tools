"""Load and check the rules file (rules.yaml).

The rules file is edited by project leads, so this module is strict and friendly:
it checks every setting, collects ALL the problems (not just the first), and says
which line each one is on, in plain words. (The shared reading code is in yamlcheck.py.)
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from .yamlcheck import Reader, SettingsError, load_yaml

# The rules file and the hints file report problems the same way, so they share one error type.
RulesError = SettingsError

# Every check the tool can run. Each one has a severity in the rules file.
CHECK_IDS = (
    "summary_missing",
    "summary_short",
    "summary_mismatch",
    "description_missing",
    "description_short",
    "description_format",
    "ac_missing",
    "ac_short",
    "ac_vague",
    "points_missing",
    "other_required_missing",
    "large_and_thin",
    "possibly_undersized",
)
LEVELS = ("high", "medium", "low")
GROUPS = ("current_sprint", "future_sprints", "backlog")
OTHER_FIELDS = ("epic", "labels", "assignee", "sprint")
SECTION_KEYS = ("summary", "labels", "not_checked")      # the Confluence sections the tool writes


@dataclass(frozen=True)
class WorkPattern:
    """A kind of work that sounds small but usually is not (for example encrypting an existing database)."""

    name: str
    words: tuple         # phrases that trigger it, for example "encrypt database"
    why_bigger: str      # one or two plain sentences on why this is more than a day or two
    split_into: tuple    # how it usually splits into smaller stories (titles only)


@dataclass(frozen=True)
class Rules:
    """The rules, checked and ready to use. Built only by parse_rules()."""

    version: int
    include_groups: tuple
    ignore_statuses: tuple          # lower case
    issue_types: tuple              # as written in the file
    summary_required: bool
    summary_min_chars: int
    description_required: bool
    description_min_chars: int
    story_format_enabled: bool
    story_format_pattern: str
    allowed_roles: tuple            # lower case
    ac_required: bool
    ac_min_chars: int
    vague_phrases: tuple            # lower case
    points_required: bool
    review_at_or_above: float
    other_required: tuple
    summary_match_enabled: bool
    summary_match_min_overlap: float
    summary_match_min_words: int
    points_equal_days: float
    typical_points: float
    max_points_before_keyword_review: float
    thin_chars: int
    work_patterns: tuple            # WorkPattern objects
    suggest_default_role: str
    suggest_max_ac: int
    suggest_max_questions: int
    suggest_max_related: int
    suggest_max_references: int
    suggest_min_shared_words: int
    suggest_ignore_words: tuple     # lower case
    suggest_action_verbs: tuple     # lower case
    workbook_title: str
    workbook_banner: str
    jira_base_url: str              # '' means no links
    raw_column_order: tuple
    confluence_marker_start: str
    confluence_marker_end: str
    confluence_include_markers: bool
    confluence_section_ids: dict    # summary / labels / not_checked -> section id
    confluence_workbook_note: str
    type_skips: dict                # lower-case issue type -> frozenset of check ids
    severity: dict                  # check id -> high / medium / low
    highlight: dict                 # high / medium / low -> color code
    raw: dict                       # the file as loaded, for the "Rules in effect" tab


def load_rules(path):
    """Read and check a rules file. Raises RulesError if anything is wrong."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise RulesError([f"Cannot read the rules file {path}: {err.strerror or err}."])
    return parse_rules(text, source=path.name)


def parse_rules(text, source="rules.yaml"):
    """Check rules text and return a Rules object. Raises RulesError with every problem found."""
    data, lines = load_yaml(text, source)
    r = Reader(data, lines, source)
    r.mapping([], ("rules_version", "scope", "fields", "summary_match", "sizing", "suggestions",
                   "workbook", "confluence", "type_skips", "severity", "highlight"))

    version = r.whole(["rules_version"], minimum=1)

    r.mapping(["scope"], ("include", "ignore_statuses", "issue_types"))
    include = r.text_list(["scope", "include"], non_empty=True, options=GROUPS)
    ignore_statuses = r.text_list(["scope", "ignore_statuses"])
    issue_types = r.text_list(["scope", "issue_types"], non_empty=True)

    r.mapping(["fields"], ("summary", "description", "acceptance_criteria", "story_points", "other_required"))
    r.mapping(["fields", "summary"], ("required", "min_chars"))
    summary_required = r.flag(["fields", "summary", "required"])
    summary_min = r.whole(["fields", "summary", "min_chars"])

    r.mapping(["fields", "description"], ("required", "min_chars", "story_format"))
    description_required = r.flag(["fields", "description", "required"])
    description_min = r.whole(["fields", "description", "min_chars"])
    r.mapping(["fields", "description", "story_format"], ("enabled", "pattern", "allowed_roles"))
    format_enabled = r.flag(["fields", "description", "story_format", "enabled"])
    format_pattern = r.pattern(["fields", "description", "story_format", "pattern"])
    allowed_roles = r.text_list(["fields", "description", "story_format", "allowed_roles"])

    r.mapping(["fields", "acceptance_criteria"], ("required", "min_chars", "vague_phrases"))
    ac_required = r.flag(["fields", "acceptance_criteria", "required"])
    ac_min = r.whole(["fields", "acceptance_criteria", "min_chars"])
    vague = r.text_list(["fields", "acceptance_criteria", "vague_phrases"])

    r.mapping(["fields", "story_points"], ("required", "review_at_or_above"))
    points_required = r.flag(["fields", "story_points", "required"])
    review_at = r.number(["fields", "story_points", "review_at_or_above"], minimum=0, allow_equal=False)
    other_required = r.text_list(["fields", "other_required"], options=OTHER_FIELDS)

    r.mapping(["summary_match"], ("enabled", "min_overlap", "min_summary_words"))
    match_enabled = r.flag(["summary_match", "enabled"])
    match_overlap = r.number(["summary_match", "min_overlap"], minimum=0, maximum=1)
    match_words = r.whole(["summary_match", "min_summary_words"], minimum=1)

    r.mapping(["sizing"], ("points_equal_days", "typical_points", "max_points_before_keyword_review", "thin_chars", "work_patterns"))
    days = r.number(["sizing", "points_equal_days"], minimum=0, allow_equal=False)
    typical = r.number(["sizing", "typical_points"], minimum=0, allow_equal=False)
    max_keyword = r.number(["sizing", "max_points_before_keyword_review"], minimum=0)
    thin = r.whole(["sizing", "thin_chars"])
    patterns = _read_work_patterns(r, ["sizing", "work_patterns"])

    r.mapping(["workbook"], ("title", "banner", "jira_base_url", "raw_column_order"))
    wb_title = r.text(["workbook", "title"])
    wb_banner = r.text(["workbook", "banner"])
    jira_url = r.optional_text(["workbook", "jira_base_url"])
    if jira_url and not jira_url.lower().startswith(("http://", "https://")):
        r.bad(["workbook", "jira_base_url"], 'must start with http:// or https://, or be "" for no links.')
    column_order = r.text_list(["workbook", "raw_column_order"])
    repeated = sorted({c for c in column_order if column_order.count(c) > 1})
    if repeated:
        r.bad(["workbook", "raw_column_order"], f"lists a column more than once: {', '.join(repeated)}.")

    r.mapping(["confluence"], ("marker_start", "marker_end", "include_markers", "section_ids", "workbook_note"))
    marker_start = r.text(["confluence", "marker_start"])
    marker_end = r.text(["confluence", "marker_end"])
    for name, marker in (("marker_start", marker_start), ("marker_end", marker_end)):
        if marker and "{id}" not in marker:
            r.bad(["confluence", name], "must contain {id}, which is replaced by the section id.")
    include_markers = r.flag(["confluence", "include_markers"])
    r.mapping(["confluence", "section_ids"], SECTION_KEYS)
    section_ids = {key: r.text(["confluence", "section_ids", key]) for key in SECTION_KEYS}
    for key, value in section_ids.items():
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
            r.bad(["confluence", "section_ids", key], f"must use only lower case letters, digits and hyphens (found {value!r}).")
    for value in sorted({v for v in section_ids.values() if v and list(section_ids.values()).count(v) > 1}):
        r.bad(["confluence", "section_ids"], f"uses the id '{value}' more than once. Each section needs its own id.")
    workbook_note = r.optional_text(["confluence", "workbook_note"])

    r.mapping(["suggestions"], ("default_role", "max_acceptance_criteria", "max_questions", "max_related_stories",
                                "max_context_references", "min_shared_words", "ignore_when_matching", "action_verbs"))
    default_role = r.text(["suggestions", "default_role"])
    if allowed_roles and default_role and default_role.lower() not in [a.lower() for a in allowed_roles]:
        r.bad(["suggestions", "default_role"], f"must be one of the allowed roles: {', '.join(allowed_roles)}.")
    max_ac = r.whole(["suggestions", "max_acceptance_criteria"], minimum=1)
    max_questions = r.whole(["suggestions", "max_questions"], minimum=1)
    max_related = r.whole(["suggestions", "max_related_stories"])
    max_references = r.whole(["suggestions", "max_context_references"])
    min_shared = r.whole(["suggestions", "min_shared_words"], minimum=1)
    ignore_words = r.text_list(["suggestions", "ignore_when_matching"])
    action_verbs = r.text_list(["suggestions", "action_verbs"])

    type_skips = _read_type_skips(r, ["type_skips"])

    r.mapping(["severity"], CHECK_IDS)
    severity = {cid: r.choice(["severity", cid], LEVELS) for cid in CHECK_IDS}

    r.mapping(["highlight"], LEVELS)
    highlight = {level: r.color(["highlight", level]) for level in LEVELS}

    if r.problems:
        raise RulesError(r.problems)

    return Rules(
        version=version,
        include_groups=tuple(include),
        ignore_statuses=tuple(s.lower() for s in ignore_statuses),
        issue_types=tuple(issue_types),
        summary_required=summary_required,
        summary_min_chars=summary_min,
        description_required=description_required,
        description_min_chars=description_min,
        story_format_enabled=format_enabled,
        story_format_pattern=format_pattern,
        allowed_roles=tuple(s.lower() for s in allowed_roles),
        ac_required=ac_required,
        ac_min_chars=ac_min,
        vague_phrases=tuple(s.lower() for s in vague),
        points_required=points_required,
        review_at_or_above=review_at,
        other_required=tuple(other_required),
        summary_match_enabled=match_enabled,
        summary_match_min_overlap=match_overlap,
        summary_match_min_words=match_words,
        points_equal_days=days,
        typical_points=typical,
        max_points_before_keyword_review=max_keyword,
        thin_chars=thin,
        work_patterns=tuple(patterns),
        suggest_default_role=default_role,
        suggest_max_ac=max_ac,
        suggest_max_questions=max_questions,
        suggest_max_related=max_related,
        suggest_max_references=max_references,
        suggest_min_shared_words=min_shared,
        suggest_ignore_words=tuple(v.lower() for v in ignore_words),
        suggest_action_verbs=tuple(v.lower() for v in action_verbs),
        workbook_title=wb_title,
        workbook_banner=wb_banner,
        jira_base_url=jira_url.rstrip("/"),
        raw_column_order=tuple(column_order),
        confluence_marker_start=marker_start,
        confluence_marker_end=marker_end,
        confluence_include_markers=include_markers,
        confluence_section_ids=section_ids,
        confluence_workbook_note=workbook_note,
        type_skips=type_skips,
        severity=severity,
        highlight=highlight,
        raw=data,
    )


# ---------------------------------------------------------------------------
# Readers for the two settings that are lists of groups (they need rules-only knowledge).
# ---------------------------------------------------------------------------

def _read_work_patterns(r, path):
    """A list of work patterns. It may be empty ([]) but the setting must be there."""
    found, value = r.find(path)
    if not found:
        r.bad(path, "is missing. Add it back. Use [] for none.")
        return []
    if not isinstance(value, list):
        r.bad(path, "must be a list of patterns, each with name, words, why_bigger and split_into. Use [] for none.")
        return []
    patterns = []
    for number in range(len(value)):
        where = path + [number]
        r.mapping(where, ("name", "words", "why_bigger", "split_into"))
        name = r.text(where + ["name"])
        words = r.text_list(where + ["words"], non_empty=True)
        why = r.text(where + ["why_bigger"])
        split = r.text_list(where + ["split_into"])
        patterns.append(WorkPattern(name, tuple(words), why, tuple(split)))
    return patterns


def _read_type_skips(r, path):
    """Optional: issue type -> list of check ids to skip."""
    found, value = r.find(path)
    if not found or value is None:
        return {}
    if not isinstance(value, dict):
        r.bad(path, "should be a list of issue types, each with the checks to skip. Use {} for none.")
        return {}
    result = {}
    for issue_type, ids in value.items():
        where = path + [issue_type]
        if not isinstance(ids, list):
            r.bad(where, "must be a list of check names, for example [description_format].")
            continue
        for cid in ids:
            if cid not in CHECK_IDS:
                close = difflib.get_close_matches(str(cid), CHECK_IDS, n=1)
                tip = f" Did you mean '{close[0]}'?" if close else ""
                r.bad(where, f"has '{cid}', which is not a check this tool knows.{tip}")
        result[str(issue_type).lower()] = frozenset(ids)
    return result
