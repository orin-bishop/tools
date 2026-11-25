import unittest

from refiner.text import contains_phrase, plain_text, stem, tokens, words


class PlainTextTests(unittest.TestCase):
    def test_none_and_blank(self):
        self.assertEqual(plain_text(None), "")
        self.assertEqual(plain_text("  \n\t "), "")

    def test_strips_wiki_markup(self):
        raw = "h3. Background\n*As a* dev, I want _this_.\n* item one\n# item two\n{{mono}} [site|http://x.example]"
        self.assertEqual(plain_text(raw), "Background As a dev, I want this. item one item two mono site")

    def test_drops_code_blocks_and_panels(self):
        raw = "Before {code:java}int x = 1;{code} after {panel:title=Note}text{panel}"
        self.assertEqual(plain_text(raw), "Before after text")

    def test_markup_only_text_becomes_empty(self):
        self.assertEqual(plain_text("{panel}{panel}"), "")

    def test_hyphens_inside_words_survive(self):
        self.assertEqual(plain_text("self-service portal"), "self-service portal")


class KeepLinesTests(unittest.TestCase):
    def test_default_joins_everything_into_one_line(self):
        self.assertEqual(plain_text("* one\n* two\n\n* three"), "one two three")

    def test_keep_lines_keeps_one_line_per_item(self):
        self.assertEqual(plain_text("* one\n* two\n\n\n# three", keep_lines=True), "one\ntwo\nthree")

    def test_keep_lines_still_removes_markup_and_extra_spaces(self):
        raw = "h3. Why\n*As a*   dev, I want   _this_.\n{code}x = 1{code}\n  "
        self.assertEqual(plain_text(raw, keep_lines=True), "Why\nAs a dev, I want this.")

    def test_keep_lines_on_empty_text(self):
        self.assertEqual(plain_text(None, keep_lines=True), "")
        self.assertEqual(plain_text("\n \n", keep_lines=True), "")


class StemTests(unittest.TestCase):
    def test_related_words_match(self):
        for word in ("migrate", "migrates", "migrated", "migrating", "migration"):
            self.assertEqual(stem(word), "migrat", word)
        for word in ("encrypt", "encrypted", "encrypting", "encryption"):
            self.assertEqual(stem(word), "encrypt", word)
        self.assertEqual(stem("database"), stem("databases"))

    def test_short_words_are_left_alone(self):
        self.assertEqual(stem("use"), "use")
        self.assertEqual(stem("is"), "is")


class WordTests(unittest.TestCase):
    def test_words_drop_stop_words(self):
        self.assertEqual(words("As a platform engineer, I want the dashboard"), ["platform", "engineer", "dashboard"])

    def test_phrase_in_order_with_gap(self):
        t = tokens("We need to encrypt the production database soon")
        self.assertTrue(contains_phrase("encrypt database", t))

    def test_phrase_wrong_order_or_too_far(self):
        self.assertFalse(contains_phrase("encrypt database", tokens("The database is fine. Encrypt nothing")))
        far = tokens("encrypt one two three four database")
        self.assertFalse(contains_phrase("encrypt database", far))

    def test_single_word_phrase(self):
        self.assertTrue(contains_phrase("migrate", tokens("The migration plan")))

    def test_empty_phrase_never_matches(self):
        self.assertFalse(contains_phrase("", tokens("anything")))


if __name__ == "__main__":
    unittest.main()
