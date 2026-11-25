import unittest

from refiner.storyform import reason_in, role_in, want_in, without_role

FULL = "As a platform engineer, I want a health check endpoint, so that the pipeline can tell it is up."


class StoryFormTests(unittest.TestCase):
    def test_all_three_parts(self):
        self.assertEqual(role_in(FULL), "platform engineer")
        self.assertEqual(want_in(FULL), "a health check endpoint")
        self.assertEqual(reason_in(FULL), "the pipeline can tell it is up")

    def test_an_and_need_and_capitals(self):
        text = "AS AN Operator, I NEED the nightly job to report failures, SO THAT someone hears about them."
        self.assertEqual(role_in(text), "Operator")
        self.assertEqual(want_in(text), "the nightly job to report failures")
        self.assertEqual(reason_in(text), "someone hears about them")

    def test_missing_so_that(self):
        text = "As a platform engineer, I want a new build tool."
        self.assertEqual(want_in(text), "a new build tool")
        self.assertEqual(reason_in(text), "")

    def test_want_stops_at_the_end_of_the_sentence(self):
        text = "As a dev, I want a faster build. Also note the cache is slow."
        self.assertEqual(want_in(text), "a faster build")

    def test_reason_stops_at_the_end_of_the_sentence(self):
        text = "As a dev, I want a faster build, so that I wait less. Notes: see the wiki."
        self.assertEqual(reason_in(text), "I wait less")

    def test_free_text_has_no_parts(self):
        for part in (role_in, want_in, reason_in):
            self.assertEqual(part("Fix the thing"), "")

    def test_without_role_removes_the_shared_boilerplate(self):
        self.assertNotIn("platform", without_role(FULL))
        self.assertIn("health check endpoint", without_role(FULL))
        self.assertEqual(without_role("Fix the thing"), "Fix the thing")


if __name__ == "__main__":
    unittest.main()
