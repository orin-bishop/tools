"""Command line. Every command reads the same inputs, so they always agree:

    --snapshot  stories (and optionally epics and stories waiting to upload) as JSON
    --intake    optional CSV of stories planned for upload that are not in Jira yet
    --rules     the rules file (default rules.yaml)
    --today     optional YYYY-MM-DD, to judge epics as of another day
    --context   folder with hints.yaml and markdown context files (commands that suggest)

Commands:
    validate-rules   check the rules file and say what is wrong
    check            the verdict and findings for every story, plus what was found across stories
    suggest          the drafted fixes, printed
    workbook         the Excel workbook
    confluence       the Confluence report as HTML body sections with their markers
    changes          every suggested edit as a CSV file
    update-pack      one HTML page with a copy-and-paste table per story
    report           all of the above outputs into one folder (what a pipeline runs)
    snapshot         turn saved Jira exports into the snapshot file (uses jira_fields.yaml)
    doctor           is this copy ready? placeholders, starter examples, and a counts-only snapshot shape

Exit codes: 0 = ran fine, 2 = an input file has a problem or an output could not be written.
Nothing here writes to Jira.
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .changes import build_changes, write_changes_csv
from .confluence import build_sections, write_sections
from .context import load_context
from . import doctor
from .jira_import import build_snapshot, load_field_map
from .model import load_data, parse_date
from .rules import RulesError, load_rules
from .runner import check_all
from .suggest import LABEL, suggest_all, to_dict
from .updatepack import build_update_pack
from .verdict import LOOKS_GOOD, MISSING_INFO, NEEDS_REVIEW, SUGGEST_SPLIT
from .workbook import save_workbook

_COLORS = {LOOKS_GOOD: "32", NEEDS_REVIEW: "33", MISSING_INFO: "31", SUGGEST_SPLIT: "31;1"}   # green, yellow, red, bold red
_SUGGESTING = ("suggest", "workbook", "changes", "update-pack", "report")
REPORT_FILES = {"workbook": "refinement-report.xlsx", "changes": "changes.csv", "update_pack": "update-pack.html",
                "confluence": "confluence"}


@dataclass
class Run:
    """Everything one command needs, loaded once."""
    rules: object
    data: object            # model.Snapshot
    summary: object         # runner.RunSummary
    context: object = None
    suggestions: dict = None
    generated: str = ""


def main(argv=None, out=None):
    out = out or sys.stdout
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor(args, out)
    if args.command == "snapshot":
        return _snapshot(args, out)
    try:
        rules = load_rules(args.rules)
    except RulesError as err:
        _print_problems("rules", err, out)
        return 2
    if args.command == "validate-rules":
        print(f"Rules OK: version {rules.version}, {len(rules.issue_types)} issue type(s), {len(rules.work_patterns)} work pattern(s).", file=out)
        return 0

    run = _prepare(args, rules, out)
    if isinstance(run, int):
        return run
    handlers = {"check": _check, "suggest": _suggest, "workbook": _workbook, "confluence": _confluence,
                "changes": _changes, "update-pack": _update_pack, "report": _report}
    return handlers[args.command](args, run, out)


# ---------------------------------------------------------------------------------------------------
# Arguments and loading
# ---------------------------------------------------------------------------------------------------

def _parser():
    parser = argparse.ArgumentParser(prog="python -m refiner", description="Check Jira stories against the refinement rules.")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-rules", help="Check the rules file and say what is wrong.")
    validate.add_argument("--rules", default="rules.yaml")

    def inputs(sub, context=False, generated=False):
        sub.add_argument("--snapshot", required=True, help="JSON file with stories (and optionally epics and intake).")
        sub.add_argument("--intake", help="CSV of stories planned for upload that are not in Jira yet.")
        sub.add_argument("--rules", default="rules.yaml")
        sub.add_argument("--today", help="Judge epics as of this day (YYYY-MM-DD). Default: the rules file, then today.")
        if context:
            sub.add_argument("--context", default="context", help="Folder with hints.yaml and markdown context files.")
        if generated:
            sub.add_argument("--generated", help="Text for the 'Generated' line. Default: the current date and time.")
        return sub

    check = inputs(commands.add_parser("check", help="Check every story and show what was found across stories."))
    check.add_argument("--details", action="store_true", help="Print the full sentence for every finding.")
    check.add_argument("--json", dest="json_out", help="Also write the results to this JSON file.")

    suggest = inputs(commands.add_parser("suggest", help="Print drafted fixes for every story that is not 'Looks good'."), context=True)
    suggest.add_argument("--json", dest="json_out", help="Also write the suggestions to this JSON file.")

    book = inputs(commands.add_parser("workbook", help="Write the Excel workbook."), context=True, generated=True)
    book.add_argument("--out", default=REPORT_FILES["workbook"], help="Where to write the .xlsx file.")

    page = inputs(commands.add_parser("confluence", help="Write the Confluence report as HTML body sections."), generated=True)
    page.add_argument("--out-dir", default="confluence-out", help="Folder for the section files, manifest.json and preview.html.")
    page.add_argument("--include-markers", action="store_true", help="Write the start and end markers into each section file.")

    changes = inputs(commands.add_parser("changes", help="Write every suggested edit to a CSV file."), context=True)
    changes.add_argument("--out", default=REPORT_FILES["changes"], help="Where to write the .csv file.")

    pack = inputs(commands.add_parser("update-pack", help="Write the copy-and-paste HTML update pack."), context=True, generated=True)
    pack.add_argument("--out", default=REPORT_FILES["update_pack"], help="Where to write the .html file.")
    pack.add_argument("--no-copy-buttons", action="store_true", help="Leave out the Copy buttons and their small script.")

    report = inputs(commands.add_parser("report", help="Write every output into one folder."), context=True, generated=True)
    report.add_argument("--out-dir", default="refinement-out", help="The folder to write everything into.")
    report.add_argument("--include-markers", action="store_true", help="Write the Confluence markers into each section file.")

    snap = commands.add_parser("snapshot", help="Turn saved Jira exports into the snapshot file.")
    snap.add_argument("--fields", default="jira_fields.yaml", help="The field map (which custom field is which).")
    snap.add_argument("--current", action="append", default=[], help="Export of the current sprint's issues. Can be given more than once.")
    snap.add_argument("--future", action="append", default=[], help="Export of upcoming sprints' issues. Can be given more than once.")
    snap.add_argument("--backlog", action="append", default=[], help="Export of the backlog's issues. Can be given more than once.")
    snap.add_argument("--epics", action="append", default=[], help="Export of the team's epics. Can be given more than once.")
    snap.add_argument("--out", default="snapshot.json", help="Where to write the snapshot.")

    doc = commands.add_parser("doctor", help="Check this copy is ready for a real run.")
    doc.add_argument("--rules", default="rules.yaml")
    doc.add_argument("--fields", default="jira_fields.yaml")
    doc.add_argument("--context", default="context")
    doc.add_argument("--pipeline-dir", default="pipeline")
    doc.add_argument("--snapshot", help="Also print the snapshot's shape (counts only, safe to share).")
    doc.add_argument("--intake", help="An intake CSV to include in the shape.")
    doc.add_argument("--strict", action="store_true", help="Fail on TODO lines too, not just FAIL lines.")
    return parser


def _prepare(args, rules, out):
    """Load the inputs and run the checks. Returns a Run, or 2 after printing what went wrong."""
    try:
        data = load_data(args.snapshot, args.intake)
    except (OSError, ValueError) as err:
        print(f"Cannot use the snapshot: {err}", file=out)
        return 2
    try:
        today = parse_date(args.today, "--today")
    except ValueError as err:
        print(f"Cannot use the date: {err}", file=out)
        return 2

    run = Run(rules, data, check_all(data.stories, rules, data.epics, today),
              generated=getattr(args, "generated", None) or datetime.now().strftime("%Y-%m-%d %H:%M"))
    if args.command in _SUGGESTING:
        try:
            run.context = load_context(args.context)
        except RulesError as err:
            _print_problems("hints", err, out)
            return 2
        run.suggestions = suggest_all(run.summary.results, rules, run.context, run.summary.analysis)
    return run


def _write(what, out, action):
    """Run a write. Turn a failure into a plain message and exit code 2."""
    try:
        action()
    except OSError as err:
        print(f"Cannot write the {what}: {err}", file=out)
        return False
    return True


# ---------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------

def _check(args, run, out):
    _print_report(run.summary, run.rules, args.details, out)
    _print_across(run.summary, out)
    if args.json_out:
        if not _write("results", out, lambda: _write_json(run.summary, run.rules, args.json_out)):
            return 2
        print(f"\nResults written to {args.json_out}", file=out)
    return 0


def _suggest(args, run, out):
    _print_suggestions(run.summary, run.suggestions, run.context, out)
    if args.json_out:
        def save():
            with open(args.json_out, "w", encoding="utf-8") as handle:
                json.dump({"label": LABEL, "files_read": run.context.files_read,
                           "suggestions": [to_dict(s) for s in run.suggestions.values()]}, handle, indent=2)
        if not _write("suggestions", out, save):
            return 2
        print(f"\nSuggestions written to {args.json_out}", file=out)
    return 0


def _workbook(args, run, out):
    if not _write("workbook", out, lambda: _save_workbook(args.out, run)):
        return 2
    print(f"Workbook written to {args.out}", file=out)
    print(f"  {len(run.summary.results)} stories checked, {len(run.suggestions)} with suggestions, "
          f"{len(run.data.stories)} in the raw data tab.", file=out)
    return 0


def _confluence(args, run, out):
    manifest = {}

    def save():
        manifest.update(write_sections(args.out_dir, build_sections(run.summary, run.rules, run.generated), run.rules,
                                       run.generated, include_markers=True if args.include_markers else None))
    if not _write("Confluence files", out, save):
        return 2
    print(f"Confluence sections written to {args.out_dir}", file=out)
    for entry in manifest["sections"]:
        print(f"  {entry['file']}   markers: {entry['start_marker']} ... {entry['end_marker']}", file=out)
    print("  manifest.json, preview.html (preview only, never publish it)", file=out)
    return 0


def _changes(args, run, out):
    changes = build_changes(run.summary, run.suggestions, run.rules)
    if not _write("changes file", out, lambda: _save_changes(args.out, run, changes)):
        return 2
    print(f"Changes written to {args.out}: {len(changes)} suggested edit(s) for {len({c.key for c in changes})} stories.", file=out)
    return 0


def _update_pack(args, run, out):
    changes = build_changes(run.summary, run.suggestions, run.rules)
    copy_buttons = False if args.no_copy_buttons else None
    if not _write("update pack", out, lambda: _save_pack(args.out, run, changes, copy_buttons)):
        return 2
    print(f"Update pack written to {args.out}: {len({c.key for c in changes})} stories with suggested edits.", file=out)
    return 0


def _report(args, run, out):
    folder = Path(args.out_dir)
    changes = build_changes(run.summary, run.suggestions, run.rules)
    paths = {name: folder / file for name, file in REPORT_FILES.items()}

    def save_all():
        folder.mkdir(parents=True, exist_ok=True)
        _save_workbook(paths["workbook"], run)
        _save_changes(paths["changes"], run, changes)
        _save_pack(paths["update_pack"], run, changes, None)
        write_sections(paths["confluence"], build_sections(run.summary, run.rules, run.generated), run.rules, run.generated,
                       include_markers=True if args.include_markers else None)
    if not _write("report", out, save_all):
        return 2
    print(f"Report written to {folder}", file=out)
    print(f"  {paths['workbook'].name}     the workbook", file=out)
    print(f"  {paths['changes'].name}                the suggested edits, one per row", file=out)
    print(f"  {paths['update_pack'].name}           the copy-and-paste page", file=out)
    print(f"  {paths['confluence'].name}/               the Confluence sections, manifest.json and preview.html", file=out)
    print(f"  {len(run.summary.results)} stories checked; {len(changes)} suggested edits for {len({c.key for c in changes})} stories.", file=out)
    return 0


def _snapshot(args, out):
    try:
        fmap = load_field_map(args.fields)
    except RulesError as err:
        _print_problems("field map", err, out)
        return 2
    files = {"current_sprint": args.current, "future_sprints": args.future, "backlog": args.backlog}
    if not any(files.values()):
        print("Give at least one export: --current, --future or --backlog.", file=out)
        return 2
    try:
        snapshot, notes = build_snapshot(files, args.epics, fmap)
    except (OSError, ValueError) as err:
        print(f"Cannot use the export: {err}", file=out)
        return 2
    if not _write("snapshot", out, lambda: Path(args.out).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")):
        return 2
    print(f"Snapshot written to {args.out}: {len(snapshot['stories'])} stories, {len(snapshot['epics'])} epics.", file=out)
    for note in notes:
        print(f"  note: {note}", file=out)
    return 0


def _doctor(args, out):
    checks = doctor.run_checks(args.rules, args.fields, args.context, args.pipeline_dir)
    print("Self-check for the Jira backlog refiner\n", file=out)
    for check in sorted(checks, key=lambda c: ("FAIL", "TODO", "OK").index(c.status)):
        print(f"  {check.status:<5} {check.topic:<18} {check.message}", file=out)
    fails = sum(c.status == "FAIL" for c in checks)
    todos = sum(c.status == "TODO" for c in checks)
    if args.snapshot:
        try:
            lines, warnings = doctor.shape(args.snapshot, args.intake)
        except (OSError, ValueError) as err:
            print(f"\nCannot read the snapshot: {err}", file=out)
            return 2
        print("\nSnapshot shape (counts only, safe to share):", file=out)
        for line in lines:
            print(f"  {line}", file=out)
        for warning in warnings:
            print(f"  WARNING {warning}", file=out)
    print(f"\nResult: {fails} to fix, {todos} to do. " + ("Fix the FAIL lines before the first real run." if fails else
          ("Ready to run. The TODO lines are worth doing." if todos else "Ready to run.")), file=out)
    return 1 if fails or (args.strict and todos) else 0


def _save_workbook(path, run):
    save_workbook(path, run.summary, run.data.stories, run.suggestions, run.rules, run.context, generated=run.generated)


def _save_changes(path, run, changes):
    write_changes_csv(path, changes, run.rules, {s.key: s for s in run.data.stories})


def _save_pack(path, run, changes, copy_buttons):
    html = build_update_pack(run.summary, run.suggestions, changes, run.rules, generated=run.generated, copy_buttons=copy_buttons)
    Path(path).write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------------------------------

def _print_problems(kind, err, out):
    print(f"The {kind} file has {len(err.problems)} problem(s):", file=out)
    for problem in err.problems:
        print(f"  - {problem}", file=out)


def _paint(text, verdict, out):
    use_color = os.environ.get("FORCE_COLOR") or getattr(out, "isatty", lambda: False)()
    return f"\033[{_COLORS[verdict]}m{text}\033[0m" if use_color else text


def _print_report(summary, rules, details, out):
    print(f"Rules version {rules.version}. Checked {len(summary.results)} stories and spikes.\n", file=out)
    print(f"{'KEY':<10} {'TYPE':<6} {'GROUP':<15} {'PTS':>4}  {'VERDICT':<14} FINDINGS", file=out)
    for result in summary.results:
        story = result.story
        points = "-" if story.story_points is None else f"{story.story_points:g}"
        codes = ", ".join(f.code for f in result.flags) or "-"
        verdict = _paint(f"{result.verdict:<14}", result.verdict, out)
        print(f"{story.key:<10} {story.issue_type[:6]:<6} {story.group:<15} {points:>4}  {verdict} {codes}", file=out)
        if details:
            for flag in result.flags:
                print(f"{'':<10} [{flag.severity}] {flag.message}", file=out)

    print("\nTotals:", file=out)
    for name, count in summary.counts_by_verdict().items():
        print(f"  {_paint(f'{name:<14}', name, out)} {count}", file=out)
    if summary.skipped:
        print("\nNot checked:", file=out)
        for reason, count in summary.skipped.items():
            print(f"  {count} x {reason}", file=out)


def _print_across(summary, out):
    """What was found by looking at stories together."""
    analysis = summary.analysis
    duplicates = [p for p in analysis.pairs if p.kind == "duplicate"]
    needing = [r for r in summary.results if {f.code for f in r.flags} & {"epic_missing", "epic_inactive"}]
    print("\nAcross stories:", file=out)
    print(f"  Possible duplicate pairs: {len(duplicates)} (related pairs: {len(analysis.pairs) - len(duplicates)})", file=out)
    print(f"  Stories that need an epic: {len(needing)} (with a suggested epic: {len(analysis.epic_matches)})", file=out)
    print(f"  New epic ideas: {len(analysis.new_epics)}", file=out)
    if analysis.themes:
        themes = ", ".join(f"{t.word} ({'listed' if t.known else 'counted'}, {len(t.starting)} of {len(t.keys)} titles start with it)"
                           for t in analysis.themes)
        print(f"  Themes: {themes}", file=out)


def _print_suggestions(summary, suggestions, context, out):
    print(f"{LABEL}\n", file=out)
    print(f"Context used: {', '.join(context.files_read) or 'none'}", file=out)
    print(f"Drafts for {len(suggestions)} of {len(summary.results)} stories.\n", file=out)
    for key, s in suggestions.items():
        print(f"{key}  [{s.verdict}]", file=out)
        if s.title:
            print(f"  Suggested title: {s.title}", file=out)
        if s.description:
            print(f"  Suggested description:\n    {s.description}", file=out)
            if s.needs_confirmation:
                print("    (has a placeholder to fill in)", file=out)
        if s.acceptance_criteria:
            print("  Suggested acceptance criteria:", file=out)
            for line in s.acceptance_criteria:
                print(f"    - {line}", file=out)
        if s.epic_options:
            print("  Suggested epic: " + "; ".join(f"{k} {n} ({round(sc * 100)}%)" for k, n, sc in s.epic_options), file=out)
        if s.new_epic:
            print(f"  New epic idea: {s.new_epic}", file=out)
        if s.labels:
            print(f"  Labels to add: {', '.join(s.labels)}", file=out)
        for other_key, other_title, score in s.duplicates:
            print(f"  Possible duplicate of: {other_key} ('{other_title}', {round(score * 100)}% alike)", file=out)
        if s.split_reason:
            print(f"  Suggest split: {s.split_reason}", file=out)
            for title in s.split_titles:
                print(f"    - {title}", file=out)
        if s.questions:
            print("  Ask in refinement:", file=out)
            for question in s.questions:
                print(f"    - {question}", file=out)
        for related_key, related_summary in s.related:
            print(f"  Similar well-written story: {related_key} ({related_summary})", file=out)
        for reference in s.references:
            print(f"  Related context: {reference}", file=out)
        print("", file=out)


def _write_json(summary, rules, path):
    data = {
        "rules_version": rules.version,
        "totals": summary.counts_by_verdict(),
        "skipped": dict(summary.skipped),
        "results": [
            {
                "key": r.story.key,
                "verdict": r.verdict,
                "worst_severity": r.worst_severity,
                "flags": [{"code": f.code, "severity": f.severity, "field": f.field, "message": f.message} for f in r.flags],
            }
            for r in summary.results
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
