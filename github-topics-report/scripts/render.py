"""Stage 4 - render.

results.json -> out/confluence.html   (Confluence storage format, full report)
             -> out/email.html        (short, inline-styled summary)
             -> out/email_subject.txt

Environment (all optional):
  REPORT_TITLE          page/email heading            (default "GitHub Topics Report")
  CONFLUENCE_PAGE_URL   link placed in the email
  EMAIL_SUBJECT_PREFIX  e.g. "[TEST] "
  EMAIL_TEST_MODE       "true" adds a test-send banner to the email
  EMAIL_MAX_ROWS        rows per table in the email   (default 15)
"""
from __future__ import annotations

import html
import os
import sys

from reportlib import log, out_dir, read_json, short_date

BADGE_COLOUR = {"high": "Red", "medium": "Yellow", "low": "Grey"}
BADGE_STYLE = {
    "high": "background:#d32f2f;color:#fff",
    "medium": "background:#f9a825;color:#000",
    "low": "background:#9e9e9e;color:#fff",
}


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def repo_link(name: str, url: str) -> str:
    return f'<a href="{esc(url)}">{esc(name)}</a>'


def badge(bucket: str, email: bool) -> str:
    label = bucket.upper()
    if email:
        return f'<span style="padding:2px 6px;border-radius:3px;font-size:11px;{BADGE_STYLE[bucket]}">{label}</span>'
    return ('<ac:structured-macro ac:name="status">'
            f'<ac:parameter ac:name="colour">{BADGE_COLOUR[bucket]}</ac:parameter>'
            f'<ac:parameter ac:name="title">{label}</ac:parameter></ac:structured-macro>')


def table(headers: list[str], rows: list[list[str]], email: bool = False) -> str:
    """Cells in `rows` must already be HTML-escaped / trusted markup."""
    th_style = ' style="text-align:left;padding:6px 10px;background:#f4f5f7;border:1px solid #ddd"' if email else ""
    td_style = ' style="padding:6px 10px;border:1px solid #ddd;vertical-align:top"' if email else ""
    tbl_style = ' style="border-collapse:collapse;font-size:13px;margin:8px 0"' if email else ""
    head = "".join(f"<th{th_style}>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td{td_style}>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table{tbl_style}><tbody><tr>{head}</tr>{body}</tbody></table>"


def repo_rows(repos: list[dict]) -> list[list[str]]:
    return [[repo_link(r["full_name"], r["url"]), esc(short_date(r["pushed_at"])), esc(r["description"])] for r in repos]


def candidate_rows(cands: list[dict], email: bool) -> list[list[str]]:
    rows = []
    for c in cands:
        why = esc("; ".join(c["reasons"]) + (" (no recent pushes)" if c["stale"] else ""))
        rows.append([repo_link(c["full_name"], c["url"]), badge(c["bucket"], email), esc(c["score"]),
                     why, esc(short_date(c["pushed_at"])), esc(c["description"])])
    return rows


CAND_HEADERS = ["Repo", "Confidence", "Score", "Why", "Last push", "Description"]
REPO_HEADERS = ["Repo", "Last push", "Description"]


def summary_table(results: dict, email: bool) -> str:
    rows = []
    for t in results["teams"].values():
        cands = t["candidates"]
        hi = sum(1 for c in cands if c["bucket"] == "high")
        med = sum(1 for c in cands if c["bucket"] == "medium")
        low = sum(1 for c in cands if c["bucket"] == "low")
        rows.append([esc(f"{t['display_name']} ({t['topic']})"), esc(sum(1 for r in t["known_repos"] if r["tagged"])),
                     esc(sum(1 for r in t["known_repos"] if r["in_registry"])), esc(len(t["missing_topic"])),
                     esc(len(t["unregistered"])), esc(len(t["registry_not_found"])), esc(f"{hi} / {med} / {low}")])
    return table(["Team", "Tagged", "In registry", "Needs topic", "Not in registry", "Registry not found",
                  "Candidates H / M / L"], rows, email)


def expand(title: str, inner: str) -> str:
    return ('<ac:structured-macro ac:name="expand">'
            f'<ac:parameter ac:name="title">{esc(title)}</ac:parameter>'
            f'<ac:rich-text-body>{inner}</ac:rich-text-body></ac:structured-macro>')


def info_panel(inner: str) -> str:
    return f'<ac:structured-macro ac:name="info"><ac:rich-text-body>{inner}</ac:rich-text-body></ac:structured-macro>'


def code_block(text: str) -> str:
    safe = text.replace("]]>", "]]]]><![CDATA[>")
    return ('<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">yaml</ac:parameter>'
            f'<ac:plain-text-body><![CDATA[{safe}]]></ac:plain-text-body></ac:structured-macro>')


# ---------------------------------------------------------- manifest sync

DRIFT_HEADERS = ["Repo", "Team", "On GitHub, not in manifest", "In manifest, not on GitHub"]


def topic_list(topics: list[str]) -> str:
    return esc(", ".join(topics)) if topics else "–"


def manifest_section(m: dict, email: bool = False, limit: int = 15) -> str:
    """Manifest-vs-GitHub comparison. Full detail for Confluence, capped tables for the email."""
    if not m.get("enabled"):
        return ""
    title = "Manifest sync"
    if m.get("error"):
        msg = f"Could not read the repo manifest ({esc(m.get('source'))}): {esc(m['error'])}"
        return (f'<h3 style="margin:18px 0 4px">{title}</h3><p style="color:#b71c1c">{msg}</p>' if email
                else f"<h2>{title}</h2>" + info_panel(f"<p>{msg}</p>"))
    c, stats = m["compare"], m["stats"]
    heading = (lambda t: f'<p style="margin:10px 0 2px"><strong>{t}</strong></p>') if email else (lambda t: f"<h3>{t}</h3>")
    parts = [f'<h3 style="margin:18px 0 4px">{title}</h3>' if email else f"<h2>{title}</h2>",
             f"<p>Source <code>{esc(m['source'])}</code>: {stats['repos']} repos in {stats['teams']} teams, "
             f"{stats['with_topic_data']} with topic data. GitHub is the source of truth for topics, so "
             "differences mean the manifest needs updating (or the topic needs adding on GitHub).</p>"]

    def block(label, headers, rows):
        if not rows:
            return
        parts.append(heading(f"{esc(label)} ({len(rows)})"))
        shown = rows[:limit] if email else rows
        parts.append(table(headers, shown, email))
        if email and len(rows) > limit:
            parts.append(f'<p style="color:#666">…and {len(rows) - limit} more in the full report.</p>')

    block("Topics differ between manifest and GitHub", DRIFT_HEADERS,
          [[repo_link(d["full_name"], d["url"]), esc(d["team"]), topic_list(d["github_only"]),
            topic_list(d["manifest_only"])] for d in c["topic_drift"]])
    block("In the manifest but not found on GitHub", ["Repo", "Team"],
          [[esc(e["full_name"]), esc(e["team"])] for e in c["not_on_github"]])
    vocab = c["vocabulary"]
    if vocab["present"]:
        if vocab["github_not_in_vocab"]:
            parts.append(heading(f"Topics in use on GitHub but missing from the manifest's topic list "
                                 f"({len(vocab['github_not_in_vocab'])})"))
            parts.append(f"<p>{esc(', '.join(vocab['github_not_in_vocab']))}</p>")
        if vocab["vocab_unused"] and not email:
            parts.append(heading(f"In the manifest's topic list but unused by any manifest repo "
                                 f"({len(vocab['vocab_unused'])})"))
            parts.append(f"<p>{esc(', '.join(vocab['vocab_unused']))}</p>")
    if not email:
        if c["multi_team"]:
            block("Repos listed under more than one team", ["Repo", "Teams"],
                  [[esc(x["repo"]), esc(", ".join(x["teams"]))] for x in c["multi_team"]])
        if c["outside_scanned_orgs"]:
            block("In the manifest but outside the scanned orgs (not checked)", ["Repo", "Team"],
                  [[esc(e["full_name"]), esc(e["team"])] for e in c["outside_scanned_orgs"]])
        notes = []
        if m["unmapped_teams"]:
            notes.append("Manifest teams with no entry in <code>teams.yml</code> (topics compared, but not merged "
                         f"into a registry): {esc(', '.join(m['unmapped_teams']))}.")
        if m.get("skipped_keys"):
            notes.append(f"Top-level manifest keys skipped as not team data: {esc(', '.join(m['skipped_keys']))}.")
        parts += [f"<p>{n}</p>" for n in notes]
    if len(parts) == 2:
        parts.append('<p style="color:#666">Manifest and GitHub are in sync.</p>' if email else "<p>In sync.</p>")
    return "\n".join(parts)


# ------------------------------------------------------------- confluence

def team_section(t: dict) -> str:
    parts = [f"<h2>{esc(t['display_name'])} <code>{esc(t['topic'])}</code></h2>",
             f"<p>{len(t['members'])} team members tracked; {len(t['known_repos'])} known repos.</p>"]
    if t.get("team_error"):
        parts.append(info_panel(f"<p>Could not read GitHub team <code>{esc(t['github_team'])}</code>: "
                                f"{esc(t['team_error'])}. Access and membership signals are missing.</p>"))
    if t["missing_topic"]:
        parts += [f"<h3>In registry, missing the <code>{esc(t['topic'])}</code> topic ({len(t['missing_topic'])})</h3>",
                  table(REPO_HEADERS, repo_rows(t["missing_topic"]))]
    if t["unregistered"]:
        parts += [f"<h3>Tagged <code>{esc(t['topic'])}</code> but not in registry ({len(t['unregistered'])})</h3>",
                  table(REPO_HEADERS, repo_rows(t["unregistered"]))]
    if t["registry_not_found"]:
        items = "".join(f"<li>{esc(n)}</li>" for n in t["registry_not_found"])
        parts += [f"<h3>Registry entries not found in scan ({len(t['registry_not_found'])})</h3>",
                  f"<p>Renamed, deleted, or outside the scanned orgs.</p><ul>{items}</ul>"]
    hot = [c for c in t["candidates"] if c["bucket"] in ("high", "medium")]
    low = [c for c in t["candidates"] if c["bucket"] == "low"]
    parts.append(f"<h3>Untagged repos to consider ({len(hot)} high/medium, {len(low)} low)</h3>")
    parts.append(table(CAND_HEADERS, candidate_rows(hot, False)) if hot else "<p>None.</p>")
    if low:
        parts.append(expand(f"Low-confidence candidates ({len(low)})", table(CAND_HEADERS, candidate_rows(low, False))))
    known_rows = [[repo_link(r["full_name"], r["url"]), "✔" if r["tagged"] else "–",
                   "✔" if r["in_registry"] else "–", "archived" if r["archived"] else "",
                   esc(short_date(r["pushed_at"]))] for r in t["known_repos"]]
    parts.append(expand(f"All known {t['display_name']} repos ({len(known_rows)})",
                        table(["Repo", "Tagged", "In registry", "", "Last push"], known_rows)))
    return "\n".join(parts)


def confluence_page(results: dict, suggestions: str, title: str) -> str:
    banner = info_panel(
        f"<p><strong>Auto-generated</strong> {esc(results['generated_at'])} from GitHub org(s) "
        f"{esc(', '.join(results['orgs']))}. {results['repos_scanned']} repos scanned; activity looked back "
        f"{results['lookback_months']} months (since {esc(results['cutoff'][:10])}).</p>"
        "<p>Do not edit this page: changes are overwritten on the next run. Edit "
        "<code>config/teams.yml</code> in the info-reports repo to change the registry, exclusions or members.</p>")
    parts = [banner, "<h2>Summary</h2>", summary_table(results, False)]
    parts += [team_section(t) for t in results["teams"].values()]
    parts.append(manifest_section(results.get("manifest", {}), email=False))
    parts += ["<h2>Suggested registry changes</h2>",
              "<p>Paste into <code>config/teams.yml</code> after review.</p>", code_block(suggestions)]
    return "\n".join(parts)


# ------------------------------------------------------------------- email

def email_section(t: dict, limit: int) -> str:
    style = 'style="margin:18px 0 4px"'
    parts = [f"<h3 {style}>{esc(t['display_name'])} <code>{esc(t['topic'])}</code></h3>"]

    def capped(title: str, headers, rows) -> None:
        if not rows:
            return
        parts.append(f"<p style=\"margin:10px 0 2px\"><strong>{esc(title)} ({len(rows)})</strong></p>")
        parts.append(table(headers, rows[:limit], True))
        if len(rows) > limit:
            parts.append(f"<p style=\"color:#666\">…and {len(rows) - limit} more in the full report.</p>")

    capped(f"In registry, missing the '{t['topic']}' topic", REPO_HEADERS, repo_rows(t["missing_topic"]))
    capped(f"Tagged '{t['topic']}' but not in registry", REPO_HEADERS, repo_rows(t["unregistered"]))
    capped("Registry entries not found", ["Repo"], [[esc(n)] for n in t["registry_not_found"]])
    hot = [c for c in t["candidates"] if c["bucket"] in ("high", "medium")]
    capped("Untagged repos to consider", CAND_HEADERS, candidate_rows(hot, True))
    if len(parts) == 1:
        parts.append('<p style="color:#666">Nothing needs attention.</p>')
    return "\n".join(parts)


def email_body(results: dict, title: str, limit: int) -> str:
    test = os.environ.get("EMAIL_TEST_MODE", "").lower() == "true"
    link = os.environ.get("CONFLUENCE_PAGE_URL")
    intro = (f"Here is what the scan found across <strong>{esc(', '.join(results['orgs']))}</strong> "
             f"({results['repos_scanned']} repos, activity since {esc(results['cutoff'][:10])}). "
             "Repos tagged with a team topic are listed as-is; the candidate lists are untagged repos that look "
             "like they may belong to the team - please confirm or tell us to exclude them.")
    parts = ['<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;max-width:900px">']
    if test:
        parts.append('<p style="background:#fff3cd;padding:8px;border:1px solid #ffe08a">'
                     "<strong>TEST SEND</strong> - this went to a small group, not the full team.</p>")
    parts += [f"<h2>{esc(title)}</h2>", f"<p>{intro}</p>", summary_table(results, True)]
    parts += [email_section(t, limit) for t in results["teams"].values()]
    parts.append(manifest_section(results.get("manifest", {}), email=True, limit=limit))
    if link:
        parts.append(f'<p style="margin-top:20px">Full report: <a href="{esc(link)}">{esc(link)}</a></p>')
    parts.append('<p style="color:#888;font-size:12px">Generated automatically. To change the lists, edit '
                 "config/teams.yml in the info-reports repo.</p></body></html>")
    return "\n".join(parts)


def email_subject(results: dict) -> str:
    prefix = os.environ.get("EMAIL_SUBJECT_PREFIX", "")
    day = results["generated_at"][:10]
    n = results["total_actions"]
    what = f"{n} item{'s' if n != 1 else ''} need attention" if n else "no action needed"
    return f"{prefix}GitHub topics report {day}: {what}"


def main() -> int:
    results = read_json("results.json")
    directory = out_dir()
    title = os.environ.get("REPORT_TITLE", "GitHub Topics Report")
    limit = int(os.environ.get("EMAIL_MAX_ROWS", "15"))
    suggestions = (directory / "registry_suggestions.yml").read_text(encoding="utf-8")
    (directory / "confluence.html").write_text(confluence_page(results, suggestions, title), encoding="utf-8")
    (directory / "email.html").write_text(email_body(results, title, limit), encoding="utf-8")
    (directory / "email_subject.txt").write_text(email_subject(results), encoding="utf-8")
    log(f"Rendered confluence.html, email.html, email_subject.txt in {directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
