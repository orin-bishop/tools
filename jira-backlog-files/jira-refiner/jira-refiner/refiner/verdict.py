"""One verdict per story, worked out from its findings."""

LOOKS_GOOD = "Looks good"
NEEDS_REVIEW = "Needs review"
MISSING_INFO = "Missing info"
SUGGEST_SPLIT = "Suggest split"

VERDICTS = (LOOKS_GOOD, NEEDS_REVIEW, MISSING_INFO, SUGGEST_SPLIT)

# Findings that point to a story that is bigger than its points say.
SPLIT_CODES = frozenset({"large_and_thin", "possibly_undersized"})
# Findings that mean something is simply not filled in.
MISSING_CODES = frozenset({
    "summary_missing", "description_missing", "ac_missing", "points_missing", "other_required_missing",
    "epic_missing", "labels_missing",
})

_ORDER = {"high": 3, "medium": 2, "low": 1}


def verdict_for(flags):
    """Pick the verdict. Order matters: a split suggestion beats missing info, which beats review."""
    codes = {f.code for f in flags}
    if codes & SPLIT_CODES:
        return SUGGEST_SPLIT
    if codes & MISSING_CODES:
        return MISSING_INFO
    if flags:
        return NEEDS_REVIEW
    return LOOKS_GOOD


def worst_severity(flags):
    """'high', 'medium' or 'low' for the most serious finding, or '' if there are none."""
    if not flags:
        return ""
    return max((f.severity for f in flags), key=lambda level: _ORDER[level])
