#!/usr/bin/env python3
"""Regression check for the workbook-publish Harness step templates (no Harness, no network needed).

    python verify_templates.py [templates_dir]        default: ../templates next to this file
    python verify_templates.py --keep                 also keep the temp folder (generated .xlsx files) to inspect

Needs: PyYAML, openpyxl, bash, and dash or sh.  Exit code 0 = everything passed.
What it proves:  both YAMLs are well formed and carry IDENTICAL script text; the script runs under the
shells Harness uses (CD = bash, CI = POSIX sh); the workbook has the right tabs, frozen headings, filters,
header look, highlight rules, links and value types; bad input fails loudly; and the usage example in each
header comment is valid YAML that actually runs.
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import openpyxl, yaml

HERE = Path(__file__).resolve().parent
KEEP = "--keep" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
TPL = Path(args[0]) if args else HERE.parent / "templates"
FILES = {"CD": TPL / "workbook-publish-template-cd-custom.yaml", "CI": TPL / "workbook-publish-template-ci-build.yaml"}
SHELL = {"CD": "bash", "CI": shutil.which("dash") and "dash" or "sh"}      # CI 'Run' step uses shell: Sh
results = []

def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))
    if not ok:
        print("FAIL  %s  %s" % (name, detail))

# ---- load + structure ---------------------------------------------------------------------------------
docs, scripts, inputs = {}, {}, {}
for v, path in FILES.items():
    t = yaml.safe_load(path.read_text())["template"]
    docs[v], sp = t, t["spec"]["spec"]
    scripts[v] = sp["source"]["spec"]["script"] if v == "CD" else sp["command"]
    inputs[v] = ({e["name"]: e["value"] for e in sp["environmentVariables"]} if v == "CD" else dict(sp["envVariables"]))
    check(f"{v}: template type/step", t["type"] == "Step" and t["identifier"].startswith("Workbook_Publish_"))
    check(f"{v}: stage-specific step type", t["spec"]["type"] == ("ShellScript" if v == "CD" else "Run"))
    check(f"{v}: shell", sp["shell"] == ("Bash" if v == "CD" else "Sh"))
    out = sp["outputVariables"]
    check(f"{v}: declares WORKBOOK_PATH output", [o["name"] for o in out] == ["WORKBOOK_PATH"] and (v == "CI" or out[0]["value"] == "WORKBOOK_PATH"))
    check(f"{v}: script has no Harness expression '<+' (Harness would try to resolve it)", "<+" not in scripts[v])
    check(f"{v}: script has no trailing whitespace/tabs", not re.search(r"[ \t]+$|\t", scripts[v], re.M))
check("CD and CI scripts are identical", scripts["CD"] == scripts["CI"])
check("CD and CI have the same inputs and defaults", inputs["CD"] == inputs["CI"], str(set(inputs["CD"]) ^ set(inputs["CI"])))
check("both versionLabels equal", docs["CD"]["versionLabel"] == docs["CI"]["versionLabel"])
m = re.search(r'VERSION = os\.environ\.get, "([^"]+)"', scripts["CD"])
check("VERSION in script == versionLabel", m and m.group(1) == str(docs["CD"]["versionLabel"]), f"script={m and m.group(1)} label={docs['CD']['versionLabel']}")
for name in ("WB_TITLE", "WB_PURPOSE", "WB_FILES"):
    check(f"input {name} is a required runtime input", inputs["CD"].get(name) == "<+input>")
for name in ("WB_NOTES", "WB_OPTIONS", "WB_OUTPUT", "WB_TZ"):
    check(f"input {name} is optional (has a default)", ".default(" in inputs["CD"].get(name, ""))
body = HERE / "body.sh"
if body.exists():
    check("script == maintainer/body.sh (run build_yaml.py if not)", scripts["CD"] == body.read_text().rstrip("\n"))

# ---- workspace with fixtures + a fake aws CLI ------------------------------------------------------------
W = Path(tempfile.mkdtemp(prefix="wbpub_"))
(W / "in").mkdir(); (W / "reports").mkdir(); (W / "out").mkdir(); (W / "fakebin").mkdir(); (W / "bucket/exports").mkdir(parents=True)
ORDERS = ("order_id,customer_id,region,order_date,amount,status,note\n1001,C-01,East,2026-10-01,1250.50,On time,\n"
          "1002,C-02,West,2026-10-03,310.00,Late,rush\n1003,C-01,East,2026-10-07,89.99,On time,\n"
          '1004,C-03,South,2026-10-09,4020.00,Very late,"=SUM(1,1) literal, text"\n1005,C-02,West,2026-10-12,,On time,missing amount\n')
SHIP = ('<html><head><style>td{color:red}</style><script>var x="<table>";</script></head><body><h1>Shipments</h1>'
        "<table><tr><th>carrier</th><th>qty</th><th>status</th></tr><tr><td>Acme &amp; Co</td><td>1,200</td><td>On time</td></tr>"
        "<tr><td>Birch</td><td>45</td><td>Late shipment</td></tr><tr><td>Cobalt<br>Freight</td><td>0</td><td>On time</td></tr></table>"
        "<p>between</p><table><tr><th>carrier</th><th>phone</th></tr><tr><td>Acme</td><td>02134</td></tr></table></body></html>")
for p, text in {"in/orders.csv": ORDERS, "reports/orders.csv": ORDERS, "in/shipments.html": SHIP, "reports/shipments.html": SHIP,
                "in/run_log.html": "<html><body><h2>Run log</h2><p>Step one finished.</p><p>Step two &amp; verified.</p><ul><li>no errors</li></ul></body></html>",
                "in/readme.txt": "Line one\nLine two\n\nLine three\n", "in/metrics.txt": "metric\tvalue\nlatency_ms\t120\nerrors\t3\n",
                "in/notes.html": '<h3>Read me first</h3><p>See <a href="https://wiki.example/x">the wiki</a>.</p><ul><li>USD</li></ul>',
                "bucket/exports/inventory_snapshot.csv": "sku,on_hand\nA-1,40\nB-2,12\n", "in/data.xlsx": "x", "in/overview.csv": "a\n1\n",
                "in/Table of Contents.csv": "a\n1\n"}.items():
    (W / p).write_text(text)
aws = W / "fakebin/aws"
aws.write_text('#!/bin/sh\nsrc="$4"; dest="$5"; key="${src#s3://*/}"\n[ -f "$FAKE_BUCKET/$key" ] || { echo NoSuchKey >&2; exit 1; }\ncp "$FAKE_BUCKET/$key" "$dest"\n')
aws.chmod(0o755)
for v in FILES:
    (W / f"{v}.sh").write_text(scripts[v])

BASE_FILES = ("in/orders.csv | Raw order lines.\nin/shipments.html | Carrier tables.\nin/run_log.html | Run log text.\nin/readme.txt | Readme lines.\n"
              "in/metrics.txt | Tab-delimited metrics.\ns3://bkt/exports/inventory_snapshot.csv | Inventory.\nmanual: Analyst notes | Added by hand.")
def run(v, out, **over):
    env = dict(os.environ, PATH=f"{W / 'fakebin'}:{os.environ['PATH']}", FAKE_BUCKET=str(W / "bucket"), PIPELINE_NAME="demo", PIPELINE_BUILD_NUMBER="7",
               TRIGGERED_BY="tester", PIPELINE_EXECUTION_URL="https://harness.example/run/1", WB_TITLE="Weekly Report", WB_PURPOSE="Review.",
               WB_TZ="America/Chicago", WB_NOTES="@in/notes.html", WB_FILES=BASE_FILES, WB_OUTPUT=f"out/{out}.xlsx")
    env.update({k: v2 for k, v2 in over.items() if v2 is not None})
    for k, v2 in over.items():
        if v2 is None:
            env.pop(k, None)
    r = subprocess.run([SHELL[v], str(W / f"{v}.sh")], env=env, cwd=W, capture_output=True, text=True)
    return r, W / "out" / f"{out}.xlsx"

def cf(ws):
    return {r.formula[0] for rules in ws.conditional_formatting._cf_rules.values() for r in rules}
def cells(ws):
    return [[c.value for c in row] for row in ws.iter_rows()]
def flat(ws):
    return [c for row in cells(ws) for c in row if c is not None]

OPTS = """# look
header_fill = 7030A0      # purple
freeze_cols = 1
highlight: orders    | amount    | >        | 1000   | green
highlight: orders    | amount    | <        | 100    | red
highlight: orders    | status    | =        | Late   | yellow
highlight: *         | status    | contains | very   | FFC7CE
highlight: shipments | qty       | =        | 0      | orange
highlight: shipments | status    | contains | late   | red
highlight: orders    | nosuchcol | >        | 5      | green"""
TABS = ["Overview", "Table of Contents", "orders", "shipments", "shipments_2", "run_log", "readme", "metrics", "inventory_snapshot"]

for v in FILES:
    p = f"[{v}] "
    # A) defaults: WB_OPTIONS not set at all
    r, f = run(v, "A", WB_OPTIONS=None)
    check(p + "defaults: exit 0, no warnings", r.returncode == 0 and "WARN" not in r.stdout, r.stdout[-300:] + r.stderr[-300:])
    if not f.exists():
        continue
    wb = openpyxl.load_workbook(f)
    check(p + "defaults: tab order", wb.sheetnames == TABS, str(wb.sheetnames))
    o = wb["orders"]; h = o["A1"]
    check(p + "defaults: heading row frozen (A2)", o.freeze_panes == "A2", str(o.freeze_panes))
    check(p + "defaults: sort/filter on every column", o.auto_filter.ref == "A1:G6", str(o.auto_filter.ref))
    check(p + "defaults: dark-blue heading, bold white Arial", h.fill.fgColor.rgb.endswith("1F3864") and h.font.color.rgb.endswith("FFFFFF") and h.font.b and h.font.name == "Arial")
    check(p + "defaults: numbers/dates are real values, blank stays blank", o["A2"].value == 1001 and o["E2"].value == 1250.5 and hasattr(o["D2"].value, "year") and o["E6"].value is None)
    check(p + "defaults: '=...' text stays text", str(o["G5"].value).startswith("=SUM") and o["G5"].data_type == "s")
    check(p + "defaults: no highlight rules unless asked", not any(cf(wb[n]) for n in wb.sheetnames))
    check(p + "html: 2 tables -> 2 tabs, 1,200 -> 1200, <br> keeps a space, 02134 stays text",
          wb["shipments"]["B2"].value == 1200 and wb["shipments"]["A4"].value == "Cobalt Freight" and wb["shipments_2"]["B2"].value == "02134")
    check(p + "html: table-less page -> text lines", [c[0] for c in cells(wb["run_log"])][:3] == ["text", "Run log", "Step one finished."])
    check(p + "txt rows", [c[0] for c in cells(wb["readme"])] == ["text", "Line one", "Line two", "Line three"] and cells(wb["metrics"])[1] == ["latency_ms", 120])
    check(p + "s3 input fetched (fake aws)", cells(wb["inventory_snapshot"])[1] == ["A-1", 40])
    toc = wb["Table of Contents"]
    links = {c.value: c.hyperlink.location for row in toc.iter_rows() for c in row if c.hyperlink}
    check(p + "toc: every tab is a clickable link", all(links.get(n) == f"'{n}'!A1" for n in TABS[2:]) and links.get("\u2190 Overview") == "'Overview'!A1", str(links))
    tflat = flat(toc)
    check(p + "toc: short explanations, table tags, manual row", "Carrier tables. (table 2 of 2)" in tflat and "Added by hand." in tflat and "Added manually" in tflat)
    ov = wb["Overview"]; oflat = [str(x) for x in flat(ov)]
    check(p + "overview: purpose, pipeline, notes from @file, how-to, link to contents",
          "Review." in oflat and any("run #7" in x for x in oflat) and "Read me first" in oflat and any("stays in view" in x for x in oflat)
          and any(c.hyperlink and c.hyperlink.location == "'Table of Contents'!A1" for row in ov.iter_rows() for c in row))
    check(p + "overview: no highlight section when no rules", "Highlight rules" not in oflat)
    check(p + "metadata: classification banner + generated stamp", "INTERNAL USE ONLY \u2014 Via Logic LLC" in oflat and any("UTC 20" in x for x in oflat))

    # B) options switch on
    r, f = run(v, "B", WB_OPTIONS=OPTS)
    check(p + "options: exit 0; the unmatched rule is warned about", r.returncode == 0 and "matched no tab/column" in r.stdout and "nosuchcol" in r.stdout)
    wb = openpyxl.load_workbook(f)
    o = wb["orders"]
    check(p + "options: header colour + freeze first column", o["A1"].fill.fgColor.rgb.endswith("7030A0") and o.freeze_panes == "B2")
    check(p + "options: orders rules", cf(o) == {"AND(ISNUMBER(E2),E2>1000)", "AND(ISNUMBER(E2),E2<100)", 'AND(ISTEXT(F2),F2="Late")', 'ISNUMBER(SEARCH("very",F2))'}, str(cf(o)))
    check(p + "options: shipments rules ('*' hits only tabs with the column)", cf(wb["shipments"]) == {'ISNUMBER(SEARCH("very",C2))', 'ISNUMBER(SEARCH("late",C2))', "AND(ISNUMBER(B2),B2=0)"} and not cf(wb["metrics"]))
    oflat = [str(x) for x in flat(wb["Overview"])]
    check(p + "options: legend lists matched rules only", "Highlight rules" in oflat and "amount  >  1000" in oflat and not any("nosuchcol" in x for x in oflat))
    r, f = run(v, "C", WB_OPTIONS="freeze_rows = 0\nfilter = off\nheader_bold = off")
    o = openpyxl.load_workbook(f)["orders"]
    check(p + "options: freeze/filter/bold can be switched off", o.freeze_panes is None and o.auto_filter.ref is None and not o["A1"].font.b)
    r, f = run(v, "D", WB_OPTIONS="header_fill = purple\nfreeze_rows = abc\nbogus = 1\nhighlight: orders | amount | ~~ | 5 | green")
    check(p + "options: invalid values warn and fall back to defaults", r.returncode == 0 and r.stdout.count("WARN") == 4, r.stdout)
    r, f = run(v, "E", WB_FILES="in/overview.csv | a\nin/Table of Contents.csv | b")
    check(p + "names that clash with the front tabs are renamed", openpyxl.load_workbook(f).sheetnames == ["Overview", "Table of Contents", "overview_2", "Table of Contents_2"])

    # D) failures must be loud
    for label, over, needle in [("empty file list", {"WB_FILES": ""}, "WB_FILES"), ("missing title", {"WB_TITLE": None}, "WB_TITLE"),
                                ("missing file", {"WB_FILES": "in/nope.csv | x"}, "input file not found"),
                                ("unsupported type", {"WB_FILES": "in/data.xlsx | x"}, "supported inputs"),
                                ("output not .xlsx", {"WB_OUTPUT": "r.txt"}, "must end in .xlsx"),
                                ("s3 fetch fails", {"WB_FILES": "s3://bkt/missing/key.csv | x"}, "could not fetch"),
                                ("only manual entries", {"WB_FILES": "manual: Only | x"}, "no data files"),
                                ("notes file missing", {"WB_NOTES": "@in/nope.html"}, "WB_NOTES file not found")]:
        r, _ = run(v, "F", **over)
        check(p + f"failure: {label}", r.returncode != 0 and needle in (r.stdout + r.stderr), (r.stdout + r.stderr)[-200:])

    # E) the usage example in the header comment must be valid YAML and must run
    lines = FILES[v].read_text().splitlines()
    i = lines.index("# USAGE"); j = next(k for k in range(i + 1, len(lines)) if lines[k].startswith("# Hand the file"))
    block = "\n".join(l[2:] if l.startswith("# ") else l[1:] for l in lines[i + 1:j] if l.strip("# "))
    ti = yaml.safe_load(block)[0]["step"]["template"]["templateInputs"]["spec"]
    ex = {e["name"]: e["value"] for e in ti["environmentVariables"]} if v == "CD" else dict(ti["envVariables"])
    ex.update(WB_OUTPUT="out/G.xlsx", WB_NOTES="")
    r, f = run(v, "G", **ex)
    wb = openpyxl.load_workbook(f) if f.exists() else None
    check(p + "header usage example runs as written (no warnings, 2 rules on orders)", r.returncode == 0 and "WARN" not in r.stdout and wb and len(cf(wb["orders"])) == 2, r.stdout[-200:] + r.stderr[-200:])

    # F) documented defaults + examples can be pasted back as WB_OPTIONS
    a = next(k for k, l in enumerate(lines) if l.startswith('# WB_OPTIONS  (optional'))
    pasted = [l[1:].strip() for l in lines[a + 1:a + 40] if re.match(r"#\s+(font|header_|freeze_|filter|max_col|date_format|highlight:)", l) and "tab | column" not in l]
    r, f = run(v, "H", WB_OPTIONS="\n".join(pasted))
    check(p + f"header option reference pastes back with no warnings ({len(pasted)} lines)", len(pasted) >= 14 and r.returncode == 0 and "WARN" not in r.stdout, r.stdout[-300:])

# ---- shell syntax --------------------------------------------------------------------------------------------
for v, sh in (("CD", "bash"), ("CI", SHELL["CI"])):
    r = subprocess.run([sh, "-n", str(W / f"{v}.sh")], capture_output=True, text=True)
    check(f"[{v}] syntax OK under {sh}", r.returncode == 0, r.stderr)

passed = sum(1 for ok, *_ in results if ok)
print(f"\n{passed}/{len(results)} checks passed" + ("" if passed == len(results) else "  <-- FAILURES ABOVE"))
if KEEP:
    print("kept:", W)
else:
    shutil.rmtree(W, ignore_errors=True)
sys.exit(0 if passed == len(results) else 1)
