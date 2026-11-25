"""Regenerates BOTH Harness step templates from maintainer/body.sh (the single source of truth for the script).

    python build_yaml.py           ->  writes ../templates/workbook-publish-template-{cd-custom,ci-build}.yaml
    python verify_templates.py     ->  then run the regression checks

Edit the script in body.sh, and the header documentation / input list below. Never hand-edit the script inside
the two YAMLs separately: they must stay identical (verify_templates.py checks that).
To release a new version: change VER here AND the VERSION string at the top of body.sh (the build refuses if they differ).
"""
import re
from pathlib import Path
HERE = Path(__file__).resolve().parent
OUTDIR = HERE.parent / "templates"
body = (HERE / "body.sh").read_text().rstrip("\n")
VER = "1.1.0"
_m = re.search(r'VERSION = os\.environ\.get, "([^"]+)"', body)
if not _m or _m.group(1) != VER:
    raise SystemExit("VERSION in body.sh (%s) must equal VER in build_yaml.py (%s)" % (_m and _m.group(1), VER))
def ind(text, n): return "\n".join((" " * n + l) if l.strip() else "" for l in text.split("\n"))

HEAD = '''# ============================================================================
# HARNESS STEP TEMPLATE: Workbook Publish  ({scope})   v{ver}
# ============================================================================
# ONE step, no other files. Turns files your pipeline already produced into one
# Excel workbook with:
#   - an Overview tab        what the report is, when/how it was generated, how to use it
#   - a Table of Contents    every tab, clickable, with a short explanation
#   - one tab per input      tab name = file name without the extension
# It does not fetch or transform anything. Do that in the steps before it.
#
# INPUTS
#   required   WB_TITLE    workbook title
#              WB_PURPOSE  why this report exists
#              WB_FILES    one per line:  path-or-s3-uri | what the tab is used for
#                          "manual: Tab name | description" lists a tab you will add by hand
#                          lines starting with # are ignored
#   optional   WB_NOTES    notes for the Overview. Plain text or HTML (flattened to text),
#                          or "@path/to/notes.html" to read them from a file
#              WB_OUTPUT   output path, must end in .xlsx          (default workbook.xlsx)
#              WB_TZ       time zone for the timestamp, e.g. America/Chicago   (default UTC)
#              WB_OPTIONS  the "style switch". Empty = all defaults below. See next section.
# OUTPUT
#   WORKBOOK_PATH  absolute path of the .xlsx, for the next step
#
# FILE TYPES (WB_FILES)
#   .csv .tsv   one tab. Numbers and dates become real Excel values; leading-zero
#               codes (02134), very long ids and text starting with "=" stay text.
#   .html .htm  every <table> becomes a tab (file, file_2, ...). A page with no
#               table becomes one tab of its text, one line per row.
#   .txt        tab-delimited -> columns; otherwise one tab of lines.
#
# EVERY DATA TAB GETS (defaults, no input needed)
#   dark-blue heading row with bold white text, heading row frozen, a filter/sort
#   arrow on every column, sensible column widths, real dates and numbers.
#
# WB_OPTIONS  (optional. One setting per line; "#" starts a comment)
#   Defaults shown. Only list what you want to change:
#     font = Arial
#     font_size = 10
#     header_fill = 1F3864       # heading row background (also the Overview/Contents accent)
#     header_font = FFFFFF       # heading row text colour
#     header_bold = on
#     freeze_rows = 1            # 0 = don't freeze
#     freeze_cols = 0            # 1 = also keep the first column in view
#     filter = on                # sort/filter arrow on every column
#     max_col_width = 60
#     date_format = yyyy-mm-dd
#   Highlight cells by value, per tab (or * for every tab that has the column):
#     highlight: tab | column | operator | value | colour
#       operator  >  <  >=  <=  =  !=  contains          (column = heading name or letter)
#       colour    red yellow green blue orange gray, or a hex code like FFC7CE
#   Examples to paste:
#     highlight: orders    | amount | >        | 1000 | green
#     highlight: orders    | amount | <        | 100  | red
#     highlight: orders    | status | =        | Late | yellow
#     highlight: *         | status | contains | fail | FFC7CE
#   Numbers compare as numbers; blanks and text are never highlighted by a number rule.
#   Highlights are live Excel conditional formatting, so they follow edits.
#   TIP: keep one "house style" in a pipeline variable and pass it to every
#   workbook:  WB_OPTIONS = <+pipeline.variables.WB_STYLE>
#   To skip the prompt entirely, set WB_OPTIONS (and the other optional inputs)
#   as fixed values in the calling pipeline instead of runtime inputs.
#
# GOOD TO KNOW
#   - Needs python3. openpyxl is installed from your package index if missing.
#   - s3:// inputs need the aws CLI and read access where this step runs.
#   - Files must be where this step runs, and so must the next step that uses
#     the workbook ({where}).
#   - Excel's limit is 1,048,575 rows per tab. Bigger? aggregate in an earlier step.
#   - When you bump versionLabel, bump VERSION in the script too (it is printed
#     on the Overview).
#   - Internal use only. Don't publish the workbook to a public location.
#
# USAGE
{usage}
# ============================================================================
'''

NEXT = '''
#
# Hand the file to the next step, e.g. your Send Email template:
#   MAIL_ATTACHMENTS = {ref}'''

USAGE_CD = '''#   - step:
#       name: Publish workbook
#       identifier: publish_workbook
#       template:
#         templateRef: account.Workbook_Publish_CD   # add org./project prefix to match where you save it
#         versionLabel: {ver}
#         templateInputs:
#           type: ShellScript
#           spec:
#             environmentVariables:
#               - name: WB_TITLE
#                 type: String
#                 value: Weekly Pipeline Report
#               - name: WB_PURPOSE
#                 type: String
#                 value: Revenue and shipment review for Finance and Ops.
#               - name: WB_FILES
#                 type: String
#                 value: |-
#                   reports/orders.csv | Raw order lines for the period.
#                   reports/shipments.html | Carrier shipment tables from the portal export.
#                   s3://your-bucket/exports/inventory_snapshot.csv | Warehouse inventory snapshot.
#                   manual: Analyst notes | Commentary added by hand after review.
#               - name: WB_OPTIONS          # optional: leave out (or "") for all defaults
#                 type: String
#                 value: |-
#                   highlight: orders | amount | > | 1000 | green
#                   highlight: orders | status | = | Late | yellow'''.format(ver=VER)
USAGE_CI = '''#   - step:
#       name: Publish workbook
#       identifier: publish_workbook
#       template:
#         templateRef: account.Workbook_Publish_CI   # add org./project prefix to match where you save it
#         versionLabel: {ver}
#         templateInputs:
#           type: Run
#           spec:
#             envVariables:
#               WB_TITLE: Weekly Pipeline Report
#               WB_PURPOSE: Revenue and shipment review for Finance and Ops.
#               WB_FILES: |-
#                 reports/orders.csv | Raw order lines for the period.
#                 reports/shipments.html | Carrier shipment tables from the portal export.
#                 s3://your-bucket/exports/inventory_snapshot.csv | Warehouse inventory snapshot.
#                 manual: Analyst notes | Commentary added by hand after review.
#               WB_OPTIONS: |-             # optional: leave out (or "") for all defaults
#                 highlight: orders | amount | > | 1000 | green
#                 highlight: orders | status | = | Late | yellow'''.format(ver=VER)

INPUTS = [("WB_TITLE", "<+input>"), ("WB_PURPOSE", "<+input>"), ("WB_FILES", "<+input>"),
          ("WB_NOTES", '<+input>.default("")'), ("WB_OPTIONS", '<+input>.default("")'),
          ("WB_OUTPUT", '<+input>.default("workbook.xlsx")'), ("WB_TZ", '<+input>.default("UTC")'),
          ("PIPELINE_NAME", "<+pipeline.name>"), ("PIPELINE_BUILD_NUMBER", "<+pipeline.sequenceId>"),
          ("PIPELINE_EXECUTION_URL", "<+pipeline.executionUrl>"), ("TRIGGERED_BY", "<+pipeline.triggeredBy.name>")]

cd = HEAD.format(scope="CD / Custom stages", ver=VER, where="same delegate: use a delegate selector",
                 usage=USAGE_CD + NEXT.format(ref="<+execution.steps.publish_workbook.output.outputVariables.WORKBOOK_PATH>")) + f'''template:
  name: Workbook Publish (CD-Custom)
  identifier: Workbook_Publish_CD
  versionLabel: {VER}
  type: Step
  tags:
    category: reporting
  spec:
    timeout: 10m
    type: ShellScript
    spec:
      shell: Bash
      executionTarget: {{}}
      delegateSelectors: []
      source:
        type: Inline
        spec:
          script: |-
{ind(body, 12)}
      environmentVariables:
''' + "".join(f"        - name: {k}\n          type: String\n          value: {v}\n" for k, v in INPUTS) + '''      outputVariables:
        - name: WORKBOOK_PATH
          type: String
          value: WORKBOOK_PATH
'''

ci = HEAD.format(scope="CI Build stage", ver=VER, where="same CI stage workspace",
                 usage=USAGE_CI + NEXT.format(ref="<+steps.publish_workbook.output.outputVariables.WORKBOOK_PATH>")) + f'''template:
  name: Workbook Publish (CI Build)
  identifier: Workbook_Publish_CI
  versionLabel: {VER}
  type: Step
  tags:
    category: reporting
  spec:
    timeout: 10m
    type: Run
    spec:
      shell: Sh
      command: |-
{ind(body, 8)}
      envVariables:
''' + "".join(f"        {k}: {v}\n" for k, v in INPUTS) + '''      outputVariables:
        - name: WORKBOOK_PATH
'''
OUTDIR.mkdir(exist_ok=True)
(OUTDIR / "workbook-publish-template-cd-custom.yaml").write_text(cd)
(OUTDIR / "workbook-publish-template-ci-build.yaml").write_text(ci)
print("built", len(cd.splitlines()), "and", len(ci.splitlines()), "lines")
