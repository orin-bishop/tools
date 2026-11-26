"""Titles (the Summary field): is it too long, and what could a better one be?

A suggested title is built ONLY from the story's own description: the "I want ..." part if there is one,
otherwise the first sentence. It adds no new words.
"""
import re

from .storyform import want_in, without_role
from .text import plain_text


def title_is_long(summary, rules):
    return len(plain_text(summary)) > rules.title_max_chars


def suggest_title(summary, description, rules):
    """A title drafted from the description, or '' when there is nothing to draft or it matches the current one."""
    text = plain_text(description)
    want = want_in(text)
    if want:
        candidate = re.sub(r"^to\s+", "", want, flags=re.IGNORECASE)                       # "to add a check" -> "add a check"
        if candidate == want:
            candidate = re.sub(r"^(?:a|an|the)\s+", "", want, flags=re.IGNORECASE)         # "a dashboard" -> "dashboard"
    else:
        candidate = _first_sentence(without_role(text))
    candidate = candidate.strip(" .,;:-")
    if not candidate:
        return ""
    candidate = _shorten(candidate[0].upper() + candidate[1:], rules.title_max_chars)
    return "" if _same(candidate, plain_text(summary)) else candidate


def _first_sentence(text):
    for part in re.split(r"(?<=[.!?])\s+", text.strip()):
        if part.strip(" .!?"):
            return part
    return ""


def _shorten(text, limit):
    """Cut at a word boundary so the title fits. No dots are added: the title should still read as a title."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" ,;:-")


def _same(first, second):
    return re.sub(r"[^a-z0-9]+", " ", first.lower()).strip() == re.sub(r"[^a-z0-9]+", " ", second.lower()).strip()
