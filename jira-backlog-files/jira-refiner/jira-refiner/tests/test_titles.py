import unittest

from refiner.checks import run_checks
from refiner.titles import suggest_title, title_is_long
from tests.helpers import make_story, rules_with

RULES = rules_with()


class LengthTests(unittest.TestCase):
    def test_boundary_at_the_limit(self):
        self.assertFalse(title_is_long("x" * 90, RULES))
        self.assertTrue(title_is_long("x" * 91, RULES))

    def test_flag_comes_from_the_checks(self):
        found = run_checks(make_story(summary="Terraform " + "module " * 20), RULES)
        self.assertIn("title_long", [f.code for f in found])

    def test_limit_comes_from_the_rules_file(self):
        rules = rules_with(lambda d: d["titles"].update(max_chars=20))
        self.assertTrue(title_is_long("Add health check to demo service", rules))


class SuggestionTests(unittest.TestCase):
    def test_built_from_the_i_want_part_and_cleaned_up(self):
        description = "As a platform engineer, I want to rotate the shared database credentials every 90 days, so that old ones stop working."
        self.assertEqual(suggest_title("Misc fixes and cleanup", description, RULES), "Rotate the shared database credentials every 90 days")

    def test_a_leading_article_is_dropped_for_noun_phrases(self):
        description = "As a platform engineer, I want a dashboard of build times, so that I can see slow builds."
        self.assertEqual(suggest_title("Stuff", description, RULES), "Dashboard of build times")

    def test_without_an_i_want_the_first_sentence_is_used(self):
        description = "The login page shows the wrong message after three tries. It confuses people."
        self.assertEqual(suggest_title("Fix", description, RULES), "The login page shows the wrong message after three tries")

    def test_wiki_markup_is_ignored(self):
        description = "h3. Why\n*As a* dev, I want to patch the base image, so that scans pass."
        self.assertEqual(suggest_title("Misc", description, RULES), "Patch the base image")

    def test_long_candidates_are_cut_at_a_word_boundary(self):
        description = "As a dev, I want to " + "update every single module in the shared library " * 4 + ", so that all is well."
        title = suggest_title("Misc", description, rules_with(lambda d: d["titles"].update(max_chars=40)))
        self.assertLessEqual(len(title), 40)
        self.assertFalse(title.endswith(" "))
        self.assertTrue("Update every single module in the shared".startswith(title[:20]))

    def test_nothing_is_suggested_when_the_title_already_matches(self):
        description = "As a dev, I want to patch the base image, so that scans pass."
        self.assertEqual(suggest_title("patch the base image.", description, RULES), "")

    def test_nothing_is_suggested_without_a_description(self):
        self.assertEqual(suggest_title("Misc", "", RULES), "")
        self.assertEqual(suggest_title("Misc", None, RULES), "")

    def test_the_suggestion_uses_only_words_from_the_description(self):
        description = "As a platform engineer, I want to rotate the shared database credentials every 90 days, so that old ones stop working."
        title = suggest_title("Misc fixes and cleanup", description, RULES)
        self.assertLessEqual(set(title.lower().split()), set(description.lower().replace(",", "").replace(".", "").split()))


if __name__ == "__main__":
    unittest.main()
