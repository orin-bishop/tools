import unittest

import helpers
from classify import build_results, bucket_for, registry_suggestions, write_outputs
from reportlib import months_ago, token_pattern
import re


class TokenPatternTests(unittest.TestCase):
    def test_matches_delimited_token_only(self):
        rx = re.compile(token_pattern("pet"), re.I)
        for good in ["pet", "pets", "pet-api", "api-pet", "my_pet_svc", "PET-Analytics", "a.pet.b"]:
            self.assertTrue(rx.search(good), good)
        for bad in ["petition-portal", "carpet-cleaner", "petstore", "competition", "pet2", "repetition"]:
            self.assertFalse(rx.search(bad), bad)

    def test_months_ago_clamps_day(self):
        from datetime import datetime, timezone
        self.assertEqual(months_ago(datetime(2026, 8, 31, tzinfo=timezone.utc), 6).date().isoformat(), "2026-02-28")
        self.assertEqual(months_ago(datetime(2026, 2, 15, tzinfo=timezone.utc), 6).date().isoformat(), "2025-08-15")


class ClassifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings, teams = helpers.write_config()
        cls.results = build_results(settings, teams, helpers.sample_inventory(),
                                    helpers.sample_enrichment(), helpers.NOW)
        cls.pet = cls.results["teams"]["pet"]
        cls.cands = {c["full_name"]: c for c in cls.pet["candidates"]}

    def test_registry_diff(self):
        self.assertEqual([r["full_name"] for r in self.pet["unregistered"]], ["acme/pet-web"])
        self.assertEqual([r["full_name"] for r in self.pet["missing_topic"]], ["acme/pet-legacy"])
        self.assertEqual(self.pet["registry_not_found"], ["acme/gone-repo"])
        known = {r["full_name"]: r for r in self.pet["known_repos"]}
        self.assertEqual(set(known), {"acme/pet-api", "acme/pet-web", "acme/pet-legacy"})
        self.assertTrue(known["acme/pet-api"]["tagged"] and known["acme/pet-api"]["in_registry"])

    def test_false_positives_and_skips(self):
        for name in ["petition-portal", "carpet-cleaner", "old-pet-thing", "pet-fork", "pet-excluded",
                     "pet-api", "pet-web", "pet-legacy", "shared-lib"]:
            self.assertNotIn(f"acme/{name}", self.cands, name)

    def test_high_medium_low_buckets(self):
        self.assertEqual(self.cands["acme/pet-tools"]["bucket"], "high")        # 4 name + 5 admin
        self.assertEqual(self.cands["acme/pet-tools"]["score"], 9)
        self.assertEqual(self.cands["acme/pets-service"]["bucket"], "high")     # 4 name + 4 near-miss
        self.assertEqual(self.cands["acme/dash-board"]["bucket"], "medium")     # 5 codeowners
        self.assertEqual(self.cands["acme/petstore-demo"]["bucket"], "low")     # 2 description
        self.assertIn("similar topic 'pets'", " ".join(self.cands["acme/pets-service"]["reasons"]))

    def test_member_activity_uses_share_and_merges_api_members(self):
        # shared-lib: alice 8% and pull-only access -> 1 point, under the low threshold
        self.assertNotIn("acme/shared-lib", self.cands)
        # new-thing: alice(6)+carol(4, from API members) of 12 = 83% -> strong 4 + new repo 1
        nt = self.cands["acme/new-thing"]
        self.assertEqual(nt["score"], 5)
        self.assertEqual(nt["bucket"], "medium")
        self.assertIn("2 team members authored 10 of the last 12 commits (83%)", nt["reasons"][0])

    def test_stale_repo_flagged_not_dropped(self):
        stale = self.cands["acme/pet-ancient"]
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["bucket"], "medium")

    def test_viz_team_independent(self):
        viz = self.results["teams"]["viz"]
        self.assertEqual(viz["unregistered"], [])
        self.assertEqual(viz["missing_topic"], [])
        self.assertEqual([r["full_name"] for r in viz["known_repos"]], ["acme/viz-dash"])

    def test_sorted_by_score_then_recency(self):
        scores = [c["score"] for c in self.pet["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_needs_action_and_sorting_of_totals(self):
        self.assertTrue(self.results["needs_action"])
        self.assertGreater(self.results["total_actions"], 0)

    def test_include_stale_false_drops_stale(self):
        settings, teams = helpers.write_config()
        settings["include_stale"] = False
        res = build_results(settings, teams, helpers.sample_inventory(), helpers.sample_enrichment(), helpers.NOW)
        self.assertNotIn("acme/pet-ancient", [c["full_name"] for c in res["teams"]["pet"]["candidates"]])

    def test_clean_state_needs_no_action(self):
        settings, teams = helpers.write_config()
        inv = {"repos": [helpers.make_repo("pet-api", ["pet"]), helpers.make_repo("viz-dash", ["viz"])],
               "teams": {}}
        teams["pet"]["repos"] = {"acme/pet-api"}
        res = build_results(settings, teams, inv, {"repos": {}}, helpers.NOW)
        self.assertFalse(res["needs_action"])

    def test_thresholds(self):
        th = {"high": 7, "medium": 4, "low": 2}
        self.assertEqual([bucket_for(s, th) for s in (1, 2, 4, 7, 12)], [None, "low", "medium", "high", "high"])

    def test_outputs_written(self):
        import os, tempfile
        from pathlib import Path
        os.environ["OUT_DIR"] = tempfile.mkdtemp()
        write_outputs(self.results)
        out = Path(os.environ["OUT_DIR"])
        self.assertEqual((out / "needs_action.txt").read_text(), "true")
        self.assertIn("acme/pet-tools", (out / "candidates.csv").read_text())
        self.assertIn("acme/pet-api", (out / "pet_repos.csv").read_text())
        import yaml
        doc = yaml.safe_load(registry_suggestions(self.results))
        self.assertEqual(doc["pet"]["add_to_repos"], ["acme/pet-web"])
        self.assertEqual(doc["pet"]["needs_topic"], ["acme/pet-legacy"])
        self.assertEqual(doc["pet"]["remove_or_fix"], ["acme/gone-repo"])
        self.assertEqual(doc["pet"]["review_candidates"][0], "acme/pet-tools")
        self.assertEqual(doc["viz"], {})


if __name__ == "__main__":
    unittest.main()
