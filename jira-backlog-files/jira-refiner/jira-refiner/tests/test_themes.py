import unittest

from refiner.themes import find_themes, prefix_title
from tests.helpers import make_story, rules_with

RULES = rules_with()


def stories(*summaries):
    return [make_story(key=f"S-{i}", summary=text) for i, text in enumerate(summaries, start=1)]


class FindThemesTests(unittest.TestCase):
    TERRAFORM = ("Terraform module for VPC", "Terraform module for security groups", "Add Terraform state backend", "Terraform pipeline for plan")

    def test_a_frequent_word_is_found_and_counts_the_titles_that_start_with_it(self):
        no_known = rules_with(lambda d: d["themes"].update(known=[]))
        theme = next(t for t in find_themes(stories(*self.TERRAFORM), no_known) if t.word == "Terraform")
        self.assertEqual(theme.keys, ("S-1", "S-2", "S-3", "S-4"))
        self.assertEqual(theme.starting, ("S-1", "S-2", "S-4"))
        self.assertFalse(theme.known)
        self.assertFalse(theme.consistent)

    def test_terraform_is_a_known_starter_theme(self):
        theme = find_themes(stories(*self.TERRAFORM), RULES)[0]
        self.assertEqual((theme.word, theme.known), ("Terraform", True))

    def test_a_theme_where_every_title_starts_with_it_is_consistent(self):
        theme = find_themes(stories("Terraform module a", "Terraform pipeline b", "Terraform backend c"), RULES)[0]
        self.assertTrue(theme.consistent)

    def test_fewer_titles_than_the_minimum_is_not_a_theme(self):
        self.assertEqual(find_themes(stories("Terraform module for VPC", "Terraform module for roles"), RULES), [])

    def test_the_minimum_comes_from_the_rules_file(self):
        rules = rules_with(lambda d: d["themes"].update(min_stories=2))
        self.assertTrue(any(t.word == "Terraform" for t in find_themes(stories("Terraform module for VPC", "Terraform module for roles"), rules)))

    def test_known_themes_come_first_and_are_marked(self):
        rules = rules_with(lambda d: d["themes"].update(known=["terraform"]))
        found = find_themes(stories(*self.TERRAFORM), rules)
        self.assertEqual((found[0].word, found[0].known), ("Terraform", True))
        self.assertEqual([t.word for t in found].count("Terraform"), 1)           # not repeated as an automatic one

    def test_a_known_theme_with_too_few_titles_is_left_out(self):
        rules = rules_with(lambda d: d["themes"].update(known=["vault"]))
        self.assertEqual(find_themes(stories("Vault policy review", "Other thing here"), rules), [])

    def test_word_endings_match_and_the_most_frequent_come_first_up_to_the_limit(self):
        rules = rules_with(lambda d: d["themes"].update(max_auto_themes=1))
        found = find_themes(stories("Rotate keys", "Rotating keys again", "Rotated key store", "Backup vault", "Backup policy", "Backup test"), rules)
        self.assertEqual(len(found), 1)
        self.assertIn(found[0].word, ("Key", "Keys", "Rotate", "Rotating", "Rotated", "Backup"))
        self.assertEqual(len(found[0].keys), 3)

    def test_everyday_words_and_verbs_are_not_themes(self):
        found = find_themes(stories("Add dashboard one", "Add dashboard two", "Add dashboard three"), RULES)
        self.assertEqual([t.word for t in found], ["Dashboard"])               # "add" is an everyday word

    def test_can_be_turned_off(self):
        rules = rules_with(lambda d: d["themes"].update(enabled=False))
        self.assertEqual(find_themes(stories(*self.TERRAFORM), rules), [])


class PrefixTests(unittest.TestCase):
    def theme(self):
        return next(t for t in find_themes(stories(*FindThemesTests.TERRAFORM), RULES) if t.word == "Terraform")

    def test_the_word_is_moved_to_the_front_and_not_said_twice(self):
        self.assertEqual(prefix_title(self.theme(), "Add Terraform state backend", RULES), "Terraform: Add state backend")

    def test_the_format_comes_from_the_rules_file(self):
        rules = rules_with(lambda d: d["themes"].update(title_format="[{theme}] {title}"))
        self.assertEqual(prefix_title(self.theme(), "Add Terraform state backend", rules), "[Terraform] Add state backend")

    def test_a_different_ending_of_the_word_is_also_moved(self):
        self.assertEqual(prefix_title(self.theme(), "Fix terraforming of state", RULES), "Terraform: Fix of state")

    def test_a_title_that_is_only_the_theme_is_left_alone(self):
        self.assertEqual(prefix_title(self.theme(), "Terraform", RULES), "Terraform")

    def test_a_title_without_the_theme_is_left_alone(self):
        self.assertEqual(prefix_title(self.theme(), "Update the onboarding page", RULES), "Update the onboarding page")

    def test_the_rules_file_must_keep_both_placeholders(self):
        from refiner.rules import RulesError
        with self.assertRaises(RulesError):
            rules_with(lambda d: d["themes"].update(title_format="{theme}"))


if __name__ == "__main__":
    unittest.main()
