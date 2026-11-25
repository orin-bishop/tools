import json
import unittest

from refiner.checks import Flag
from refiner.model import Story, load_snapshot
from refiner.runner import check_all, out_of_scope_reason
from refiner.verdict import (LOOKS_GOOD, MISSING_INFO, NEEDS_REVIEW, SUGGEST_SPLIT, verdict_for, worst_severity)
from tests.helpers import SNAPSHOT_PATH, make_story, rules_with


def flag(code, severity="medium"):
    return Flag(code, severity, "description", "x")


class VerdictTests(unittest.TestCase):
    def test_no_findings_looks_good(self):
        self.assertEqual(verdict_for([]), LOOKS_GOOD)

    def test_any_finding_needs_review(self):
        self.assertEqual(verdict_for([flag("ac_vague")]), NEEDS_REVIEW)

    def test_empty_field_is_missing_info(self):
        self.assertEqual(verdict_for([flag("ac_vague"), flag("description_missing", "high")]), MISSING_INFO)
        self.assertEqual(verdict_for([flag("points_missing")]), MISSING_INFO)

    def test_split_beats_missing_info(self):
        self.assertEqual(verdict_for([flag("description_missing", "high"), flag("possibly_undersized")]), SUGGEST_SPLIT)
        self.assertEqual(verdict_for([flag("large_and_thin", "high")]), SUGGEST_SPLIT)

    def test_worst_severity(self):
        self.assertEqual(worst_severity([]), "")
        self.assertEqual(worst_severity([flag("a", "low"), flag("b", "high"), flag("c", "medium")]), "high")


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.rules = rules_with()

    def test_in_scope(self):
        self.assertEqual(out_of_scope_reason(make_story(), self.rules), "")

    def test_done_is_ignored_whatever_the_capitals(self):
        self.assertIn("ignored", out_of_scope_reason(make_story(status="DONE"), self.rules))

    def test_bug_is_not_in_scope(self):
        self.assertIn("not in scope", out_of_scope_reason(make_story(issue_type="Bug"), self.rules))

    def test_group_can_be_left_out(self):
        rules = rules_with(lambda d: d["scope"].update(include=["current_sprint", "future_sprints"]))
        self.assertIn("not included", out_of_scope_reason(make_story(group="backlog"), rules))

    def test_skipped_stories_are_counted_not_checked(self):
        stories = [make_story(key="A"), make_story(key="B", status="Done"), make_story(key="C", status="Closed")]
        summary = check_all(stories, self.rules)
        self.assertEqual([r.story.key for r in summary.results], ["A"])
        self.assertEqual(sum(summary.skipped.values()), 2)


class FixtureTests(unittest.TestCase):
    """Every fake story in fixtures/snapshot.json says what verdict it should get."""

    def test_every_fixture_story_gets_its_expected_verdict(self):
        raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["stories"]
        expected = {item["key"]: item["_expect"] for item in raw}
        summary = check_all(load_snapshot(SNAPSHOT_PATH), rules_with())
        got = {r.story.key: r.verdict for r in summary.results}
        checked = {k: v for k, v in expected.items() if v != "skipped"}
        self.assertEqual(got, checked)
        self.assertEqual(sum(summary.skipped.values()), sum(1 for v in expected.values() if v == "skipped"))

    def test_fixture_covers_all_four_verdicts(self):
        counts = check_all(load_snapshot(SNAPSHOT_PATH), rules_with()).counts_by_verdict()
        self.assertTrue(all(count > 0 for count in counts.values()), counts)


class SnapshotLoadingTests(unittest.TestCase):
    def test_missing_key(self):
        with self.assertRaises(ValueError):
            Story.from_dict({"summary": "no key"})

    def test_bad_group(self):
        with self.assertRaises(ValueError) as caught:
            Story.from_dict({"key": "X-1", "group": "someday"})
        self.assertIn("X-1", str(caught.exception))

    def test_points_can_be_text_or_blank(self):
        self.assertEqual(Story.from_dict({"key": "X-1", "story_points": "3"}).story_points, 3.0)
        self.assertIsNone(Story.from_dict({"key": "X-1", "story_points": ""}).story_points)
        with self.assertRaises(ValueError):
            Story.from_dict({"key": "X-1", "story_points": "lots"})

    def test_null_text_fields_become_empty(self):
        story = Story.from_dict({"key": "X-1", "description": None, "labels": "one"})
        self.assertEqual((story.description, story.labels), ("", ["one"]))


if __name__ == "__main__":
    unittest.main()
