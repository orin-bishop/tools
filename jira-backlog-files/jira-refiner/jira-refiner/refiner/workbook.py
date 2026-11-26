"""The Excel workbook (P1-8): every story, every finding, every suggestion, filterable.

Tabs, in order:
  Table of Contents   what is in the file, the color key, the rules version
  Summary             counts by group and by label. These are FORMULAS that read the Findings tab,
                      so filtering or editing Findings never leaves the numbers behind.
  Findings            one row per checked story, weak cells shaded by severity, with a comment saying why
  Suggestions         one row per story that has a draft, plus an "Approved?" column for later use
  Changes             every concrete edit, one row per field: what is there now and what to put there
  Epics               the team's epics (current and future first) with story counts, and the stories that need an epic
  Duplicates          pairs of stories that are possible duplicates or just related
  Themes              words in several titles, and whether titles start with them
  Raw Jira data       every story in the snapshot, every Jira field, original text, column order from rules.yaml
  Rules in effect     a copy of the rules that produced this file

Nothing here writes to Jira.
"""
from __future__ import annotations

import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink

from .changes import build_changes
from .measures import (GROUP_TITLES, MEASURES, NO_EPIC, NO_LABEL, VERDICT_COLUMNS, count_by_epic, count_by_group, epic_key,
                       has_any, label_key, shown_groups)
from .runner import out_of_scope_reason
from .suggest import LABEL as SUGGESTION_LABEL
from .text import natural_key, plain_text
from .themes import prefix_title
from .yamlcheck import dotted

TOC, SUMMARY, FINDINGS, SUGGESTIONS, CHANGES, EPICS, DUPLICATES, THEMES, RAW, RULES = (
    "Table of Contents", "Summary", "Findings", "Suggestions", "Changes", "Epics", "Duplicates", "Themes",
    "Raw Jira data", "Rules in effect")

FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
INPUT_FILL = PatternFill("solid", fgColor="DDEBF7")        # light blue: a cell a person fills in
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")      # characters Excel files cannot hold
_MAX_CELL = 32000                                           # Excel's limit is 32,767 characters per cell
_LEVEL_ORDER = {"high": 3, "medium": 2, "low": 1}

# Which column to shade for each finding's field, per tab.
_FINDINGS_FIELD_COLUMN = {"summary": "Summary", "description": "Description", "acceptance_criteria": "Acceptance criteria",
                          "story_points": "Points", "epic": "Epic", "labels": "Labels", "assignee": "Assignee", "sprint": "Sprint"}
_RAW_FIELD_COLUMN = dict(_FINDINGS_FIELD_COLUMN, story_points="Story points")


def build_workbook(summary, stories, suggestions, rules, context=None, generated=None):
    """Build the workbook and return it (an openpyxl Workbook). Call save_workbook() to write it."""
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    wb = Workbook()
    toc = wb.active
    toc.title = TOC
    sheets = {name: wb.create_sheet(name) for name in (SUMMARY, FINDINGS, SUGGESTIONS, CHANGES, EPICS, DUPLICATES, THEMES, RAW, RULES)}
    changes = build_changes(summary, suggestions, rules)

    findings_cols = _write_findings(sheets[FINDINGS], summary, rules)
    raw_cols = _write_raw(sheets[RAW], summary, stories, rules)
    _write_suggestions(sheets[SUGGESTIONS], summary, suggestions, rules)
    _write_changes(sheets[CHANGES], changes, rules)
    _write_epics(sheets[EPICS], summary, suggestions, rules, findings_cols)
    _write_duplicates(sheets[DUPLICATES], summary, rules)
    _write_themes(sheets[THEMES], summary, rules)
    total_cell = _write_summary(sheets[SUMMARY], summary, rules, findings_cols, raw_cols)
    _write_rules(sheets[RULES], rules)
    _write_toc(toc, summary, rules, context, generated, total_cell)

    wb.properties.title = rules.workbook_title
    wb.properties.subject = rules.workbook_banner
    wb.properties.creator = "Jira Backlog Refiner"
    wb.calculation.fullCalcOnLoad = True        # Excel works out the formulas as soon as the file opens
    return wb


def save_workbook(path, *args, **kwargs):
    build_workbook(*args, **kwargs).save(path)


# ---------------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------------

def _clean(value):
    """Text that is safe to put in a cell: no control characters, and short enough for Excel."""
    text = _ILLEGAL.sub("", str(value))
    if len(text) > _MAX_CELL:
        text = text[:_MAX_CELL] + " ... [cut: the text was longer than Excel allows in one cell]"
    return text


def _text(ws, row, col, value, *, bold=False, italic=False, size=10, color=None, fill=None, wrap=False, valign="top"):
    """Write one cell in Arial. Anything that is not a formula goes through here.

    Text is always stored AS TEXT, even when it starts with '=' (Jira text sometimes does, and
    openpyxl would otherwise turn it into a formula). Numbers are written as numbers.
    """
    cell = ws.cell(row=row, column=col)
    if isinstance(value, str):
        cell.value = _clean(value)
        cell.data_type = "s"
    else:
        cell.value = value
    cell.font = Font(name=FONT, size=size, bold=bold, italic=italic, color=color)
    if fill:
        cell.fill = fill
    cell.alignment = Alignment(wrap_text=wrap, vertical=valign)
    return cell


def _formula(ws, row, col, formula, **kwargs):
    cell = ws.cell(row=row, column=col, value=formula)
    cell.font = Font(name=FONT, size=10, bold=kwargs.get("bold", False))
    cell.alignment = Alignment(vertical="top")
    return cell


def _banner(ws, rules, width=8):
    return _text(ws, 1, 1, rules.workbook_banner, italic=True, size=9, color="7F7F7F")


def _header(ws, row, titles, widths):
    for index, (title, width) in enumerate(zip(titles, widths), start=1):
        cell = _text(ws, row, index, title, bold=True, color="FFFFFF", fill=HEADER_FILL, wrap=True, valign="center")
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.row_dimensions[row].height = 32


def _finish_table(ws, header_row, titles, last_row, freeze_col="B"):
    last = max(last_row, header_row + 1)
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(titles))}{last}"
    ws.freeze_panes = f"{freeze_col}{header_row + 1}"


def _points(story):
    points = story.story_points
    if points is None:
        return None
    return int(points) if float(points).is_integer() else points


def _shade(rules, flags, field_to_column, column_index, ws, row, comments):
    """Shade the cell of every flagged field by its worst severity. Optionally add a comment saying why."""
    worst, notes = {}, {}
    for flag in flags:
        column = field_to_column.get(flag.field)
        if column not in column_index:
            continue
        if _LEVEL_ORDER[flag.severity] > _LEVEL_ORDER.get(worst.get(column, ""), 0):
            worst[column] = flag.severity
        notes.setdefault(column, []).append(flag.message)
    for column, severity in worst.items():
        cell = ws.cell(row=row, column=column_index[column])
        cell.fill = PatternFill("solid", fgColor=rules.highlight[severity])
        if comments:
            comment = Comment("\n".join(notes[column]), "Refiner")
            comment.width, comment.height = 360, 40 + 30 * len(notes[column])
            cell.comment = comment


def _key_cell(ws, row, col, key, rules, group=""):
    """A story key. It links to the story in Jira when an address is set, except for stories not in Jira yet."""
    cell = _text(ws, row, col, key)
    if rules.jira_base_url and group != "intake":
        cell.hyperlink = f"{rules.jira_base_url}/browse/{key}"
        cell.font = Font(name=FONT, size=10, color="0563C1", underline="single")
    return cell


_PREVIEW_CHARS = 300


def _preview(value):
    """Readable text for the Findings tab: markup removed, line breaks kept, long text shortened.
    (The Raw Jira data tab keeps the full original.)"""
    text = plain_text(value, keep_lines=True)
    return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS].rstrip() + " ... [shortened: see Raw Jira data]"


def _quote(sheet_name):
    return "'" + sheet_name.replace("'", "''") + "'"


# ---------------------------------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------------------------------

_FINDINGS_TITLES = ["Key", "Type", "Group", "Sprint", "Epic", "Labels", "Assignee", "Points", "Summary", "Verdict",
                    "Worst severity", "Description", "Acceptance criteria"] + [m[0] for m in MEASURES] + \
                   ["Findings", "Details", "Label key (used by Summary)", "Epic key (used by Summary)"]
_FINDINGS_WIDTH = {"Key": 12, "Type": 9, "Group": 17, "Sprint": 14, "Epic": 12, "Labels": 18, "Assignee": 18, "Points": 8,
                   "Summary": 40, "Verdict": 15, "Worst severity": 10, "Description": 58, "Acceptance criteria": 58,
                   "Findings": 30, "Details": 70, "Label key (used by Summary)": 22, "Epic key (used by Summary)": 22}
_FINDINGS_WIDTHS = [_FINDINGS_WIDTH.get(title, 15) for title in _FINDINGS_TITLES]      # measure columns default to 15


def _write_findings(ws, summary, rules):
    _banner(ws, rules)
    _header(ws, 2, _FINDINGS_TITLES, _FINDINGS_WIDTHS)
    index = {title: i for i, title in enumerate(_FINDINGS_TITLES, start=1)}

    for offset, result in enumerate(summary.results):
        row = 3 + offset
        story = result.story
        _key_cell(ws, row, index["Key"], story.key, rules, story.group)
        _text(ws, row, index["Type"], story.issue_type)
        _text(ws, row, index["Group"], GROUP_TITLES[story.group])
        _text(ws, row, index["Sprint"], story.sprint)
        _text(ws, row, index["Epic"], story.epic)
        _text(ws, row, index["Labels"], ", ".join(story.labels))
        _text(ws, row, index["Assignee"], story.assignee)
        _text(ws, row, index["Points"], _points(story))
        ws.cell(row=row, column=index["Points"]).alignment = Alignment(horizontal="center", vertical="top")
        _text(ws, row, index["Summary"], plain_text(story.summary), wrap=True)
        _text(ws, row, index["Verdict"], result.verdict)
        _text(ws, row, index["Worst severity"], result.worst_severity)
        _text(ws, row, index["Description"], _preview(story.description), wrap=True)
        _text(ws, row, index["Acceptance criteria"], _preview(story.acceptance_criteria), wrap=True)
        for title, codes in MEASURES:
            _text(ws, row, index[title], "Yes" if has_any(result.flags, codes) else "No")
        _text(ws, row, index["Findings"], "; ".join(f.code for f in result.flags))
        _text(ws, row, index["Details"], "\n".join(f"[{f.severity}] {f.message}" for f in result.flags), wrap=True)
        _text(ws, row, index["Label key (used by Summary)"], label_key(story), color="7F7F7F")
        _text(ws, row, index["Epic key (used by Summary)"], epic_key(story), color="7F7F7F")
        _shade(rules, result.flags, _FINDINGS_FIELD_COLUMN, index, ws, row, comments=True)

    _finish_table(ws, 2, _FINDINGS_TITLES, 2 + len(summary.results))
    return {title: get_column_letter(i) for title, i in index.items()}


# ---------------------------------------------------------------------------------------------------
# Raw Jira data
# ---------------------------------------------------------------------------------------------------

_CORE_RAW = ["Key", "Type", "Status", "Group", "Sprint", "Epic", "Labels", "Assignee", "Story points",
             "Summary", "Description", "Acceptance criteria", "Checked", "Verdict"]
_RAW_WIDTHS = {"Key": 12, "Type": 9, "Status": 13, "Group": 17, "Sprint": 14, "Epic": 12, "Labels": 18, "Assignee": 18,
               "Story points": 8, "Summary": 40, "Description": 60, "Acceptance criteria": 60, "Checked": 30, "Verdict": 15}


def _raw_value(story, column, checked, verdict):
    return {
        "Key": story.key, "Type": story.issue_type, "Status": story.status, "Group": GROUP_TITLES[story.group],
        "Sprint": story.sprint, "Epic": story.epic, "Labels": ", ".join(story.labels), "Assignee": story.assignee,
        "Story points": _points(story), "Summary": story.summary, "Description": story.description,
        "Acceptance criteria": story.acceptance_criteria, "Checked": checked, "Verdict": verdict,
    }[column]


def _raw_columns(stories, rules):
    """The column order: the rules file's list first, then anything left out (other Jira fields A to Z)."""
    extras = sorted({name for s in stories for name in s.extra}, key=str.lower)
    extras = [name if name not in _CORE_RAW else f"{name} (Jira)" for name in extras]
    everything = _CORE_RAW + [e for e in extras if e not in _CORE_RAW]
    chosen = [c for c in rules.raw_column_order if c in everything]
    return chosen + [c for c in everything if c not in chosen]


def _write_raw(ws, summary, stories, rules):
    _banner(ws, rules)
    columns = _raw_columns(stories, rules)
    _header(ws, 2, columns, [_RAW_WIDTHS.get(c, 18) for c in columns])
    index = {title: i for i, title in enumerate(columns, start=1)}
    results = {r.story.key: r for r in summary.results}

    for offset, story in enumerate(stories):
        row = 3 + offset
        result = results.get(story.key)
        reason = out_of_scope_reason(story, rules)
        checked = "Yes" if result else (reason or "No")
        verdict = result.verdict if result else ""
        for column in columns:
            if column in _CORE_RAW:
                value = _raw_value(story, column, checked, verdict)
            else:
                value = story.extra.get(column[:-7] if column.endswith(" (Jira)") else column, "")
            if column == "Key":
                _key_cell(ws, row, index[column], value, rules, story.group)
            else:
                _text(ws, row, index[column], value)
        if result:
            _shade(rules, result.flags, _RAW_FIELD_COLUMN, index, ws, row, comments=False)

    _finish_table(ws, 2, columns, 2 + len(stories), freeze_col="B")
    return {title: get_column_letter(i) for title, i in index.items()}


# ---------------------------------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------------------------------

_SUGGESTION_TITLES = ["Key", "Summary", "Verdict", "Status", "Suggested description", "Needs confirmation",
                      "Suggested acceptance criteria", "Ask in refinement", "Split reason", "Proposed split titles",
                      "Similar well-written stories", "Related context", "Based on", "Approved?"]
_SUGGESTION_WIDTHS = [12, 36, 15, 20, 60, 14, 50, 50, 40, 44, 36, 36, 36, 11]


def _bullets(items):
    return "\n".join(f"- {item}" for item in items)


def _write_suggestions(ws, summary, suggestions, rules):
    _banner(ws, rules)
    _header(ws, 2, _SUGGESTION_TITLES, _SUGGESTION_WIDTHS)
    index = {title: i for i, title in enumerate(_SUGGESTION_TITLES, start=1)}
    summaries = {r.story.key: plain_text(r.story.summary) for r in summary.results}
    groups = {r.story.key: r.story.group for r in summary.results}

    row = 3
    for key, s in suggestions.items():
        _key_cell(ws, row, index["Key"], key, rules, groups.get(key, ""))
        _text(ws, row, index["Summary"], summaries.get(key, ""), wrap=True)
        _text(ws, row, index["Verdict"], s.verdict)
        _text(ws, row, index["Status"], s.label, wrap=True)
        _text(ws, row, index["Suggested description"], s.description, wrap=True)
        _text(ws, row, index["Needs confirmation"], "Yes" if s.needs_confirmation else "")
        _text(ws, row, index["Suggested acceptance criteria"], _bullets(s.acceptance_criteria), wrap=True)
        _text(ws, row, index["Ask in refinement"], _bullets(s.questions), wrap=True)
        _text(ws, row, index["Split reason"], s.split_reason, wrap=True)
        _text(ws, row, index["Proposed split titles"], _bullets(s.split_titles), wrap=True)
        _text(ws, row, index["Similar well-written stories"], "\n".join(f"{k}: {t}" for k, t in s.related), wrap=True)
        _text(ws, row, index["Related context"], "\n".join(s.references), wrap=True)
        _text(ws, row, index["Based on"], "\n".join(s.basis), wrap=True)
        ws.cell(row=row, column=index["Approved?"]).fill = INPUT_FILL
        row += 1

    if not suggestions:
        _text(ws, 3, 1, "No story needs a suggestion. Every checked story looks good.", italic=True)
    else:
        approval = DataValidation(type="list", formula1='"Y,N"', allow_blank=True, showErrorMessage=True,
                                  errorTitle="Approved?", error="Type Y or N, or leave it empty.")
        ws.add_data_validation(approval)
        letter = get_column_letter(index["Approved?"])
        approval.add(f"{letter}3:{letter}{row - 1}")
    _finish_table(ws, 2, _SUGGESTION_TITLES, row - 1)


# ---------------------------------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------------------------------

_CHANGE_TITLES = ["Key", "Group", "Field", "Kind", "Current", "Suggested", "Reason", "Done?"]
_CHANGE_WIDTHS = [12, 17, 18, 9, 45, 55, 55, 9]


def _write_changes(ws, changes, rules):
    _banner(ws, rules)
    _header(ws, 2, _CHANGE_TITLES, _CHANGE_WIDTHS)
    row = 3
    for change in changes:
        _key_cell(ws, row, 1, change.key, rules, change.group)
        _text(ws, row, 2, GROUP_TITLES[change.group])
        _text(ws, row, 3, change.field)
        _text(ws, row, 4, change.kind)
        _text(ws, row, 5, change.current, wrap=True)
        _text(ws, row, 6, change.suggested, wrap=True)
        _text(ws, row, 7, change.reason, wrap=True)
        ws.cell(row=row, column=8).fill = INPUT_FILL
        row += 1
    if not changes:
        _text(ws, 3, 1, "No changes are suggested.", italic=True)
    else:
        done = DataValidation(type="list", formula1='"Y,N"', allow_blank=True, showErrorMessage=True,
                              errorTitle="Done?", error="Type Y or N, or leave it empty.")
        ws.add_data_validation(done)
        done.add(f"H3:H{row - 1}")
    _finish_table(ws, 2, _CHANGE_TITLES, row - 1)


# ---------------------------------------------------------------------------------------------------
# Epics
# ---------------------------------------------------------------------------------------------------

_EPIC_TITLES = ["Epic", "Name", "Status", "Start", "End", "Current or future?", "Stories"]
_EPIC_WIDTHS = [14, 40, 14, 12, 12, 18, 10]


def _write_epics(ws, summary, suggestions, rules, findings_cols):
    _banner(ws, rules)
    _header(ws, 2, _EPIC_TITLES, _EPIC_WIDTHS)
    analysis = summary.analysis
    active = {e.key for e in analysis.active_epics}
    helper = findings_cols["Epic key (used by Summary)"]
    column = f"{_quote(FINDINGS)}!${helper}:${helper}"

    row = 3
    for epic in sorted(analysis.epics, key=lambda e: (e.key not in active, natural_key(e.key))):
        _key_cell(ws, row, 1, epic.key, rules)
        _text(ws, row, 2, epic.name)
        _text(ws, row, 3, epic.status)
        _text(ws, row, 4, str(epic.start_date or ""))
        _text(ws, row, 5, str(epic.end_date or ""))
        _text(ws, row, 6, "Yes" if epic.key in active else "No")
        _formula(ws, row, 7, f"=COUNTIFS({column},$A{row})")
        row += 1
    _text(ws, row, 1, NO_EPIC, bold=True)
    _formula(ws, row, 7, f"=COUNTIFS({column},$A{row})", bold=True)
    _finish_table(ws, 2, _EPIC_TITLES, row)

    row += 2
    _text(ws, row, 1, f"Current or future means not finished and not past its end date, as of {analysis.today}. "
                      "The Stories column is a formula on the Findings tab. 'No epic' should be 0.", italic=True, size=9, color="595959")

    # To the right of the epic list (its own, wider columns): the stories that need an epic, then new-epic ideas.
    left = len(_EPIC_TITLES) + 2                     # one empty column between the two tables
    for offset, width in enumerate([12, 40, 12, 50]):
        ws.column_dimensions[get_column_letter(left + offset)].width = width
    needing = [r for r in summary.results if {f.code for f in r.flags} & {"epic_missing", "epic_inactive"}]
    _text(ws, 1, left, "Stories that need an epic", bold=True, size=12)
    for index, title in enumerate(["Story", "Summary", "Epic now", "Suggestion"]):
        _text(ws, 2, left + index, title, bold=True, color="FFFFFF", fill=HEADER_FILL)
    row = 2
    if not needing:
        row += 1
        _text(ws, row, left, "Every story has a current or future epic.", italic=True)
    for result in sorted(needing, key=lambda r: natural_key(r.story.key)):
        row += 1
        story, found = result.story, suggestions.get(result.story.key)
        if found and found.epic_options:
            idea = "; ".join(f"{k} {n} ({round(sc * 100)}%)" for k, n, sc in found.epic_options)
        elif found and found.new_epic:
            idea = found.new_epic
        else:
            idea = "No existing epic fits well. Choose one."
        _key_cell(ws, row, left, story.key, rules, story.group)
        _text(ws, row, left + 1, plain_text(story.summary), wrap=True)
        _text(ws, row, left + 2, story.epic)
        _text(ws, row, left + 3, idea, wrap=True)

    if analysis.new_epics:
        row += 3
        _text(ws, row, left, "Ideas for new epics (stories that share a word and fit no current epic)", bold=True, size=12)
        row += 1
        for index, title in enumerate(["Name", "Stories"]):
            _text(ws, row, left + index, title, bold=True, color="FFFFFF", fill=HEADER_FILL)
        for proposal in analysis.new_epics:
            row += 1
            _text(ws, row, left, proposal.name)
            _text(ws, row, left + 1, ", ".join(proposal.keys), wrap=True)


# ---------------------------------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------------------------------

_DUP_TITLES = ["Kind", "Alike", "Story A", "Title A", "Group A", "Story B", "Title B", "Group B", "Note"]
_DUP_WIDTHS = [18, 9, 12, 40, 17, 12, 40, 17, 36]


def _write_duplicates(ws, summary, rules):
    _banner(ws, rules)
    _header(ws, 2, _DUP_TITLES, _DUP_WIDTHS)
    stories = {r.story.key: r.story for r in summary.results}
    row = 3
    for pair in summary.analysis.pairs:
        a, b = stories.get(pair.a.key, pair.a), stories.get(pair.b.key, pair.b)
        _text(ws, row, 1, "Possible duplicate" if pair.kind == "duplicate" else "Related")
        _text(ws, row, 2, round(pair.score, 2)).number_format = "0%"
        _key_cell(ws, row, 3, a.key, rules, a.group)
        _text(ws, row, 4, plain_text(a.summary), wrap=True)
        _text(ws, row, 5, GROUP_TITLES[a.group])
        _key_cell(ws, row, 6, b.key, rules, b.group)
        _text(ws, row, 7, plain_text(b.summary), wrap=True)
        _text(ws, row, 8, GROUP_TITLES[b.group])
        waiting = [x.key for x in (a, b) if x.group == "intake"]
        if pair.kind == "duplicate" and len(waiting) == 1:
            _text(ws, row, 9, f"{waiting[0]} is not in Jira yet. The other one already is.")
        elif pair.kind == "duplicate":
            _text(ws, row, 9, "Close or merge one of them.")
        else:
            _text(ws, row, 9, "Fine as they are. Consider grouping them.")
        row += 1
    if not summary.analysis.pairs:
        _text(ws, 3, 1, "No duplicate or related stories were found.", italic=True)
    _finish_table(ws, 2, _DUP_TITLES, row - 1)


# ---------------------------------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------------------------------

_THEME_TITLES = ["Theme", "Where from", "Titles", "Start with it", "Consistent?", "Mention it but do not start with it",
                 "Suggested titles (listed themes only)"]
_THEME_WIDTHS = [16, 22, 8, 12, 12, 50, 55]


def _write_themes(ws, summary, rules):
    _banner(ws, rules)
    _header(ws, 2, _THEME_TITLES, _THEME_WIDTHS)
    stories = {r.story.key: r.story for r in summary.results}
    row = 3
    for theme in summary.analysis.themes:
        rest = [k for k in theme.keys if k not in theme.starting]
        _text(ws, row, 1, theme.word)
        _text(ws, row, 2, "Listed in the rules file" if theme.known else "Found by counting")
        _text(ws, row, 3, len(theme.keys))
        _text(ws, row, 4, len(theme.starting))
        _text(ws, row, 5, "Yes" if theme.consistent else "No")
        _text(ws, row, 6, "\n".join(f"{k}: {plain_text(stories[k].summary)}" for k in rest), wrap=True)
        suggested = [f"{k}: {prefix_title(theme, plain_text(stories[k].summary), rules)}" for k in rest] if theme.known else []
        _text(ws, row, 7, "\n".join(suggested), wrap=True)
        row += 1
    if not summary.analysis.themes:
        _text(ws, 3, 1, "No themes were found.", italic=True)
    _finish_table(ws, 2, _THEME_TITLES, row - 1)


# ---------------------------------------------------------------------------------------------------
# Summary (formulas)
# ---------------------------------------------------------------------------------------------------

_SUMMARY_COLUMNS = ["Stories"] + [m[0] for m in MEASURES] + list(VERDICT_COLUMNS)


def _count_formulas(row, header_row, findings_cols, criteria_ref, criteria_column):
    """One row of COUNTIFS formulas. `criteria_column` is the Findings column that holds the group or label key."""
    f = _quote(FINDINGS) + "!"
    key = f"{f}${criteria_column}:${criteria_column}"
    formulas = [f"=COUNTIFS({key},{criteria_ref})"]
    for title, _ in MEASURES:
        col = findings_cols[title]
        formulas.append(f'=COUNTIFS({key},{criteria_ref},{f}${col}:${col},"Yes")')
    verdict_col = findings_cols["Verdict"]
    for offset, _ in enumerate(VERDICT_COLUMNS):
        header_cell = f"{get_column_letter(2 + len(MEASURES) + 1 + offset)}${header_row}"
        formulas.append(f"=COUNTIFS({key},{criteria_ref},{f}${verdict_col}:${verdict_col},{header_cell})")
    return formulas


def _summary_header(ws, row, first_title):
    titles = [first_title] + _SUMMARY_COLUMNS
    for index, title in enumerate(titles, start=1):
        _text(ws, row, index, title, bold=True, color="FFFFFF", fill=HEADER_FILL, wrap=True, valign="center")
    ws.row_dimensions[row].height = 44


def _write_summary(ws, summary, rules, findings_cols, raw_cols):
    _banner(ws, rules)
    _text(ws, 2, 1, "Summary", bold=True, size=14)
    _text(ws, 3, 1, "Every number below is a formula that counts rows on the Findings tab. Filter Findings to see the stories behind a number.",
          italic=True, size=9, color="595959")
    ws.column_dimensions["A"].width = 26
    for number in range(2, 3 + len(_SUMMARY_COLUMNS)):
        ws.column_dimensions[get_column_letter(number)].width = 15
    ws.column_dimensions[get_column_letter(2 + len(_SUMMARY_COLUMNS))].width = 30         # the epic name column

    # --- by group -----------------------------------------------------------------------------------
    header = 5
    _text(ws, 4, 1, "By group", bold=True)
    _summary_header(ws, header, "Group")
    groups = [GROUP_TITLES[g] for g in shown_groups(summary.results, rules.include_groups)]
    for offset, title in enumerate(groups):
        row = header + 1 + offset
        _text(ws, row, 1, title)
        for col, formula in enumerate(_count_formulas(row, header, findings_cols, f"$A{row}", findings_cols["Group"]), start=2):
            _formula(ws, row, col, formula)
    first, last = header + 1, header + len(groups)
    total_row = last + 1
    _text(ws, total_row, 1, "Total", bold=True)
    for col in range(2, 2 + len(_SUMMARY_COLUMNS)):
        letter = get_column_letter(col)
        _formula(ws, total_row, col, f"=SUM({letter}{first}:{letter}{last})", bold=True)

    # --- by epic ------------------------------------------------------------------------------------
    epic_rows = count_by_epic(summary.results, summary.analysis.epics if summary.analysis else ())
    epic_header = total_row + 3
    name_col = 2 + len(_SUMMARY_COLUMNS)
    _text(ws, epic_header - 1, 1, "By epic", bold=True)
    _text(ws, epic_header - 1, 4, "Every story should have an epic: the 'No epic' row should be 0. The list of epics was taken from this run.",
          italic=True, size=9, color="595959")
    _summary_header(ws, epic_header, "Epic")
    _text(ws, epic_header, name_col, "Epic name", bold=True, color="FFFFFF", fill=HEADER_FILL, wrap=True, valign="center")
    epic_col = findings_cols["Epic key (used by Summary)"]
    for offset, (key, (name, _)) in enumerate(epic_rows.items()):
        row = epic_header + 1 + offset
        _text(ws, row, 1, key)
        for col, formula in enumerate(_count_formulas(row, epic_header, findings_cols, f"$A{row}", epic_col), start=2):
            _formula(ws, row, col, formula)
        _text(ws, row, name_col, name or ("" if key == NO_EPIC else "(not in the epic list)"))

    # --- by label -----------------------------------------------------------------------------------
    labels = sorted({label for r in summary.results for label in ([x for x in r.story.labels if x] or [NO_LABEL])},
                    key=lambda x: (x == NO_LABEL, x.lower()))
    label_header = epic_header + len(epic_rows) + 3
    _text(ws, label_header - 1, 1, "By label", bold=True)
    _text(ws, label_header - 1, 4, "A story with several labels counts under each one, so these rows can add up to more than the total.",
          italic=True, size=9, color="595959")
    _summary_header(ws, label_header, "Label")
    label_col = findings_cols["Label key (used by Summary)"]
    for offset, label in enumerate(labels):
        row = label_header + 1 + offset
        _text(ws, row, 1, label)
        criteria = f'"*|"&$A{row}&"|*"'
        for col, formula in enumerate(_count_formulas(row, label_header, findings_cols, criteria, label_col), start=2):
            _formula(ws, row, col, formula)
    after_labels = label_header + len(labels) + 2
    if labels:
        _text(ws, after_labels - 1, 1, "The list of labels was taken from this run. The counts are formulas.",
              italic=True, size=9, color="595959")

    # --- not checked --------------------------------------------------------------------------------
    start = after_labels + 2
    _text(ws, start - 1, 1, "Stories in the snapshot that were not checked", bold=True)
    checked_col = raw_cols["Checked"]
    raw_ref = f"{_quote(RAW)}!${checked_col}:${checked_col}"
    _text(ws, start, 1, "Reason", bold=True, color="FFFFFF", fill=HEADER_FILL)
    _text(ws, start, 2, "Stories", bold=True, color="FFFFFF", fill=HEADER_FILL)
    row = start + 1
    _text(ws, row, 1, "Checked")
    _formula(ws, row, 2, f'=COUNTIF({raw_ref},"Yes")')
    for reason in sorted(summary.skipped):
        row += 1
        _text(ws, row, 1, reason)
        _formula(ws, row, 2, f"=COUNTIF({raw_ref},$A{row})")
    ws.freeze_panes = "B6"
    return f"{_quote(SUMMARY)}!$B${total_row}"


# ---------------------------------------------------------------------------------------------------
# Rules in effect
# ---------------------------------------------------------------------------------------------------

def _flatten(value, path=()):
    """Turn the loaded rules into (setting path, value) rows a person can read."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, path + (key,))
    elif isinstance(value, list) and any(isinstance(x, (dict, list)) for x in value):
        for number, item in enumerate(value):
            yield from _flatten(item, path + (number,))
    elif isinstance(value, list):
        yield dotted(path), ", ".join(str(x) for x in value)
    else:
        yield dotted(path), "" if value is None else str(value)


def _write_rules(ws, rules):
    _banner(ws, rules)
    _header(ws, 2, ["Setting", "Value"], [52, 110])
    row = 3
    for setting, value in _flatten(rules.raw):
        _text(ws, row, 1, setting)
        _text(ws, row, 2, value, wrap=True)
        row += 1
    _finish_table(ws, 2, ["Setting", "Value"], row - 1, freeze_col="A")


# ---------------------------------------------------------------------------------------------------
# Table of Contents
# ---------------------------------------------------------------------------------------------------

def _write_toc(ws, summary, rules, context, generated, total_cell):
    _banner(ws, rules)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 100
    _text(ws, 3, 1, rules.workbook_title, bold=True, size=16)

    facts = [
        ("Generated", generated),
        ("Rules version", rules.version),
        ("When it runs", rules.schedule_note or "Not set (see schedule.note in rules.yaml)"),
        ("In scope", f"{', '.join(GROUP_TITLES[g] for g in rules.include_groups)}; types: {', '.join(rules.issue_types)}; "
                     f"statuses ignored: {', '.join(str(x) for x in rules.raw['scope']['ignore_statuses']) or 'none'}"),
        ("Context used", ", ".join(context.files_read) if context and context.files_read else "none"),
    ]
    row = 5
    for label, value in facts:
        _text(ws, row, 1, label, bold=True)
        _text(ws, row, 2, value, wrap=True)
        ws.cell(row=row, column=2).alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        row += 1
    _text(ws, row, 1, "Stories checked", bold=True)
    _formula(ws, row, 2, f"={total_cell}")
    ws.cell(row=row, column=2).alignment = Alignment(horizontal="left", vertical="top")

    row += 2
    _text(ws, row, 1, "Tabs", bold=True, size=12)
    tabs = [
        (SUMMARY, "Counts by group and by label. Formulas that read the Findings tab."),
        (FINDINGS, "One row per checked story, with its verdict. Weak or missing cells are shaded; hover for the reason. Shows plain text."),
        (SUGGESTIONS, "Drafts for stories that are not 'Looks good': description, acceptance criteria, questions, split ideas. Fill in 'Approved?' with Y or N."),
        (CHANGES, "Every concrete edit, one row per field: what is there now and what to put there. Mark 'Done?' as you go. The same list is in changes.csv and the update pack."),
        (EPICS, "The team's epics, current and future first, with story counts, plus the stories that still need an epic and ideas for new epics."),
        (DUPLICATES, "Pairs of stories that are possible duplicates (close or merge one) or just related (fine, and worth grouping)."),
        (THEMES, "Words found in several titles, and whether titles start with them. Listed themes also get suggested titles."),
        (RAW, "Every story in the snapshot with every Jira field and the original Jira text. Filter and search here."),
        (RULES, "The rules that produced this file."),
    ]
    for name, description in tabs:
        row += 1
        cell = _text(ws, row, 1, name, color="0563C1")
        cell.font = Font(name=FONT, size=10, color="0563C1", underline="single")
        cell.hyperlink = Hyperlink(ref=cell.coordinate, location=f"{_quote(name)}!A1", display=name)
        _text(ws, row, 2, description, wrap=True)

    row += 2
    _text(ws, row, 1, "Color key", bold=True, size=12)
    legend = [
        ("High", PatternFill("solid", fgColor=rules.highlight["high"]), "Missing or seriously weak"),
        ("Medium", PatternFill("solid", fgColor=rules.highlight["medium"]), "Short, vague or unpointed"),
        ("Low", PatternFill("solid", fgColor=rules.highlight["low"]), "Worth a look"),
        ("Fill in", INPUT_FILL, "A cell a person edits (the 'Approved?' column)"),
    ]
    for name, fill, meaning in legend:
        row += 1
        _text(ws, row, 1, name, fill=fill)
        _text(ws, row, 2, meaning)

    row += 2
    _text(ws, row, 1, "Notes", bold=True, size=12)
    notes = [
        "Suggestions are drafts for a person to review. Nothing in this file changes Jira.",
        "Findings shows plain text, shortened to 300 characters. Raw Jira data keeps the full original Jira text, including its markup.",
        "Text longer than 32,000 characters is cut so Excel can hold it.",
        f"Every suggestion is labelled: {SUGGESTION_LABEL}.",
    ]
    for note in notes:
        row += 1
        _text(ws, row, 2, note, wrap=True)
