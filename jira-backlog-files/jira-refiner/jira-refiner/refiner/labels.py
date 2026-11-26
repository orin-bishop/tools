"""Label rules: which labels a story must have, which are allowed, and which to suggest from its words.

Every list comes from the `labels` section of rules.yaml. Matching ignores capital letters.
"""
from .text import contains_phrase, plain_text, tokens


def _have(story):
    return {label.strip().lower() for label in story.labels}


def missing_required(story, rules):
    """Required labels the story does not have, as written in the rules file."""
    have = _have(story)
    return [label for label in rules.labels_required if label.lower() not in have]


def unknown_labels(story, rules):
    """The story's labels that are not on the allowed list. Empty if no allowed list is set."""
    if not rules.labels_allowed:
        return []
    allowed = {label.lower() for label in rules.labels_allowed}
    return [label for label in story.labels if label.strip().lower() not in allowed]


def suggested_by_words(story, rules):
    """Labels whose trigger words appear in the story text, if the story lacks them."""
    have = _have(story)
    story_tokens = tokens(f"{plain_text(story.summary)} {plain_text(story.description)} {plain_text(story.acceptance_criteria)}")
    found = []
    for rule in rules.label_rules:
        if rule.label.lower() in have or rule.label in found:
            continue
        if any(contains_phrase(word, story_tokens) for word in rule.words):
            found.append(rule.label)
    return found


def labels_to_add(story, rules):
    """Everything worth adding: missing required labels first, then labels the text suggests."""
    if not rules.labels_enabled:
        return []
    found = list(missing_required(story, rules))
    found += [label for label in suggested_by_words(story, rules) if label not in found]
    return found


def label_findings(story, rules):
    """[(check id, message)] for one story."""
    if not rules.labels_enabled:
        return []
    found = []
    missing = missing_required(story, rules)
    if missing:
        found.append(("labels_missing", f"The story is missing the label(s): {', '.join(missing)}."))
    unknown = unknown_labels(story, rules)
    if unknown:
        found.append(("label_unknown", f"The label(s) {', '.join(unknown)} are not on the allowed list: {', '.join(rules.labels_allowed)}."))
    suggested = [label for label in suggested_by_words(story, rules) if label not in missing]
    if suggested:
        found.append(("labels_suggested", f"The text suggests adding the label(s): {', '.join(suggested)}."))
    return found
