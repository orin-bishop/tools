import re
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from html import unescape

from refiner.changes import build_changes
from refiner.context import load_context
from refiner.model import Epic, Story, load_data
from refiner.runner import check_all
from refiner.suggest import suggest_all
from refiner.updatepack import build_update_pack
from tests.helpers import ROOT, make_story, rules_with

TODAY = date(2026, 11, 25)
GENERATED = "2026-11-25 10:00"
LINKED = lambda d: d["workbook"].update(jira_base_url="https://jira.example.com")  # noqa: E731


def pack(stories=None, epics=None, edit=None, **kwargs):
    rules = rules_with(edit)
    if stories is None:
        data = load_data(ROOT / "fixtures" / "program.json")
        stories, epics = data.stories, data.epics
    summary = check_all(stories, rules, epics or [], today=TODAY)
    suggestions = suggest_all(summary.results, rules, load_context(ROOT / "context"), summary.analysis)
    changes = build_changes(summary, suggestions, rules)
    return build_update_pack(summary, suggestions, changes, rules, generated=GENERATED, **kwargs), changes, summary


def parse(html):
    """The page must be well formed (apart from the doctype line), so any XML reader can open it."""
    return ET.fromstring(html.split("\n", 1)[1])


def text_of(element):
    return "".join(element.itertext())


class PageTests(unittest.TestCase):
    def setUp(self):
        self.html, self.changes, self.summary = pack(edit=LINKED)
        self.root = parse(self.html)

    def test_it_is_well_formed_and_starts_with_the_doctype(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))

    def test_banner_title_date_and_version(self):
        text = text_of(self.root)
        self.assertIn("INTERNAL USE ONLY", text)
        self.assertIn("Backlog refinement report: update pack", text)
        self.assertIn("Generated 2026-11-25 10:00. Rules version 1.", text)
        self.assertIn("Nothing here changes Jira.", text)

    def test_it_uses_no_outside_files(self):
        lowered = self.html.lower()
        for outside in ("<link", "src=", "@import", "url(", "<iframe", "<img"):
            self.assertNotIn(outside, lowered)

    def test_every_in_page_link_goes_somewhere(self):
        ids = {element.get("id") for element in self.root.iter() if element.get("id")}
        targets = {element.get("href")[1:] for element in self.root.iter("a") if element.get("href", "").startswith("#")}
        self.assertTrue(targets)
        self.assertEqual(targets - ids, set())

    def test_the_contents_list_every_story_that_has_a_table(self):
        cards = {element.get("id") for element in self.root.iter("h3") if (element.get("id") or "").startswith("story-")}
        keys = {c.key for c in self.changes}
        self.assertTrue({f"story-{k}" for k in keys} <= cards)

    def test_the_overview_table_uses_the_shared_counts(self):
        text = text_of(self.root)
        self.assertIn("At a glance: Suggest split 0, Missing info 7, Needs review 5, Looks good 4.", text)
        self.assertIn("Epic needs attention", text)

    def test_jira_links_open_in_a_new_window_safely(self):
        links = [a for a in self.root.iter("a") if (a.get("href") or "").startswith("https://jira.example.com/browse/")]
        self.assertTrue(links)
        for link in links:
            self.assertEqual((link.get("target"), link.get("rel")), ("_blank", "noopener noreferrer"))
        hrefs = {a.get("href") for a in links}
        self.assertIn("https://jira.example.com/browse/P-3", hrefs)
        self.assertNotIn("https://jira.example.com/browse/NEW-1", hrefs)          # not in Jira yet: no link

    def test_no_links_without_a_jira_address(self):
        html, _, _ = pack()
        self.assertNotIn("/browse/", html)

    def test_the_same_input_gives_the_same_page(self):
        again, _, _ = pack(edit=LINKED)
        self.assertEqual(self.html, again)


class StoryCardTests(unittest.TestCase):
    def setUp(self):
        self.html, self.changes, self.summary = pack(edit=LINKED)
        self.root = parse(self.html)

    def rows_for(self, key):
        """[(field, now, suggested boxes, why)] for the story's table."""
        for div in self.root.iter("div"):
            heading = div.find("h3")
            if div.get("class") == "story" and heading is not None and heading.get("id") == f"story-{key}":
                table = div.find("table")
                if table is None:
                    return []
                rows = []
                for tr in list(table.iter("tr"))[1:]:
                    cells = tr.findall("td")
                    boxes = [d for d in cells[2].iter("div")]
                    rows.append((text_of(cells[0]), text_of(cells[1]), boxes, text_of(cells[3])))
                return rows
        raise AssertionError(f"no card for {key}")

    def test_a_copy_box_holds_exactly_the_suggested_text(self):
        for change in self.changes:
            if change.kind == "review":
                continue
            row = next(r for r in self.rows_for(change.key) if r[0].startswith(change.field))
            self.assertEqual(text_of(row[2][0]), change.suggested)
            self.assertEqual(row[2][0].get("class"), "copybox")

    def test_decide_rows_are_notes_not_copy_boxes(self):
        row = next(r for r in self.rows_for("P-5") if r[0].startswith("Duplicate"))
        self.assertEqual(row[2][0].get("class"), "note")
        self.assertIn("Decide", row[0])

    def test_an_empty_field_says_set_and_shows_it_is_empty(self):
        row = next(r for r in self.rows_for("P-3") if r[0].startswith("Epic"))
        self.assertIn("Set", row[0])
        self.assertEqual(row[1], "(empty)")

    def test_a_field_with_a_value_says_replace_and_shows_it(self):
        row = next(r for r in self.rows_for("NEW-2") if r[0].startswith("Summary"))
        self.assertIn("Replace", row[0])
        self.assertEqual(row[1], "Misc fixes and cleanup")
        self.assertIn("Rotate the shared database credentials every 90 days", text_of(row[2][0]))

    def test_the_reason_is_shown(self):
        row = next(r for r in self.rows_for("P-3") if r[0].startswith("Epic"))
        self.assertIn("Best fit: Terraform migration", row[3])

    def test_questions_are_listed(self):
        self.assertIn("Is this a duplicate of NEW-3?", text_of(self.root))

    def test_waiting_stories_are_marked_as_not_in_jira_yet(self):
        self.assertIn("Not in Jira yet. Use these when you create the story.", text_of(self.root))

    def test_stories_with_nothing_to_do_have_no_card(self):
        ids = {h.get("id") for h in self.root.iter("h3")}
        self.assertNotIn("story-P-1", ids)
        self.assertNotIn("story-P-7", ids)


class SafetyTests(unittest.TestCase):
    def test_hostile_text_is_escaped_everywhere(self):
        nasty = '<script>alert(1)</script> & "quotes" \'apostrophes\''
        story = Story.from_dict(dict(key="X-1", summary=nasty, description="", acceptance_criteria="", story_points=2, epic=nasty))
        epic = Epic.from_dict(dict(key="E-1", name=nasty, status="In Progress"))
        html, _, _ = pack([story], [epic])
        parse(html)                                                  # still well formed
        self.assertNotIn("<script>alert", html)
        self.assertIn(unescape("&lt;script&gt;alert(1)&lt;/script&gt;"), text_of(parse(html)))

    def test_a_key_with_odd_characters_cannot_break_an_anchor(self):
        story = Story.from_dict(dict(key='X 1"><b>', summary="Rotate service credentials", description="", acceptance_criteria="", story_points=2))
        html, _, _ = pack([story], [])
        root = parse(html)
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids), ids)

    def test_a_jira_address_with_quotes_cannot_break_a_link(self):
        rules_edit = lambda d: d["workbook"].update(jira_base_url='https://jira.example.com/"><script>x</script>')  # noqa: E731
        html, _, _ = pack(edit=rules_edit)
        parse(html)
        self.assertNotIn("<script>x</script>", html)


class ScriptTests(unittest.TestCase):
    def test_copy_buttons_come_with_a_small_script(self):
        html, changes, _ = pack(copy_buttons=True)
        root = parse(html)
        copyable = [c for c in changes if c.kind != "review"]
        self.assertEqual(html.count('class="copy"'), len(copyable))
        self.assertEqual(len(list(root.iter("script"))), 1)
        self.assertIn("navigator.clipboard", html)
        self.assertNotIn("http", [s.text for s in root.iter("script")][0])        # the script reaches nowhere

    def test_without_buttons_there_is_no_script_at_all(self):
        html, _, _ = pack(copy_buttons=False)
        self.assertNotIn("<script", html)
        self.assertNotIn('class="copy"', html)
        self.assertIn("then copy it", html)                                       # the instructions change to match
        self.assertIn('class="copybox"', html)                                    # boxes still select on click

    def test_the_rules_file_controls_the_buttons(self):
        html, _, _ = pack(edit=lambda d: d["update_pack"].update(copy_buttons=False))
        self.assertNotIn("<script", html)

    def test_an_explicit_choice_beats_the_rules_file(self):
        html, _, _ = pack(edit=lambda d: d["update_pack"].update(copy_buttons=False), copy_buttons=True)
        self.assertIn("<script", html)


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.html, _, self.summary = pack(edit=LINKED)
        self.text = text_of(parse(self.html))

    def test_epics_section_lists_epics_with_their_state_and_story_counts(self):
        root = parse(self.html)
        section = [t for t in root.iter("table") if "Epic" in text_of(t.find(".//tr")) and "Dates" in text_of(t.find(".//tr"))][0]
        rows = {text_of(tr.findall("td")[0]): [text_of(td) for td in tr.findall("td")] for tr in list(section.iter("tr"))[1:]}
        self.assertEqual(rows["EPIC-1"][4:], ["Current or future", "5"])          # P-1, P-2, P-4, P-13 and NEW-1
        self.assertEqual(rows["EPIC-4"][4], "Finished or ended")
        self.assertIn("As of 2026-11-25.", self.text)

    def test_stories_that_need_an_epic_are_listed_with_a_suggestion(self):
        self.assertIn("Stories that need an epic", self.text)
        self.assertIn("EPIC-1 Terraform migration (50%)", self.text)
        self.assertIn('New epic idea: "Credentials"', self.text)

    def test_new_epic_ideas_section(self):
        self.assertIn("New epic ideas", self.text)
        self.assertIn("P-10, P-11, P-12", self.text)

    def test_duplicates_section_names_both_stories_and_the_score(self):
        self.assertIn("Possible duplicate", self.text)
        self.assertIn("100%", self.text)
        self.assertIn("Related", self.text)

    def test_themes_section_separates_listed_themes_from_counted_ones(self):
        self.assertIn("Listed in the rules file", self.text)
        self.assertIn("Found by counting", self.text)
        self.assertIn("A possible theme found by counting words.", self.text)

    def test_when_nothing_is_wrong_the_sections_say_so(self):
        good = make_story(key="G-1", epic="E-1")
        html, _, _ = pack([good], [Epic.from_dict(dict(key="E-1", name="Anything", status="In Progress"))])
        text = text_of(parse(html))
        self.assertIn("Every story has a current or future epic.", text)
        self.assertIn("No duplicate or related stories were found.", text)
        self.assertIn("No themes were found.", text)
        self.assertIn("No story needs an update.", text)

    def test_with_no_epic_list_it_says_so(self):
        html, _, _ = pack([make_story(key="G-1", epic="")], [])
        self.assertIn("No epic list was given, so only missing epics could be checked.", text_of(parse(html)))


if __name__ == "__main__":
    unittest.main()
