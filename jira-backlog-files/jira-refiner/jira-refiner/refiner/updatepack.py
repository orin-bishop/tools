"""The update pack: ONE standalone HTML page that makes updating Jira stories easy.

Open it in a browser. For each story that needs something there is a small table:

    Field | Now | Suggested | Why

Click the Suggested box to select all of it (or press Copy), open the story with its link (it opens in a new
window), paste, and Save in Jira. Jira cannot be pre-filled from a link for an existing story, so copy and paste
is the practical way. Nothing here writes to Jira. The page uses no outside files: its styles and its small copy
script are inside it, and the script can be switched off in the rules file (the boxes still select on click).
All text is escaped.
"""
import re
from collections import Counter
from datetime import datetime

from .changes import GROUP_ORDER
from .confluence import COLUMNS, count_table, esc
from .measures import GROUP_TITLES, VERDICT_COLUMNS, count_by_group, count_row
from .text import natural_key, plain_text

_KIND_LABEL = {"update": "Replace", "add": "Add", "review": "Decide"}      # an update to an empty field reads "Set"

_CSS = """
body { font-family: Arial, Helvetica, sans-serif; margin: 24px auto; max-width: 1100px; color: #172b4d; line-height: 1.4; }
.banner { color: #7f7f7f; font-style: italic; font-size: 12px; }
h1 { margin-bottom: 4px; } h2 { border-bottom: 2px solid #1f3864; padding-bottom: 4px; margin-top: 32px; }
h3 { margin: 24px 0 6px; } table { border-collapse: collapse; margin: 8px 0 16px; width: 100%; }
th, td { border: 1px solid #c1c7d0; padding: 6px 10px; vertical-align: top; text-align: left; }
th { background: #1f3864; color: #ffffff; } td.num, th.num { text-align: right; }
.now { white-space: pre-wrap; color: #505f79; } .empty { color: #97a0af; font-style: italic; }
.copybox { background: #eaf3ff; border: 1px solid #99c2ff; padding: 6px 8px; white-space: pre-wrap; user-select: all; cursor: copy; }
.note { background: #fff7d6; border: 1px solid #f0d36b; padding: 6px 8px; white-space: pre-wrap; }
button.copy { margin-top: 4px; font-size: 12px; cursor: pointer; }
table.changes { table-layout: fixed; }
table.changes th:nth-child(1) { width: 11%; } table.changes th:nth-child(2) { width: 20%; }
table.changes th:nth-child(3) { width: 40%; } table.changes th:nth-child(4) { width: 29%; }
.kind { font-size: 11px; font-weight: bold; text-transform: uppercase; color: #5e6c84; }
.verdict { font-size: 13px; font-weight: normal; color: #5e6c84; } .top { font-size: 12px; }
.low { color: #8a8a8a; } ul.contents li { margin: 2px 0; }
@media print { .top, button.copy { display: none; } }
"""

_SCRIPT = """//<![CDATA[
document.addEventListener('click', function (event) {
  var button = event.target.closest('button.copy');
  if (!button) { return; }
  var box = button.parentNode.querySelector('.copybox');
  var text = box.innerText;
  function done() { button.textContent = 'Copied'; setTimeout(function () { button.textContent = 'Copy'; }, 1500); }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done);
  } else {
    var range = document.createRange(); range.selectNodeContents(box);
    var selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    try { document.execCommand('copy'); done(); } catch (problem) { }
  }
});
//]]>"""


def build_update_pack(summary, suggestions, changes, rules, generated=None, copy_buttons=None):
    """The whole page as a string. `copy_buttons` None means: follow the rules file."""
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    copy_buttons = rules.update_pack_copy_buttons if copy_buttons is None else copy_buttons
    by_key = {}
    for change in changes:
        by_key.setdefault(change.key, []).append(change)
    ordered = sorted(summary.results, key=lambda r: (GROUP_ORDER.index(r.story.group), natural_key(r.story.key)))
    cards = [r for r in ordered if by_key.get(r.story.key) or (suggestions.get(r.story.key) and suggestions[r.story.key].questions)]

    parts = [
        '<!DOCTYPE html>',
        '<html lang="en"><head><meta charset="utf-8" />',
        f"<title>{esc(rules.workbook_title)}: update pack</title>",
        f"<style>{_CSS}</style></head><body>",
        f'<p class="banner">{esc(rules.workbook_banner)}</p>',
        f"<h1>{esc(rules.workbook_title)}: update pack</h1>",
        f"<p>Generated {esc(generated)}. Rules version {esc(rules.version)}. These are suggestions for people to review. "
        "Nothing here changes Jira.</p>",
        f"<p><strong>{esc(rules.schedule_note)}</strong></p>" if rules.schedule_note else "",
        _how_to(copy_buttons),
        _contents(cards, rules),
        _overview(summary, rules),
        _epics(summary, rules),
        _duplicates(summary, rules),
        _themes(summary, rules),
        _stories(cards, by_key, suggestions, rules, copy_buttons),
    ]
    if copy_buttons:
        parts.append(f"<script>{_SCRIPT}</script>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------------

def _anchor(key):
    return "story-" + re.sub(r"[^A-Za-z0-9_-]", "-", key)


def _link(key, group, rules):
    """The key as a link that opens the story in Jira in a new window. Plain text when there is no address or no story yet."""
    if rules.jira_base_url and group != "intake":
        return f'<a href="{esc(rules.jira_base_url)}/browse/{esc(key)}" target="_blank" rel="noopener noreferrer">{esc(key)}</a>'
    return esc(key)


def _epic_link(key, rules):
    if rules.jira_base_url and key:
        return f'<a href="{esc(rules.jira_base_url)}/browse/{esc(key)}" target="_blank" rel="noopener noreferrer">{esc(key)}</a>'
    return esc(key)


def _how_to(copy_buttons):
    copy_step = "click a blue <em>Suggested</em> box to select all of it, or press <em>Copy</em>" if copy_buttons \
        else "click a blue <em>Suggested</em> box to select all of it, then copy it"
    return ("<h2 id=\"how-to\">How to use this page</h2><ol>"
            "<li>Find a story under <a href=\"#stories\">Stories</a> and open its link. It opens in a new window.</li>"
            f"<li>In the table, {copy_step}.</li>"
            "<li>Paste it into that field in Jira and press Save.</li>"
            "<li>Yellow <em>Decide</em> rows are choices for a person, such as closing a duplicate, not text to paste.</li></ol>")


def _contents(cards, rules):
    items = ['<li><a href="#overview">Overview</a></li>', '<li><a href="#epics">Epics</a></li>',
             '<li><a href="#duplicates">Duplicates and related stories</a></li>', '<li><a href="#themes">Themes</a></li>',
             '<li><a href="#stories">Stories</a><ul>']
    for result in cards:
        story = result.story
        title = plain_text(story.summary) or "(no title)"
        items.append(f'<li><a href="#{_anchor(story.key)}">{esc(story.key)}</a> {esc(title)} '
                     f'<span class="verdict">({esc(GROUP_TITLES[story.group])}, {esc(result.verdict)})</span></li>')
    items.append("</ul></li>")
    return f'<h2 id="contents">Contents</h2><ul class="contents">{"".join(items)}</ul>'


def _overview(summary, rules):
    total = count_row(summary.results)
    glance = ", ".join(f"{v} {total[v]}" for v in VERDICT_COLUMNS)
    groups = count_by_group(summary.results, rules.include_groups)
    return (f'<h2 id="overview">Overview</h2><p><strong>At a glance:</strong> {esc(glance)}.</p>'
            + count_table("Group", groups, total))


def _epics(summary, rules):
    analysis = summary.analysis
    used = Counter(r.story.epic.strip() for r in summary.results if r.story.epic.strip())
    out = ['<h2 id="epics">Epics</h2>']
    if analysis.epics:
        rows = []
        active = {e.key for e in analysis.active_epics}
        for epic in sorted(analysis.epics, key=lambda e: (e.key not in active, natural_key(e.key))):
            dates = " to ".join(str(d) for d in (epic.start_date, epic.end_date) if d) or ""
            rows.append(f"<tr><td>{_epic_link(epic.key, rules)}</td><td>{esc(epic.name)}</td><td>{esc(epic.status)}</td>"
                        f"<td>{esc(dates)}</td><td>{'Current or future' if epic.key in active else 'Finished or ended'}</td>"
                        f'<td class="num">{used.get(epic.key, 0)}</td></tr>')
        out.append(f"<p>As of {esc(analysis.today)}. Stories should belong to a current or future epic.</p>"
                   "<table><tr><th>Epic</th><th>Name</th><th>Status</th><th>Dates</th><th>Now</th><th class=\"num\">Stories</th></tr>"
                   + "".join(rows) + "</table>")
    else:
        out.append("<p>No epic list was given, so only missing epics could be checked.</p>")

    needing = [r for r in summary.results if {f.code for f in r.flags} & {"epic_missing", "epic_inactive"}]
    if needing:
        rows = []
        for result in sorted(needing, key=lambda r: natural_key(r.story.key)):
            story = result.story
            matches = analysis.epic_matches.get(story.key, [])
            idea = "; ".join(f"{m.epic.key} {m.epic.name} ({round(m.score * 100)}%)" for m in matches)
            if not idea:
                idea = next((f'New epic idea: "{n.name}"' for n in analysis.new_epics if story.key in n.keys), "")
            rows.append(f"<tr><td>{_link(story.key, story.group, rules)}</td><td>{esc(plain_text(story.summary))}</td>"
                        f"<td>{esc(story.epic) or '<span class=\"empty\">none</span>'}</td><td>{esc(idea)}</td></tr>")
        out.append("<h3>Stories that need an epic</h3><table><tr><th>Story</th><th>Title</th><th>Epic now</th><th>Suggestion</th></tr>"
                   + "".join(rows) + "</table>")
    else:
        out.append("<p>Every story has a current or future epic.</p>")
    if analysis.new_epics:
        items = "".join(f"<li><strong>{esc(n.name)}</strong>: {esc(', '.join(n.keys))}</li>" for n in analysis.new_epics)
        out.append(f"<h3>New epic ideas</h3><p>These stories share a word and fit no current epic.</p><ul>{items}</ul>")
    return "".join(out)


def _duplicates(summary, rules):
    analysis = summary.analysis
    stories = {r.story.key: r.story for r in summary.results}
    if not analysis.pairs:
        return '<h2 id="duplicates">Duplicates and related stories</h2><p>No duplicate or related stories were found.</p>'
    rows = []
    for pair in analysis.pairs:
        a, b = stories.get(pair.a.key, pair.a), stories.get(pair.b.key, pair.b)
        rows.append(f"<tr><td>{'Possible duplicate' if pair.kind == 'duplicate' else 'Related'}</td>"
                    f'<td class="num">{round(pair.score * 100)}%</td>'
                    f"<td>{_link(a.key, a.group, rules)} {esc(plain_text(a.summary))}</td>"
                    f"<td>{_link(b.key, b.group, rules)} {esc(plain_text(b.summary))}</td></tr>")
    return ('<h2 id="duplicates">Duplicates and related stories</h2>'
            "<p>Possible duplicates should be closed or merged. Related stories are fine and can be grouped.</p>"
            '<table><tr><th>Kind</th><th class="num">Alike</th><th>Story</th><th>Story</th></tr>' + "".join(rows) + "</table>")


def _themes(summary, rules):
    themes = summary.analysis.themes
    if not themes:
        return '<h2 id="themes">Themes</h2><p>No themes were found.</p>'
    rows = []
    for theme in themes:
        if theme.known:
            note = "Consistent." if theme.consistent else "Titles that mention it but do not start with it are in the update tables below."
        else:
            note = "A possible theme found by counting words. Add it under themes: known in the rules file to start titles with it."
        rows.append(f"<tr><td>{esc(theme.word)}</td><td>{'Listed in the rules file' if theme.known else 'Found by counting'}</td>"
                    f'<td class="num">{len(theme.keys)}</td><td class="num">{len(theme.starting)}</td><td>{esc(note)}</td></tr>')
    return ('<h2 id="themes">Themes</h2><p>Several stories about the same thing can start their titles the same way, so they sort together.</p>'
            '<table><tr><th>Theme</th><th>Where from</th><th class="num">Titles</th><th class="num">Start with it</th><th>Note</th></tr>'
            + "".join(rows) + "</table>")


def _stories(cards, by_key, suggestions, rules, copy_buttons):
    if not cards:
        return '<h2 id="stories">Stories</h2><p>No story needs an update.</p>'
    out = ['<h2 id="stories">Stories</h2>']
    for result in cards:
        story = result.story
        title = plain_text(story.summary) or "(no title)"
        out.append(f'<div class="story"><h3 id="{_anchor(story.key)}">{_link(story.key, story.group, rules)} {esc(title)} '
                   f'<span class="verdict">({esc(GROUP_TITLES[story.group])}, {esc(result.verdict)})</span></h3>')
        if story.group == "intake":
            out.append("<p>Not in Jira yet. Use these when you create the story.</p>")
        rows = by_key.get(story.key, [])
        if rows:
            body = "".join(_row(change, copy_buttons) for change in rows)
            out.append('<table class="changes"><tr><th>Field</th><th>Now</th><th>Suggested</th><th>Why</th></tr>' + body + "</table>")
        found = suggestions.get(story.key)
        if found and found.questions:
            out.append("<p><strong>Ask in refinement</strong></p><ul>" + "".join(f"<li>{esc(q)}</li>" for q in found.questions) + "</ul>")
        out.append('<p class="top"><a href="#contents">Back to contents</a></p></div>')
    return "".join(out)


def _label(change):
    if change.kind == "update" and not change.current.strip():
        return "Set"
    return _KIND_LABEL[change.kind]


def _row(change, copy_buttons):
    now = f'<div class="now">{esc(change.current)}</div>' if change.current else '<span class="empty">(empty)</span>'
    if change.kind == "review":
        suggested = f'<div class="note">{esc(change.suggested)}</div>'
    else:
        suggested = f'<div class="copybox" tabindex="0">{esc(change.suggested)}</div>'
        if copy_buttons:
            suggested += '<button type="button" class="copy">Copy</button>'
    return (f'<tr><td>{esc(change.field)}<br /><span class="kind">{_label(change)}</span></td><td>{now}</td>'
            f"<td>{suggested}</td><td>{esc(change.reason)}</td></tr>")
