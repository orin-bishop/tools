import unittest

from refiner.checks import run_checks
from tests.helpers import make_story, rules_with


def codes(rules=None, **changes):
    rules = rules or rules_with()
    return [f.code for f in run_checks(make_story(**changes), rules)]


class GoodStoryTests(unittest.TestCase):
    def test_a_good_story_has_no_findings(self):
        self.assertEqual(codes(), [])


class SummaryTests(unittest.TestCase):
    def test_empty_summary(self):
        self.assertIn("summary_missing", codes(summary=""))

    def test_empty_summary_is_fine_when_not_required(self):
        rules = rules_with(lambda d: d["fields"]["summary"].update(required=False))
        self.assertNotIn("summary_missing", codes(rules, summary=""))

    def test_short_summary(self):
        self.assertIn("summary_short", codes(summary="Fix it"))

    def test_summary_that_does_not_match_the_description(self):
        found = run_checks(make_story(summary="Rotate service account credentials"), rules_with())
        self.assertEqual([f.code for f in found], ["summary_mismatch"])
        self.assertEqual(found[0].field, "summary")
        self.assertIn("25%", found[0].message)      # only the word "service" is shared

    def test_short_summaries_are_not_compared(self):
        self.assertNotIn("summary_mismatch", codes(summary="Zebra stripes"))

    def test_mismatch_check_can_be_turned_off(self):
        rules = rules_with(lambda d: d["summary_match"].update(enabled=False))
        self.assertEqual(codes(rules, summary="Rotate service account credentials"), [])


class DescriptionTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(codes(description=""), ["description_missing"])

    def test_markup_only_counts_as_empty(self):
        self.assertEqual(codes(description="{panel}{panel}"), ["description_missing"])

    def test_boundary_20_characters_is_flagged_and_21_is_not(self):
        twenty = "As a dev I want x so"          # 20 characters
        self.assertEqual(len(twenty), 20)
        self.assertIn("description_short", codes(description=twenty))
        twenty_one = twenty + "."
        self.assertNotIn("description_short", codes(description=twenty_one))

    def test_story_format_missing_so_that(self):
        self.assertEqual(codes(description="As a platform engineer, I want a health check endpoint for the demo service."), ["description_format"])

    def test_story_format_ignores_capitals(self):
        self.assertEqual(codes(description="AS A platform engineer, I WANT a health check endpoint, SO THAT the pipeline knows it is up."), [])

    def test_story_format_accepts_i_need(self):
        self.assertEqual(codes(description="As an operator, I need a health check endpoint, so that the pipeline knows it is up."), [])

    def test_story_format_works_on_wiki_markup(self):
        raw = "h3. Why\n*As a* platform engineer, I want a health check endpoint, so that the pipeline knows it is up."
        self.assertEqual(codes(description=raw), [])

    def test_story_format_can_be_turned_off(self):
        rules = rules_with(lambda d: d["fields"]["description"]["story_format"].update(enabled=False))
        self.assertEqual(codes(rules, description="Add a health check endpoint to the demo service."), [])

    def test_allowed_roles_rejects_other_roles(self):
        rules = rules_with(lambda d: d["fields"]["description"]["story_format"].update(allowed_roles=["platform engineer", "project lead"]))
        found = run_checks(make_story(description="As a gardener, I want a health check endpoint, so that the pipeline knows it is up."), rules)
        self.assertEqual([f.code for f in found], ["description_format"])
        self.assertIn("'gardener'", found[0].message)

    def test_allowed_roles_accepts_listed_role_in_any_case(self):
        rules = rules_with(lambda d: d["fields"]["description"]["story_format"].update(allowed_roles=["platform engineer"]))
        self.assertEqual(codes(rules, description="As a Platform Engineer, I want a health check endpoint, so that the pipeline knows it is up."), [])


class CriteriaTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(codes(acceptance_criteria=""), ["ac_missing"])

    def test_short(self):
        self.assertEqual(codes(acceptance_criteria="TBD"), ["ac_short"])

    def test_boundary_20_characters_is_flagged_and_21_is_not(self):
        twenty, twenty_one = "The endpoint is up o", "The endpoint is up ok"
        self.assertEqual((len(twenty), len(twenty_one)), (20, 21))
        self.assertIn("ac_short", codes(acceptance_criteria=twenty))
        self.assertNotIn("ac_short", codes(acceptance_criteria=twenty_one))

    def test_vague(self):
        self.assertEqual(codes(acceptance_criteria="Works as expected and should work fine."), ["ac_vague"])

    def test_vague_phrase_inside_real_criteria_is_fine(self):
        self.assertEqual(codes(acceptance_criteria="* The endpoint returns 200 when the service is up, as expected by the pipeline"), [])

    def test_missing_ac_is_fine_when_not_required(self):
        rules = rules_with(lambda d: d["fields"]["acceptance_criteria"].update(required=False))
        self.assertEqual(codes(rules, acceptance_criteria=""), [])


class PointsAndOtherFieldTests(unittest.TestCase):
    def test_unpointed(self):
        self.assertEqual(codes(story_points=None), ["points_missing"])

    def test_zero_points_is_a_number(self):
        self.assertNotIn("points_missing", codes(story_points=0))

    def test_points_not_required(self):
        rules = rules_with(lambda d: d["fields"]["story_points"].update(required=False))
        self.assertEqual(codes(rules, story_points=None), [])

    def test_other_required_field_empty(self):
        rules = rules_with(lambda d: d["fields"].update(other_required=["epic", "labels"]))
        found = run_checks(make_story(epic="", labels=[]), rules)
        self.assertEqual([(f.code, f.field) for f in found], [("other_required_missing", "epic"), ("other_required_missing", "labels")])

    def test_other_required_field_filled(self):
        rules = rules_with(lambda d: d["fields"].update(other_required=["epic"]))
        self.assertEqual(codes(rules), [])


class RulesFileControlsTests(unittest.TestCase):
    def test_severity_comes_from_the_rules_file(self):
        rules = rules_with(lambda d: d["severity"].update(ac_missing="low"))
        found = run_checks(make_story(acceptance_criteria=""), rules)
        self.assertEqual(found[0].severity, "low")

    def test_findings_name_the_field_to_highlight(self):
        found = run_checks(make_story(description="", acceptance_criteria="", story_points=None), rules_with())
        self.assertEqual({f.code: f.field for f in found}, {
            "description_missing": "description", "ac_missing": "acceptance_criteria", "points_missing": "story_points"})

    def test_type_skips(self):
        rules = rules_with(lambda d: (d.update(type_skips={"Spike": ["description_format"]}), d["summary_match"].update(enabled=False)))
        text = "Find out whether the new scanner can read our image registry."
        self.assertEqual(codes(rules, description=text, issue_type="Spike"), [])
        self.assertEqual(codes(rules, description=text, issue_type="Story"), ["description_format"])

    def test_issue_type_match_ignores_capitals(self):
        rules = rules_with(lambda d: (d.update(type_skips={"spike": ["description_format"]}), d["summary_match"].update(enabled=False)))
        self.assertEqual(codes(rules, description="Find out whether the new scanner can read our registry.", issue_type="SPIKE"), [])


if __name__ == "__main__":
    unittest.main()
