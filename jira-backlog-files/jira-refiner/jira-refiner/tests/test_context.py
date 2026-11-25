import tempfile
import unittest
from pathlib import Path

from refiner.context import find_hint, find_sections, load_context, parse_hints
from refiner.rules import RulesError
from refiner.text import words

GOOD_HINTS = """
hints_version: 1
hints:
  - name: Add a dashboard
    words: [dashboard]
    so_that: "the team can see the numbers"
    acceptance_criteria:
      - "The dashboard shows the numbers named in the story"
    questions:
      - "Who looks at it?"
  - name: Rotate credentials
    words: ["rotate credentials", "rotate keys"]
"""

MARKDOWN = """# Top title

Intro text about nothing much.

## Database encryption

Databases are encrypted at rest. Plan a test environment first.

### Snapshots

Keep snapshots for a week.

## Dashboards

A dashboard names its audience.
"""


def problems(text):
    try:
        parse_hints(text)
    except RulesError as err:
        return err.problems
    return []


class ParseHintsTests(unittest.TestCase):
    def test_good_file(self):
        hints = parse_hints(GOOD_HINTS)
        self.assertEqual([h.name for h in hints], ["Add a dashboard", "Rotate credentials"])
        self.assertEqual(hints[0].so_that, "the team can see the numbers")
        self.assertEqual(hints[0].acceptance_criteria, ("The dashboard shows the numbers named in the story",))
        self.assertEqual(hints[1].so_that, "")          # optional parts may be left out
        self.assertEqual(hints[1].questions, ())

    def test_empty_list_is_allowed(self):
        self.assertEqual(parse_hints("hints_version: 1\nhints: []\n"), ())

    def test_hint_without_words_names_the_hint_and_line(self):
        found = problems(GOOD_HINTS.replace('words: [dashboard]', 'words: []'))
        self.assertEqual(len(found), 1, found)
        self.assertIn("hints[1].words", found[0])
        self.assertIn("line", found[0])

    def test_misspelt_setting_gets_a_suggestion(self):
        found = problems(GOOD_HINTS.replace("so_that:", "so_thatt:"))
        self.assertTrue(any("Did you mean 'so_that'" in p for p in found), found)

    def test_missing_name(self):
        found = problems(GOOD_HINTS.replace("  - name: Add a dashboard\n    words", "  - words", 1))
        self.assertTrue(any("hints[1].name" in p and "missing" in p for p in found), found)

    def test_hints_must_be_a_list(self):
        self.assertTrue(any("must be a list" in p for p in problems("hints_version: 1\nhints: dashboards\n")))

    def test_broken_yaml(self):
        self.assertIn("not valid YAML", problems("hints_version: 1\nhints: [unclosed\n")[0])


class LoadContextTests(unittest.TestCase):
    def make_folder(self, hints=GOOD_HINTS, markdown=MARKDOWN):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        if hints is not None:
            (root / "hints.yaml").write_text(hints)
        if markdown is not None:
            (root / "sub").mkdir()
            (root / "sub" / "standards.md").write_text(markdown)
        return root

    def test_reads_hints_and_markdown(self):
        index = load_context(self.make_folder())
        self.assertEqual(len(index.hints), 2)
        self.assertEqual(index.files_read, ["hints.yaml", "sub/standards.md"])
        headings = [s.heading for s in index.sections]
        self.assertEqual(headings, ["Top title", "Database encryption", "Snapshots", "Dashboards"])

    def test_missing_folder_or_no_folder_is_empty(self):
        for place in (None, "", "/no/such/folder"):
            index = load_context(place)
            self.assertEqual((index.hints, index.sections, index.files_read), ((), (), []))

    def test_hints_file_is_optional(self):
        index = load_context(self.make_folder(hints=None))
        self.assertEqual(index.hints, ())
        self.assertEqual(len(index.sections), 4)

    def test_broken_hints_file_raises_with_the_file_name(self):
        with self.assertRaises(RulesError) as caught:
            load_context(self.make_folder(hints="hints_version: 1\nhints: nope\n"))
        self.assertIn("hints.yaml", caught.exception.problems[0])

    def test_section_words_include_the_heading_and_the_text(self):
        section = next(s for s in load_context(self.make_folder()).sections if s.heading == "Database encryption")
        self.assertIn("encrypt", section.words)
        self.assertIn("test", section.words)
        self.assertEqual(section.heading_words, frozenset(words("Database encryption")))


class FindTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / "hints.yaml").write_text(GOOD_HINTS)
        (Path(folder.name) / "standards.md").write_text(MARKDOWN)
        self.index = load_context(folder.name)

    def test_hint_found_by_phrase_with_word_endings_and_gaps(self):
        self.assertEqual(find_hint(self.index, "We should rotate the shared keys").name, "Rotate credentials")
        self.assertEqual(find_hint(self.index, "Add dashboards for builds").name, "Add a dashboard")

    def test_no_hint(self):
        self.assertIsNone(find_hint(self.index, "Fix the thing"))

    def test_first_matching_hint_wins(self):
        self.assertEqual(find_hint(self.index, "rotate keys and add a dashboard").name, "Add a dashboard")

    def test_sections_need_enough_shared_words(self):
        story = set(words("Encrypt the database"))
        self.assertEqual([s.heading for s in find_sections(self.index, story, 2, 5)], ["Database encryption"])
        self.assertEqual(find_sections(self.index, story, 3, 5), [])

    def test_sections_best_first_and_limited(self):
        story = set(words("Dashboard audience for database encryption test environment"))
        found = find_sections(self.index, story, 2, 5)
        self.assertEqual(found[0].heading, "Database encryption")
        self.assertEqual(len(find_sections(self.index, story, 1, 1)), 1)


if __name__ == "__main__":
    unittest.main()
