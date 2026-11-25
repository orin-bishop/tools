import tempfile
import unittest
from pathlib import Path

from refiner.rules import CHECK_IDS, RulesError, load_rules, parse_rules
from tests.helpers import RULES_PATH

TEXT = RULES_PATH.read_text(encoding="utf-8")


def line_of(snippet):
    for number, line in enumerate(TEXT.splitlines(), start=1):
        if snippet in line:
            return number
    raise AssertionError(f"{snippet!r} is not in rules.yaml")


def problems_for(text):
    try:
        parse_rules(text, source="rules.yaml")
    except RulesError as err:
        return err.problems
    return []


class GoodFileTests(unittest.TestCase):
    def test_real_rules_file_loads(self):
        rules = load_rules(RULES_PATH)
        self.assertEqual(rules.version, 1)
        self.assertEqual(rules.include_groups, ("current_sprint", "future_sprints", "backlog"))
        self.assertEqual(rules.issue_types, ("Story", "Spike"))
        self.assertEqual(rules.description_min_chars, 21)
        self.assertEqual(rules.review_at_or_above, 5.0)
        self.assertEqual(rules.allowed_roles, ())
        self.assertEqual(rules.type_skips, {})
        self.assertEqual(set(rules.severity), set(CHECK_IDS))
        self.assertEqual(rules.highlight["high"], "FFD966")

    def test_raw_copy_is_kept_for_the_workbook(self):
        self.assertEqual(load_rules(RULES_PATH).raw["rules_version"], 1)


class ProblemTests(unittest.TestCase):
    def test_bad_number_names_the_line_and_the_setting(self):
        text = TEXT.replace("review_at_or_above: 5 ", "review_at_or_above: lots ")
        found = problems_for(text)
        self.assertEqual(len(found), 1)
        self.assertIn(f"line {line_of('review_at_or_above')}", found[0])
        self.assertIn("fields.story_points.review_at_or_above", found[0])

    def test_unknown_setting_gets_a_suggestion(self):
        text = TEXT.replace("review_at_or_above:", "review_at_or_abov:")
        found = problems_for(text)
        self.assertTrue(any("Did you mean 'review_at_or_above'" in p for p in found), found)
        self.assertTrue(any("is missing" in p for p in found), found)

    def test_every_problem_is_reported_not_just_the_first(self):
        text = TEXT.replace("min_chars: 21                # 20 characters or fewer gets flagged\n    story_format", "min_chars: many\n    story_format", 1)
        text = text.replace("high: \"FFD966\"", "high: 123456")
        text = text.replace("ac_vague: medium", "ac_vague: urgent")
        found = problems_for(text)
        self.assertGreaterEqual(len(found), 3, found)

    def test_bad_severity_word(self):
        found = problems_for(TEXT.replace("ac_vague: medium", "ac_vague: urgent"))
        self.assertEqual(len(found), 1)
        self.assertIn("severity.ac_vague", found[0])
        self.assertIn("high, medium, low", found[0])

    def test_unquoted_color_number_is_rejected(self):
        found = problems_for(TEXT.replace('high: "FFD966"', "high: 123456"))
        self.assertTrue(any("highlight.high" in p and "6-digit" in p for p in found), found)

    def test_bad_pattern(self):
        found = problems_for(TEXT.replace('pattern: "as an? .+?,? i (want|need) .+?,? so that .+"', 'pattern: "as an? (unclosed"'))
        self.assertTrue(any("not a valid pattern" in p for p in found), found)

    def test_wrong_group_name(self):
        found = problems_for(TEXT.replace("include: [current_sprint, future_sprints, backlog]", "include: [current_sprint, someday]"))
        self.assertTrue(any("someday" in p and "not allowed" in p for p in found), found)

    def test_true_false_check(self):
        found = problems_for(TEXT.replace("required: true\n    min_chars: 10", "required: maybe\n    min_chars: 10", 1))
        self.assertTrue(any("true or false" in p for p in found), found)

    def test_bad_yaml_gives_one_message_with_a_line(self):
        found = problems_for(TEXT.replace("include: [current_sprint, future_sprints, backlog]", "include: [current_sprint, future_sprints"))
        self.assertEqual(len(found), 1)
        self.assertIn("not valid YAML", found[0])
        self.assertIn("line", found[0])

    def test_file_that_is_not_a_list_of_settings(self):
        self.assertIn("list of settings", problems_for("just some words")[0])

    def test_unknown_check_in_type_skips(self):
        found = problems_for(TEXT.replace("type_skips: {}", "type_skips:\n  Spike: [description_formt]"))
        self.assertTrue(any("Did you mean 'description_format'" in p for p in found), found)

    def test_type_skips_can_be_used(self):
        rules = parse_rules(TEXT.replace("type_skips: {}", "type_skips:\n  Spike: [description_format]"))
        self.assertEqual(rules.type_skips, {"spike": frozenset({"description_format"})})

    def test_missing_section(self):
        start = TEXT.index("summary_match:")
        end = TEXT.index("# ----", TEXT.index("sizing:"))   # drop summary_match and sizing
        text = TEXT[:start] + TEXT[end:]
        found = problems_for(text)
        self.assertTrue(any("'summary_match' is missing" in p for p in found), found)

    def test_work_patterns_load_with_their_details(self):
        rules = load_rules(RULES_PATH)
        first = rules.work_patterns[0]
        self.assertEqual(first.name, "Encrypt an existing database")
        self.assertIn("encrypt database", first.words)
        self.assertEqual(len(first.split_into), 4)

    def test_work_pattern_without_words_names_the_pattern_and_line(self):
        text = TEXT.replace('      words: ["encrypt database", "encrypt db", "encrypt rds", "database encryption", "rds encryption"]\n', "      words: []\n")
        found = problems_for(text)
        self.assertEqual(len(found), 1, found)
        self.assertIn("sizing.work_patterns[1].words", found[0])
        self.assertIn("at least one entry", found[0])

    def test_work_pattern_with_misspelt_setting(self):
        found = problems_for(TEXT.replace("why_bigger: \"An existing", "why_bigr: \"An existing", 1))
        self.assertTrue(any("Did you mean 'why_bigger'" in p for p in found), found)

    def test_work_patterns_must_be_a_list(self):
        start = TEXT.index("  work_patterns:")
        end = TEXT.index("# ----", start)
        text = TEXT[:start] + "  work_patterns: encrypt things\n\n" + TEXT[end:]
        found = problems_for(text)
        self.assertTrue(any("must be a list of patterns" in p for p in found), found)

    def test_empty_work_patterns_list_is_allowed(self):
        start = TEXT.index("  work_patterns:")
        end = TEXT.index("# ----", start)
        rules = parse_rules(TEXT[:start] + "  work_patterns: []\n\n" + TEXT[end:])
        self.assertEqual(rules.work_patterns, ())

    def test_the_old_keyword_setting_gets_a_helpful_message(self):
        found = problems_for(TEXT.replace("  work_patterns:", "  big_topic_keywords: [migrate]\n  work_patterns_old:", 1))
        self.assertTrue(any("big_topic_keywords" in p and "not a setting" in p for p in found), found)

    def test_suggestion_settings_load(self):
        rules = load_rules(RULES_PATH)
        self.assertEqual(rules.suggest_default_role, "platform engineer")
        self.assertEqual((rules.suggest_max_ac, rules.suggest_max_questions, rules.suggest_max_related), (5, 6, 2))
        self.assertIn("encrypt", rules.suggest_action_verbs)
        self.assertNotIn("encrypt", rules.suggest_ignore_words)       # a topic word, not an everyday one
        self.assertIn("create", rules.suggest_ignore_words)

    def test_default_role_must_be_an_allowed_role(self):
        text = TEXT.replace("allowed_roles: []", "allowed_roles: [project lead]")
        found = problems_for(text)
        self.assertEqual(len(found), 1, found)
        self.assertIn("suggestions.default_role", found[0])
        self.assertIn("project lead", found[0])

    def test_default_role_passes_when_it_is_allowed(self):
        rules = parse_rules(TEXT.replace("allowed_roles: []", "allowed_roles: [Platform Engineer]"))
        self.assertEqual(rules.allowed_roles, ("platform engineer",))

    def test_suggestion_numbers_are_checked(self):
        found = problems_for(TEXT.replace("max_acceptance_criteria: 5", "max_acceptance_criteria: 0"))
        self.assertTrue(any("suggestions.max_acceptance_criteria" in p for p in found), found)

    def test_suggestions_section_is_required(self):
        start = TEXT.index("suggestions:")
        end = TEXT.index("# ----", start)
        found = problems_for(TEXT[:start] + TEXT[end:])
        self.assertTrue(any("'suggestions' is missing" in p for p in found), found)

    def test_missing_file(self):
        with self.assertRaises(RulesError) as caught:
            load_rules(Path(tempfile.gettempdir()) / "no-such-rules-file.yaml")
        self.assertIn("Cannot read", caught.exception.problems[0])


if __name__ == "__main__":
    unittest.main()
