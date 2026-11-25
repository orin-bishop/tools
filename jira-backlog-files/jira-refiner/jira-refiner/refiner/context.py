"""Context for suggestions: a hints file plus the markdown files of the context repo.

On the Fed side the context repo is the program metrics repo. Here we use a made-up sample folder
(`context/`). Two kinds of context, kept deliberately simple:

  hints.yaml    Short, structured, person-confirmed hints for topics the team meets often
                (for example "dashboard" or "alert"): a reason, acceptance criteria, questions.
                The Fed-side assistant drafts this file from the real context repo; a person confirms it.
  *.md files    Free text. We never copy from them. We only point at the sections that look related
                ("platform-standards.md > Database encryption") so an engineer can read them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .text import contains_phrase, tokens, words
from .yamlcheck import Reader, SettingsError, load_yaml


@dataclass(frozen=True)
class Hint:
    name: str
    words: tuple                 # phrases that trigger it
    so_that: str                 # the usual reason, as in "so that <reason>"; '' if unknown
    acceptance_criteria: tuple   # a few plain, testable checks
    questions: tuple             # what to ask in refinement


@dataclass(frozen=True)
class Section:
    file: str
    heading: str
    words: frozenset             # meaningful words in the heading and the text under it
    heading_words: frozenset


@dataclass
class ContextIndex:
    hints: tuple = ()
    sections: tuple = ()
    files_read: list = field(default_factory=list)    # for the log: which files were used


def parse_hints(text, source="hints.yaml"):
    """Check hints text and return a tuple of Hint objects. Raises SettingsError listing every problem."""
    data, lines = load_yaml(text, source)
    r = Reader(data, lines, source)
    r.mapping([], ("hints_version", "hints"))
    r.whole(["hints_version"], minimum=1)

    found, value = r.find(["hints"])
    hints = []
    if not found:
        r.bad(["hints"], "is missing. Add it back. Use [] for none.")
    elif not isinstance(value, list):
        r.bad(["hints"], "must be a list of hints. Use [] for none.")
    else:
        for number in range(len(value)):
            where = ["hints", number]
            r.mapping(where, ("name", "words", "so_that", "acceptance_criteria", "questions"))
            hints.append(Hint(
                name=r.text(where + ["name"]),
                words=tuple(r.text_list(where + ["words"], non_empty=True)),
                so_that=r.optional_text(where + ["so_that"]),
                acceptance_criteria=tuple(r.text_list(where + ["acceptance_criteria"])),
                questions=tuple(r.text_list(where + ["questions"])),
            ))
    if r.problems:
        raise SettingsError(r.problems)
    return tuple(hints)


def load_context(folder):
    """Read hints.yaml (optional) and every .md file under `folder`. A missing folder gives an empty index."""
    folder = Path(folder) if folder else None
    index = ContextIndex()
    if folder is None or not folder.is_dir():
        return index

    hints_path = folder / "hints.yaml"
    if hints_path.is_file():
        index.hints = parse_hints(hints_path.read_text(encoding="utf-8"), source="hints.yaml")
        index.files_read.append("hints.yaml")

    sections = []
    for path in sorted(folder.rglob("*.md")):
        relative = path.relative_to(folder).as_posix()
        sections.extend(_sections_of(relative, path.read_text(encoding="utf-8")))
        index.files_read.append(relative)
    index.sections = tuple(sections)
    return index


def _sections_of(relative, text):
    """Split a markdown file into (heading, text under it) sections."""
    found = []
    heading, body = None, []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.*\S)\s*$", line)
        if match:
            if heading is not None:
                found.append(_section(relative, heading, body))
            heading, body = match.group(1), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        found.append(_section(relative, heading, body))
    return found


def _section(relative, heading, body):
    heading_words = frozenset(words(heading))
    return Section(relative, heading, frozenset(words(" ".join(body))) | heading_words, heading_words)


def find_hint(index, story_text):
    """The first hint whose words appear in the story text, or None."""
    story_tokens = tokens(story_text)
    for hint in index.hints:
        if any(contains_phrase(word, story_tokens) for word in hint.words):
            return hint
    return None


def find_sections(index, story_words, minimum_shared, limit):
    """The sections that share the most meaningful words with the story (a set of words), best first."""
    scored = []
    for position, section in enumerate(index.sections):
        shared = story_words & section.words
        if len(shared) >= minimum_shared:
            scored.append((-len(shared), -len(story_words & section.heading_words), position, section))
    scored.sort(key=lambda item: item[:3])
    return [item[3] for item in scored[:limit]]
