import unittest
from datetime import date

from refiner.epics import (active_epics, inactive_findings, match_epics, needs_epic, new_epic_proposals,
                           resolve_today)
from refiner.model import Epic
from tests.helpers import make_story, rules_with

TODAY = date(2026, 11, 25)
RULES = rules_with()


def epic(key, name="Epic", status="In Progress", start=None, end=None):
    return Epic.from_dict(dict(key=key, name=name, status=status, start_date=start, end_date=end))


class TodayTests(unittest.TestCase):
    def test_an_explicit_date_wins(self):
        rules = rules_with(lambda d: d["epics"].update(today="2030-01-01"))
        self.assertEqual(resolve_today(rules, date(2026, 1, 1)), date(2026, 1, 1))

    def test_the_rules_file_can_pretend_it_is_another_day(self):
        rules = rules_with(lambda d: d["epics"].update(today="2030-01-01"))
        self.assertEqual(resolve_today(rules), date(2030, 1, 1))

    def test_default_is_the_real_date(self):
        self.assertEqual(resolve_today(RULES), date.today())


class ActiveEpicTests(unittest.TestCase):
    def test_finished_status_is_not_active_whatever_the_capitals(self):
        self.assertFalse(epic("E-1", status="DONE").is_active(TODAY, ["done"]))

    def test_ended_epics_are_not_active_but_the_end_day_itself_is(self):
        self.assertFalse(epic("E-1", end="2026-11-24").is_active(TODAY))
        self.assertTrue(epic("E-1", end="2026-11-25").is_active(TODAY))

    def test_no_end_date_and_future_starts_are_active(self):
        self.assertTrue(epic("E-1").is_active(TODAY))
        self.assertTrue(epic("E-2", start="2027-02-01", end="2027-05-01").is_active(TODAY))

    def test_active_epics_uses_the_rules_status_list(self):
        epics = [epic("A"), epic("B", status="Done"), epic("C", end="2026-01-01"), epic("D", start="2027-01-01")]
        self.assertEqual([e.key for e in active_epics(epics, RULES, TODAY)], ["A", "D"])
        rules = rules_with(lambda d: d["epics"].update(ignore_statuses=[]))
        self.assertEqual([e.key for e in active_epics(epics, rules, TODAY)], ["A", "B", "D"])

    def test_bad_dates_are_a_plain_error(self):
        with self.assertRaises(ValueError) as caught:
            Epic.from_dict(dict(key="E-9", end_date="31/12/2026"))
        self.assertIn("epic E-9 end_date", str(caught.exception))


class InactiveFindingsTests(unittest.TestCase):
    def test_story_in_a_finished_or_ended_epic_is_flagged_with_the_reason(self):
        epics = [epic("E-1", "Legacy cleanup", status="Done"), epic("E-2", "Docs", end="2026-10-31"), epic("E-3", "Live")]
        stories = [make_story(key="A", epic="E-1"), make_story(key="B", epic="E-2"), make_story(key="C", epic="E-3"),
                   make_story(key="D", epic="")]
        found = inactive_findings(stories, epics, RULES, TODAY)
        self.assertEqual(sorted(found), ["A", "B"])
        self.assertIn("has status Done", found["A"][0][1])
        self.assertIn("ended on 2026-10-31", found["B"][0][1])
        self.assertEqual(found["A"][0][0], "epic_inactive")

    def test_an_epic_the_list_does_not_know_is_left_alone(self):
        self.assertEqual(inactive_findings([make_story(key="A", epic="OTHER-TEAM-1")], [epic("E-1")], RULES, TODAY), {})


class MatchTests(unittest.TestCase):
    EPICS = [epic("E-1", "Terraform migration"), epic("E-2", "Logging and alerting"), epic("E-3", "Database encryption")]

    def story(self, summary, description=""):
        return make_story(key="S", summary=summary, description=description, epic="")

    def test_best_fit_first(self):
        found = match_epics(self.story("Terraform module for VPC"), self.EPICS, RULES)
        self.assertEqual([(m.epic.key, m.score) for m in found], [("E-1", 0.5)])
        self.assertEqual(found[0].shared, ("terraform",))

    def test_the_better_match_comes_first(self):
        epics = [epic("E-1", "Terraform migration"), epic("E-2", "Terraform")]
        found = match_epics(self.story("Terraform module for VPC"), epics, RULES)
        self.assertEqual([(m.epic.key, m.score) for m in found], [("E-2", 1.0), ("E-1", 0.5)])

    def test_word_endings_match(self):
        found = match_epics(self.story("Add alert for failed log shipping"), self.EPICS, RULES)
        self.assertEqual(found[0].epic.key, "E-2")
        self.assertEqual(found[0].score, 1.0)           # alert and log both found ("logging" and "log" match)

    def test_the_description_counts_too_but_not_the_role(self):
        story = self.story("Misc work", "As a platform engineer, I want the database encrypted, so that data is safe.")
        self.assertEqual(match_epics(story, self.EPICS, RULES)[0].epic.key, "E-3")
        only_the_role = self.story("Misc work", "As a platform engineer, I want old notes tidied, so that the wiki is clear.")
        self.assertEqual(match_epics(only_the_role, [epic("E-9", "Platform engineer")], RULES), [])

    def test_below_the_score_nothing_is_suggested(self):
        rules = rules_with(lambda d: d["epics"].update(min_match_score=0.9))
        self.assertEqual(match_epics(self.story("Terraform module for VPC"), self.EPICS, rules), [])

    def test_a_story_matching_nothing_gets_nothing(self):
        self.assertEqual(match_epics(self.story("Update the onboarding page"), self.EPICS, RULES), [])

    def test_ties_break_by_key_and_the_list_is_limited(self):
        epics = [epic("E-2", "Terraform"), epic("E-1", "Terraform"), epic("E-3", "Terraform"), epic("E-4", "Terraform")]
        found = match_epics(self.story("Terraform module"), epics, RULES, limit=3)
        self.assertEqual([m.epic.key for m in found], ["E-1", "E-2", "E-3"])

    def test_epics_with_no_usable_words_are_skipped(self):
        self.assertEqual(match_epics(self.story("Terraform module"), [epic("E-1", "Work"), epic("E-2", "")], RULES), [])


class NeedsEpicTests(unittest.TestCase):
    def test_no_epic_or_an_inactive_one(self):
        by_key = {"E-1": epic("E-1", status="Done"), "E-2": epic("E-2")}
        self.assertTrue(needs_epic(make_story(epic=""), by_key, RULES, TODAY))
        self.assertTrue(needs_epic(make_story(epic="  "), by_key, RULES, TODAY))
        self.assertTrue(needs_epic(make_story(epic="E-1"), by_key, RULES, TODAY))
        self.assertFalse(needs_epic(make_story(epic="E-2"), by_key, RULES, TODAY))
        self.assertFalse(needs_epic(make_story(epic="UNKNOWN-1"), by_key, RULES, TODAY))


class NewEpicTests(unittest.TestCase):
    def stories(self, *summaries):
        return [make_story(key=f"S-{i}", summary=text, description="", epic="") for i, text in enumerate(summaries, start=1)]

    def test_a_shared_word_in_enough_stories_makes_a_proposal(self):
        found = new_epic_proposals(self.stories("Rotate service credentials", "Rotate cloud credentials", "Rotate API credentials"), RULES)
        self.assertEqual([(n.name, n.keys) for n in found], [("Credentials", ("S-1", "S-2", "S-3"))])

    def test_two_stories_are_not_enough(self):
        self.assertEqual(new_epic_proposals(self.stories("Rotate service credentials", "Rotate cloud credentials"), RULES), [])

    def test_the_minimum_comes_from_the_rules_file(self):
        rules = rules_with(lambda d: d["epics"].update(new_epic_min_stories=2))
        self.assertEqual(len(new_epic_proposals(self.stories("Rotate service credentials", "Rotate cloud credentials"), rules)), 1)

    def test_a_story_joins_only_one_proposal_and_the_biggest_group_goes_first(self):
        stories = self.stories("Vault policy review", "Vault secret cleanup", "Vault audit logging", "Vault token rotation",
                               "Audit report review", "Audit evidence upload")
        found = new_epic_proposals(stories, RULES)
        self.assertEqual(found[0].name, "Vault")
        taken = [k for n in found for k in n.keys]
        self.assertEqual(len(taken), len(set(taken)))

    def test_the_name_is_a_readable_word_not_a_stem(self):
        found = new_epic_proposals(self.stories("Encrypting the databases", "Encrypting more databases", "Encrypting old databases"), RULES)
        self.assertIn(found[0].name, ("Encrypting", "Databases"))

    def test_can_be_turned_off(self):
        rules = rules_with(lambda d: d["epics"].update(suggest_new=False))
        self.assertEqual(new_epic_proposals(self.stories("Rotate a credentials", "Rotate b credentials", "Rotate c credentials"), rules), [])


if __name__ == "__main__":
    unittest.main()
