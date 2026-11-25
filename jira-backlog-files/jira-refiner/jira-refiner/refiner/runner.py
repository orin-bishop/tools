"""Run every check on every story and keep the results together."""
from collections import Counter
from dataclasses import dataclass, field

from .checks import run_checks
from .verdict import VERDICTS, verdict_for, worst_severity


@dataclass
class StoryResult:
    story: object
    flags: list
    verdict: str
    worst_severity: str


@dataclass
class RunSummary:
    results: list = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)    # reason -> how many stories

    def counts_by_verdict(self):
        counts = Counter(r.verdict for r in self.results)
        return {name: counts.get(name, 0) for name in VERDICTS}


def out_of_scope_reason(story, rules):
    """Return why a story is not checked, or '' if it is in scope."""
    if story.group not in rules.include_groups:
        return f"group '{story.group}' is not included"
    if story.status.lower() in rules.ignore_statuses:
        return f"status '{story.status}' is ignored"
    if story.issue_type.lower() not in [t.lower() for t in rules.issue_types]:
        return f"issue type '{story.issue_type}' is not in scope"
    return ""


def check_all(stories, rules):
    """Check every in-scope story. Returns a RunSummary."""
    summary = RunSummary()
    for story in stories:
        reason = out_of_scope_reason(story, rules)
        if reason:
            summary.skipped[reason] += 1
            continue
        flags = run_checks(story, rules)
        summary.results.append(StoryResult(story, flags, verdict_for(flags), worst_severity(flags)))
    return summary
