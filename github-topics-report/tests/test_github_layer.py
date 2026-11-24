import io
import json
import unittest
import urllib.error
from unittest import mock

import helpers
import enrich
import inventory
from ghclient import GitHubClient, GitHubError, derive_graphql_url


class FakeResponse(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(json.dumps(payload).encode())
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, headers=None, body=b"{}"):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.client = GitHubClient(token="t", api_url="https://api.github.com", sleep=self.sleeps.append)

    def test_graphql_url_derivation(self):
        self.assertEqual(derive_graphql_url("https://api.github.com"), "https://api.github.com/graphql")
        self.assertEqual(derive_graphql_url("https://ghe.corp/api/v3"), "https://ghe.corp/api/graphql")

    def test_retries_transient_then_succeeds(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=[http_error(502), FakeResponse({"data": {"ok": 1}})]) as m:
            self.assertEqual(self.client.graphql("query{x}"), {"ok": 1})
        self.assertEqual(m.call_count, 2)
        self.assertEqual(len(self.sleeps), 1)

    def test_honours_retry_after_on_secondary_limit(self):
        err = http_error(403, {"Retry-After": "7"}, b'{"message":"secondary rate limit"}')
        with mock.patch("urllib.request.urlopen", side_effect=[err, FakeResponse({"data": {}})]):
            self.client.graphql("query{x}")
        self.assertEqual(self.sleeps, [7])

    def test_non_retryable_error_raises(self):
        with mock.patch("urllib.request.urlopen", side_effect=[http_error(401, body=b"bad creds")]):
            with self.assertRaises(GitHubError):
                self.client.graphql("query{x}")

    def test_graphql_errors_without_data_raise_but_partial_data_ok(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse({"errors": [{"message": "boom"}]})):
            with self.assertRaises(GitHubError):
                self.client.graphql("query{x}")
        partial = {"data": {"nodes": [None]}, "errors": [{"message": "forbidden repo"}]}
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(partial)):
            self.assertEqual(self.client.graphql("query{x}"), {"nodes": [None]})

    def test_sleeps_when_graphql_budget_nearly_spent(self):
        data = {"data": {"rateLimit": {"remaining": 3, "resetAt": "2099-01-01T00:00:00Z"}}}
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(data)):
            self.client.graphql("query{x}")
        self.assertEqual(self.sleeps, [900])  # capped at MAX_WAIT

    def test_rest_pagination(self):
        pages = [FakeResponse([{"n": i} for i in range(100)]), FakeResponse([{"n": 100}])]
        with mock.patch("urllib.request.urlopen", side_effect=pages):
            self.assertEqual(len(self.client.rest_paginated("/orgs/a/teams/b/members")), 101)


class FakeGraphQL:
    """Stands in for GitHubClient in inventory/enrich tests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def graphql(self, query, variables=None):
        self.calls.append(variables)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def repo_node(name, topics=(), codeowners=None):
    return {
        "id": f"ID_{name}", "nameWithOwner": f"acme/{name}", "name": name, "description": None,
        "url": f"https://github.com/acme/{name}", "isArchived": False, "isFork": False, "isPrivate": True,
        "createdAt": "2024-01-01T00:00:00Z", "pushedAt": "2026-09-01T00:00:00Z",
        "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in topics]},
        "coA": None, "coB": {"text": codeowners} if codeowners else None, "coC": None,
    }


class InventoryTests(unittest.TestCase):
    def test_pagination_and_flatten(self):
        def page(nodes, more, cursor):
            return {"organization": {"repositories": {
                "pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}}}
        client = FakeGraphQL([page([repo_node("a", ["Pet", "viz"]), None], True, "C1"),
                              page([repo_node("b", codeowners="* @acme/pet")], False, None)])
        repos = inventory.fetch_org_repos(client, "acme")
        self.assertEqual([r["name"] for r in repos], ["a", "b"])
        self.assertEqual(repos[0]["topics"], ["pet", "viz"])
        self.assertEqual(repos[1]["codeowners"], "* @acme/pet")
        self.assertEqual(repos[0]["description"], "")
        self.assertEqual(client.calls[1]["cursor"], "C1")

    def test_missing_org_raises(self):
        with self.assertRaises(GitHubError):
            inventory.fetch_org_repos(FakeGraphQL([{"organization": None}]), "nope")

    def test_role_of(self):
        self.assertEqual(inventory.role_of({"role_name": "Admin"}), "admin")
        self.assertEqual(inventory.role_of({"permissions": {"admin": False, "push": True, "pull": True}}), "push")
        self.assertEqual(inventory.role_of({}), "none")

    def test_team_failure_degrades_gracefully(self):
        settings, teams = helpers.write_config()

        class Client(FakeGraphQL):
            def rest_paginated(self, path, per_page=100):
                raise GitHubError("403 read:org missing")

        page = {"organization": {"repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                                  "nodes": [repo_node("a")]}}}
        inv = inventory.build_inventory(Client([page]), settings, teams)
        self.assertEqual(len(inv["repos"]), 1)
        self.assertIn("error", inv["teams"]["pet"])
        self.assertNotIn("viz", inv["teams"])  # no github_team configured


class EnrichTests(unittest.TestCase):
    def test_summarize(self):
        node = {"defaultBranchRef": {"target": {"history": {"totalCount": 250, "nodes": [
                    {"author": {"user": {"login": "Alice"}}}, {"author": {"user": {"login": "alice"}}},
                    {"author": {"user": None}}, {"author": None}]}}},
                "readme": {"text": "x" * 10_000}}
        s = enrich.summarize(node)
        self.assertEqual(s["total_commits"], 250)
        self.assertEqual(s["sampled"], 4)
        self.assertEqual(s["authors"], {"alice": 2, "": 2})
        self.assertEqual(len(s["readme_head"]), enrich.README_CHARS)

    def test_summarize_empty_repo(self):
        s = enrich.summarize({"defaultBranchRef": None, "readme": None})
        self.assertEqual((s["total_commits"], s["sampled"], s["authors"]), (0, 0, {}))

    def test_pool_excludes_stale_archived_forks(self):
        from reportlib import months_ago
        settings, teams = helpers.write_config()
        pool = enrich.candidate_pool(helpers.sample_inventory()["repos"], teams, settings,
                                     months_ago(helpers.NOW, 6))
        names = {r["name"] for r in pool}
        self.assertIn("pet-tools", names)
        self.assertNotIn("pet-ancient", names)      # no push inside the window
        self.assertNotIn("old-pet-thing", names)    # archived
        self.assertNotIn("pet-fork", names)         # fork
        # pet-api is tagged for pet but is still a possible *viz* candidate, so it stays in the pool
        self.assertIn("pet-api", names)

    def test_pool_is_capped_newest_first(self):
        from reportlib import months_ago
        settings, teams = helpers.write_config()
        settings["max_enrich_repos"] = 1
        repos = [helpers.make_repo("a", pushed="2026-08-01T00:00:00Z"),
                 helpers.make_repo("b", pushed="2026-09-20T00:00:00Z")]
        pool = enrich.candidate_pool(repos, teams, settings, months_ago(helpers.NOW, 6))
        self.assertEqual([r["name"] for r in pool], ["b"])

    def test_batches_and_splits_on_failure(self):
        settings, teams = helpers.write_config()
        settings["enrich_batch_size"] = 4
        inv = {"repos": [helpers.make_repo(f"r{i}") for i in range(4)]}

        def node(i):
            return {"id": f"ID_r{i}", "nameWithOwner": f"acme/r{i}",
                    "defaultBranchRef": {"target": {"history": {"totalCount": 1, "nodes": [
                        {"author": {"user": {"login": "alice"}}}]}}}, "readme": None}

        # Whole batch fails, then each half succeeds.
        client = FakeGraphQL([GitHubError("timeout"),
                              {"nodes": [node(0), node(1)]}, {"nodes": [node(2), node(3)]}])
        result = enrich.enrich(client, inv, teams, settings, helpers.NOW)
        self.assertEqual(sorted(result["repos"]), [f"acme/r{i}" for i in range(4)])
        self.assertEqual(result["repos"]["acme/r0"]["authors"], {"alice": 1})
        self.assertEqual(len(client.calls[0]["ids"]), 4)
        self.assertEqual(len(client.calls[1]["ids"]), 2)

    def test_single_failing_repo_is_skipped(self):
        settings, teams = helpers.write_config()
        inv = {"repos": [helpers.make_repo("solo")]}
        result = enrich.enrich(FakeGraphQL([GitHubError("too big")]), inv, teams, settings, helpers.NOW)
        self.assertEqual(result["repos"], {})


if __name__ == "__main__":
    unittest.main()
