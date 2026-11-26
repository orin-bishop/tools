import unittest

from refiner.duplicates import DUPLICATE, RELATED, duplicate_groups, find_pairs, findings
from tests.helpers import make_story, rules_with

RULES = rules_with()


def story(key, summary, description="", group="backlog"):
    return make_story(key=key, summary=summary, description=description, group=group)


class PairTests(unittest.TestCase):
    def kinds(self, *stories, rules=RULES):
        return [(p.a.key, p.b.key, p.kind) for p in find_pairs(list(stories), rules)]

    def test_same_title_is_a_duplicate_and_word_order_or_endings_do_not_matter(self):
        self.assertEqual(self.kinds(story("A", "Add alert for failed log shipping"), story("B", "Alert on failed log shipping")),
                         [("A", "B", DUPLICATE)])
        self.assertEqual(self.kinds(story("A", "Rotate service credentials"), story("B", "Credentials rotation for service")),
                         [("A", "B", DUPLICATE)])

    def test_exactly_at_the_duplicate_line_counts_as_duplicate(self):
        pair = find_pairs([story("A", "Vault policy audit token"), story("B", "Vault policy audit token rotation")], RULES)[0]
        self.assertAlmostEqual(pair.score, 0.8)                    # 4 shared words out of 5
        self.assertEqual(pair.kind, DUPLICATE)

    def test_partly_alike_is_related_not_duplicate(self):
        found = self.kinds(story("A", "Terraform module for VPC"), story("B", "Terraform module for VPC endpoints"))
        self.assertEqual(found, [("A", "B", RELATED)])

    def test_unalike_stories_are_not_paired(self):
        self.assertEqual(self.kinds(story("A", "Terraform module for VPC"), story("B", "Update the onboarding page")), [])

    def test_role_words_and_everyday_verbs_do_not_make_stories_alike(self):
        a = story("A", "Add dashboard for builds", "As a platform engineer, I want a dashboard, so that I see builds.")
        b = story("B", "Create platform engineer notes")
        self.assertEqual(self.kinds(a, b), [])

    def test_titles_with_too_few_words_are_not_compared(self):
        self.assertEqual(self.kinds(story("A", "Terraform"), story("B", "Terraform")), [])

    def test_the_thresholds_come_from_the_rules_file(self):
        rules = rules_with(lambda d: d["duplicates"].update(duplicate_at=1.0, related_at=0.9))
        self.assertEqual(self.kinds(story("A", "Terraform module for VPC"), story("B", "Terraform module for VPC endpoints"), rules=rules), [])

    def test_descriptions_count_when_both_stories_have_one(self):
        same = "As a dev, I want logs shipped to the central store, so that we can search them."
        other = "As a dev, I want invoices exported to the finance system, so that billing is easy."
        titles = ("Ship logs to the central store", "Ship logs to central archive")      # titles alone: 60% alike
        title_only = find_pairs([story("A", titles[0]), story("B", titles[1])], RULES)[0]
        with_same = find_pairs([story("A", titles[0], same), story("B", titles[1], same)], RULES)[0]
        with_other = find_pairs([story("A", titles[0], same), story("B", titles[1], other)], RULES)
        self.assertAlmostEqual(title_only.score, 0.6)
        self.assertGreater(with_same.score, title_only.score)       # the same description lifts the pair
        self.assertEqual(with_other, [])                            # very different descriptions pull it below "related"

    def test_a_missing_description_means_titles_only(self):
        pair = find_pairs([story("A", "Rotate service credentials", "As a dev, I want credentials rotated, so that keys stop working."),
                           story("B", "Rotate service credentials")], RULES)[0]
        self.assertIsNone(pair.description_score)
        self.assertEqual(pair.score, pair.title_score)

    def test_zero_description_weight_uses_the_title_alone(self):
        rules = rules_with(lambda d: d["duplicates"].update(description_weight=0))
        text = "As a dev, I want logs shipped to the central store, so that we can search them."
        pair = find_pairs([story("A", "Ship logs to the central store", text), story("B", "Ship logs to central archive", text)], rules)[0]
        self.assertAlmostEqual(pair.score, pair.title_score)

    def test_most_alike_first_and_the_order_is_stable(self):
        stories = [story("C", "Terraform module for VPC endpoints"), story("A", "Terraform module for VPC"), story("B", "Terraform module for VPC")]
        pairs = find_pairs(stories, RULES)
        self.assertEqual((pairs[0].a.key, pairs[0].b.key), ("A", "B"))
        self.assertEqual([p.kind for p in pairs], [DUPLICATE, RELATED, RELATED])

    def test_can_be_turned_off(self):
        rules = rules_with(lambda d: d["duplicates"].update(enabled=False))
        self.assertEqual(find_pairs([story("A", "Rotate service credentials"), story("B", "Rotate service credentials")], rules), [])


class GroupTests(unittest.TestCase):
    def test_chains_of_duplicates_join_into_one_group(self):
        stories = [story("A", "Rotate service credentials"), story("B", "Credentials rotate service"),
                   story("C", "Service credentials rotation"), story("D", "Update the onboarding page")]
        self.assertEqual(duplicate_groups(find_pairs(stories, RULES)), [["A", "B", "C"]])

    def test_related_stories_do_not_form_groups(self):
        stories = [story("A", "Terraform module for VPC"), story("B", "Terraform module for VPC endpoints")]
        self.assertEqual(duplicate_groups(find_pairs(stories, RULES)), [])


class FindingTests(unittest.TestCase):
    def test_both_stories_in_jira_are_flagged_with_the_other_one_named(self):
        found = findings(find_pairs([story("A", "Rotate service credentials"), story("B", "Rotate service credentials")], RULES))
        self.assertEqual(sorted(found), ["A", "B"])
        self.assertIn("duplicate of B ('Rotate service credentials')", found["A"][0][1])
        self.assertIn("100% alike", found["A"][0][1])
        self.assertEqual(found["A"][0][0], "duplicate_story")

    def test_only_the_waiting_story_is_flagged_when_the_other_is_already_in_jira(self):
        found = findings(find_pairs([story("A", "Rotate service credentials"), story("NEW-1", "Rotate service credentials", group="intake")], RULES))
        self.assertEqual(list(found), ["NEW-1"])
        self.assertIn("already in Jira", found["NEW-1"][0][1])

    def test_two_waiting_stories_are_both_flagged(self):
        stories = [story("NEW-1", "Rotate service credentials", group="intake"), story("NEW-2", "Rotate service credentials", group="intake")]
        self.assertEqual(sorted(findings(find_pairs(stories, RULES))), ["NEW-1", "NEW-2"])

    def test_related_stories_get_no_flag(self):
        stories = [story("A", "Terraform module for VPC"), story("B", "Terraform module for VPC endpoints")]
        self.assertEqual(findings(find_pairs(stories, RULES)), {})

    def test_a_story_matching_two_others_gets_two_messages(self):
        stories = [story("NEW-1", "Rotate service credentials", group="intake"), story("A", "Rotate service credentials"), story("B", "Service credentials rotate")]
        self.assertEqual(len(findings(find_pairs(stories, RULES))["NEW-1"]), 2)


class RulesFileTests(unittest.TestCase):
    def test_related_must_not_be_higher_than_duplicate(self):
        from refiner.rules import RulesError
        with self.assertRaises(RulesError) as caught:
            rules_with(lambda d: d["duplicates"].update(related_at=0.9, duplicate_at=0.6))
        self.assertIn("duplicates.related_at", caught.exception.problems[0])

    def test_both_weights_cannot_be_zero(self):
        from refiner.rules import RulesError
        with self.assertRaises(RulesError):
            rules_with(lambda d: d["duplicates"].update(title_weight=0, description_weight=0))


if __name__ == "__main__":
    unittest.main()
