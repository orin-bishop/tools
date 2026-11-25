"""Command line: validate the rules, check a snapshot of stories, or draft suggestions.

    python -m refiner validate-rules --rules rules.yaml
    python -m refiner check   --snapshot fixtures/snapshot.json --rules rules.yaml [--details] [--json out.json]
    python -m refiner suggest --snapshot fixtures/snapshot.json --rules rules.yaml --context context [--json out.json]
    python -m refiner workbook --snapshot fixtures/snapshot.json --rules rules.yaml --context context --out report.xlsx
    python -m refiner confluence --snapshot fixtures/snapshot.json --rules rules.yaml --out-dir confluence-out

Exit codes: 0 = ran fine, 2 = the rules file, hints file or snapshot has a problem.
Nothing here writes to Jira.
"""
import argparse
import json
import os
import sys
from datetime import datetime

from .confluence import build_sections, write_sections
from .context import load_context
from .model import load_snapshot
from .rules import RulesError, load_rules
from .runner import check_all
from .suggest import LABEL, suggest_all, to_dict
from .workbook import save_workbook
from .verdict import LOOKS_GOOD, MISSING_INFO, NEEDS_REVIEW, SUGGEST_SPLIT

_COLORS = {LOOKS_GOOD: "32", NEEDS_REVIEW: "33", MISSING_INFO: "31", SUGGEST_SPLIT: "31;1"}   # green, yellow, red, bold red


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m refiner", description="Check Jira stories against the refinement rules.")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-rules", help="Check the rules file and say what is wrong.")
    validate.add_argument("--rules", default="rules.yaml")

    check = commands.add_parser("check", help="Check every story in a snapshot file.")
    check.add_argument("--snapshot", required=True)
    check.add_argument("--rules", default="rules.yaml")
    check.add_argument("--details", action="store_true", help="Print the full sentence for every finding.")
    check.add_argument("--json", dest="json_out", help="Also write the results to this JSON file.")

    suggest = commands.add_parser("suggest", help="Draft suggestions for every story that is not 'Looks good'.")
    suggest.add_argument("--snapshot", required=True)
    suggest.add_argument("--rules", default="rules.yaml")
    suggest.add_argument("--context", default="context", help="Folder with hints.yaml and markdown context files.")
    suggest.add_argument("--json", dest="json_out", help="Also write the suggestions to this JSON file.")

    book = commands.add_parser("workbook", help="Write the Excel workbook: summary, findings, suggestions, raw data.")
    book.add_argument("--snapshot", required=True)
    book.add_argument("--rules", default="rules.yaml")
    book.add_argument("--context", default="context", help="Folder with hints.yaml and markdown context files.")
    book.add_argument("--out", default="refinement-report.xlsx", help="Where to write the .xlsx file.")
    book.add_argument("--generated", help="Text for the 'Generated' line. Default: the current date and time.")

    page = commands.add_parser("confluence", help="Write the Confluence report as HTML body sections with their markers.")
    page.add_argument("--snapshot", required=True)
    page.add_argument("--rules", default="rules.yaml")
    page.add_argument("--out-dir", default="confluence-out", help="Folder for the section files, manifest.json and preview.html.")
    page.add_argument("--include-markers", action="store_true", help="Write the start and end markers into each section file.")
    page.add_argument("--generated", help="Text for the 'Generated' line. Default: the current date and time.")

    args = parser.parse_args(argv)
    try:
        rules = load_rules(args.rules)
    except RulesError as err:
        _print_problems("rules", err, out)
        return 2

    if args.command == "validate-rules":
        print(f"Rules OK: version {rules.version}, {len(rules.issue_types)} issue type(s), {len(rules.work_patterns)} work pattern(s).", file=out)
        return 0

    try:
        stories = load_snapshot(args.snapshot)
    except (OSError, ValueError) as err:
        print(f"Cannot use the snapshot: {err}", file=out)
        return 2

    summary = check_all(stories, rules)

    if args.command == "confluence":
        generated = args.generated or datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            manifest = write_sections(args.out_dir, build_sections(summary, rules, generated), rules, generated,
                                      include_markers=True if args.include_markers else None)
        except OSError as err:
            print(f"Cannot write the Confluence files: {err}", file=out)
            return 2
        print(f"Confluence sections written to {args.out_dir}", file=out)
        for entry in manifest["sections"]:
            print(f"  {entry['file']}   markers: {entry['start_marker']} ... {entry['end_marker']}", file=out)
        print(f"  manifest.json, preview.html (preview only, never publish it)", file=out)
        return 0

    if args.command == "check":
        _print_report(summary, rules, args.details, out)
        if args.json_out:
            _write_json(summary, rules, args.json_out)
            print(f"\nResults written to {args.json_out}", file=out)
        return 0

    # suggest and workbook both use the context folder
    try:
        context = load_context(args.context)
    except RulesError as err:
        _print_problems("hints", err, out)
        return 2
    suggestions = suggest_all(summary.results, rules, context)

    if args.command == "workbook":
        try:
            save_workbook(args.out, summary, stories, suggestions, rules, context, generated=args.generated)
        except OSError as err:
            print(f"Cannot write the workbook: {err}", file=out)
            return 2
        print(f"Workbook written to {args.out}", file=out)
        print(f"  {len(summary.results)} stories checked, {len(suggestions)} with suggestions, {len(stories)} in the raw data tab.", file=out)
        return 0

    _print_suggestions(summary, suggestions, context, out)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"label": LABEL, "files_read": context.files_read,
                       "suggestions": [to_dict(s) for s in suggestions.values()]}, handle, indent=2)
        print(f"\nSuggestions written to {args.json_out}", file=out)
    return 0


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


def _print_suggestions(summary, suggestions, context, out):
    print(f"{LABEL}\n", file=out)
    print(f"Context used: {', '.join(context.files_read) or 'none'}", file=out)
    print(f"Drafts for {len(suggestions)} of {len(summary.results)} stories.\n", file=out)
    for key, s in suggestions.items():
        print(f"{key}  [{s.verdict}]", file=out)
        if s.description:
            print(f"  Suggested description:\n    {s.description}", file=out)
            if s.needs_confirmation:
                print("    (has a placeholder to fill in)", file=out)
        if s.acceptance_criteria:
            print("  Suggested acceptance criteria:", file=out)
            for line in s.acceptance_criteria:
                print(f"    - {line}", file=out)
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
