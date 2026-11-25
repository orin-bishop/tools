"""The sizing checks (P1-5): is the story the size its points say?

We size 1 point = 1 day. Two things are worth a second look:
  * large_and_thin       a big story with very little written about it
  * possibly_undersized  a small story that matches a "work pattern": a kind of work that
                         sounds small but usually is not (for example encrypting an existing
                         database). The patterns live in rules.yaml, so the people who know the
                         tech stack can add to them. They are a prompt to look again, not a verdict.
"""
from .text import contains_phrase, tokens


def find_work_patterns(rules, summary, description, criteria):
    """Return the work patterns whose words appear in the story text, in rules-file order."""
    story_tokens = tokens(f"{summary} {description} {criteria}")
    return [
        pattern
        for pattern in rules.work_patterns
        if any(contains_phrase(word, story_tokens) for word in pattern.words)
    ]


def check_sizing(story, rules, summary, description, criteria):
    """Return a list of (check id, message). The caller adds severity and the field."""
    points = story.story_points
    if points is None:
        return []        # an unpointed story is reported by the quality checks

    found = []
    days = points * rules.points_equal_days

    if points >= rules.review_at_or_above:
        thin_description = len(description) < rules.thin_chars
        thin_criteria = len(criteria) < rules.ac_min_chars
        if thin_description or thin_criteria:
            what = "description and acceptance criteria are" if thin_description and thin_criteria else (
                "description is" if thin_description else "acceptance criteria are")
            found.append((
                "large_and_thin",
                f"The story is {points:g} points (about {days:g} days) but the {what} thin. Add detail, or split the story.",
            ))

    if points <= rules.max_points_before_keyword_review:
        patterns = find_work_patterns(rules, summary, description, criteria)
        if patterns:
            names = " and ".join(f"'{p.name}'" for p in patterns[:2])
            unit = "point" if points == 1 else "points"
            found.append((
                "possibly_undersized",
                f"The story is {points:g} {unit} but looks like {names}. {patterns[0].why_bigger} Check whether it needs splitting.",
            ))

    return found
