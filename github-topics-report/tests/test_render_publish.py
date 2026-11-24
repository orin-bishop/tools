import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import helpers
import classify
import publish_confluence
import render
import send_email

NS_WRAP = '<root xmlns:ac="http://atlassian.com/ac" xmlns:ri="http://atlassian.com/ri">{}</root>'


def build_results(extra_repos=()):
    settings, teams = helpers.write_config()
    inv = helpers.sample_inventory()
    inv["repos"].extend(extra_repos)
    return classify.build_results(settings, teams, inv, helpers.sample_enrichment(), helpers.NOW)


class RenderTests(unittest.TestCase):
    def test_confluence_is_well_formed_and_escapes_markup(self):
        evil = helpers.make_repo("pet-evil", desc='<script>alert(1)</script> & "quotes" ]]> tail')
        results = build_results([evil])
        page = render.confluence_page(results, classify.registry_suggestions(results) + "\n# ]]> end", "T")
        ET.fromstring(NS_WRAP.format(page))          # raises if not well-formed XML
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("acme/pet-tools", page)
        self.assertIn("Do not edit this page", page)

    def test_confluence_sections_present(self):
        page = render.confluence_page(build_results(), "yaml: here", "T")
        for text in ["In registry, missing the <code>pet</code> topic", "not in registry",
                     "Registry entries not found", "Untagged repos to consider", "Suggested registry changes",
                     "Low-confidence candidates", "acme/gone-repo"]:
            self.assertIn(text, page)

    def test_email_is_capped_and_links_to_report(self):
        many = [helpers.make_repo(f"pet-x{i}") for i in range(30)]
        with mock.patch.dict(os.environ, {"CONFLUENCE_PAGE_URL": "https://wiki/x", "EMAIL_TEST_MODE": "true"}):
            body = render.email_body(build_results(many), "Report", limit=5)
        self.assertIn("TEST SEND", body)
        self.assertIn("https://wiki/x", body)
        self.assertIn("more in the full report", body)
        ET.fromstring(body.replace("&nbsp;", " "))   # email HTML is XHTML-clean too

    def test_email_subject(self):
        results = build_results()
        with mock.patch.dict(os.environ, {"EMAIL_SUBJECT_PREFIX": "[TEST] "}):
            subject = render.email_subject(results)
        self.assertTrue(subject.startswith("[TEST] GitHub topics report 2026-09-29: "))
        self.assertIn("need attention", subject)
        results["total_actions"] = 0
        self.assertTrue(render.email_subject(results).endswith("no action needed"))


class EndToEndTests(unittest.TestCase):
    def test_cli_stages_over_fixtures(self):
        out = tempfile.mkdtemp()
        cfg = Path(out) / "teams.yml"
        cfg.write_text(helpers.CONFIG_YAML)
        with mock.patch.dict(os.environ, {"OUT_DIR": out}):
            Path(out, "inventory.json").write_text(json.dumps(helpers.sample_inventory()))
            Path(out, "enrichment.json").write_text(json.dumps(helpers.sample_enrichment()))
            self.assertEqual(classify.main(["--config", str(cfg)]), 0)
            self.assertEqual(render.main(), 0)
        for name in ["results.json", "needs_action.txt", "confluence.html", "email.html", "email_subject.txt",
                     "registry_suggestions.yml", "candidates.csv", "pet_repos.csv", "viz_repos.csv"]:
            self.assertTrue(Path(out, name).exists(), name)
        ET.fromstring(NS_WRAP.format(Path(out, "confluence.html").read_text()))


class PublishTests(unittest.TestCase):
    def test_bumps_version_and_puts_storage_body(self):
        out = tempfile.mkdtemp()
        Path(out, "confluence.html").write_text("<p>hi</p>")
        env = {"CONFLUENCE_BASE_URL": "https://x.atlassian.net/wiki/", "CONFLUENCE_PAGE_ID": "123",
               "CONFLUENCE_API_TOKEN": "tok", "CONFLUENCE_EMAIL": "me@x.com",
               "REPORT_HTML": str(Path(out, "confluence.html")), "OUT_DIR": out}
        calls = []

        def fake_call(method, url, headers, body=None):
            calls.append((method, url, headers, body))
            if method == "GET":
                return {"type": "page", "title": "Old title", "version": {"number": 7}}
            return {"version": {"number": 8}, "_links": {"base": "https://x.atlassian.net/wiki", "webui": "/spaces/A/pages/123"}}

        with mock.patch.dict(os.environ, env), mock.patch.object(publish_confluence, "call", fake_call):
            self.assertEqual(publish_confluence.main(), 0)
        put = calls[1]
        self.assertEqual(put[0], "PUT")
        self.assertEqual(put[1], "https://x.atlassian.net/wiki/rest/api/content/123")
        self.assertEqual(put[3]["version"]["number"], 8)
        self.assertEqual(put[3]["title"], "Old title")
        self.assertEqual(put[3]["body"]["storage"], {"value": "<p>hi</p>", "representation": "storage"})
        self.assertTrue(put[2]["Authorization"].startswith("Basic "))
        self.assertEqual(Path(out, "confluence_url.txt").read_text(), "https://x.atlassian.net/wiki/spaces/A/pages/123")

    def test_bearer_auth_when_no_email(self):
        with mock.patch.dict(os.environ, {"CONFLUENCE_API_TOKEN": "pat"}, clear=True):
            self.assertEqual(publish_confluence.auth_headers()["Authorization"], "Bearer pat")


class EmailTests(unittest.TestCase):
    def test_build_message_is_multipart_with_text_fallback(self):
        msg = send_email.build_message("<h2>Title</h2><p>Body &amp; more</p>", "Subj", "a@x.com", ["b@x.com", "c@x.com"])
        self.assertEqual(msg["To"], "b@x.com, c@x.com")
        self.assertEqual(msg.get_body(("plain",)).get_content().strip().splitlines()[0], "Title")
        self.assertIn("<h2>Title</h2>", msg.get_body(("html",)).get_content())

    def test_main_sends_via_smtp(self):
        out = tempfile.mkdtemp()
        Path(out, "email.html").write_text("<p>x</p>")
        Path(out, "email_subject.txt").write_text("Hello\n")
        env = {"OUT_DIR": out, "EMAIL_RECIPIENTS": "a@x.com, b@x.com", "EMAIL_FROM": "me@x.com",
               "SMTP_HOST": "smtp.x.com", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}
        with mock.patch.dict(os.environ, env), mock.patch("smtplib.SMTP") as smtp_cls:
            self.assertEqual(send_email.main(), 0)
        smtp = smtp_cls.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("u", "p")
        self.assertEqual(smtp.send_message.call_args[0][0]["Subject"], "Hello")


if __name__ == "__main__":
    unittest.main()
