"""The Confluence report (P1-9): HTML body sections, one per marker pair.

The existing publisher takes an HTML body and replaces whatever sits between a start marker and an
end marker. A page can hold several such sections, so the report is written as SEPARATE sections:

    refiner-summary      the header, "at a glance", the by-group table and how to read it
    refiner-epics        the by-epic table and epic coverage (every story should have a current or future epic)
    refiner-themes       words that show up in several titles, and whether titles start with them
    refiner-labels       the by-label table
    refiner-not-checked  what was in the snapshot but not checked

Each section is a BODY ONLY fragment in Confluence storage format. That means no <html>, <head>,
<body>, <style> or <script>; every tag closed (<br />); every piece of text escaped; colors set inline
on a <span>. The page shows COUNTS ONLY: no story keys, titles, people or text. The numbers come from
measures.py, the same code the workbook's formulas are checked against, so the two always agree.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from .measures import GROUP_TITLES, MEASURES, NO_EPIC, VERDICT_COLUMNS, count_by_epic, count_by_group, count_by_label, count_row

COLUMNS = ["Stories"] + [title for title, _ in MEASURES] + list(VERDICT_COLUMNS)

# Colors are written the way Confluence stores them: rgb(r,g,b).
GRAY, AMBER, RED, GREEN = "rgb(137,137,137)", "rgb(180,95,6)", "rgb(191,38,0)", "rgb(0,102,68)"
_ATTENTION = {
    "Not pointed": AMBER, "Description needs update": AMBER, "Acceptance criteria needs update": AMBER,
    "Needs review": AMBER, "Missing info": RED, "Suggest split": RED, "Looks good": GREEN,
    "Epic needs attention": RED, "Possible duplicate": RED, "Title needs attention": AMBER, "Labels need attention": AMBER,
}


@dataclass
class Section:
    id: str            # the marker id, for example "refiner-summary"
    title: str         # a plain name, for the manifest and the preview only
    html: str          # the body fragment (no markers)

    def markers(self, rules):
        """(start marker, end marker) as the rules file says to write them."""
        return (rules.confluence_marker_start.replace("{id}", self.id),
                rules.confluence_marker_end.replace("{id}", self.id))

    def with_markers(self, rules):
        start, end = self.markers(rules)
        return f"{start}\n{self.html}\n{end}\n"


# ---------------------------------------------------------------------------------------------------
# Building the sections
# ---------------------------------------------------------------------------------------------------

def build_sections(summary, rules, generated=None):
    """Return the Confluence sections, in page order."""
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    ids = rules.confluence_section_ids
    return [
        Section(ids["summary"], "Summary", _summary_html(summary, rules, generated)),
        Section(ids["epics"], "By epic", _epics_html(summary)),
        Section(ids["themes"], "Themes", _themes_html(summary)),
        Section(ids["labels"], "By label", _labels_html(summary)),
        Section(ids["not_checked"], "Not checked", _not_checked_html(summary)),
    ]


def esc(text):
    """Escape text for storage format. Every piece of text goes through here."""
    return escape(str(text), quote=True)


def _cell(column, value, bold=False):
    """A number cell: gray for zero, colored when there is something to look at."""
    text = esc(value)
    if column != "Stories":
        color = GRAY if value == 0 else _ATTENTION[column]
        text = f'<span style="color: {color};">{text}</span>'
    if bold:
        text = f"<strong>{text}</strong>"
    return f'<td style="text-align: right;">{text}</td>'


def count_table(first_title, rows, total=None):
    """A table of count rows. `rows` is {name: count row}; `total` is an optional last, bold row."""
    head = "".join(f'<th style="text-align: right;">{esc(t)}</th>' if i else f"<th>{esc(t)}</th>"
                   for i, t in enumerate([first_title] + COLUMNS))
    body = []
    for name, counts in rows.items():
        body.append("<tr><td>" + esc(name) + "</td>" + "".join(_cell(c, counts[c]) for c in COLUMNS) + "</tr>")
    if total is not None:
        body.append("<tr><td><strong>Total</strong></td>" + "".join(_cell(c, total[c], bold=True) for c in COLUMNS) + "</tr>")
    return f"<table><tbody><tr>{head}</tr>{''.join(body)}</tbody></table>"


def _summary_html(summary, rules, generated):
    total = count_row(summary.results)
    groups = count_by_group(summary.results, rules.include_groups)
    glance = ", ".join(f"{verdict} {total[verdict]}" for verdict in VERDICT_COLUMNS)
    ignore = ", ".join(str(x) for x in rules.raw["scope"]["ignore_statuses"]) or "none"

    explain = [
        ("Not pointed", "the story has no points."),
        ("Description needs update", f"the description is empty, {rules.description_min_chars - 1} characters or fewer"
                                    + (", or not written as \"As a ..., I want ..., so that ...\"." if rules.story_format_enabled else ".")),
        ("Acceptance criteria needs update", f"the acceptance criteria are empty, {rules.ac_min_chars - 1} characters or fewer, or only vague words."),
        ("Suggest split", f"the story looks bigger than its points: {rules.review_at_or_above:g} points or more with little written, "
                          f"or {rules.max_points_before_keyword_review:g} points or fewer for a kind of work that usually takes longer."),
        ("Epic needs attention", "the story has no epic, or its epic has finished or ended."),
        ("Possible duplicate", "the title (and description) are very close to another story's."),
        ("Title needs attention", "the title is missing, short, long, or does not fit the description."),
        ("Labels need attention", "a required label is missing, a label is not allowed, or the text suggests a label."),
        ("Missing info", "something required is empty (and the story is not a split suggestion)."),
        ("Needs review", "something is short, vague or off, but nothing is missing."),
        ("Looks good", "no findings."),
    ]
    items = "".join(f"<li><strong>{esc(name)}</strong>: {esc(text)}</li>" for name, text in explain)

    parts = [
        f"<p><em>{esc(rules.workbook_banner)}</em></p>",
        f"<h2>{esc(rules.workbook_title)}</h2>",
        f"<p>Generated {esc(generated)}. Rules version {esc(rules.version)}. "
        f"{esc(total['Stories'])} stories and spikes checked ({esc(', '.join(GROUP_TITLES[g] for g in rules.include_groups))}; statuses ignored: {esc(ignore)}).</p>",
        f"<p><strong>At a glance:</strong> {esc(glance)}.</p>",
        *([f"<p><em>{esc(rules.schedule_note)}</em></p>"] if rules.schedule_note else []),
        "<h3>By group</h3>",
        count_table("Group", groups, total),
        "<h3>What the columns mean</h3>",
        f"<ul>{items}</ul>",
        "<p>Each story is counted once per row. The first three measure columns can overlap (a story can be both unpointed and "
        "missing a description). The last four are each story's single verdict, so they add up to the number of stories.</p>",
        "<p>This page shows counts only. It does not name people or stories.</p>",
    ]
    if rules.confluence_workbook_note:
        parts.append(f"<p>{esc(rules.confluence_workbook_note)}</p>")
    return "\n".join(parts)


def _epics_html(summary):
    epics = count_by_epic(summary.results, summary.analysis.epics)
    rows = {(f"{key} {name}".strip() if name else key): counts for key, (name, counts) in epics.items()}
    without = epics[NO_EPIC][1]["Stories"]
    coverage = ("Every story has an epic." if without == 0
                else f"{without} {'story has' if without == 1 else 'stories have'} no epic. The goal is none.")
    parts = [
        "<h3>By epic</h3>",
        f"<p>{esc(coverage)} Epics that have finished or ended are marked in the Epic needs attention column.</p>",
        count_table("Epic", rows),
    ]
    return "\n".join(parts)


def _themes_html(summary):
    themes = summary.analysis.themes
    if not themes:
        return "<h3>Themes</h3>\n<p>No themes were found.</p>"
    rows = "".join(
        f"<tr><td>{esc(t.word)}</td><td>{'Listed in the rules file' if t.known else 'Found by counting'}</td>"
        f'<td style="text-align: right;">{esc(len(t.keys))}</td><td style="text-align: right;">{esc(len(t.starting))}</td></tr>'
        for t in themes)
    return "\n".join([
        "<h3>Themes</h3>",
        "<p>Words that show up in several titles. Titles that start with the same word sort together.</p>",
        '<table><tbody><tr><th>Theme</th><th>Where from</th><th style="text-align: right;">Titles</th>'
        f'<th style="text-align: right;">Start with it</th></tr>{rows}</tbody></table>',
    ])


def _labels_html(summary):
    labels = count_by_label(summary.results)
    if not labels:
        return "<h3>By label</h3>\n<p>No stories were checked.</p>"
    return "\n".join([
        "<h3>By label</h3>",
        "<p>A story with several labels is counted under each of them, so these rows can add up to more than the total. "
        "Stories with no label are under &quot;No label&quot;.</p>",
        count_table("Label", labels),
    ])


def _not_checked_html(summary):
    if not summary.skipped:
        return "<h3>Not checked</h3>\n<p>Every story in the snapshot was checked.</p>"
    rows = "".join(f"<tr><td>{esc(reason)}</td>" + f'<td style="text-align: right;">{esc(count)}</td></tr>'
                   for reason, count in sorted(summary.skipped.items()))
    return "\n".join([
        "<h3>Not checked</h3>",
        "<p>These stories were in the snapshot but are outside the scope in the rules file.</p>",
        f"<table><tbody><tr><th>Reason</th><th style=\"text-align: right;\">Stories</th></tr>{rows}</tbody></table>",
    ])


# ---------------------------------------------------------------------------------------------------
# Writing files
# ---------------------------------------------------------------------------------------------------

def write_sections(out_dir, sections, rules, generated, include_markers=None):
    """Write one .html file per section, a manifest.json, and preview.html. Returns the manifest (a dict)."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if include_markers is None:
        include_markers = rules.confluence_include_markers

    entries = []
    for section in sections:
        start, end = section.markers(rules)
        name = f"section-{section.id}.html"
        (folder / name).write_text(section.with_markers(rules) if include_markers else section.html + "\n", encoding="utf-8")
        entries.append({"id": section.id, "title": section.title, "file": name, "start_marker": start, "end_marker": end})

    manifest = {
        "generated": generated,
        "rules_version": rules.version,
        "markers_included_in_files": bool(include_markers),
        "sections": entries,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "preview.html").write_text(preview_html(sections, rules), encoding="utf-8")
    return manifest


def preview_html(sections, rules):
    """The whole report as one page you can open in a browser. FOR LOOKING ONLY: never publish this file."""
    body = "\n<hr />\n".join(section.with_markers(rules) for section in sections)
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\" />\n<title>Preview only</title>\n"
        "<style>body{font-family:Arial,sans-serif;margin:24px;max-width:1100px}"
        "table{border-collapse:collapse}th,td{border:1px solid #c1c7d0;padding:4px 10px}th{background:#f4f5f7}</style>\n"
        "</head>\n<body>\n<p style=\"color:#bf2600\"><strong>PREVIEW ONLY. This is how the sections look together. "
        "Publish the section-*.html files, not this file.</strong></p>\n"
        f"{body}\n</body>\n</html>\n"
    )
