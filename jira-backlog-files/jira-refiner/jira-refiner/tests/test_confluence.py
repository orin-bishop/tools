import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from refiner.cli import main
from refiner.confluence import AMBER, COLUMNS, GRAY, GREEN, RED, build_sections, write_sections
from refiner.measures import count_by_group, count_by_label, count_row
from refiner.model import Story, load_snapshot
from refiner.rules import RulesError, parse_rules
from refiner.runner import check_all
from tests.helpers import RULES_PATH, SNAPSHOT_PATH, make_story, rules_with

GENERATED = "2026-11-25 10:00"
ALLOWED_TAGS = {"p", "em", "strong", "h2", "h3", "ul", "li", "table", "tbody", "tr", "th", "td", "span"}
ALLOWED_ATTRIBUTES = {("td", "style"), ("th", "style"), ("span", "style")}


def build(stories=None, rules=None):
    rules = rules or rules_with()
    stories = stories if stories is not None else load_snapshot(SNAPSHOT_PATH)
    summary = check_all(stories, rules)
    return build_sections(summary, rules, GENERATED), summary, rules


def parse(section):
    """Parse a section as XML. Confluence storage format is XML, so a section that does not parse is broken."""
    return ET.fromstring(f"<root>{section.html}</root>")


def table_rows(root):
    """[[cell text, ...], ...] for the first table in the section."""
    table = root.find(".//table")
    return [["".join(cell.itertext()) for cell in row] for row in table.iter("tr")]


class StorageFormatTests(unittest.TestCase):
    def setUp(self):
        self.sections, self.summary, self.rules = build()

    def test_three_sections_in_page_order_with_the_ids_from_the_rules(self):
        self.assertEqual([s.id for s in self.sections], ["refiner-summary", "refiner-labels", "refiner-not-checked"])

    def test_every_section_is_well_formed(self):
        for section in self.sections:
            parse(section)

    def test_only_storage_format_tags_and_attributes_are_used(self):
        for section in self.sections:
            for element in parse(section).iter():
                if element.tag == "root":
                    continue
                self.assertIn(element.tag, ALLOWED_TAGS, f"{section.id}: <{element.tag}>")
                for attribute in element.attrib:
                    self.assertIn((element.tag, attribute), ALLOWED_ATTRIBUTES, f"{section.id}: {element.tag}@{attribute}")

    def test_no_page_level_tags_or_scripts_anywhere_in_the_text(self):
        for section in self.sections:
            lowered = section.html.lower()
            for forbidden in ("<html", "<head", "<body", "<style", "<script", "<br>", "javascript:", "onclick"):
                self.assertNotIn(forbidden, lowered, f"{section.id}: {forbidden}")

    def test_hostile_text_is_escaped(self):
        nasty = Story.from_dict(dict(key="N-1", summary="x", labels=['<script>alert(1)</script>', 'a&b "quoted"', "it's"],
                                     description="d", acceptance_criteria="a", story_points=2))
        sections, _, _ = build([nasty])
        labels = sections[1]
        root = parse(labels)                                   # still well formed
        self.assertNotIn("<script>", labels.html)
        names = [row[0] for row in table_rows(root)[1:]]
        self.assertIn('<script>alert(1)</script>', names)     # shown as text, not run
        self.assertIn('a&b "quoted"', names)
        self.assertIn("it's", names)


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.sections, self.summary, self.rules = build()
        self.summary_section, self.labels_section, self.skipped_section = self.sections

    def test_banner_title_date_version_and_total(self):
        text = "".join(parse(self.summary_section).itertext())
        self.assertIn("INTERNAL USE ONLY", text)
        self.assertIn("Backlog refinement report", text)
        self.assertIn(f"Generated {GENERATED}.", text)
        self.assertIn("Rules version 1.", text)
        self.assertIn("18 stories and spikes checked", text)
        self.assertIn("statuses ignored: Done, Closed", text)

    def test_the_page_says_it_shows_counts_only(self):
        self.assertIn("This page shows counts only. It does not name people or stories.", "".join(parse(self.summary_section).itertext()))

    def test_at_a_glance(self):
        text = "".join(parse(self.summary_section).itertext())
        self.assertIn("At a glance: Suggest split 4, Missing info 5, Needs review 4, Looks good 5.", text)

    def test_group_table_matches_the_shared_counts(self):
        rows = table_rows(parse(self.summary_section))
        self.assertEqual(rows[0], ["Group"] + COLUMNS)
        groups = count_by_group(self.summary.results, self.rules.include_groups)
        expected = [[name] + [str(counts[c]) for c in COLUMNS] for name, counts in groups.items()]
        total = count_row(self.summary.results)
        expected.append(["Total"] + [str(total[c]) for c in COLUMNS])
        self.assertEqual(rows[1:], expected)

    def test_label_table_matches_the_shared_counts(self):
        rows = table_rows(parse(self.labels_section))
        self.assertEqual(rows[0], ["Label"] + COLUMNS)
        labels = count_by_label(self.summary.results)
        self.assertEqual(rows[1:], [[name] + [str(counts[c]) for c in COLUMNS] for name, counts in labels.items()])
        self.assertEqual([r[0] for r in rows[1:]], ["platform", "tooling", "No label"])

    def test_not_checked_table(self):
        rows = table_rows(parse(self.skipped_section))
        self.assertEqual(rows, [["Reason", "Stories"], ["issue type 'Bug' is not in scope", "1"], ["status 'Done' is ignored", "1"]])

    def test_not_checked_reasons_are_sorted_whatever_order_the_stories_came_in(self):
        bug = make_story(key="B-1", issue_type="Bug")
        done = make_story(key="D-1", status="Done")
        for stories in ([bug, done, make_story(key="G-1")], [done, bug, make_story(key="G-1")]):
            sections, _, _ = build(stories)
            reasons = [row[0] for row in table_rows(parse(sections[2]))[1:]]
            self.assertEqual(reasons, ["issue type 'Bug' is not in scope", "status 'Done' is ignored"])

    def test_explanations_use_the_thresholds_from_the_rules_file(self):
        text = "".join(parse(self.summary_section).itertext())
        self.assertIn("empty, 20 characters or fewer", text)
        self.assertIn("5 points or more with little written", text)
        rules = rules_with(lambda d: (d["fields"]["description"].update(min_chars=31), d["fields"]["story_points"].update(review_at_or_above=8)))
        sections, _, _ = build(rules=rules)
        text = "".join(parse(sections[0]).itertext())
        self.assertIn("empty, 30 characters or fewer", text)
        self.assertIn("8 points or more with little written", text)

    def test_story_format_sentence_follows_the_rules_switch(self):
        rules = rules_with(lambda d: d["fields"]["description"]["story_format"].update(enabled=False))
        sections, _, _ = build(rules=rules)
        self.assertNotIn("As a ..., I want", "".join(parse(sections[0]).itertext()))

    def test_workbook_note_can_be_left_empty(self):
        rules = rules_with(lambda d: d["confluence"].update(workbook_note=""))
        sections, _, _ = build(rules=rules)
        self.assertNotIn("attached to the pipeline run", sections[0].html)

    def test_group_rows_follow_the_rules_scope(self):
        rules = rules_with(lambda d: d["scope"].update(include=["current_sprint", "backlog"]))
        sections, _, _ = build(rules=rules)
        self.assertEqual([r[0] for r in table_rows(parse(sections[0]))[1:]], ["Current sprint", "Backlog", "Total"])

    def test_nothing_skipped_says_so(self):
        sections, _, _ = build([make_story(key="A-1")])
        self.assertIn("Every story in the snapshot was checked.", "".join(parse(sections[2]).itertext()))

    def test_empty_snapshot_still_gives_valid_sections(self):
        sections, _, _ = build([])
        for section in sections:
            parse(section)
        self.assertIn("No stories were checked.", "".join(parse(sections[1]).itertext()))
        self.assertIn("At a glance: Suggest split 0, Missing info 0, Needs review 0, Looks good 0.", "".join(parse(sections[0]).itertext()))


class CountsOnlyTests(unittest.TestCase):
    def test_no_story_text_keys_or_people_appear_anywhere(self):
        stories = [
            Story.from_dict(dict(key="SECRET-1", summary="Confidential summary words", description="Private description words",
                                 acceptance_criteria="Hidden criteria words", story_points=2, assignee="Jane Q. Public",
                                 epic="EPIC-SECRET", sprint="Sprint Secret", labels=["team-a"],
                                 extra={"Reporter": "John Smith"})),
        ]
        sections, _, _ = build(stories)
        everything = " ".join(s.html for s in sections)
        for hidden in ("SECRET-1", "Confidential", "Private description", "Hidden criteria", "Jane", "EPIC-SECRET", "Sprint Secret", "John Smith"):
            self.assertNotIn(hidden, everything)
        self.assertIn("team-a", everything)                      # a label is a category, not a person or a story


class ColorTests(unittest.TestCase):
    def colors(self, html):
        import re
        return re.findall(r'color: (rgb\([0-9,]+\))', html)

    def test_zero_is_gray_and_problems_are_colored(self):
        sections, _, _ = build([make_story(key="G-1")])           # one good story
        found = set(self.colors(sections[0].html))
        self.assertIn(GRAY, found)                                # zeros
        self.assertIn(GREEN, found)                               # one that looks good
        self.assertNotIn(RED, found)
        self.assertNotIn(AMBER, found)

    def test_missing_info_is_red_and_review_is_amber(self):
        sections, _, _ = build([make_story(key="M-1", description=""), make_story(key="R-1", acceptance_criteria="TBD")])
        found = set(self.colors(sections[0].html))
        self.assertIn(RED, found)
        self.assertIn(AMBER, found)

    def test_the_stories_column_is_never_colored(self):
        sections, _, _ = build([make_story(key="G-1")])
        rows = parse(sections[0]).find(".//table").findall(".//tr")
        stories_cell = rows[1].findall("td")[1]
        self.assertEqual(stories_cell.findall("span"), [])


class MarkerTests(unittest.TestCase):
    def test_default_markers_use_the_section_id(self):
        sections, _, rules = build()
        self.assertEqual(sections[0].markers(rules), ("<!-- refiner-summary START -->", "<!-- refiner-summary END -->"))

    def test_markers_follow_the_rules_file(self):
        rules = rules_with(lambda d: d["confluence"].update(marker_start="[[{id}:begin]]", marker_end="[[{id}:finish]]"))
        sections, _, _ = build(rules=rules)
        self.assertEqual(sections[1].markers(rules), ("[[refiner-labels:begin]]", "[[refiner-labels:finish]]"))

    def test_section_ids_follow_the_rules_file(self):
        rules = rules_with(lambda d: d["confluence"]["section_ids"].update(summary="team-summary"))
        sections, _, _ = build(rules=rules)
        self.assertEqual(sections[0].id, "team-summary")

    def test_with_markers_wraps_the_body_in_order(self):
        sections, _, rules = build()
        wrapped = sections[2].with_markers(rules)
        lines = wrapped.splitlines()
        self.assertEqual(lines[0], "<!-- refiner-not-checked START -->")
        self.assertEqual(lines[-1], "<!-- refiner-not-checked END -->")
        self.assertIn(sections[2].html, wrapped)

    def test_same_input_gives_the_same_html(self):
        first = [s.html for s in build()[0]]
        second = [s.html for s in build()[0]]
        self.assertEqual(first, second)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.sections, _, self.rules = build()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_files_manifest_and_preview(self):
        manifest = write_sections(self.folder, self.sections, self.rules, GENERATED)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["manifest.json", "preview.html", "section-refiner-labels.html",
                          "section-refiner-not-checked.html", "section-refiner-summary.html"])
        self.assertEqual(json.loads((self.folder / "manifest.json").read_text()), manifest)
        first = manifest["sections"][0]
        self.assertEqual(first, {"id": "refiner-summary", "title": "Summary", "file": "section-refiner-summary.html",
                                 "start_marker": "<!-- refiner-summary START -->", "end_marker": "<!-- refiner-summary END -->"})
        self.assertFalse(manifest["markers_included_in_files"])
        self.assertEqual(manifest["rules_version"], 1)

    def test_section_files_hold_the_body_only_by_default(self):
        write_sections(self.folder, self.sections, self.rules, GENERATED)
        text = (self.folder / "section-refiner-summary.html").read_text()
        self.assertNotIn("START", text)
        self.assertTrue(text.startswith("<p><em>INTERNAL USE ONLY"))

    def test_markers_can_be_written_into_the_files(self):
        manifest = write_sections(self.folder, self.sections, self.rules, GENERATED, include_markers=True)
        text = (self.folder / "section-refiner-labels.html").read_text()
        self.assertTrue(text.startswith("<!-- refiner-labels START -->"))
        self.assertTrue(text.rstrip().endswith("<!-- refiner-labels END -->"))
        self.assertTrue(manifest["markers_included_in_files"])

    def test_the_rules_file_can_turn_markers_on(self):
        rules = rules_with(lambda d: d["confluence"].update(include_markers=True))
        sections, _, _ = build(rules=rules)
        write_sections(self.folder, sections, rules, GENERATED)
        self.assertIn("START", (self.folder / "section-refiner-summary.html").read_text())

    def test_only_the_preview_has_page_level_tags(self):
        write_sections(self.folder, self.sections, self.rules, GENERATED)
        preview = (self.folder / "preview.html").read_text()
        self.assertIn("PREVIEW ONLY", preview)
        self.assertIn("<style>", preview)
        for path in self.folder.glob("section-*.html"):
            self.assertNotIn("<style", path.read_text())
            self.assertNotIn("<html", path.read_text())

    def test_the_folder_is_created_if_needed(self):
        target = self.folder / "deep" / "er"
        write_sections(target, self.sections, self.rules, GENERATED)
        self.assertTrue((target / "manifest.json").is_file())


class RulesTests(unittest.TestCase):
    TEXT = RULES_PATH.read_text(encoding="utf-8")

    def problems(self, text):
        try:
            parse_rules(text)
        except RulesError as err:
            return err.problems
        return []

    def test_settings_load(self):
        rules = rules_with()
        self.assertEqual(rules.confluence_marker_start, "<!-- {id} START -->")
        self.assertFalse(rules.confluence_include_markers)
        self.assertEqual(rules.confluence_section_ids, {"summary": "refiner-summary", "labels": "refiner-labels", "not_checked": "refiner-not-checked"})

    def test_marker_must_contain_the_id_placeholder(self):
        found = self.problems(self.TEXT.replace('marker_start: "<!-- {id} START -->"', 'marker_start: "<!-- START -->"'))
        self.assertEqual(len(found), 1, found)
        self.assertIn("confluence.marker_start", found[0])
        self.assertIn("{id}", found[0])

    def test_section_id_characters(self):
        found = self.problems(self.TEXT.replace("summary: refiner-summary", "summary: Refiner Summary"))
        self.assertTrue(any("confluence.section_ids.summary" in p and "lower case" in p for p in found), found)

    def test_section_ids_must_be_different(self):
        found = self.problems(self.TEXT.replace("labels: refiner-labels", "labels: refiner-summary"))
        self.assertTrue(any("more than once" in p for p in found), found)

    def test_unknown_section_name_gets_a_suggestion(self):
        found = self.problems(self.TEXT.replace("not_checked: refiner-not-checked", "not_cheked: refiner-not-checked"))
        self.assertTrue(any("Did you mean 'not_checked'" in p for p in found), found)

    def test_include_markers_must_be_true_or_false(self):
        found = self.problems(self.TEXT.replace("include_markers: false", "include_markers: sometimes"))
        self.assertTrue(any("true or false" in p for p in found), found)

    def test_confluence_section_is_required(self):
        start = self.TEXT.index("confluence:")
        end = self.TEXT.index("# ----", start)
        self.assertTrue(any("'confluence' is missing" in p for p in self.problems(self.TEXT[:start] + self.TEXT[end:])))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        return main(list(argv), out=out), out.getvalue()

    def test_command_writes_everything_and_names_the_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            code, text = self.run_cli("confluence", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH),
                                      "--out-dir", folder, "--generated", GENERATED)
            names = sorted(p.name for p in Path(folder).iterdir())
        self.assertEqual(code, 0)
        self.assertIn("section-refiner-summary.html", text)
        self.assertIn("<!-- refiner-summary START --> ... <!-- refiner-summary END -->", text)
        self.assertIn("manifest.json", names)
        self.assertEqual(len(names), 5)

    def test_include_markers_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            self.run_cli("confluence", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH), "--out-dir", folder,
                         "--include-markers", "--generated", GENERATED)
            self.assertTrue((Path(folder) / "section-refiner-summary.html").read_text().startswith("<!-- refiner-summary START -->"))

    def test_a_bad_snapshot_is_a_clean_error(self):
        code, text = self.run_cli("confluence", "--snapshot", "/no/such.json", "--rules", str(RULES_PATH))
        self.assertEqual(code, 2)
        self.assertIn("Cannot use the snapshot", text)

    def test_an_unwritable_folder_is_a_clean_error(self):
        code, text = self.run_cli("confluence", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH),
                                  "--out-dir", "/proc/not-allowed/here")
        self.assertEqual(code, 2)
        self.assertIn("Cannot write the Confluence files", text)


if __name__ == "__main__":
    unittest.main()
