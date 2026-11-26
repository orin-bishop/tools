import json
import unittest

from refiner.context import ContextIndex, Section, parse_hints
from refiner.model import load_snapshot
from refiner.runner import check_all
from refiner.suggest import LABEL, PLACEHOLDER, suggest_all, to_dict
from refiner.text import tokens, words
from tests.helpers import ROOT, SNAPSHOT_PATH, make_story, rules_with

HINTS = parse_hints("""
hints_version: 1
hints:
  - name: Add an alert
    words: [alert]
    so_that: "the right people hear about a problem quickly"
    acceptance_criteria:
      - "An alert is sent when the problem happens"
      - "The alert says what failed and who should look"
      - "The alert goes to the agreed channel"
    questions:
      - "Who should get the alert?"
""")


def section(file, heading, text):
    return Section(file, heading, frozenset(words(heading + " " + text)), frozenset(words(heading)))


def run(stories, rules=None, context=None):
    rules = rules or rules_with()
    return suggest_all(check_all(stories, rules).results, rules, context)


def one(rules=None, context=None, **changes):
    """The suggestion for a single story built from the usual good story plus `changes`."""
    story = make_story(**changes)
    return run([story], rules, context)[story.key]


class DescriptionTests(unittest.TestCase):
    def test_built_from_the_summary_with_a_placeholder_reason(self):
        s = one(summary="Add alert for failed deployments", description="")
        self.assertEqual(s.description, f"As a platform engineer, I want to add alert for failed deployments, so that {PLACEHOLDER}.")
        self.assertTrue(s.needs_confirmation)
        self.assertIn("Why does this matter? The answer fills the 'so that' part of the story.", s.questions)

    def test_reason_comes_from_a_hint_when_there_is_one(self):
        s = one(context=ContextIndex(hints=HINTS), summary="Add alert for failed deployments", description="")
        self.assertIn("so that the right people hear about a problem quickly.", s.description)
        self.assertFalse(s.needs_confirmation)
        self.assertFalse(any("Why does this matter" in q for q in s.questions))
        self.assertIn("Who should get the alert?", s.questions)

    def test_existing_want_is_kept_and_only_the_reason_is_added(self):
        s = one(summary="Set up new build tool", description="As a platform engineer, I want a new build tool.")
        self.assertEqual(s.description, f"As a platform engineer, I want a new build tool, so that {PLACEHOLDER}.")

    def test_existing_reason_is_kept_and_a_wrong_role_is_replaced(self):
        rules = rules_with(lambda d: d["fields"]["description"]["story_format"].update(allowed_roles=["platform engineer"]))
        s = one(rules, summary="Add health check to demo service",
                description="As a gardener, I want a health check endpoint, so that the pipeline knows it is up.")
        self.assertEqual(s.description, "As a platform engineer, I want a health check endpoint, so that the pipeline knows it is up.")
        self.assertFalse(s.needs_confirmation)

    def test_summary_that_is_not_an_action_gets_no_to(self):
        s = one(summary="Health check dashboard", description="")
        self.assertIn("I want health check dashboard, so that", s.description)

    def test_acronyms_keep_their_capitals(self):
        self.assertIn("I want to upgrade RDS Postgres, so that", one(summary="Upgrade RDS Postgres", description="").description)
        self.assertIn("I want API key rotation, so that", one(summary="API key rotation", description="").description)

    def test_brief_free_text_is_kept_as_notes(self):
        s = one(summary="Fix log forwarding", description="Fix the thing")
        self.assertTrue(s.description.endswith("Existing notes: Fix the thing"))

    def test_long_free_text_is_not_copied_into_the_line(self):
        long_text = "The login page shows the wrong message after tries. " * 6
        s = one(summary="Fix login message", description=long_text)
        self.assertTrue(s.description.endswith("Keep the existing text below this line."))
        self.assertNotIn("wrong message", s.description)

    def test_a_vowel_role_gets_an(self):
        rules = rules_with(lambda d: d["suggestions"].update(default_role="operator"))
        self.assertTrue(one(rules, description="").description.startswith("As an operator, I want"))

    def test_nothing_to_build_from_asks_a_question_instead(self):
        s = one(summary="", description="")
        self.assertEqual(s.description, "")
        self.assertTrue(any(q.startswith("What is this story about?") for q in s.questions))

    def test_wiki_markup_in_the_description_is_handled(self):
        s = one(summary="Set up new build tool", description="h3. Why\n*As a* platform engineer, I want a new build tool.")
        self.assertIn("I want a new build tool, so that", s.description)

    def test_no_description_suggestion_when_the_description_is_fine(self):
        self.assertEqual(one(story_points=None).description, "")

    def test_suggestion_words_come_only_from_the_story_and_the_template(self):
        s = one(summary="Fix log forwarding", description="Fix the thing")
        allowed = set(tokens("as a i want to so that existing notes platform engineer reason to confirm in refinement"))
        allowed |= set(tokens("Fix log forwarding Fix the thing"))
        self.assertLessEqual(set(tokens(s.description)), allowed)


class CriteriaTests(unittest.TestCase):
    def story(self, **changes):
        base = dict(summary="Add alert for failed deployments", acceptance_criteria="")
        base.update(changes)
        return base

    def test_criteria_come_from_a_hint(self):
        s = one(context=ContextIndex(hints=HINTS), **self.story())
        self.assertEqual(len(s.acceptance_criteria), 3)
        self.assertIn("hint 'Add an alert'", " ".join(s.basis))

    def test_never_more_than_the_limit(self):
        rules = rules_with(lambda d: d["suggestions"].update(max_acceptance_criteria=1))
        self.assertEqual(one(rules, ContextIndex(hints=HINTS), **self.story()).acceptance_criteria, ["An alert is sent when the problem happens"])

    def test_without_a_hint_nothing_is_invented_and_a_question_is_asked(self):
        s = one(**self.story())
        self.assertEqual(s.acceptance_criteria, [])
        self.assertIn("What would show that this is done? Write 2 or 3 checks anyone on the team could run.", s.questions)

    def test_vague_and_short_criteria_get_the_same_help(self):
        for text in ("TBD", "Works as expected and should work fine."):
            s = one(context=ContextIndex(hints=HINTS), **self.story(acceptance_criteria=text))
            self.assertEqual(len(s.acceptance_criteria), 3, text)

    def test_good_criteria_are_left_alone(self):
        s = one(context=ContextIndex(hints=HINTS), **self.story(acceptance_criteria="* An alert is sent when a deploy fails\n* It names the service", story_points=None))
        self.assertEqual(s.acceptance_criteria, [])


class QuestionTests(unittest.TestCase):
    def test_unpointed_story(self):
        self.assertIn("How many days of work is this? Most stories here are 2 points (1 point = 1 day).", one(story_points=None).questions)

    def test_days_follow_the_rules(self):
        rules = rules_with(lambda d: d["sizing"].update(points_equal_days=2))
        self.assertIn("(1 point = 2 days)", " ".join(one(rules, story_points=None).questions))

    def test_summary_questions(self):
        self.assertIn("What should the summary say? One short line that names the work.", one(summary="", description="").questions)
        self.assertIn("Can the summary say a little more about the work?", one(summary="Fix it", description="").questions)
        self.assertIn("The summary and the description may describe different work. Which one is right?",
                      one(summary="Rotate service account credentials").questions)

    def test_other_required_field_is_named(self):
        rules = rules_with(lambda d: d["fields"].update(other_required=["epic"]))
        self.assertIn("Which epic does this story belong to?", one(rules, epic="").questions)

    def test_questions_are_capped_and_not_repeated(self):
        rules = rules_with(lambda d: d["suggestions"].update(max_questions=2))
        s = one(rules, summary="", description="", acceptance_criteria="", story_points=None)
        self.assertEqual(len(s.questions), 2)
        self.assertEqual(len(set(s.questions)), len(s.questions))


class RepeatedQuestionTests(unittest.TestCase):
    def test_a_question_is_asked_once_even_if_a_hint_repeats_it(self):
        built_in = "What would show that this is done? Write 2 or 3 checks anyone on the team could run."
        hints = parse_hints(f"""
hints_version: 1
hints:
  - name: Add an alert
    words: [alert]
    questions:
      - "Who should get the alert?"
      - "Who should get the alert?"
      - "{built_in}"
""")
        s = one(context=ContextIndex(hints=hints), summary="Add alert for failed deployments", acceptance_criteria="")
        self.assertEqual(s.questions.count("Who should get the alert?"), 1)
        self.assertEqual(s.questions.count(built_in), 1)


class SplitTests(unittest.TestCase):
    def test_titles_and_reason_come_from_the_work_pattern(self):
        s = one(summary="Encrypt production database")
        self.assertEqual(len(s.split_titles), 4)
        self.assertIn("encrypted in place", s.split_reason)
        self.assertIn("work pattern 'Encrypt an existing database'", " ".join(s.basis))
        self.assertIn("Which of these pieces does the team need first?", s.questions)

    def test_two_patterns_give_one_combined_list_without_repeats(self):
        s = one(summary="Migrate and encrypt the database")
        self.assertEqual(len(s.split_titles), len(set(s.split_titles)))
        self.assertGreater(len(s.split_titles), 4)

    def test_a_title_shared_by_two_patterns_is_listed_once(self):
        def edit(d):
            d["sizing"]["work_patterns"] = [
                {"name": "One", "words": ["alpha"], "why_bigger": "Why one.", "split_into": ["Plan", "Cut over"]},
                {"name": "Two", "words": ["beta"], "why_bigger": "Why two.", "split_into": ["Cut over", "Verify"]},
            ]
        s = one(rules_with(edit), summary="Alpha and beta work")
        self.assertEqual(s.split_titles, ["Plan", "Cut over", "Verify"])
        self.assertEqual(s.split_reason, "Why one.")

    def test_large_and_thin_without_a_pattern_gives_a_reason_and_no_titles(self):
        s = one(summary="Set up new build tool", description="As a platform engineer, I want a new tool.", story_points=8)
        self.assertEqual(s.split_titles, [])
        self.assertIn("At 8 points the story is about 8 days of work", s.split_reason)
        self.assertIn("Can this be broken into pieces of about 2 points each?", s.questions)

    def test_no_split_advice_for_a_normal_story(self):
        s = one(story_points=None)
        self.assertEqual((s.split_titles, s.split_reason), ([], ""))


class SelectionTests(unittest.TestCase):
    def test_looks_good_stories_get_nothing(self):
        good = make_story(key="G-1")
        thin = make_story(key="B-1", summary="Rotate service credentials monthly", description="")     # a different title: not a duplicate
        self.assertEqual(list(run([good, thin])), ["B-1"])

    def test_every_suggestion_is_labelled_and_says_where_it_came_from(self):
        s = one(description="")
        self.assertEqual(s.label, LABEL)
        self.assertTrue(s.basis)

    def test_to_dict_is_plain_and_complete(self):
        data = to_dict(one(summary="Encrypt production database"))
        json.dumps(data)                                      # must be JSON-safe
        self.assertEqual(set(data), {"key", "verdict", "label", "description", "needs_confirmation", "acceptance_criteria",
                                      "questions", "split_reason", "split_titles", "title", "epic_options", "new_epic",
                                      "labels", "duplicates", "related", "references", "basis"})

    def test_same_input_gives_the_same_output(self):
        stories = [make_story(key="A", description=""), make_story(key="B", acceptance_criteria="")]
        first = {k: to_dict(v) for k, v in run(stories).items()}
        second = {k: to_dict(v) for k, v in run(stories).items()}
        self.assertEqual(first, second)


class RelatedTests(unittest.TestCase):
    GOOD = dict(key="G-1", epic="E1", summary="Add dashboard for deploy frequency", story_points=3,
                description="As a platform engineer, I want a dashboard of deploy frequency by team, so that we can see how often each team ships.")

    def related(self, rules=None, **flagged):
        base = dict(key="F-1", epic="E1", summary="Deploy frequency report for leadership", description="", story_points=2)
        base.update(flagged)
        results = run([make_story(**self.GOOD), make_story(**base)], rules)
        return results["F-1"].related

    def test_a_well_written_story_in_the_same_epic_is_pointed_at(self):
        self.assertEqual(self.related(), [("G-1", "Add dashboard for deploy frequency")])

    def test_other_epics_are_ignored(self):
        self.assertEqual(self.related(epic="E2"), [])

    def test_a_story_with_no_epic_gets_none(self):
        self.assertEqual(self.related(epic=""), [])

    def test_one_shared_word_is_not_enough(self):
        self.assertEqual(self.related(summary="Dashboard for build times"), [])

    def test_generic_action_verbs_do_not_count(self):
        self.assertEqual(self.related(summary="Add create build update tool"), [])

    def test_role_words_do_not_count(self):
        self.assertEqual(self.related(summary="Platform engineer onboarding"), [])

    def test_stories_that_only_share_the_role_are_not_related(self):
        flagged = dict(summary="Fix log forwarding", acceptance_criteria="",
                       description="As a platform engineer, I want logs forwarded, so that they reach the tool.")
        self.assertEqual(self.related(**flagged), [])

    def test_can_be_turned_off(self):
        rules = rules_with(lambda d: d["suggestions"].update(max_related_stories=0))
        self.assertEqual(self.related(rules), [])

    def test_a_flagged_story_is_never_offered_as_an_example(self):
        results = run([make_story(key="A", epic="E1", summary="Deploy frequency dashboard", description=""),
                       make_story(key="B", epic="E1", summary="Build deploy frequency dashboard", description="")])
        self.assertEqual(results["A"].related, [])


class ReferenceTests(unittest.TestCase):
    CONTEXT = ContextIndex(sections=(
        section("standards.md", "Database encryption", "Databases are encrypted at rest."),
        section("standards.md", "Platform engineer notes", "Notes for every platform engineer."),
    ))

    def test_related_sections_are_pointed_at(self):
        s = one(context=self.CONTEXT, summary="Encrypt production database")
        self.assertEqual(s.references, ["standards.md > Database encryption"])

    def test_role_words_do_not_create_references(self):
        s = one(context=self.CONTEXT, summary="Add alert for failed deployments", description="")
        self.assertEqual(s.references, [])

    def test_can_be_turned_off(self):
        rules = rules_with(lambda d: d["suggestions"].update(max_context_references=0))
        self.assertEqual(one(rules, self.CONTEXT, summary="Encrypt production database").references, [])


# ---------------------------------------------------------------------------------------------------
# Titles, epics, labels and duplicates
# ---------------------------------------------------------------------------------------------------
from datetime import date

from refiner.model import Epic

TODAY = date(2026, 11, 25)
EPICS = [Epic.from_dict(dict(key="E-1", name="Terraform migration", status="In Progress")),
         Epic.from_dict(dict(key="E-2", name="Legacy cleanup", status="Done"))]


def run_full(stories, rules=None, epics=EPICS, context=None):
    """Check, analyse and suggest, the way the command line does."""
    rules = rules or rules_with()
    summary = check_all(stories, rules, epics, today=TODAY)
    return suggest_all(summary.results, rules, context, summary.analysis)


class TitleSuggestionTests(unittest.TestCase):
    DESCRIPTION = "As a platform engineer, I want to rotate the shared database credentials every 90 days, so that old ones stop working."

    def test_a_title_that_does_not_fit_gets_a_suggestion_from_the_description(self):
        s = run_full([make_story(key="T-1", summary="Misc fixes and cleanup", description=self.DESCRIPTION)])["T-1"]
        self.assertEqual(s.title, "Rotate the shared database credentials every 90 days")
        self.assertIn("title: drafted from the description", s.basis)

    def test_a_missing_title_gets_a_suggestion_and_no_question(self):
        s = run_full([make_story(key="T-1", summary="", description=self.DESCRIPTION)])["T-1"]
        self.assertTrue(s.title)
        self.assertFalse(any(q.startswith("What should the summary say") for q in s.questions))

    def test_a_long_title_gets_a_shorter_one(self):
        long_title = "Rotate the shared database credentials " + "and more " * 12
        s = run_full([make_story(key="T-1", summary=long_title, description=self.DESCRIPTION)])["T-1"]
        self.assertTrue(s.title)
        self.assertLessEqual(len(s.title), 90)

    def test_no_suggestion_when_the_title_is_fine_or_suggestions_are_off(self):
        self.assertEqual(run_full([make_story(key="T-1", description="")])["T-1"].title, "")          # flagged for something else
        rules = rules_with(lambda d: d["titles"].update(suggest=False))
        s = run_full([make_story(key="T-1", summary="Misc fixes and cleanup", description=self.DESCRIPTION)], rules)["T-1"]
        self.assertEqual(s.title, "")
        self.assertIn("The summary and the description may describe different work. Which one is right?", s.questions)


class EpicSuggestionTests(unittest.TestCase):
    def test_a_story_with_no_epic_gets_the_best_current_epic(self):
        s = run_full([make_story(key="E-9", summary="Terraform module for VPC", epic="")])["E-9"]
        self.assertEqual(s.epic_options, [("E-1", "Terraform migration", 0.5)])
        self.assertFalse(any("Which epic" in q for q in s.questions))

    def test_a_story_in_a_finished_epic_is_pointed_to_a_current_one(self):
        s = run_full([make_story(key="E-9", summary="Terraform module for VPC", epic="E-2")])["E-9"]
        self.assertEqual(s.epic_options[0][0], "E-1")

    def test_finished_epics_are_never_suggested(self):
        s = run_full([make_story(key="E-9", summary="Legacy cleanup of old scripts", epic="")])["E-9"]
        self.assertEqual(s.epic_options, [])

    def test_stories_that_fit_no_epic_but_share_a_word_get_a_new_epic_idea(self):
        stories = [make_story(key=f"C-{i}", summary=f"Rotate {x} credentials", description="", epic="")
                   for i, x in enumerate(("service", "cloud", "API"), start=1)]
        found = run_full(stories)
        self.assertEqual(found["C-1"].new_epic, 'Create an epic "Credentials" for this story and C-2, C-3')
        self.assertEqual(found["C-3"].new_epic, 'Create an epic "Credentials" for this story and C-1, C-2')
        self.assertEqual(found["C-1"].epic_options, [])

    def test_a_lone_story_that_fits_nothing_gets_a_question(self):
        s = run_full([make_story(key="E-9", summary="Update the onboarding page", epic="")])["E-9"]
        self.assertIn("Which current or future epic does this story belong to? No existing epic fits well.", s.questions)

    def test_without_the_analysis_a_plain_question_is_asked(self):
        rules = rules_with()
        summary = check_all([make_story(key="E-9", summary="Terraform module", epic="")], rules, EPICS, today=TODAY)
        s = suggest_all(summary.results, rules)["E-9"]                       # no analysis passed
        self.assertEqual(s.epic_options, [])
        self.assertIn("Which current or future epic does this story belong to?", s.questions)


class LabelAndDuplicateSuggestionTests(unittest.TestCase):
    def test_missing_required_and_suggested_labels_are_listed(self):
        rules = rules_with(lambda d: d["labels"].update(required_all=["team-save"], suggest=[{"label": "terraform", "words": ["terraform"]}]))
        s = run_full([make_story(key="L-1", summary="Terraform module for VPC", labels=[])], rules)["L-1"]
        self.assertEqual(s.labels, ["team-save", "terraform"])
        self.assertIn("labels: the rules file", s.basis)

    def test_duplicates_name_the_other_story_and_ask_the_question(self):
        stories = [make_story(key="D-1", summary="Rotate service credentials"), make_story(key="D-2", summary="Service credentials rotate")]
        found = run_full(stories)
        self.assertEqual(found["D-1"].duplicates, [("D-2", "Service credentials rotate", 1.0)])
        self.assertIn("Is this a duplicate of D-2? If so, close or merge one of them.", found["D-1"].questions)

    def test_a_description_that_is_already_in_story_form_is_not_suggested_again(self):
        text = "As a platform engineer, I want a new build tool, so that builds are faster."          # 71 characters
        rules = rules_with(lambda d: d["fields"]["description"].update(brief_chars=100))                 # flagged brief
        s = run_full([make_story(key="B-1", summary="Set up new build tool", description=text)], rules)["B-1"]
        self.assertEqual(s.description, "")


class FixtureTests(unittest.TestCase):
    def setUp(self):
        from refiner.context import load_context
        self.rules = rules_with()
        self.results = check_all(load_snapshot(SNAPSHOT_PATH), self.rules).results
        self.found = suggest_all(self.results, self.rules, load_context(ROOT / "context"))

    def test_only_stories_that_are_not_good_get_suggestions(self):
        expected = {r.story.key for r in self.results if r.verdict != "Looks good"}
        self.assertEqual(set(self.found), expected)

    def test_limits_hold_everywhere(self):
        for s in self.found.values():
            self.assertLessEqual(len(s.acceptance_criteria), self.rules.suggest_max_ac)
            self.assertLessEqual(len(s.questions), self.rules.suggest_max_questions)
            self.assertLessEqual(len(s.related), self.rules.suggest_max_related)
            self.assertEqual(s.label, LABEL)

    def test_known_stories(self):
        self.assertIn("so that the right people hear about a problem quickly", self.found["DEMO-2"].description)   # hint reason
        self.assertEqual(len(self.found["DEMO-3"].acceptance_criteria), 2)                                       # dashboard hint
        self.assertEqual(len(self.found["DEMO-4"].acceptance_criteria), 3)                                       # rotate keys hint
        self.assertEqual(len(self.found["DEMO-9"].split_titles), 4)
        self.assertEqual(self.found["DEMO-9"].references, ["platform-standards.md > Database encryption"])
        self.assertTrue(self.found["DEMO-6"].needs_confirmation)


if __name__ == "__main__":
    unittest.main()
