import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from refiner.cli import main
from refiner.context import load_context
from refiner.measures import GROUP_TITLES, MEASURES, count_by_group, count_by_label, count_row, label_key, shown_groups
from refiner.model import Story, load_data, load_snapshot
from refiner.runner import check_all
from refiner.suggest import suggest_all
from refiner.workbook import (CHANGES, DUPLICATES, EPICS, FINDINGS, RAW, RULES, SUGGESTIONS, SUMMARY, THEMES, TOC,
                              build_workbook)
from tests.helpers import ROOT, RULES_PATH, SNAPSHOT_PATH, make_story, rules_with

GENERATED = "2026-11-25 10:00"


def build(stories=None, rules=None, context=None):
    rules = rules or rules_with()
    stories = stories if stories is not None else load_snapshot(SNAPSHOT_PATH)
    summary = check_all(stories, rules)
    suggestions = suggest_all(summary.results, rules, context)
    return build_workbook(summary, stories, suggestions, rules, context, generated=GENERATED), summary


def headers(ws, row=2):
    return {cell.value: cell.column for cell in ws[row] if cell.value}


def find_row(ws, key, column=1):
    for row in range(1, ws.max_row + 1):
        if ws.cell(row=row, column=column).value == key:
            return row
    raise AssertionError(f"{key!r} not found in {ws.title}")


def fill(cell):
    return cell.fill.fgColor.rgb[-6:] if cell.fill and cell.fill.fill_type == "solid" else None


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.wb, self.summary = build(context=load_context(ROOT / "context"))

    def test_tabs_and_their_order(self):
        self.assertEqual(self.wb.sheetnames, [TOC, SUMMARY, FINDINGS, SUGGESTIONS, CHANGES, EPICS, DUPLICATES, THEMES, RAW, RULES])

    def test_every_tab_carries_the_banner(self):
        for ws in self.wb.worksheets:
            self.assertIn("INTERNAL USE ONLY", ws["A1"].value, ws.title)

    def test_everything_is_arial(self):
        for ws in self.wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        self.assertEqual(cell.font.name, "Arial", f"{ws.title}!{cell.coordinate}")

    def test_data_tabs_have_filters_and_frozen_headers(self):
        for name in (FINDINGS, SUGGESTIONS, CHANGES, EPICS, DUPLICATES, THEMES, RAW, RULES):
            ws = self.wb[name]
            self.assertTrue(ws.auto_filter.ref.startswith("A2:"), name)
            self.assertTrue(ws.freeze_panes.endswith("3"), name)

    def test_formulas_are_recalculated_when_excel_opens_the_file(self):
        self.assertTrue(self.wb.calculation.fullCalcOnLoad)

    def test_properties(self):
        self.assertEqual(self.wb.properties.title, "Backlog refinement report")
        self.assertIn("INTERNAL USE ONLY", self.wb.properties.subject)

    def test_toc_facts_and_links(self):
        ws = self.wb[TOC]
        self.assertEqual(ws.cell(row=find_row(ws, "Generated"), column=2).value, GENERATED)
        self.assertEqual(ws.cell(row=find_row(ws, "Rules version"), column=2).value, 1)
        self.assertIn("hints.yaml", ws.cell(row=find_row(ws, "Context used"), column=2).value)
        self.assertIn("statuses ignored: Done, Closed", ws.cell(row=find_row(ws, "In scope"), column=2).value)
        for name in (SUMMARY, FINDINGS, SUGGESTIONS, CHANGES, EPICS, DUPLICATES, THEMES, RAW, RULES):
            cell = ws.cell(row=find_row(ws, name), column=1)
            self.assertEqual(cell.hyperlink.location, f"'{name}'!A1")


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.wb, self.summary = build()
        self.ws = self.wb[FINDINGS]
        self.cols = headers(self.ws)

    def cell(self, key, column):
        return self.ws.cell(row=find_row(self.ws, key), column=self.cols[column])

    def test_one_row_per_checked_story_only(self):
        keys = [self.ws.cell(row=r, column=1).value for r in range(3, self.ws.max_row + 1)]
        self.assertEqual(keys, [r.story.key for r in self.summary.results])
        self.assertNotIn("DEMO-13", keys)                 # Done: not checked
        self.assertNotIn("DEMO-14", keys)                 # Bug: not in scope

    def test_empty_description_is_shaded_high(self):
        self.assertEqual(fill(self.cell("DEMO-2", "Description")), "FFD966")

    def test_short_criteria_are_shaded_medium_and_low_is_paler(self):
        self.assertEqual(fill(self.cell("DEMO-4", "Acceptance criteria")), "FFF2CC")
        self.assertEqual(fill(self.cell("DEMO-15", "Summary")), "FFFFE5")

    def test_a_cell_with_two_findings_takes_the_worst_color_and_lists_both_reasons(self):
        cell = self.cell("DEMO-6", "Description")          # short (medium) and not in story form (low)
        self.assertEqual(fill(cell), "FFF2CC")
        self.assertIn("The description is short", cell.comment.text)
        self.assertIn("not in the form 'As a", cell.comment.text)

    def test_unpointed_story_has_its_points_cell_shaded(self):
        self.assertEqual(fill(self.cell("DEMO-7", "Points")), "FFF2CC")
        self.assertIsNone(self.cell("DEMO-7", "Points").value)

    def test_split_story_has_points_shaded_high(self):
        self.assertEqual(fill(self.cell("DEMO-8", "Points")), "FFD966")

    def test_good_story_has_no_shading_anywhere(self):
        row = find_row(self.ws, "DEMO-1")
        shaded = [c.coordinate for c in self.ws[row] if fill(c)]
        self.assertEqual(shaded, [])

    def test_whole_number_points_are_stored_as_whole_numbers(self):
        value = self.cell("DEMO-1", "Points").value
        self.assertEqual(value, 2)
        self.assertIsInstance(value, int)

    def test_a_shaded_cell_explains_why(self):
        comment = self.cell("DEMO-2", "Description").comment
        self.assertIn("The description is empty.", comment.text)

    def test_colors_come_from_the_rules_file(self):
        rules = rules_with(lambda d: d["highlight"].update(high="FF0000"))
        wb, _ = build(rules=rules)
        ws = wb[FINDINGS]
        cell = ws.cell(row=find_row(ws, "DEMO-2"), column=headers(ws)["Description"])
        self.assertEqual(fill(cell), "FF0000")

    def test_yes_no_columns_follow_the_measures(self):
        for title, _ in MEASURES:
            col = self.cols[title]
            values = {self.ws.cell(row=r, column=col).value for r in range(3, self.ws.max_row + 1)}
            self.assertLessEqual(values, {"Yes", "No"}, title)
            self.assertIn("No", values, title)
            if title in ("Not pointed", "Description needs update", "Acceptance criteria needs update"):
                self.assertEqual(values, {"Yes", "No"}, title)
        self.assertEqual(self.cell("DEMO-7", "Not pointed").value, "Yes")
        self.assertEqual(self.cell("DEMO-2", "Description needs update").value, "Yes")
        self.assertEqual(self.cell("DEMO-3", "Acceptance criteria needs update").value, "Yes")

    def test_details_and_codes(self):
        self.assertEqual(self.cell("DEMO-8", "Findings").value, "description_brief; description_format; ac_brief; large_and_thin")
        self.assertIn("[high] The story is 8 points", self.cell("DEMO-8", "Details").value)

    def test_multi_line_criteria_keep_their_line_breaks(self):
        self.assertEqual(self.cell("DEMO-1", "Acceptance criteria").value.count("\n"), 1)

    def test_long_text_is_shortened_in_findings_but_not_in_raw(self):
        long_text = "word " * 200
        story = make_story(key="L-1", description=long_text)
        wb, _ = build([story])
        shown = wb[FINDINGS].cell(row=3, column=headers(wb[FINDINGS])["Description"]).value
        kept = wb[RAW].cell(row=3, column=headers(wb[RAW])["Description"]).value
        self.assertIn("shortened", shown)
        self.assertLess(len(shown), 400)
        self.assertEqual(kept, long_text)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.wb, self.summary = build()
        self.ws = self.wb[SUMMARY]
        self.findings = headers(self.wb[FINDINGS])

    def test_numbers_are_formulas_not_typed_in(self):
        row = find_row(self.ws, "Current sprint")
        for col in range(2, 10):
            self.assertTrue(str(self.ws.cell(row=row, column=col).value).startswith("="), col)

    def test_group_formulas_point_at_the_right_findings_columns(self):
        from openpyxl.utils import get_column_letter as letter
        row = find_row(self.ws, "Current sprint")
        group = letter(self.findings["Group"])
        not_pointed = letter(self.findings["Not pointed"])
        self.assertEqual(self.ws.cell(row=row, column=2).value, f"=COUNTIFS('Findings'!${group}:${group},$A{row})")
        self.assertIn(f"'Findings'!${not_pointed}:${not_pointed},\"Yes\"", self.ws.cell(row=row, column=3).value)

    def test_verdict_columns_use_their_own_header_text(self):
        from openpyxl.utils import get_column_letter
        row = find_row(self.ws, "Backlog")
        column = headers(self.ws, 5)["Suggest split"]
        formula = self.ws.cell(row=row, column=column).value
        self.assertTrue(formula.endswith(f",{get_column_letter(column)}$5)"), formula)

    def test_group_rows_follow_the_rules_scope(self):
        rules = rules_with(lambda d: d["scope"].update(include=["current_sprint", "backlog"]))
        wb, _ = build(rules=rules)
        titles = [wb[SUMMARY].cell(row=r, column=1).value for r in range(6, 9)]
        self.assertEqual(titles, ["Current sprint", "Backlog", "Total"])

    def test_total_row_sums_the_group_rows(self):
        row = find_row(self.ws, "Total")
        self.assertEqual(self.ws.cell(row=row, column=2).value, "=SUM(B6:B8)")

    def test_label_rows_and_no_label(self):
        labels = []
        start = find_row(self.ws, "Label") + 1
        while self.ws.cell(row=start, column=1).value and not self.ws.cell(row=start, column=1).value.startswith("The list"):
            labels.append(self.ws.cell(row=start, column=1).value)
            start += 1
        self.assertEqual(labels, ["platform", "tooling", "No label"])

    def test_label_formula_matches_whole_labels_only(self):
        row = find_row(self.ws, "tooling")
        self.assertIn('"*|"&$A', self.ws.cell(row=row, column=2).value)
        self.assertIn('&"|*"', self.ws.cell(row=row, column=2).value)

    def test_not_checked_table(self):
        row = find_row(self.ws, "status 'Done' is ignored")
        self.assertTrue(self.ws.cell(row=row, column=2).value.startswith("=COUNTIF('Raw Jira data'!"))

    def test_python_counts_match_the_measure_definitions(self):
        row = count_row(self.summary.results)
        self.assertEqual(row["Stories"], len(self.summary.results))
        self.assertEqual(sum(row[v] for v in ("Suggest split", "Missing info", "Needs review", "Looks good")), row["Stories"])
        groups = count_by_group(self.summary.results, rules_with().include_groups)
        self.assertEqual(sum(g["Stories"] for g in groups.values()), row["Stories"])
        shown = shown_groups(self.summary.results, rules_with().include_groups)
        self.assertEqual(list(groups), [GROUP_TITLES[g] for g in shown])
        self.assertNotIn("intake", shown)                 # no stories waiting to be uploaded, so no row for them

    def test_label_counting_helpers(self):
        stories = [Story.from_dict(dict(key="A", labels=["x", "y"])), Story.from_dict(dict(key="B"))]
        self.assertEqual(label_key(stories[0]), "|x|y|")
        self.assertEqual(label_key(stories[1]), "|No label|")
        results = check_all(stories, rules_with()).results
        counts = count_by_label(results)
        self.assertEqual(list(counts), ["x", "y", "No label"])
        self.assertTrue(all(c["Stories"] == 1 for c in counts.values()))


class SuggestionsTabTests(unittest.TestCase):
    def setUp(self):
        self.wb, _ = build(context=load_context(ROOT / "context"))
        self.ws = self.wb[SUGGESTIONS]
        self.cols = headers(self.ws)

    def cell(self, key, column):
        return self.ws.cell(row=find_row(self.ws, key), column=self.cols[column])

    def test_one_row_per_suggestion_and_none_for_good_stories(self):
        keys = [self.ws.cell(row=r, column=1).value for r in range(3, self.ws.max_row + 1)]
        self.assertEqual(len(keys), 13)
        self.assertNotIn("DEMO-1", keys)

    def test_every_row_is_labelled(self):
        for row in range(3, self.ws.max_row + 1):
            self.assertEqual(self.ws.cell(row=row, column=self.cols["Status"]).value, "SUGGESTED - review before use")

    def test_content(self):
        self.assertIn("so that the right people hear about a problem quickly", self.cell("DEMO-2", "Suggested description").value)
        self.assertTrue(self.cell("DEMO-3", "Suggested acceptance criteria").value.startswith("- The dashboard shows"))
        self.assertEqual(self.cell("DEMO-6", "Needs confirmation").value, "Yes")
        self.assertEqual(self.cell("DEMO-9", "Proposed split titles").value.count("\n"), 3)
        self.assertEqual(self.cell("DEMO-9", "Related context").value, "platform-standards.md > Database encryption")

    def test_approved_column_is_an_empty_input_with_a_y_n_dropdown(self):
        approved = self.cell("DEMO-2", "Approved?")
        self.assertIsNone(approved.value)
        self.assertEqual(fill(approved), "DDEBF7")
        validations = self.ws.data_validations.dataValidation
        self.assertEqual(len(validations), 1)
        self.assertEqual(validations[0].formula1, '"Y,N"')
        self.assertIn(approved.coordinate, str(validations[0].sqref))

    def test_nothing_to_suggest_says_so(self):
        wb, _ = build([make_story(key="G-1")])
        self.assertIn("No story needs a suggestion", wb[SUGGESTIONS]["A3"].value)
        self.assertEqual(wb[SUGGESTIONS].data_validations.dataValidation, [])


class RawTabTests(unittest.TestCase):
    def setUp(self):
        self.wb, self.summary = build()
        self.ws = self.wb[RAW]
        self.cols = headers(self.ws)

    def test_every_story_is_there_including_unchecked_ones(self):
        keys = [self.ws.cell(row=r, column=1).value for r in range(3, self.ws.max_row + 1)]
        self.assertEqual(len(keys), 20)
        self.assertIn("DEMO-13", keys)

    def test_checked_column_says_yes_or_why_not(self):
        def checked(key):
            return self.ws.cell(row=find_row(self.ws, key), column=self.cols["Checked"]).value
        self.assertEqual(checked("DEMO-1"), "Yes")
        self.assertEqual(checked("DEMO-13"), "status 'Done' is ignored")
        self.assertEqual(checked("DEMO-14"), "issue type 'Bug' is not in scope")

    def test_every_extra_jira_field_is_a_column(self):
        for name in ("Priority", "Reporter", "Created", "Components"):
            self.assertIn(name, self.cols)
        row = find_row(self.ws, "DEMO-2")
        self.assertEqual(self.ws.cell(row=row, column=self.cols["Priority"]).value, "Low")

    def test_original_markup_is_kept(self):
        row = find_row(self.ws, "DEMO-18")
        self.assertIn("h3. Background", self.ws.cell(row=row, column=self.cols["Description"]).value)

    def test_column_order_comes_from_the_rules_file_and_nothing_is_dropped(self):
        rules = rules_with(lambda d: d["workbook"].update(raw_column_order=["Summary", "Key"]))
        wb, _ = build(rules=rules)
        order = [c.value for c in wb[RAW][2] if c.value]
        self.assertEqual(order[:2], ["Summary", "Key"])
        self.assertEqual(len(order), len(set(order)))
        for name in ("Description", "Priority", "Checked", "Verdict"):
            self.assertIn(name, order)

    def test_default_order_puts_other_fields_after_the_listed_ones_alphabetically(self):
        order = [c.value for c in self.ws[2] if c.value]
        self.assertEqual(order[:14], ["Key", "Type", "Status", "Group", "Sprint", "Epic", "Labels", "Assignee", "Story points",
                                      "Summary", "Description", "Acceptance criteria", "Checked", "Verdict"])
        self.assertEqual(order[14:], ["Components", "Created", "Priority", "Reporter"])

    def test_an_extra_field_named_like_a_core_column_is_kept_separately(self):
        story = Story.from_dict(dict(key="X-1", status="To Do", extra={"Status": "Backlog-status-from-jira"}))
        wb, _ = build([story])
        ws = wb[RAW]
        cols = headers(ws)
        self.assertEqual(ws.cell(row=3, column=cols["Status (Jira)"]).value, "Backlog-status-from-jira")
        self.assertEqual(ws.cell(row=3, column=cols["Status"]).value, "To Do")

    def test_weak_cells_are_shaded_here_too(self):
        row = find_row(self.ws, "DEMO-2")
        self.assertEqual(fill(self.ws.cell(row=row, column=self.cols["Description"])), "FFD966")


class SafetyTests(unittest.TestCase):
    def test_text_that_looks_like_a_formula_stays_text(self):
        story = make_story(key="F-1", summary="=HYPERLINK(\"http://example.com\",\"click\")", description="=1+1")
        wb, _ = build([story])
        for name in (FINDINGS, RAW):
            ws = wb[name]
            cell = ws.cell(row=3, column=headers(ws)["Summary"])
            self.assertEqual(cell.data_type, "s", name)
            self.assertTrue(cell.value.startswith("=HYPERLINK"))

    def test_control_characters_are_removed(self):
        story = make_story(key="C-1", description="As a dev\x00, I want\x07 a thing, so that it works.")
        wb, _ = build([story])
        value = wb[RAW].cell(row=3, column=headers(wb[RAW])["Description"]).value
        self.assertEqual(value, "As a dev, I want a thing, so that it works.")

    def test_text_over_the_excel_limit_is_cut(self):
        story = make_story(key="B-1", description="x" * 40000)
        wb, _ = build([story])
        value = wb[RAW].cell(row=3, column=headers(wb[RAW])["Description"]).value
        self.assertLess(len(value), 32767)
        self.assertIn("[cut:", value)

    def test_key_links_only_when_a_jira_address_is_set(self):
        wb, _ = build()
        self.assertIsNone(wb[FINDINGS]["A3"].hyperlink)
        rules = rules_with(lambda d: d["workbook"].update(jira_base_url="https://jira.example.com/"))
        wb, _ = build(rules=rules)
        self.assertEqual(wb[FINDINGS]["A3"].hyperlink.target, "https://jira.example.com/browse/DEMO-1")
        self.assertEqual(wb[RAW]["A3"].hyperlink.target, "https://jira.example.com/browse/DEMO-1")

    def test_empty_snapshot_still_builds(self):
        wb, _ = build([])
        self.assertEqual(wb.sheetnames, [TOC, SUMMARY, FINDINGS, SUGGESTIONS, CHANGES, EPICS, DUPLICATES, THEMES, RAW, RULES])

    def test_rules_in_effect_lists_the_settings(self):
        wb, _ = build()
        ws = wb[RULES]
        values = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value for r in range(3, ws.max_row + 1)}
        self.assertEqual(values["rules_version"], "1")
        self.assertEqual(values["fields.description.min_chars"], "21")
        self.assertEqual(values["sizing.work_patterns[1].name"], "Encrypt an existing database")
        self.assertIn("encrypt database", values["sizing.work_patterns[1].words"])

    def test_same_input_gives_the_same_workbook(self):
        def snapshot(wb):
            return [[[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets]
        self.assertEqual(snapshot(build()[0]), snapshot(build()[0]))


def build_program(edit=None):
    """The made-up program fixture: epics, duplicates, themes and stories waiting to be uploaded."""
    from datetime import date
    rules = rules_with(edit)
    data = load_data(ROOT / "fixtures" / "program.json")
    summary = check_all(data.stories, rules, data.epics, today=date(2026, 11, 25))
    suggestions = suggest_all(summary.results, rules, load_context(ROOT / "context"), summary.analysis)
    return build_workbook(summary, data.stories, suggestions, rules, None, generated=GENERATED), summary, suggestions, rules


class ProgramWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.wb, self.summary, self.suggestions, self.rules = build_program()

    def test_the_summary_has_a_by_epic_table_made_of_formulas_with_no_epic_last(self):
        ws = self.wb[SUMMARY]
        start = find_row(ws, "Epic")
        keys = []
        row = start + 1
        while ws.cell(row=row, column=1).value:
            keys.append(ws.cell(row=row, column=1).value)
            row += 1
        self.assertEqual(keys, ["EPIC-1", "EPIC-2", "EPIC-3", "EPIC-4", "EPIC-5", "No epic"])
        self.assertTrue(ws.cell(row=start + 1, column=2).value.startswith("=COUNTIFS('Findings'!$"))
        self.assertIn("$A", ws.cell(row=start + 1, column=2).value)
        # the epic name sits after the counts
        name_col = 2 + len(MEASURES) + 5
        self.assertEqual(ws.cell(row=start, column=name_col).value, "Epic name")
        self.assertEqual(ws.cell(row=start + 1, column=name_col).value, "Terraform migration")

    def test_the_findings_tab_has_an_epic_helper_column(self):
        ws = self.wb[FINDINGS]
        cols = headers(ws)
        values = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=cols["Epic key (used by Summary)"]).value for r in range(3, ws.max_row + 1)}
        self.assertEqual(values["P-3"], "No epic")
        self.assertEqual(values["P-1"], "EPIC-1")

    def test_the_changes_tab(self):
        ws = self.wb[CHANGES]
        cols = headers(ws)
        self.assertEqual(list(cols), ["Key", "Group", "Field", "Kind", "Current", "Suggested", "Reason", "Done?"])
        rows = [{h: ws.cell(row=r, column=c).value for h, c in cols.items()} for r in range(3, ws.max_row + 1)]
        epic = next(r for r in rows if r["Key"] == "P-3" and r["Field"] == "Epic")
        self.assertEqual((epic["Group"], epic["Kind"], epic["Suggested"], epic["Done?"]), ("Backlog", "update", "EPIC-1", None))
        theme = next(r for r in rows if r["Key"] == "P-3" and r["Field"] == "Summary")
        self.assertEqual(theme["Suggested"], "Terraform: Add state backend")
        self.assertEqual(fill(ws.cell(row=3, column=cols["Done?"])), "DDEBF7")
        validation = ws.data_validations.dataValidation[0]
        self.assertEqual(validation.formula1, '"Y,N"')

    def test_the_changes_tab_matches_the_change_list(self):
        from refiner.changes import build_changes
        expected = build_changes(self.summary, self.suggestions, self.rules)
        self.assertEqual(self.wb[CHANGES].max_row, 2 + len(expected))

    def test_the_epics_tab(self):
        ws = self.wb[EPICS]
        keys = [ws.cell(row=r, column=1).value for r in range(3, 10)]
        self.assertEqual(keys[:6], ["EPIC-1", "EPIC-2", "EPIC-3", "EPIC-4", "EPIC-5", "No epic"])      # current and future first
        flags = [ws.cell(row=r, column=6).value for r in range(3, 8)]
        self.assertEqual(flags, ["Yes", "Yes", "Yes", "No", "No"])
        self.assertTrue(ws.cell(row=3, column=7).value.startswith("=COUNTIFS('Findings'!$"))
        self.assertEqual(ws.cell(row=3, column=4).value, "2026-09-01")

    def test_the_epics_tab_lists_stories_that_need_an_epic_beside_the_epic_list(self):
        ws = self.wb[EPICS]
        left = 9                                                     # its own columns, to the right of the epic list
        self.assertEqual(ws.cell(row=1, column=left).value, "Stories that need an epic")
        self.assertEqual([ws.cell(row=2, column=left + i).value for i in range(4)], ["Story", "Summary", "Epic now", "Suggestion"])
        rows, row = {}, 3
        while ws.cell(row=row, column=left).value:
            rows[ws.cell(row=row, column=left).value] = [ws.cell(row=row, column=left + c).value for c in range(1, 4)]
            row += 1
        self.assertEqual(set(rows), {"NEW-3", "P-3", "P-5", "P-8", "P-9", "P-10", "P-11", "P-12"})
        self.assertIn("EPIC-1 Terraform migration (50%)", rows["P-3"][2])
        self.assertIn('Create an epic "Credentials"', rows["P-10"][2])
        self.assertEqual(rows["P-8"][1], "EPIC-4")
        self.assertIn("No existing epic fits well", rows["P-8"][2])
        self.assertGreaterEqual(ws.column_dimensions["L"].width, 40)          # the suggestion column is wide enough to read

    def test_new_epic_ideas_are_listed(self):
        ws = self.wb[EPICS]
        row = find_row(ws, "Ideas for new epics (stories that share a word and fit no current epic)", column=9) + 2
        self.assertEqual([ws.cell(row=row, column=9).value, ws.cell(row=row, column=10).value], ["Credentials", "P-10, P-11, P-12"])

    def test_the_duplicates_tab(self):
        ws = self.wb[DUPLICATES]
        cols = headers(ws)
        rows = [{h: ws.cell(row=r, column=c).value for h, c in cols.items()} for r in range(3, ws.max_row + 1)]
        first = rows[0]
        self.assertEqual((first["Kind"], first["Alike"]), ("Possible duplicate", 1.0))
        self.assertEqual(ws.cell(row=3, column=cols["Alike"]).number_format, "0%")
        waiting = next(r for r in rows if {r["Story A"], r["Story B"]} == {"NEW-1", "P-1"})
        self.assertIn("NEW-1 is not in Jira yet", waiting["Note"])
        related = next(r for r in rows if r["Kind"] == "Related")
        self.assertIn("Consider grouping", related["Note"])
        both_in_jira = next(r for r in rows if {r["Story A"], r["Story B"]} == {"P-5", "P-6"})
        self.assertEqual(both_in_jira["Note"], "Close or merge one of them.")

    def test_the_themes_tab(self):
        ws = self.wb[THEMES]
        cols = headers(ws)
        row = next(r for r in range(3, ws.max_row + 1) if ws.cell(row=r, column=1).value == "Terraform")
        value = lambda name: ws.cell(row=row, column=cols[name]).value                    # noqa: E731
        self.assertEqual((value("Where from"), value("Titles"), value("Start with it"), value("Consistent?")),
                         ("Listed in the rules file", 6, 5, "No"))
        self.assertEqual(value("Mention it but do not start with it"), "P-3: Add Terraform state backend")
        self.assertEqual(value("Suggested titles (listed themes only)"), "P-3: Terraform: Add state backend")

    def test_counted_themes_are_listed_without_suggested_titles(self):
        ws = self.wb[THEMES]
        cols = headers(ws)
        for row in range(3, ws.max_row + 1):
            if ws.cell(row=row, column=cols["Where from"]).value == "Found by counting":
                self.assertIn(ws.cell(row=row, column=cols["Suggested titles (listed themes only)"]).value, (None, ""))

    def test_waiting_stories_never_get_jira_links(self):
        wb, _, _, _ = build_program(lambda d: d["workbook"].update(jira_base_url="https://jira.example.com"))
        for name in (FINDINGS, RAW, CHANGES):
            ws = wb[name]
            for row in range(3, ws.max_row + 1):
                cell = ws.cell(row=row, column=1)
                if str(cell.value).startswith("NEW-"):
                    self.assertIsNone(cell.hyperlink, f"{name} {cell.value}")
                elif str(cell.value).startswith("P-"):
                    self.assertEqual(cell.hyperlink.target, f"https://jira.example.com/browse/{cell.value}", name)

    def test_the_contents_tab_lists_every_tab(self):
        ws = self.wb[TOC]
        for name in (CHANGES, EPICS, DUPLICATES, THEMES):
            self.assertTrue(ws.cell(row=find_row(ws, name), column=2).value)

    def test_the_tabs_for_no_problems_say_so(self):
        wb, _ = build([make_story(key="G-1", epic="E-1")])
        self.assertIn("No changes are suggested.", wb[CHANGES]["A3"].value)
        self.assertIn("No duplicate or related stories were found.", wb[DUPLICATES]["A3"].value)
        self.assertIn("No themes were found.", wb[THEMES]["A3"].value)


class CliWorkbookTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        return main(list(argv), out=out), out.getvalue()

    def test_workbook_command_writes_a_file_that_opens(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "report.xlsx"
            code, text = self.run_cli("workbook", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH),
                                      "--context", str(ROOT / "context"), "--out", str(target), "--generated", GENERATED)
            self.assertEqual(code, 0)
            self.assertIn("18 stories checked, 13 with suggestions, 20 in the raw data tab", text)
            self.assertEqual(load_workbook(target).sheetnames[0], TOC)

    def test_unwritable_path_is_a_clean_error(self):
        code, text = self.run_cli("workbook", "--snapshot", str(SNAPSHOT_PATH), "--rules", str(RULES_PATH),
                                  "--context", str(ROOT / "context"), "--out", "/no/such/folder/report.xlsx")
        self.assertEqual(code, 2)
        self.assertIn("Cannot write the workbook", text)


if __name__ == "__main__":
    unittest.main()
