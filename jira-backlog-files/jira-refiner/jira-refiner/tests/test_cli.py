import io
import json
import tempfile
import unittest
from pathlib import Path

from refiner.cli import main
from tests.helpers import ROOT, RULES_PATH, SNAPSHOT_PATH

CONTEXT = ROOT / "context"


def run(*argv):
    out = io.StringIO()
    code = main(list(argv), out=out)
    return code, out.getvalue()


class CliTests(unittest.TestCase):
    def test_validate_rules_ok(self):
        code, text = run("validate-rules", "--rules", str(RULES_PATH))
        self.assertEqual(code, 0)
        self.assertIn("Rules OK: version 1", text)

    def test_validate_rules_reports_every_problem(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.yaml"
            bad.write_text(RULES_PATH.read_text().replace("review_at_or_above: 5", "review_at_or_above: lots"))
            code, text = run("validate-rules", "--rules", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("1 problem(s)", text)
        self.assertIn("review_at_or_above", text)

    def test_check_prints_a_table_and_totals(self):
        code, text = run("check", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH))
        self.assertEqual(code, 0)
        self.assertIn("DEMO-9", text)
        self.assertIn("Suggest split", text)
        self.assertIn("Totals:", text)
        self.assertIn("Not checked:", text)
        self.assertNotIn("\033[", text)      # no color codes when not printing to a terminal

    def test_details_prints_the_sentences(self):
        _, text = run("check", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH), "--details")
        self.assertIn("[high] The description is empty.", text)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.json"
            code, _ = run("check", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH), "--json", str(target))
            data = json.loads(target.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(data["rules_version"], 1)
        self.assertEqual(sum(data["totals"].values()), len(data["results"]))
        nine = next(r for r in data["results"] if r["key"] == "DEMO-9")
        self.assertEqual(nine["verdict"], "Suggest split")
        self.assertEqual(nine["flags"][0]["code"], "possibly_undersized")

    def test_suggest_prints_labelled_drafts(self):
        code, text = run("suggest", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH), "--context", str(CONTEXT))
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith("SUGGESTED - review before use"))
        self.assertIn("Context used: hints.yaml, platform-standards.md", text)
        self.assertIn("DEMO-9  [Suggest split]", text)
        self.assertIn("Ask in refinement:", text)
        self.assertIn("(has a placeholder to fill in)", text)
        self.assertNotIn("DEMO-1  [", text)            # a story that looks good gets no draft

    def test_suggest_works_with_no_context_folder(self):
        code, text = run("suggest", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH), "--context", "/no/such/folder")
        self.assertEqual(code, 0)
        self.assertIn("Context used: none", text)

    def test_suggest_json(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "suggestions.json"
            code, _ = run("suggest", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH),
                          "--context", str(CONTEXT), "--json", str(target))
            data = json.loads(target.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(data["label"], "SUGGESTED - review before use")
        self.assertEqual(data["files_read"], ["hints.yaml", "platform-standards.md"])
        nine = next(s for s in data["suggestions"] if s["key"] == "DEMO-9")
        self.assertEqual(len(nine["split_titles"]), 4)

    def test_suggest_with_a_broken_hints_file_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "hints.yaml").write_text("hints_version: 1\nhints:\n  - name: Oops\n")
            code, text = run("suggest", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH), "--context", folder)
        self.assertEqual(code, 2)
        self.assertIn("The hints file has", text)
        self.assertIn("hints[1].words", text)

    def test_bad_snapshot_is_a_clean_error(self):
        code, text = run("check", "--snapshot", "/no/such/file.json", "--rules", str(RULES_PATH))
        self.assertEqual(code, 2)
        self.assertIn("Cannot use the snapshot", text)


if __name__ == "__main__":
    unittest.main()


PROGRAM = ROOT / "fixtures" / "program.json"
INTAKE = ROOT / "fixtures" / "intake.csv"
TODAY = ("--today", "2026-11-25")


class ProgramCliTests(unittest.TestCase):
    def test_check_shows_what_was_found_across_stories(self):
        code, text = run("check", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), *TODAY)
        self.assertEqual(code, 0)
        self.assertIn("Across stories:", text)
        self.assertIn("Possible duplicate pairs: 4 (related pairs: 5)", text)
        self.assertIn("Stories that need an epic: 8 (with a suggested epic: 3)", text)
        self.assertIn("New epic ideas: 1", text)
        self.assertIn("Terraform (listed, 5 of 6 titles start with it)", text)

    def test_the_epic_list_in_the_snapshot_is_used(self):
        _, text = run("check", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--details", *TODAY)
        self.assertIn("Epic EPIC-4 (Legacy cleanup) has status Done", text)

    def test_today_changes_which_epics_are_current(self):
        _, before = run("check", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--details", "--today", "2026-10-01")
        self.assertNotIn("Epic EPIC-5 (Onboarding docs) ended", before)
        _, after = run("check", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--details", *TODAY)
        self.assertIn("Epic EPIC-5 (Onboarding docs) ended on 2026-10-31", after)

    def test_a_bad_date_is_a_clean_error(self):
        code, text = run("check", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--today", "next tuesday")
        self.assertEqual(code, 2)
        self.assertIn("Cannot use the date", text)

    def test_an_intake_csv_adds_stories_that_are_not_in_jira_yet(self):
        _, text = run("check", "--snapshot", str(PROGRAM), "--intake", str(INTAKE), "--rules", str(RULES_PATH), *TODAY)
        self.assertIn("Checked 18 stories", text)
        self.assertIn("NEW-4", text)
        self.assertIn("intake", text)

    def test_a_broken_intake_csv_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.csv"
            bad.write_text("Name\nx\n")
            code, text = run("check", "--snapshot", str(PROGRAM), "--intake", str(bad), "--rules", str(RULES_PATH))
        self.assertEqual(code, 2)
        self.assertIn("needs a 'Summary'", text)

    def test_suggest_prints_titles_epics_and_duplicates(self):
        _, text = run("suggest", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--context", str(CONTEXT), *TODAY)
        self.assertIn("Suggested title: Rotate the shared database credentials every 90 days", text)
        self.assertIn("Suggested epic: EPIC-1 Terraform migration (50%)", text)
        self.assertIn('New epic idea: Create an epic "Credentials"', text)
        self.assertIn("Possible duplicate of: P-1 ('Terraform module for VPC', 100% alike)", text)

    def test_suggest_prints_labels_to_add(self):
        with tempfile.TemporaryDirectory() as folder:
            rules = Path(folder) / "rules.yaml"
            rules.write_text(RULES_PATH.read_text().replace("  required_all: []", "  required_all: [team-save]"))
            _, text = run("suggest", "--snapshot", str(PROGRAM), "--rules", str(rules), "--context", str(CONTEXT), *TODAY)
        self.assertIn("Labels to add: team-save", text)

    def test_changes_writes_one_csv_row_per_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "changes.csv"
            code, text = run("changes", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--context", str(CONTEXT),
                             "--out", str(target), *TODAY)
            with target.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(__import__("csv").DictReader(handle))
        self.assertEqual(code, 0)
        self.assertIn(f"{len(rows)} suggested edit(s)", text)
        self.assertTrue(any(r["Key"] == "P-3" and r["Field"] == "Epic" and r["Suggested"] == "EPIC-1" for r in rows))

    def test_update_pack_with_and_without_copy_buttons(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "pack.html"
            code, text = run("update-pack", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--context", str(CONTEXT),
                             "--out", str(target), "--generated", "x", *TODAY)
            with_buttons = target.read_text()
            run("update-pack", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--context", str(CONTEXT),
                "--out", str(target), "--no-copy-buttons", *TODAY)
            without = target.read_text()
        self.assertEqual(code, 0)
        self.assertIn("stories with suggested edits", text)
        self.assertIn("<script>", with_buttons)
        self.assertNotIn("<script", without)

    def test_report_writes_everything_into_one_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "deep" / "out"
            code, text = run("report", "--snapshot", str(PROGRAM), "--intake", str(INTAKE), "--rules", str(RULES_PATH),
                             "--context", str(CONTEXT), "--out-dir", str(target), "--generated", "x", *TODAY)
            names = sorted(p.name for p in target.iterdir())
            sections = sorted(p.name for p in (target / "confluence").iterdir())
            opened = load_workbook(target / "refinement-report.xlsx").sheetnames
        self.assertEqual(code, 0)
        self.assertEqual(names, ["changes.csv", "confluence", "refinement-report.xlsx", "update-pack.html"])
        self.assertIn("manifest.json", sections)
        self.assertIn("section-refiner-epics.html", sections)
        self.assertIn("Epics", opened)
        self.assertIn("18 stories checked", text)

    def test_report_into_a_folder_it_cannot_create_is_a_clean_error(self):
        code, text = run("report", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), "--context", str(CONTEXT),
                         "--out-dir", "/proc/not-allowed/here", *TODAY)
        self.assertEqual(code, 2)
        self.assertIn("Cannot write the report", text)

    def test_check_does_not_need_a_context_folder(self):
        code, _ = run("check", "--snapshot", str(PROGRAM), "--rules", str(RULES_PATH), *TODAY)
        self.assertEqual(code, 0)


from openpyxl import load_workbook  # noqa: E402  (used by the report test)
