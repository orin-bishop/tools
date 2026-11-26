import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from refiner import doctor
from refiner.cli import main
from tests.helpers import ROOT, RULES_PATH

EXPORTS = ROOT / "fixtures" / "jira_export"
FILLED_FIELDS = ROOT / "fixtures" / "jira_fields.test.yaml"


def run(*argv):
    out = io.StringIO()
    return main(list(argv), out=out), out.getvalue()


def ready_copy(folder):
    """A copy of the project settings with every placeholder and starter example replaced."""
    root = Path(folder)
    rules = RULES_PATH.read_text()
    for old, new in [('jira_base_url: ""', 'jira_base_url: "https://jira.example.com"'),
                     ("  required_all: []", "  required_all: [team-save]"),
                     ("allowed_roles: []", "allowed_roles: [platform engineer]"),
                     ("known: [terraform]", "known: [terraform, ansible]"),
                     ("    - name: Upgrade a cluster", "    - name: Upgrade the OpenShift cluster"),
                     ('marker_start: "<!-- {id} START -->"', 'marker_start: "[[{id}:start]]"')]:
        assert old in rules, old
        rules = rules.replace(old, new, 1)
    (root / "rules.yaml").write_text(rules)
    shutil.copy(FILLED_FIELDS, root / "jira_fields.yaml")
    (root / "context").mkdir()
    (root / "context" / "hints.yaml").write_text("hints_version: 1\nhints: []\n")
    (root / "pipeline").mkdir()
    (root / "pipeline" / "pipe.yaml").write_text("pipeline:\n  name: filled in\n")
    return root


def checks_in(root):
    return doctor.run_checks(root / "rules.yaml", root / "jira_fields.yaml", root / "context", root / "pipeline")


class PlaceholderTests(unittest.TestCase):
    def test_placeholders_are_found_with_line_numbers_and_comments_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.yaml"
            path.write_text("# REPLACE_IN_A_COMMENT is fine\nname: REPLACE_ORG   # REPLACE_ALSO_FINE\nother: ok\nid: REPLACE_PROJECT\n")
            self.assertEqual(doctor.find_placeholders(path), [("REPLACE_ORG", 2), ("REPLACE_PROJECT", 4)])


class RepositoryStateTests(unittest.TestCase):
    """The repository as shipped: it must FAIL until the Fed side fills in the placeholders."""

    def setUp(self):
        self.checks = doctor.run_checks(RULES_PATH, ROOT / "jira_fields.yaml", ROOT / "context", ROOT / "pipeline")
        self.by_status = {s: [c for c in self.checks if c.status == s] for s in ("FAIL", "TODO", "OK")}

    def test_placeholders_in_the_field_map_and_pipeline_sketches_fail(self):
        failing = " ".join(c.message for c in self.by_status["FAIL"])
        self.assertIn("jira_fields.yaml still has 4 REPLACE_ value(s)", failing)
        self.assertIn("harness-pipeline.example.yaml", failing)
        self.assertIn("harness-trigger.example.yaml", failing)

    def test_starter_examples_are_todo_not_fail(self):
        topics = {c.topic for c in self.by_status["TODO"]}
        self.assertEqual(topics, {"jira link", "labels", "roles", "themes", "work patterns", "confluence markers", "hints"})

    def test_the_rules_file_and_schedule_are_ok(self):
        topics = {c.topic for c in self.by_status["OK"]}
        self.assertIn("rules", topics)
        self.assertIn("schedule", topics)


class ReadyTests(unittest.TestCase):
    def test_a_filled_in_copy_has_no_fail_and_no_todo(self):
        with tempfile.TemporaryDirectory() as folder:
            checks = checks_in(ready_copy(folder))
        self.assertEqual([c for c in checks if c.status != "OK"], [])

    def test_an_empty_schedule_note_is_a_todo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ready_copy(folder)
            path = root / "rules.yaml"
            path.write_text(path.read_text().replace('  note: "This report runs every week, the working day before team refinement."', '  note: ""'))
            todo = [c.topic for c in checks_in(root) if c.status == "TODO"]
        self.assertEqual(todo, ["schedule"])

    def test_a_broken_rules_file_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ready_copy(folder)
            (root / "rules.yaml").write_text("rules_version: [")
            failing = [c.topic for c in checks_in(root) if c.status == "FAIL"]
        self.assertIn("rules", failing)

    def test_a_missing_field_map_or_hints_file_is_a_todo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ready_copy(folder)
            (root / "jira_fields.yaml").unlink()
            (root / "context" / "hints.yaml").unlink()
            todo = {c.topic for c in checks_in(root) if c.status == "TODO"}
        self.assertEqual(todo, {"jira fields", "hints"})


class ShapeTests(unittest.TestCase):
    def test_counts_only_and_no_story_text(self):
        lines, warnings = doctor.shape(ROOT / "fixtures" / "program.json")
        text = "\n".join(lines + warnings)
        self.assertIn("Stories: 16 (current sprint 0, upcoming 0, backlog 13, not in Jira yet 3)", text)
        self.assertIn("Epics: 5 (with an end date: 5)", text)
        self.assertIn("acceptance criteria", text)
        for secret in ("Terraform", "credentials", "log shipping", "Sample Person"):
            self.assertNotIn(secret, text)

    def test_warnings_point_at_the_likely_mapping_mistake(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snap.json"
            path.write_text(json.dumps({"stories": [{"key": "A-1", "summary": "x"}, {"key": "A-2", "summary": "y"}]}))
            _, warnings = doctor.shape(path)
        text = " ".join(warnings)
        self.assertIn("No story has acceptance criteria", text)
        self.assertIn("No story has points", text)
        self.assertIn("Every story is in one group", text)
        self.assertIn("The snapshot has no epics", text)


class CliTests(unittest.TestCase):
    def test_doctor_on_the_repository_fails_until_placeholders_are_filled(self):
        code, text = run("doctor", "--rules", str(RULES_PATH), "--fields", str(ROOT / "jira_fields.yaml"),
                         "--context", str(ROOT / "context"), "--pipeline-dir", str(ROOT / "pipeline"))
        self.assertEqual(code, 1)
        self.assertTrue(text.index("FAIL") < text.index("TODO") < text.index("OK"))        # most urgent first
        self.assertIn("Fix the FAIL lines before the first real run.", text)

    def test_doctor_passes_on_a_ready_copy_and_strict_only_matters_for_todo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ready_copy(folder)
            args = ["doctor", "--rules", str(root / "rules.yaml"), "--fields", str(root / "jira_fields.yaml"),
                    "--context", str(root / "context"), "--pipeline-dir", str(root / "pipeline")]
            code, text = run(*args)
            strict_code, _ = run(*args, "--strict")
        self.assertEqual((code, strict_code), (0, 0))
        self.assertIn("Ready to run.", text)

    def test_strict_fails_on_todo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ready_copy(folder)
            path = root / "rules.yaml"
            path.write_text(path.read_text().replace('jira_base_url: "https://jira.example.com"', 'jira_base_url: ""'))
            args = ["doctor", "--rules", str(path), "--fields", str(root / "jira_fields.yaml"),
                    "--context", str(root / "context"), "--pipeline-dir", str(root / "pipeline")]
            self.assertEqual(run(*args)[0], 0)
            self.assertEqual(run(*args, "--strict")[0], 1)

    def test_doctor_prints_the_shape(self):
        _, text = run("doctor", "--rules", str(RULES_PATH), "--snapshot", str(ROOT / "fixtures" / "program.json"))
        self.assertIn("Snapshot shape (counts only, safe to share):", text)
        self.assertIn("Stories: 16", text)

    def test_doctor_with_a_bad_snapshot_is_a_clean_error(self):
        code, text = run("doctor", "--rules", str(RULES_PATH), "--snapshot", "/no/such.json")
        self.assertEqual(code, 2)
        self.assertIn("Cannot read the snapshot", text)

    def test_snapshot_command_builds_a_file_the_other_commands_can_use(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "snapshot.json"
            code, text = run("snapshot", "--fields", str(FILLED_FIELDS), "--current", str(EXPORTS / "current_sprint.json"),
                             "--future", str(EXPORTS / "future_sprints.json"), "--backlog", str(EXPORTS / "backlog.json"),
                             "--epics", str(EXPORTS / "epics.json"), "--out", str(target))
            check_code, check_text = run("check", "--snapshot", str(target), "--rules", str(RULES_PATH), "--today", "2026-11-25")
        self.assertEqual(code, 0)
        self.assertIn("4 stories, 2 epics", text)
        self.assertIn("note: J-1 is in both current_sprint and backlog", text)
        self.assertEqual(check_code, 0)
        self.assertIn("Checked 4 stories", check_text)

    def test_snapshot_refuses_a_field_map_with_placeholders(self):
        code, text = run("snapshot", "--fields", str(ROOT / "jira_fields.yaml"), "--current", str(EXPORTS / "current_sprint.json"))
        self.assertEqual(code, 2)
        self.assertIn("REPLACE_ACCEPTANCE_CRITERIA_FIELD_ID", text)

    def test_snapshot_needs_at_least_one_export(self):
        code, text = run("snapshot", "--fields", str(FILLED_FIELDS))
        self.assertEqual(code, 2)
        self.assertIn("Give at least one export", text)

    def test_snapshot_with_a_bad_export_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.json"
            bad.write_text('{"nothing": 1}')
            code, text = run("snapshot", "--fields", str(FILLED_FIELDS), "--current", str(bad))
        self.assertEqual(code, 2)
        self.assertIn("Cannot use the export", text)


if __name__ == "__main__":
    unittest.main()
