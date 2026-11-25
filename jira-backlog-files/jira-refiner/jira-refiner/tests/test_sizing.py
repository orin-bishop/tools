import unittest

from refiner.checks import run_checks
from refiner.sizing import find_work_patterns
from tests.helpers import make_story, rules_with

THIN = "As a platform engineer, I want a new tool."      # under 80 characters
LONG = ("As a platform engineer, I want a new build tool for every team, so that builds are "
        "faster and all teams build the same way.")         # over 80 characters
GOOD_AC = "* The new tool runs the main build for every team"
DECOMMISSION = {
    "name": "Decommission a service",
    "words": ["decommission"],
    "why_bigger": "Decommissioning needs a plan.",
    "split_into": ["Plan", "Switch off"],
}


def codes(**changes):
    return [f.code for f in run_checks(make_story(**changes), rules_with())]


class LargeAndThinTests(unittest.TestCase):
    def test_five_points_with_thin_description(self):
        self.assertIn("large_and_thin", codes(description=THIN, acceptance_criteria=GOOD_AC, story_points=5, summary="Set up new build tool"))

    def test_four_points_with_thin_description_is_not_flagged(self):
        self.assertNotIn("large_and_thin", codes(description=THIN, acceptance_criteria=GOOD_AC, story_points=4, summary="Set up new build tool"))

    def test_five_points_with_enough_detail_is_fine(self):
        self.assertNotIn("large_and_thin", codes(description=LONG, acceptance_criteria=GOOD_AC, story_points=5, summary="Set up new build tool"))

    def test_five_points_with_thin_criteria(self):
        self.assertIn("large_and_thin", codes(description=LONG, acceptance_criteria="See description", story_points=5, summary="Set up new build tool"))

    def test_message_uses_points_and_days(self):
        found = run_checks(make_story(description=THIN, story_points=8, summary="Set up new build tool"), rules_with())
        message = next(f.message for f in found if f.code == "large_and_thin")
        self.assertIn("8 points (about 8 days)", message)

    def test_days_follow_points_equal_days(self):
        rules = rules_with(lambda d: d["sizing"].update(points_equal_days=2))
        found = run_checks(make_story(description=THIN, story_points=5, summary="Set up new build tool"), rules)
        self.assertIn("about 10 days", next(f.message for f in found if f.code == "large_and_thin"))

    def test_review_threshold_comes_from_the_rules_file(self):
        rules = rules_with(lambda d: d["fields"]["story_points"].update(review_at_or_above=3))
        found = run_checks(make_story(description=THIN, story_points=3, summary="Set up new build tool"), rules)
        self.assertIn("large_and_thin", [f.code for f in found])

    def test_unpointed_story_gets_no_sizing_flags(self):
        found = codes(summary="Encrypt production database", description="As a platform engineer, I want the production database encrypted, so that data is safe.", story_points=None)
        self.assertEqual(found, ["points_missing"])


class PossiblyUndersizedTests(unittest.TestCase):
    def test_encrypt_database_at_two_points(self):
        self.assertIn("possibly_undersized", codes(summary="Encrypt production database"))

    def test_word_endings_and_gaps_still_match(self):
        found = codes(summary="Turn on encryption for the production databases")
        self.assertIn("possibly_undersized", found)

    def test_found_in_the_description_or_criteria_too(self):
        self.assertIn("possibly_undersized", codes(acceptance_criteria="* The team has migrated the logs to the new bucket"))

    def test_boundary_three_points_flagged_four_not(self):
        self.assertIn("possibly_undersized", codes(summary="Migrate the log bucket", story_points=3))
        self.assertNotIn("possibly_undersized", codes(summary="Migrate the log bucket", story_points=4))

    def test_patterns_come_from_the_rules_file(self):
        rules = rules_with(lambda d: d["sizing"].update(work_patterns=[DECOMMISSION]))
        found = run_checks(make_story(summary="Migrate the log bucket"), rules)
        self.assertNotIn("possibly_undersized", [f.code for f in found])         # migrate is no longer a pattern
        found = run_checks(make_story(summary="Decommission the demo service"), rules)
        self.assertIn("possibly_undersized", [f.code for f in found])

    def test_no_patterns_means_no_flag(self):
        rules = rules_with(lambda d: d["sizing"].update(work_patterns=[]))
        self.assertNotIn("possibly_undersized", [f.code for f in run_checks(make_story(summary="Encrypt production database"), rules)])

    def test_message_names_the_pattern_and_says_why(self):
        found = run_checks(make_story(summary="Migrate the log bucket"), rules_with())
        message = next(f.message for f in found if f.code == "possibly_undersized")
        self.assertIn("'Migrate data or a workload'", message)
        self.assertIn("cut-over", message)

    def test_message_names_up_to_two_matching_patterns(self):
        found = run_checks(make_story(summary="Migrate and encrypt the database"), rules_with())
        message = next(f.message for f in found if f.code == "possibly_undersized")
        self.assertIn("'Encrypt an existing database' and 'Migrate data or a workload'", message)

    def test_aws_style_wording_matches_the_starter_patterns(self):
        for summary, pattern in [
            ("Encrypt the RDS instance for the demo app", "Encrypt an existing database"),
            ("Turn on database encryption for the reporting database", "Encrypt an existing database"),
            ("Upgrade RDS Postgres to the next major version", "Upgrade a database or its engine"),
            ("Upgrade the OpenShift cluster", "Upgrade a cluster"),
        ]:
            found = find_work_patterns(rules_with(), summary, "", "")
            self.assertIn(pattern, [p.name for p in found], summary)

    def test_ordinary_upgrades_are_not_flagged(self):
        self.assertEqual(find_work_patterns(rules_with(), "Upgrade the python package pin", "", ""), [])

    def test_every_matching_pattern_is_returned_in_file_order(self):
        found = find_work_patterns(rules_with(), "Migrate and encrypt the database", "", "")
        self.assertEqual([p.name for p in found], ["Encrypt an existing database", "Migrate data or a workload"])

    def test_split_ideas_are_available_for_the_suggestions(self):
        pattern = find_work_patterns(rules_with(), "Encrypt production database", "", "")[0]
        self.assertEqual(len(pattern.split_into), 4)
        self.assertIn("Cut over", pattern.split_into[-1])

    def test_unrelated_story_is_fine(self):
        self.assertEqual(codes(), [])


if __name__ == "__main__":
    unittest.main()
