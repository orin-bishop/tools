"""Themes: several stories about the same thing can start their titles the same way, so they sort together.

A theme is a word found in at least `min_stories` titles. Words you list under `known` are always looked for;
other frequent words are reported as possible themes (up to `max_auto_themes`). For each story whose title
mentions a theme but does not start with it, we can draft a title that does, in the format from the rules file.
"""
import re
from collections import Counter
from dataclasses import dataclass

from .text import plain_text, stem, surface_map, tokens, topic_words


@dataclass(frozen=True)
class Theme:
    word: str           # as it would start a title, for example "Terraform"
    stem: str
    keys: tuple         # stories whose title mentions it
    starting: tuple     # of those, the ones whose title already starts with it
    known: bool         # True if it came from the rules file, False if it was found by counting

    @property
    def consistent(self):
        """True when every title that mentions the theme already starts with it."""
        return len(self.starting) == len(self.keys)


def _display(word):
    return word.capitalize() if word.islower() else word


def find_themes(stories, rules):
    """Themes in the titles of `stories`, known ones first, then the most frequent others."""
    if not rules.themes_enabled:
        return []
    titles = {s.key: plain_text(s.summary) for s in stories}
    title_tokens = {key: tokens(title) for key, title in titles.items()}
    spelling = surface_map(titles.values())

    def build(word_stem, display, known):
        keys = sorted(k for k, t in title_tokens.items() if word_stem in t)
        starting = sorted(k for k in keys if title_tokens[k] and title_tokens[k][0] == word_stem)
        return Theme(display, word_stem, tuple(keys), tuple(starting), known)

    themes, known_stems = [], set()
    for word in rules.themes_known:
        word_stem = stem(word.lower())
        known_stems.add(word_stem)
        theme = build(word_stem, _display(word.strip()), True)
        if len(theme.keys) >= rules.themes_min_stories:
            themes.append(theme)

    counts = Counter()
    for title in titles.values():
        counts.update(topic_words(title, rules.suggest_ignore_words))
    frequent = sorted(((w, n) for w, n in counts.items() if n >= rules.themes_min_stories and w not in known_stems),
                      key=lambda item: (-item[1], item[0]))
    themes += [build(w, _display(spelling.get(w, w)), False) for w, _ in frequent[: rules.themes_max_auto]]
    return themes


def prefix_title(theme, title, rules):
    """The title rewritten to start with the theme, using the format in the rules file.

    The theme word is taken out of the old title so it is not said twice. A title that is only the theme is left alone.
    """
    for match in re.finditer(r"[A-Za-z0-9]+", title):
        if stem(match.group().lower()) == theme.stem:
            remainder = re.sub(r"\s+", " ", title[: match.start()] + " " + title[match.end():]).strip(" -:,;")
            if not remainder:
                return title
            remainder = remainder[0].upper() + remainder[1:]
            return rules.themes_title_format.replace("{theme}", theme.word).replace("{title}", remainder)
    return title
