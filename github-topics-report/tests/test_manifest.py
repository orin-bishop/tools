import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import helpers
import classify
import manifest
import render
from ghclient import GitHubClient, GitHubError
from reportlib import DEFAULT_SETTINGS, apply_manifest_registry, load_config

NS_WRAP = '<root xmlns:ac="http://atlassian.com/ac" xmlns:ri="http://atlassian.com/ri">{}</root>'


def mf(**overrides):
    return {**DEFAULT_SETTINGS["manifest"], **overrides}


def names(entries):
    return sorted((e["team"], e["full_name"]) for e in entries)


class LayoutTests(unittest.TestCase):
    def extract(self, data, **over):
        return manifest.extract_entries(data, mf(**over), "acme")

    def test_team_to_list_of_strings(self):
        entries, skipped = self.extract({"pet": ["acme/a", "b"], "viz": ["acme/c"], "generated_at": "2026-01-01"})
        self.assertEqual(names(entries), [("pet", "acme/a"), ("pet", "acme/b"), ("viz", "acme/c")])
        self.assertEqual(skipped, ["generated_at"])
        self.assertTrue(all(e["topics"] is None for e in entries))

    def test_team_to_object_with_repos(self):
        entries, _ = self.extract({"pet": {"repos": [{"name": "a", "topics": ["Pet", "go"]}]}})
        self.assertEqual(entries[0]["topics"], ["go", "pet"])
        self.assertEqual(entries[0]["full_name"], "acme/a")

    def test_team_to_repo_map(self):
        entries, _ = self.extract({"pet": {"a": {"topics": ["pet"]}, "b": {}}})
        self.assertEqual(names(entries), [("pet", "acme/a"), ("pet", "acme/b")])
        self.assertEqual(entries[0]["topics"], ["pet"])
        self.assertIsNone(entries[1]["topics"])

    def test_list_of_team_objects(self):
        entries, _ = self.extract([{"name": "Pet", "repositories": ["a", "acme/b"]}, {"team": "viz", "repos": ["c"]}])
        self.assertEqual(names(entries), [("pet", "acme/a"), ("pet", "acme/b"), ("viz", "acme/c")])

    def test_flat_list_with_team_field(self):
        entries, _ = self.extract([{"full_name": "acme/a", "team": "pet", "topics": "pet, go"},
                                   {"full_name": "acme/b", "team": {"name": "viz"}}])
        self.assertEqual(names(entries), [("pet", "acme/a"), ("viz", "acme/b")])
        self.assertEqual(entries[0]["topics"], ["go", "pet"])

    def test_flat_object_with_repos_key(self):
        entries, _ = self.extract({"repos": [{"name": "a", "team": "pet"}]})
        self.assertEqual(names(entries), [("pet", "acme/a")])

    def test_nested_under_teams_and_custom_path(self):
        self.assertEqual(len(self.extract({"teams": {"pet": ["a"]}, "topics": ["x"]})[0]), 1)
        entries, _ = self.extract({"data": {"groups": {"pet": ["a"]}}}, teams_path="data.groups")
        self.assertEqual(names(entries), [("pet", "acme/a")])
        with self.assertRaises(manifest.ManifestError):
            self.extract({"x": 1}, teams_path="data.groups")

    def test_repo_name_forms(self):
        for raw, want in [("https://github.com/Acme/Thing", "acme/thing"),
                          ("git@github.com:acme/thing.git", "acme/thing"),
                          ("https://ghe.corp/acme/thing.git", "acme/thing"), ("Thing", "acme/thing")]:
            self.assertEqual(manifest.repo_from_text(raw, "acme"), want)
        entry = manifest.parse_entry({"name": "thing", "owner": {"login": "Other"}}, "t", mf(), "acme")
        self.assertEqual(entry["full_name"], "other/thing")
        entry = manifest.parse_entry({"url": "https://github.com/o/r", "name": "r"}, "t", mf(), "acme")
        self.assertEqual(entry["full_name"], "o/r")   # full URL wins over bare name

    def test_custom_keys(self):
        data = [{"slug": "pet", "members": [{"id": "acme/a", "labels": ["pet"]}]}]
        entries, _ = self.extract(data, team_name_key="slug", repos_key="members", name_key="id", topics_key="labels")
        self.assertEqual((entries[0]["team"], entries[0]["full_name"], entries[0]["topics"]),
                         ("pet", "acme/a", ["pet"]))

    def test_vocabulary_detection(self):
        self.assertEqual(manifest.extract_vocabulary({"topics": ["B", "a"], "teams": {}}, mf()), ["a", "b"])
        self.assertEqual(manifest.extract_vocabulary({"topic_list": {"x": "desc", "y": "d"}}, mf()), ["x", "y"])
        self.assertEqual(manifest.extract_vocabulary({"v": {"all": [{"name": "z"}]}}, mf(topic_list_path="v.all")), ["z"])
        self.assertIsNone(manifest.extract_vocabulary({"pet": ["a"]}, mf()))
        self.assertIsNone(manifest.extract_vocabulary([{"team": "x"}], mf()))


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings, cls.teams = helpers.write_config(helpers.config_text())
        cls.built = manifest.build_manifest(helpers.sample_manifest_json(), "src", cls.settings, cls.teams,
                                            helpers.sample_inventory())
        cls.cmp = cls.built["compare"]

    def test_topic_drift(self):
        drift = {d["full_name"]: d for d in self.cmp["topic_drift"]}
        self.assertEqual(set(drift), {"acme/pet-legacy", "acme/viz-dash", "acme/shared-lib", "acme/pets-service"})
        # 'pet' is the team topic: already reported as "registry repo missing the topic", so not repeated here
        self.assertEqual(drift["acme/pet-legacy"]["manifest_only"], ["legacy"])
        self.assertEqual(drift["acme/viz-dash"]["manifest_only"], ["d3"])
        self.assertEqual(drift["acme/shared-lib"]["manifest_only"], ["go", "platform"])   # platform not a report team
        self.assertEqual(drift["acme/pets-service"]["github_only"], ["pets"])
        self.assertNotIn("acme/pet-api", drift)

    def test_not_found_vs_outside_orgs(self):
        self.assertEqual([e["full_name"] for e in self.cmp["not_on_github"]], ["acme/pet-gone"])
        self.assertEqual([e["full_name"] for e in self.cmp["outside_scanned_orgs"]], ["outside-org/their-repo"])

    def test_vocabulary(self):
        v = self.cmp["vocabulary"]
        self.assertTrue(v["present"])
        self.assertEqual(v["github_not_in_vocab"], ["pets"])
        self.assertEqual(v["vocab_unused"], ["go", "legacy", "platform"])

    def test_registry_merge_and_unmapped(self):
        self.assertEqual(self.built["teams"]["pet"], ["acme/pet-api", "acme/pet-gone", "acme/pet-legacy"])
        self.assertEqual(self.built["teams"]["viz"], ["acme/viz-dash"])
        self.assertNotIn("outside-org/their-repo", self.built["teams"]["pet"])
        self.assertEqual(self.built["unmapped_teams"], ["platform"])
        self.assertEqual(self.built["stats"], {"repos": 7, "teams": 3, "with_topic_data": 6})

    def test_team_map(self):
        settings, teams = helpers.write_config(
            helpers.config_text(manifest_extra="    team_map: {platform: pet}\n"))
        built = manifest.build_manifest(helpers.sample_manifest_json(), "src", settings, teams,
                                        helpers.sample_inventory())
        self.assertIn("acme/shared-lib", built["teams"]["pet"])
        self.assertEqual(built["unmapped_teams"], [])

    def test_multi_team_detected(self):
        data = {"pet": ["a"], "viz": ["a"]}
        built = manifest.build_manifest(data, "src", self.settings, self.teams,
                                        {"repos": [helpers.make_repo("a")]})
        self.assertEqual(built["compare"]["multi_team"], [{"repo": "acme/a", "teams": ["pet", "viz"]}])

    def test_zero_entries_fails_loudly(self):
        with self.assertRaises(manifest.ManifestError) as ctx:
            manifest.build_manifest({"hello": "world"}, "src", self.settings, self.teams, {"repos": []})
        self.assertIn("parsed 0 repos", str(ctx.exception))

    def test_manifest_repos_flow_into_classify(self):
        settings, teams = helpers.write_config(helpers.config_text())
        apply_manifest_registry(teams, self.built)
        res = classify.build_results(settings, teams, helpers.sample_inventory(), helpers.sample_enrichment(),
                                     helpers.NOW, manifest=self.built)
        pet = res["teams"]["pet"]
        self.assertIn("acme/pet-gone", pet["registry_not_found"])
        self.assertEqual([r["full_name"] for r in pet["unregistered"]], ["acme/pet-web"])
        info = res["manifest"]
        # 4 drifts + 1 vocabulary addition; not_on_github for pet is counted under the team instead
        self.assertEqual(info["actions"], 5)
        self.assertTrue(res["needs_action"])

    def test_apply_ignores_disabled_or_errored(self):
        _, teams = helpers.write_config(helpers.config_text())
        before = set(teams["pet"]["repos"])
        apply_manifest_registry(teams, {"enabled": False})
        apply_manifest_registry(teams, {"enabled": True, "error": "boom", "teams": {"pet": ["x/y"]}})
        apply_manifest_registry(teams, None)
        self.assertEqual(teams["pet"]["repos"], before)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"OUT_DIR": self.out})
        self.env.start()
        self.addCleanup(self.env.stop)
        Path(self.out, "inventory.json").write_text(json.dumps(helpers.sample_inventory()))
        self.data_file = Path(self.out, "repos.json")
        self.data_file.write_text(json.dumps(helpers.sample_manifest_json()))

    def cfg(self, text):
        path = Path(self.out, "teams.yml")
        path.write_text(text)
        return str(path)

    def test_disabled_writes_marker(self):
        self.assertEqual(manifest.main(["--config", self.cfg(helpers.config_text(manifest=False))]), 0)
        self.assertEqual(json.loads(Path(self.out, "manifest.json").read_text()), {"enabled": False})

    def test_file_source_writes_outputs(self):
        with mock.patch.dict(os.environ, {"MANIFEST_FILE": str(self.data_file)}):
            self.assertEqual(manifest.main(["--config", self.cfg(helpers.config_text(manifest=False))]), 0)
        proposed = json.loads(Path(self.out, "manifest_proposed.json").read_text())
        self.assertEqual(proposed["topics_by_repo"]["acme/pets-service"], ["pets"])
        self.assertEqual(proposed["topics_by_repo"]["acme/pet-legacy"], [])
        self.assertEqual(proposed["vocabulary_additions"], ["pets"])
        csv_text = Path(self.out, "manifest_topic_drift.csv").read_text()
        self.assertIn("acme/viz-dash", csv_text)
        self.assertIn("d3", csv_text)

    def test_required_failure_exits_and_optional_degrades(self):
        self.data_file.write_text('{"nothing": "useful"}')
        with mock.patch.dict(os.environ, {"MANIFEST_FILE": str(self.data_file)}):
            with self.assertRaises(SystemExit) as ctx:
                manifest.main(["--config", self.cfg(helpers.config_text(manifest=False))])
            self.assertIn("Manifest sync failed", str(ctx.exception))
            optional = helpers.config_text(manifest=False).replace(
                "  lookback_months: 6\n", "  lookback_months: 6\n  manifest: {required: false}\n")
            self.assertEqual(manifest.main(["--config", self.cfg(optional)]), 0)
        result = json.loads(Path(self.out, "manifest.json").read_text())
        self.assertIn("parsed 0 repos", result["error"])
        # downstream stages cope with an errored manifest and say so in the report
        settings, teams = load_config(self.cfg(helpers.config_text(manifest=False)))
        res = classify.build_results(settings, teams, helpers.sample_inventory(), helpers.sample_enrichment(),
                                     helpers.NOW, manifest=result)
        self.assertIn("error", res["manifest"])
        page = render.confluence_page(res, "yaml", "T")
        ET.fromstring(NS_WRAP.format(page))
        self.assertIn("Could not read the repo manifest", page)

    def test_github_source_requires_repo(self):
        text = helpers.config_text().replace("    repo: acme/repo-downloader\n", "")
        with mock.patch.object(manifest, "GitHubClient"):
            with self.assertRaises(SystemExit) as ctx:
                manifest.main(["--config", self.cfg(text)])
        self.assertIn("manifest.repo", str(ctx.exception))

    def test_fetches_via_client(self):
        class Client:
            def get_file_json(self, repo, path, ref):
                self.args = (repo, path, ref)
                return helpers.sample_manifest_json()

        client = Client()
        data, source = manifest.load_manifest_data(mf(repo="acme/repo-downloader", path="data/x.json", ref="dev"), client)
        self.assertEqual(client.args, ("acme/repo-downloader", "data/x.json", "dev"))
        self.assertEqual(source, "acme/repo-downloader@dev:data/x.json")
        self.assertIn("teams", data)


class RenderManifestTests(unittest.TestCase):
    def results(self, extra=()):
        settings, teams = helpers.write_config(helpers.config_text())
        data = helpers.sample_manifest_json()
        inventory = helpers.sample_inventory()
        built = manifest.build_manifest(data, "acme/repo-downloader@main:repos.json", settings, teams, inventory)
        apply_manifest_registry(teams, built)
        return classify.build_results(settings, teams, inventory, helpers.sample_enrichment(), helpers.NOW,
                                      manifest=built)

    def test_confluence_section(self):
        res = self.results()
        page = render.confluence_page(res, "yaml", "T")
        ET.fromstring(NS_WRAP.format(page))
        for text in ["Manifest sync", "Topics differ between manifest and GitHub", "acme/shared-lib",
                     "In the manifest but not found on GitHub", "outside the scanned orgs",
                     "missing from the manifest's topic list", "Manifest teams with no entry in"]:
            self.assertIn(text, page)

    def test_email_section_is_capped(self):
        res = self.results()
        body = render.email_body(res, "Report", limit=2)
        ET.fromstring(body)
        self.assertIn("Manifest sync", body)
        self.assertIn("more in the full report", body)   # 4 drifts, limit 2
        self.assertNotIn("outside the scanned orgs", body)

    def test_in_sync_message(self):
        settings, teams = helpers.write_config(helpers.config_text())
        inv = {"repos": [helpers.make_repo("pet-api", ["pet"])]}
        built = manifest.build_manifest({"pet": [{"name": "pet-api", "topics": ["pet"]}]}, "s", settings, teams, inv)
        self.assertIn("in sync", render.manifest_section({**classify.manifest_summary(built, {"pet", "viz"})}, email=True))

    def test_disabled_renders_nothing(self):
        self.assertEqual(render.manifest_section({"enabled": False}), "")


class ClientFileTests(unittest.TestCase):
    def test_get_file_json_builds_url_and_uses_raw_media_type(self):
        seen = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok": true}'

            headers = {}

        def fake_urlopen(req, timeout=None):
            seen["url"], seen["accept"] = req.full_url, req.get_header("Accept")
            return Resp()

        client = GitHubClient(token="t", api_url="https://ghe.corp/api/v3")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(client.get_file_json("acme/repo", "data/my repos.json", "release/1"), {"ok": True})
        self.assertEqual(seen["url"], "https://ghe.corp/api/v3/repos/acme/repo/contents/data/my%20repos.json?ref=release/1")
        self.assertEqual(seen["accept"], "application/vnd.github.v3.raw")

    def test_non_json_file_raises_clear_error(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"<html>not json</html>"

            headers = {}

        client = GitHubClient(token="t")
        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            with self.assertRaises(GitHubError) as ctx:
                client.get_file_json("acme/repo", "x.json")
        self.assertIn("not valid JSON", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
