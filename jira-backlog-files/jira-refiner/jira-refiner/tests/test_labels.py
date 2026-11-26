import unittest

from refiner.labels import label_findings, labels_to_add, missing_required, suggested_by_words, unknown_labels
from tests.helpers import make_story, rules_with


def with_labels(**settings):
    return rules_with(lambda d: d["labels"].update(**settings))


TERRAFORM = [{"label": "terraform", "words": ["terraform"]}]


class RequiredTests(unittest.TestCase):
    def test_nothing_is_required_by_default(self):
        self.assertEqual(label_findings(make_story(labels=[]), rules_with()), [])

    def test_missing_required_label_is_reported(self):
        rules = with_labels(required_all=["team-save", "platform"])
        self.assertEqual(missing_required(make_story(labels=["platform"]), rules), ["team-save"])
        found = label_findings(make_story(labels=["platform"]), rules)
        self.assertEqual([code for code, _ in found], ["labels_missing"])
        self.assertIn("team-save", found[0][1])

    def test_capital_letters_do_not_matter(self):
        rules = with_labels(required_all=["Team-Save"])
        self.assertEqual(missing_required(make_story(labels=["team-save"]), rules), [])

    def test_story_with_every_required_label_is_fine(self):
        rules = with_labels(required_all=["team-save"])
        self.assertEqual(label_findings(make_story(labels=["team-save", "other"]), rules), [])


class AllowedTests(unittest.TestCase):
    def test_no_allowed_list_means_any_label_is_fine(self):
        self.assertEqual(unknown_labels(make_story(labels=["anything"]), rules_with()), [])

    def test_labels_outside_the_allowed_list_are_flagged(self):
        rules = with_labels(allowed=["team-save", "terraform"])
        story = make_story(labels=["team-save", "Typo-label"])
        self.assertEqual(unknown_labels(story, rules), ["Typo-label"])
        self.assertEqual([c for c, _ in label_findings(story, rules)], ["label_unknown"])

    def test_allowed_matching_ignores_capitals(self):
        rules = with_labels(allowed=["Terraform"])
        self.assertEqual(unknown_labels(make_story(labels=["terraform"]), rules), [])


class SuggestionTests(unittest.TestCase):
    def test_label_is_suggested_when_the_words_appear(self):
        rules = with_labels(suggest=TERRAFORM)
        story = make_story(labels=[], summary="Terraform module for VPC")
        self.assertEqual(suggested_by_words(story, rules), ["terraform"])
        self.assertEqual([c for c, _ in label_findings(story, rules)], ["labels_suggested"])

    def test_not_suggested_if_the_story_already_has_it(self):
        rules = with_labels(suggest=TERRAFORM)
        story = make_story(labels=["Terraform"], summary="Terraform module for VPC")
        self.assertEqual(suggested_by_words(story, rules), [])

    def test_words_are_found_in_the_description_too_and_with_other_endings(self):
        rules = with_labels(suggest=[{"label": "migration", "words": ["migrate"]}])
        story = make_story(labels=[], description="As a dev, I want logs migrated, so that they are safe.")
        self.assertEqual(suggested_by_words(story, rules), ["migration"])

    def test_each_suggested_label_once(self):
        rules = with_labels(suggest=[{"label": "terraform", "words": ["terraform"]}, {"label": "terraform", "words": ["tf"]}])
        story = make_story(labels=[], summary="Terraform and tf work")
        self.assertEqual(suggested_by_words(story, rules), ["terraform"])

    def test_labels_to_add_lists_required_first_then_suggested_without_repeats(self):
        rules = with_labels(required_all=["team-save"], suggest=TERRAFORM + [{"label": "team-save", "words": ["terraform"]}])
        story = make_story(labels=[], summary="Terraform module")
        self.assertEqual(labels_to_add(story, rules), ["team-save", "terraform"])

    def test_a_missing_required_label_is_not_also_reported_as_suggested(self):
        rules = with_labels(required_all=["terraform"], suggest=TERRAFORM)
        found = label_findings(make_story(labels=[], summary="Terraform module"), rules)
        self.assertEqual([c for c, _ in found], ["labels_missing"])

    def test_turning_labels_off(self):
        rules = with_labels(enabled=False, required_all=["team-save"], suggest=TERRAFORM)
        story = make_story(labels=[], summary="Terraform module")
        self.assertEqual(label_findings(story, rules), [])
        self.assertEqual(labels_to_add(story, rules), [])


class RulesFileTests(unittest.TestCase):
    def test_label_suggestions_are_validated(self):
        from refiner.rules import RulesError
        with self.assertRaises(RulesError) as caught:
            with_labels(suggest=[{"label": "terraform", "words": []}])
        self.assertIn("labels.suggest[1].words", caught.exception.problems[0])

    def test_label_rules_load(self):
        rules = with_labels(suggest=TERRAFORM)
        self.assertEqual(rules.label_rules[0].label, "terraform")
        self.assertEqual(rules.label_rules[0].words, ("terraform",))


if __name__ == "__main__":
    unittest.main()
