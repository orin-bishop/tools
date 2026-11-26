import unittest
from datetime import date

from refiner.model import load_data
from refiner.runner import check_all
from tests.helpers import ROOT, rules_with

TODAY = date(2026, 11, 25)
PROGRAM = ROOT / "fixtures" / "program.json"


def run(rules=None, **kwargs):
    rules = rules or rules_with()
    data = load_data(PROGRAM)
    return check_all(data.stories, rules, kwargs.pop("epics", data.epics), today=kwargs.pop("today", TODAY))


def codes(summary):
    return {r.story.key: {f.code for f in r.flags} for r in summary.results}


class FlagTests(unittest.TestCase):
    def setUp(self):
        self.summary = run()
        self.codes = codes(self.summary)

    def test_stories_with_no_epic_are_flagged_high(self):
        for key in ("P-3", "P-5", "P-10", "P-11", "P-12", "NEW-3"):
            self.assertIn("epic_missing", self.codes[key], key)
        flag = next(f for r in self.summary.results if r.story.key == "P-3" for f in r.flags if f.code == "epic_missing")
        self.assertEqual((flag.severity, flag.field), ("high", "epic"))

    def test_stories_in_finished_or_ended_epics_are_flagged(self):
        self.assertIn("epic_inactive", self.codes["P-8"])            # epic status Done
        self.assertIn("epic_inactive", self.codes["P-9"])            # epic ended 2026-10-31
        self.assertNotIn("epic_inactive", self.codes["P-7"])         # a future epic is fine

    def test_duplicates_are_flagged_and_related_stories_are_not(self):
        self.assertIn("duplicate_story", self.codes["P-5"])
        self.assertIn("duplicate_story", self.codes["P-6"])
        self.assertNotIn("duplicate_story", self.codes["P-1"])        # its twin is waiting to upload, so only NEW-1 is flagged
        self.assertIn("duplicate_story", self.codes["NEW-1"])
        self.assertNotIn("duplicate_story", self.codes["P-13"])       # related to P-1, not a duplicate

    def test_a_stories_title_that_does_not_fit_is_flagged(self):
        self.assertIn("summary_mismatch", self.codes["NEW-2"])

    def test_good_stories_stay_good(self):
        for key in ("P-1", "P-2", "P-4", "P-7"):
            self.assertEqual(self.codes[key], set(), key)

    def test_missing_epic_means_missing_info_and_duplicate_means_review(self):
        verdicts = {r.story.key: r.verdict for r in self.summary.results}
        self.assertEqual(verdicts["P-10"], "Missing info")
        self.assertEqual(verdicts["P-6"], "Needs review")
        self.assertEqual(verdicts["NEW-1"], "Needs review")


class AnalysisContentTests(unittest.TestCase):
    def setUp(self):
        self.analysis = run().analysis

    def test_only_current_and_future_epics_are_active(self):
        self.assertEqual([e.key for e in self.analysis.active_epics], ["EPIC-1", "EPIC-2", "EPIC-3"])
        self.assertEqual(self.analysis.today, TODAY)

    def test_epic_matches_for_stories_that_need_one(self):
        matches = {k: [(m.epic.key, m.score) for m in v] for k, v in self.analysis.epic_matches.items()}
        self.assertEqual(matches["P-3"], [("EPIC-1", 0.5)])
        self.assertEqual(matches["P-5"], [("EPIC-2", 1.0)])
        self.assertEqual(matches["NEW-3"], [("EPIC-2", 1.0)])
        self.assertNotIn("P-10", matches)

    def test_new_epic_idea_for_stories_that_fit_nothing(self):
        found = [(n.name, n.keys) for n in self.analysis.new_epics]
        self.assertEqual(found, [("Credentials", ("P-10", "P-11", "P-12"))])

    def test_pairs_and_groups(self):
        pairs = {(p.a.key, p.b.key): p.kind for p in self.analysis.pairs}
        self.assertEqual(pairs[("NEW-1", "P-1")], "duplicate")
        self.assertEqual(pairs[("P-5", "P-6")], "duplicate")
        self.assertEqual(pairs[("P-1", "P-13")], "related")
        self.assertEqual(self.analysis.duplicate_groups, [["NEW-1", "P-1"], ["NEW-3", "P-5", "P-6"]])

    def test_themes(self):
        terraform = next(t for t in self.analysis.themes if t.word == "Terraform")
        self.assertEqual(terraform.keys, ("NEW-1", "P-1", "P-13", "P-2", "P-3", "P-4"))
        self.assertNotIn("P-3", terraform.starting)


class SettingsTests(unittest.TestCase):
    def test_pretending_it_is_an_earlier_day_makes_an_ended_epic_current_again(self):
        summary = run(today=date(2026, 10, 1))
        self.assertNotIn("epic_inactive", codes(summary)["P-9"])
        self.assertIn("EPIC-5", [e.key for e in summary.analysis.active_epics])

    def test_the_rules_file_can_set_the_date(self):
        rules = rules_with(lambda d: d["epics"].update(today="2026-10-01"))
        data = load_data(PROGRAM)
        summary = check_all(data.stories, rules, data.epics)
        self.assertEqual(summary.analysis.today, date(2026, 10, 1))

    def test_with_no_epic_list_stories_can_still_be_missing_one_but_none_are_inactive(self):
        summary = run(epics=[])
        found = codes(summary)
        self.assertIn("epic_missing", found["P-3"])
        self.assertNotIn("epic_inactive", found["P-8"])
        self.assertEqual(summary.analysis.epic_matches, {})
        self.assertEqual([n.name for n in summary.analysis.new_epics][:1], ["Credentials"])

    def test_epic_checks_can_be_turned_off(self):
        summary = run(rules_with(lambda d: d["epics"].update(enabled=False)))
        found = codes(summary)
        self.assertFalse(any({"epic_missing", "epic_inactive"} & c for c in found.values()))
        self.assertEqual((summary.analysis.epic_matches, summary.analysis.new_epics), ({}, []))

    def test_only_listed_groups_must_have_an_epic(self):
        summary = run(rules_with(lambda d: d["epics"].update(required_groups=["intake"])))
        found = codes(summary)
        self.assertNotIn("epic_missing", found["P-3"])
        self.assertIn("epic_missing", found["NEW-3"])

    def test_duplicates_can_be_turned_off(self):
        summary = run(rules_with(lambda d: d["duplicates"].update(enabled=False)))
        self.assertFalse(any("duplicate_story" in c for c in codes(summary).values()))
        self.assertEqual(summary.analysis.pairs, [])

    def test_stories_that_are_not_checked_are_left_out_of_the_analysis(self):
        data = load_data(PROGRAM)
        data.stories[5].status = "Done"                       # P-6, P-5's twin, is finished
        summary = check_all(data.stories, rules_with(), data.epics, today=TODAY)
        self.assertNotIn("duplicate_story", codes(summary)["P-5"])        # with its twin finished, P-5 is no longer flagged
        self.assertEqual(summary.skipped["status 'Done' is ignored"], 1)
        self.assertNotIn(("P-5", "P-6"), {(p.a.key, p.b.key) for p in summary.analysis.pairs})


class MeasureTests(unittest.TestCase):
    def test_new_measures_count_the_new_flags(self):
        from refiner.measures import count_row
        row = count_row(run().results)
        self.assertEqual(row["Epic needs attention"], 8)        # six with no epic, two in inactive epics
        self.assertEqual(row["Possible duplicate"], 4)           # NEW-1, NEW-3, P-5 and P-6 (P-1 is not: only the waiting copy is flagged)
        self.assertEqual(row["Title needs attention"], 1)
        self.assertEqual(row["Labels need attention"], 0)


if __name__ == "__main__":
    unittest.main()
