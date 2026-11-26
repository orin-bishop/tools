import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from refiner.changes import CSV_COLUMNS, FIELD_ORDER, GROUP_ORDER, build_changes, issue_url, write_changes_csv
from refiner.context import load_context
from refiner.model import Epic, load_data
from refiner.runner import check_all
from refiner.suggest import suggest_all
from tests.helpers import ROOT, make_story, rules_with

TODAY = date(2026, 11, 25)
PROGRAM = ROOT / "fixtures" / "program.json"
EPICS = [Epic.from_dict(dict(key="E-1", name="Terraform migration", status="In Progress")),
         Epic.from_dict(dict(key="E-2", name="Legacy cleanup", status="Done"))]


def changes_for(stories, rules=None, epics=EPICS, context=None):
    rules = rules or rules_with()
    summary = check_all(stories, rules, epics, today=TODAY)
    suggestions = suggest_all(summary.results, rules, context, summary.analysis)
    return build_changes(summary, suggestions, rules), summary, rules


def by_field(changes, key):
    return {c.field: c for c in changes if c.key == key}


class FromTheFixtureTests(unittest.TestCase):
    def setUp(self):
        data = load_data(PROGRAM)
        self.rules = rules_with()
        self.summary = check_all(data.stories, self.rules, data.epics, today=TODAY)
        self.suggestions = suggest_all(self.summary.results, self.rules, load_context(ROOT / "context"), self.summary.analysis)
        self.changes = build_changes(self.summary, self.suggestions, self.rules)
        self.data = data

    def test_a_missing_epic_gets_an_update_row_with_the_best_fit(self):
        row = by_field(self.changes, "P-3")["Epic"]
        self.assertEqual((row.kind, row.current, row.suggested), ("update", "", "EPIC-1"))
        self.assertIn("Terraform migration", row.reason)
        self.assertIn("50% of its name", row.reason)

    def test_stories_that_fit_no_epic_get_a_review_row_with_the_new_epic_idea(self):
        row = by_field(self.changes, "P-10")["Epic"]
        self.assertEqual(row.kind, "review")
        self.assertIn('Create an epic "Credentials"', row.suggested)

    def test_a_story_in_a_finished_epic_with_no_good_fit_still_gets_a_visible_row(self):
        row = by_field(self.changes, "P-8")["Epic"]
        self.assertEqual((row.kind, row.current, row.suggested), ("review", "EPIC-4", "Choose a current or future epic"))
        self.assertIn("Done", row.reason)

    def test_a_better_title_for_a_title_that_does_not_fit(self):
        row = by_field(self.changes, "NEW-2")["Summary"]
        self.assertEqual((row.current, row.suggested), ("Misc fixes and cleanup", "Rotate the shared database credentials every 90 days"))

    def test_a_known_theme_moves_to_the_front_of_the_title_for_a_good_story_too(self):
        row = by_field(self.changes, "P-3")["Summary"]
        self.assertEqual(row.suggested, "Terraform: Add state backend")
        self.assertIn("Theme 'Terraform'", row.reason)
        self.assertIn("5 of 6 titles start with it", row.reason)

    def test_titles_that_already_start_with_the_theme_are_left_alone(self):
        for key in ("P-1", "P-2", "P-4", "P-13", "NEW-1"):
            self.assertNotIn("Summary", by_field(self.changes, key), key)

    def test_words_found_only_by_counting_never_rewrite_titles(self):
        suggested = [c.suggested for c in self.changes if c.field == "Summary"]
        self.assertFalse(any(text.startswith(("Module:", "Alert:", "Failed:", "Credentials:")) for text in suggested), suggested)

    def test_duplicate_rows_name_the_other_stories(self):
        row = by_field(self.changes, "P-5")["Duplicate"]
        self.assertEqual(row.kind, "review")
        self.assertIn("NEW-3", row.suggested)
        self.assertIn("P-6", row.suggested)
        self.assertIn("Possible duplicate of P-6", row.reason)

    def test_a_theme_only_change_exists_for_a_story_that_otherwise_looks_good(self):
        data = load_data(PROGRAM)
        story = next(s for s in data.stories if s.key == "P-3")
        story.epic = "EPIC-1"                                         # now P-3 has an epic, and nothing else is wrong
        summary = check_all(data.stories, self.rules, data.epics, today=TODAY)
        suggestions = suggest_all(summary.results, self.rules, None, summary.analysis)
        self.assertNotIn("P-3", suggestions)                          # a good story has no suggestion ...
        row = by_field(build_changes(summary, suggestions, self.rules), "P-3")["Summary"]
        self.assertEqual(row.suggested, "Terraform: Add state backend")        # ... but its title can still be tidied

    def test_rows_are_in_report_order(self):
        order = [(GROUP_ORDER.index(c.group), FIELD_ORDER.index(c.field)) for c in self.changes]
        groups = [o[0] for o in order]
        self.assertEqual(groups, sorted(groups))
        keys = [c.key for c in self.changes if c.group == "backlog"]
        self.assertEqual(keys, sorted(keys, key=lambda k: int(k.split("-")[1])))          # P-3 before P-10

    def test_the_same_input_gives_the_same_rows(self):
        again = build_changes(self.summary, self.suggestions, self.rules)
        self.assertEqual(self.changes, again)


class SingleStoryTests(unittest.TestCase):
    def test_description_and_criteria_rows_use_jira_style_bullets(self):
        context = load_context(ROOT / "context")
        stories = [make_story(key="A-1", summary="Add alert for failed deployments", description="", acceptance_criteria="")]
        rows = by_field(changes_for(stories, context=context)[0], "A-1")
        self.assertTrue(rows["Description"].suggested.startswith("As a platform engineer, I want to add alert"))
        self.assertEqual(rows["Acceptance criteria"].suggested.splitlines()[0], "* An alert is sent when the problem happens")
        self.assertEqual(rows["Description"].kind, "update")

    def test_labels_are_an_add_row_that_keeps_the_existing_ones(self):
        rules = rules_with(lambda d: d["labels"].update(required_all=["team-save"]))
        rows = by_field(changes_for([make_story(key="A-1", labels=["platform"])], rules)[0], "A-1")
        self.assertEqual((rows["Labels"].kind, rows["Labels"].current, rows["Labels"].suggested), ("add", "platform", "team-save"))
        self.assertIn("Keep the existing labels.", rows["Labels"].reason)

    def test_a_split_row_lists_the_pieces_or_asks_for_pieces_of_the_usual_size(self):
        rows = by_field(changes_for([make_story(key="A-1", summary="Encrypt production database")])[0], "A-1")
        self.assertEqual(rows["Split"].kind, "review")
        self.assertIn("Cut over and retire the old database", rows["Split"].suggested)
        thin = make_story(key="A-2", summary="Set up new build tool", description="As a platform engineer, I want a new tool.", story_points=8)
        row = by_field(changes_for([thin])[0], "A-2")["Split"]
        self.assertEqual((row.current, row.suggested), ("8 points", "Pieces of about 2 points each"))

    def test_a_story_that_needs_nothing_has_no_rows(self):
        self.assertEqual(changes_for([make_story(key="A-1", epic="E-1")])[0], [])

    def test_good_stories_with_a_known_theme_title_only_get_that_one_row(self):
        pairs = [("Terraform module for VPC", "a Terraform module for the VPC, so that networks are built the same way"),
                 ("Terraform pipeline for plan", "a Terraform pipeline for plan and apply, so that changes are reviewed"),
                 ("Add Terraform backend", "a Terraform state backend added, so that teams share state")]
        stories = [make_story(key=f"T-{i}", summary=title, description=f"As a platform engineer, I want {want}.", epic="E-1")
                   for i, (title, want) in enumerate(pairs, start=1)]
        changes = changes_for(stories)[0]
        self.assertEqual([(c.key, c.field) for c in changes], [("T-3", "Summary")])


class TwoThemeTests(unittest.TestCase):
    def test_a_title_that_starts_with_one_listed_theme_is_not_moved_to_another(self):
        rules = rules_with(lambda d: d["themes"].update(known=["terraform", "vault"]))
        titles = ["Terraform module for Vault", "Terraform pipeline for plan", "Terraform backend for state",
                  "Vault policy review", "Vault audit logging", "Add Vault token rotation"]
        stories = [make_story(key=f"T-{i}", summary=t, description="", acceptance_criteria="* Done when a second person checks it in review",
                              epic="E-1") for i, t in enumerate(titles, start=1)]
        rows = {c.key: c for c in changes_for(stories, rules)[0] if c.field == "Summary"}
        self.assertNotIn("T-1", rows)                               # starts with Terraform, so not rewritten as "Vault: ..."
        self.assertEqual(rows["T-6"].suggested, "Vault: Add token rotation")


class LinkAndCsvTests(unittest.TestCase):
    def test_links_only_for_stories_in_jira_and_only_with_an_address(self):
        in_jira, waiting = make_story(key="A-1"), make_story(key="NEW-1", group="intake")
        plain = rules_with()
        linked = rules_with(lambda d: d["workbook"].update(jira_base_url="https://jira.example.com/"))
        self.assertEqual(issue_url(in_jira, plain), "")
        self.assertEqual(issue_url(in_jira, linked), "https://jira.example.com/browse/A-1")
        self.assertEqual(issue_url(waiting, linked), "")

    def test_csv_has_one_row_per_change_with_safe_text(self):
        data = load_data(PROGRAM)
        rules = rules_with(lambda d: d["workbook"].update(jira_base_url="https://jira.example.com"))
        summary = check_all(data.stories, rules, data.epics, today=TODAY)
        changes = build_changes(summary, suggest_all(summary.results, rules, None, summary.analysis), rules)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "changes.csv"
            write_changes_csv(path, changes, rules, {s.key: s for s in data.stories})
            raw = path.read_bytes()
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                       # Excel reads it as UTF-8
        self.assertEqual(list(rows[0]), CSV_COLUMNS)
        self.assertEqual(len(rows), len(changes))
        epic_row = next(r for r in rows if r["Key"] == "P-3" and r["Field"] == "Epic")
        self.assertEqual((epic_row["Suggested"], epic_row["Link"]), ("EPIC-1", "https://jira.example.com/browse/P-3"))
        waiting = next(r for r in rows if r["Key"] == "NEW-1")
        self.assertEqual(waiting["Link"], "")

    def test_text_that_starts_like_a_formula_is_made_safe(self):
        stories = [make_story(key="A-1", summary="=SUM(A1)", description="As a dev, I want to patch the base image, so that scans pass.")]
        changes, summary, rules = changes_for(stories)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "changes.csv"
            write_changes_csv(path, changes, rules, {"A-1": stories[0]})
            with path.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
        self.assertTrue(row["Current"].startswith("'="), row["Current"])


if __name__ == "__main__":
    unittest.main()
