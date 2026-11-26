import json
import tempfile
import unittest
from pathlib import Path

from refiner.model import Epic, load_data, load_intake_csv, load_snapshot
from tests.helpers import ROOT

CSV_PATH = ROOT / "fixtures" / "intake.csv"
PROGRAM = ROOT / "fixtures" / "program.json"


def temp_file(text, suffix=".csv"):
    folder = tempfile.TemporaryDirectory()
    path = Path(folder.name) / f"file{suffix}"
    path.write_text(text, encoding="utf-8")
    return folder, path


class IntakeCsvTests(unittest.TestCase):
    def test_fixture_file(self):
        stories = load_intake_csv(CSV_PATH)
        self.assertEqual([s.key for s in stories], ["NEW-1", "NEW-2"])       # the blank line is skipped
        first, second = stories
        self.assertEqual((first.group, first.issue_type, first.story_points, first.epic), ("intake", "Story", 2.0, "EPIC-2"))
        self.assertEqual(first.labels, ["team-save", "alerts"])               # a semicolon works as a separator
        self.assertEqual(first.summary, "Add alert for failed deployments")
        self.assertEqual((second.issue_type, second.story_points, second.labels), ("Spike", 3.0, []))

    def test_column_names_are_flexible_and_a_key_column_is_kept(self):
        folder, path = temp_file("Id,Title,AC,Points,Epic Link\nX-9,Do a thing,Done when done,5,EPIC-1\n")
        with folder:
            story = load_intake_csv(path)[0]
        self.assertEqual((story.key, story.summary, story.acceptance_criteria, story.story_points, story.epic),
                         ("X-9", "Do a thing", "Done when done", 5.0, "EPIC-1"))

    def test_numbering_continues_from_the_given_start(self):
        folder, path = temp_file("Summary\nOne\nTwo\n")
        with folder:
            self.assertEqual([s.key for s in load_intake_csv(path, first_number=4)], ["NEW-4", "NEW-5"])

    def test_a_summary_column_is_required_and_the_message_lists_what_was_found(self):
        folder, path = temp_file("Name,Notes\nx,y\n")
        with folder, self.assertRaises(ValueError) as caught:
            load_intake_csv(path)
        self.assertIn("needs a 'Summary' (or 'Title') column", str(caught.exception))
        self.assertIn("Name, Notes", str(caught.exception))

    def test_an_empty_file_is_a_plain_error(self):
        folder, path = temp_file("")
        with folder, self.assertRaises(ValueError) as caught:
            load_intake_csv(path)
        self.assertIn("empty", str(caught.exception))

    def test_a_bad_value_names_the_line(self):
        folder, path = temp_file("Summary,Story points\nOk,2\nBad,lots\n")
        with folder, self.assertRaises(ValueError) as caught:
            load_intake_csv(path)
        self.assertIn("line 3", str(caught.exception))
        self.assertIn("'lots'", str(caught.exception))

    def test_excel_style_byte_order_mark_is_handled(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "bom.csv"
        path.write_bytes("\ufeffSummary,Epic\nOne,EPIC-1\n".encode("utf-8"))
        self.assertEqual(load_intake_csv(path)[0].epic, "EPIC-1")


class SnapshotTests(unittest.TestCase):
    def test_stories_intake_and_epics_load_together(self):
        data = load_data(PROGRAM)
        self.assertEqual(len(data.epics), 5)
        self.assertEqual([s.key for s in data.stories if s.group == "intake"], ["NEW-1", "NEW-2", "NEW-3"])
        self.assertEqual(len([s for s in data.stories if s.group == "backlog"]), 13)

    def test_intake_in_the_file_gets_group_and_keys(self):
        folder, path = temp_file(json.dumps({"stories": [], "intake": [{"summary": "One"}, {"summary": "Two", "key": "KEEP-1"}]}), ".json")
        with folder:
            stories = load_data(path).stories
        self.assertEqual([(s.key, s.group) for s in stories], [("NEW-1", "intake"), ("KEEP-1", "intake")])

    def test_a_csv_is_added_after_the_intake_in_the_file(self):
        folder, path = temp_file(json.dumps({"stories": [], "intake": [{"summary": "One"}]}), ".json")
        with folder:
            stories = load_data(path, intake_csv=CSV_PATH).stories
        self.assertEqual([s.key for s in stories], ["NEW-1", "NEW-2", "NEW-3"])

    def test_the_old_stories_only_format_still_works(self):
        self.assertEqual(len(load_snapshot(ROOT / "fixtures" / "snapshot.json")), 20)
        self.assertEqual(load_data(ROOT / "fixtures" / "snapshot.json").epics, [])

    def test_a_plain_list_still_works(self):
        folder, path = temp_file(json.dumps([{"key": "A-1"}]), ".json")
        with folder:
            self.assertEqual([s.key for s in load_data(path).stories], ["A-1"])

    def test_bad_shapes_are_plain_errors(self):
        for text in ('{"stories": [], "epics": "nope"}', '{"stories": [], "intake": "nope"}', '{"nothing": 1}'):
            folder, path = temp_file(text, ".json")
            with folder, self.assertRaises(ValueError):
                load_data(path)

    def test_epic_needs_a_key(self):
        with self.assertRaises(ValueError):
            Epic.from_dict({"name": "No key"})


if __name__ == "__main__":
    unittest.main()
