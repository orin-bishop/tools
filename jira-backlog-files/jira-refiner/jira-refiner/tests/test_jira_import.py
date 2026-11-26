import json
import tempfile
import unittest
from pathlib import Path

from refiner.jira_import import (build_snapshot, epic_key_of, load_field_map, parse_field_map, read_export, sprint_name,
                                 text_of)
from refiner.model import Story, load_data
from refiner.rules import RulesError
from tests.helpers import ROOT

EXPORTS = ROOT / "fixtures" / "jira_export"
FMAP_PATH = ROOT / "fixtures" / "jira_fields.test.yaml"


def build():
    fmap = load_field_map(FMAP_PATH)
    files = {"current_sprint": [EXPORTS / "current_sprint.json"], "future_sprints": [EXPORTS / "future_sprints.json"],
             "backlog": [EXPORTS / "backlog.json"]}
    return build_snapshot(files, [EXPORTS / "epics.json"], fmap)


class FieldMapTests(unittest.TestCase):
    def test_the_test_map_loads(self):
        fmap = load_field_map(FMAP_PATH)
        self.assertEqual((fmap.acceptance_criteria, fmap.epic_end, fmap.extra), ("customfield_10100", "duedate", "all"))

    def test_the_shipped_map_is_refused_while_it_has_placeholders(self):
        with self.assertRaises(RulesError) as caught:
            load_field_map(ROOT / "jira_fields.yaml")
        problems = " ".join(caught.exception.problems)
        self.assertIn("REPLACE_ACCEPTANCE_CRITERIA_FIELD_ID", problems)
        self.assertIn("story_fields.sprint", problems)

    def test_extra_fields_can_be_none_or_a_list(self):
        text = FMAP_PATH.read_text()
        self.assertEqual(parse_field_map(text.replace("extra_fields: all", "extra_fields: []")).extra, ())
        self.assertEqual(parse_field_map(text.replace("extra_fields: all", "extra_fields: [priority]")).extra, ("priority",))
        with self.assertRaises(RulesError):
            parse_field_map(text.replace("extra_fields: all", "extra_fields: 7"))

    def test_a_missing_file_is_a_plain_error(self):
        with self.assertRaises(RulesError) as caught:
            load_field_map("/no/such/fields.yaml")
        self.assertIn("Cannot read the field map", caught.exception.problems[0])


class ValueTests(unittest.TestCase):
    def test_text_of_handles_every_jira_shape(self):
        self.assertEqual(text_of(None), "")
        self.assertEqual(text_of({"displayName": "Sample Person", "name": "s"}), "Sample Person")
        self.assertEqual(text_of({"value": "Option A"}), "Option A")
        self.assertEqual(text_of([{"name": "A"}, {"name": "B"}, None]), "A, B")
        self.assertEqual(text_of(3.0), "3")
        self.assertEqual(text_of(True), "Yes")

    def test_sprint_names_from_old_text_new_objects_and_lists(self):
        old = "com.atlassian.greenhopper.service.sprint.Sprint@1[id=3,rapidViewId=1,state=ACTIVE,name=Sprint 12,goal=]"
        self.assertEqual(sprint_name(old), "Sprint 12")
        self.assertEqual(sprint_name({"name": "Sprint 13"}), "Sprint 13")
        self.assertEqual(sprint_name([{"name": "Sprint 11"}, {"name": "Sprint 12"}]), "Sprint 12")
        self.assertEqual(sprint_name(None), "")
        self.assertEqual(sprint_name([]), "")

    def test_epic_link_as_key_or_object(self):
        self.assertEqual(epic_key_of("JE-1"), "JE-1")
        self.assertEqual(epic_key_of({"key": "JE-1", "name": "x"}), "JE-1")
        self.assertEqual(epic_key_of(None), "")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.notes = build()
        self.stories = {s["key"]: s for s in self.snapshot["stories"]}

    def test_the_file_decides_the_group_and_a_repeat_keeps_the_first(self):
        self.assertEqual({k: s["group"] for k, s in self.stories.items()},
                         {"J-1": "current_sprint", "J-2": "current_sprint", "J-3": "future_sprints", "J-4": "backlog"})
        self.assertEqual(self.notes, ["J-1 is in both current_sprint and backlog; kept it in current_sprint."])

    def test_custom_fields_are_read_through_the_map(self):
        j1 = self.stories["J-1"]
        self.assertEqual(j1["acceptance_criteria"], "* Returns 200 when the service is up\n* Returns 503 when the database is down")
        self.assertEqual((j1["story_points"], j1["epic"], j1["sprint"]), (2.0, "JE-1", "Sprint 12"))
        self.assertEqual((j1["status"], j1["issue_type"], j1["assignee"], j1["labels"]), ("In Progress", "Story", "Sample Person A", ["platform"]))

    def test_agile_style_epic_object_and_text_points_work(self):
        self.assertEqual(self.stories["J-3"]["epic"], "JE-1")
        self.assertEqual(self.stories["J-4"]["story_points"], 5.0)
        self.assertIsNone(self.stories["J-2"]["story_points"])

    def test_wiki_markup_is_kept_as_jira_gave_it(self):
        self.assertTrue(self.stories["J-2"]["description"].startswith("h3. Why"))

    def test_other_fields_use_readable_names_and_skip_empty_ones(self):
        extra = self.stories["J-1"]["extra"]
        self.assertEqual(extra["Priority"], "Medium")
        self.assertEqual(extra["Components"], "Platform")
        self.assertNotIn("Acceptance Criteria", extra)          # already used, not repeated

    def test_epics(self):
        epics = {e["key"]: e for e in self.snapshot["epics"]}
        self.assertEqual(epics["JE-1"], {"key": "JE-1", "name": "Terraform migration", "status": "In Progress", "start_date": "", "end_date": "2027-03-31"})
        self.assertEqual(epics["JE-2"]["end_date"], "")

    def test_the_result_loads_as_a_snapshot_and_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.json"
            path.write_text(json.dumps(self.snapshot))
            data = load_data(path)
        self.assertEqual(len(data.stories), 4)
        self.assertEqual(len(data.epics), 2)
        self.assertIsInstance(data.stories[0], Story)

    def test_bad_exports_are_plain_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            for text in ('{"something": 1}', '[{"issues": [{"no_key": 1}]}]'):
                path = Path(folder) / "bad.json"
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_export(path)


if __name__ == "__main__":
    unittest.main()
