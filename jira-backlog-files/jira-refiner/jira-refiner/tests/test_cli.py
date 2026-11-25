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
