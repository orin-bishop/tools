"""Pull the parts out of a story written as 'As a <role>, I want <what>, so that <why>.'

All three helpers expect PLAIN text (run plain_text() first) and return '' when a part is not there.
"""
import re

_FLAGS = re.IGNORECASE | re.DOTALL


def role_in(description):
    """The role in 'As a <role>, I want ...'."""
    found = re.search(r"\bas an? (.+?),?\s+i (?:want|need)\b", description, _FLAGS)
    return found.group(1).strip() if found else ""


def want_in(description):
    """The 'what' in 'I want <what>', up to 'so that' or the end of the sentence."""
    found = re.search(r"\bi (?:want|need) (.+?)(?:,?\s+so that\b|[.!?](?:\s|$)|$)", description, _FLAGS)
    return found.group(1).strip(" ,;") if found else ""


def reason_in(description):
    """The 'why' in 'so that <why>', up to the end of the sentence."""
    found = re.search(r"\bso that\s+(.+?)(?:[.!?](?:\s|$)|$)", description, _FLAGS)
    return found.group(1).strip(" ,;") if found else ""


def without_role(description):
    """The description with 'As a <role>, I want' taken out.

    Every story starts with the same role words. When we compare stories or look for related
    context, those shared words would make everything look alike, so we leave them out.
    """
    return re.sub(r"\bas an? .+?,?\s+i (?:want|need)\b", " ", description, flags=_FLAGS)
