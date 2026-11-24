"""Runs the real scripts/run_report.sh against a local mock of the GitHub API."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import helpers

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 5  # small on purpose, to exercise cursor pagination


def repo_node(repo):
    return {
        "id": repo["id"], "nameWithOwner": repo["nameWithOwner"], "name": repo["name"],
        "description": repo["description"] or None, "url": repo["url"], "isArchived": repo["isArchived"],
        "isFork": repo["isFork"], "isPrivate": False, "createdAt": repo["createdAt"], "pushedAt": repo["pushedAt"],
        "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in repo["topics"]]},
        "coA": {"text": repo["codeowners"]} if repo["codeowners"] else None, "coB": None, "coC": None,
    }


def enrich_node(full_name, summary):
    commits = [{"committedDate": "2026-09-01T00:00:00Z", "author": {"user": {"login": login}}}
               for login, n in summary["authors"].items() for _ in range(n)]
    return {"id": "x", "nameWithOwner": full_name,
            "defaultBranchRef": {"target": {"history": {"totalCount": summary["total_commits"], "nodes": commits}}},
            "readme": {"text": summary["readme_head"]}}


class MockGitHub(BaseHTTPRequestHandler):
    repos = helpers.sample_inventory()["repos"]
    enrichment = helpers.sample_enrichment()["repos"]

    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.headers["Authorization"] == "Bearer test-token"
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        query, variables = request["query"], request["variables"]
        if "organization(login" in query:
            start = int(variables["cursor"] or 0)
            page = self.repos[start:start + PAGE_SIZE]
            more = start + PAGE_SIZE < len(self.repos)
            return self._send({"data": {"organization": {"repositories": {
                "pageInfo": {"hasNextPage": more, "endCursor": str(start + PAGE_SIZE)},
                "nodes": [repo_node(r) for r in page]}}}})
        if "nodes(ids" in query:
            by_id = {r["id"]: r["nameWithOwner"] for r in self.repos}
            nodes = []
            for repo_id in variables["ids"]:
                full = by_id[repo_id]
                nodes.append(enrich_node(full, self.enrichment[full.lower()]) if full.lower() in self.enrichment
                             else {"id": repo_id, "nameWithOwner": full, "defaultBranchRef": None, "readme": None})
            return self._send({"data": {"nodes": nodes}})
        self.send_error(400)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/repos/acme/repo-downloader/contents/repos.json":
            assert self.headers["Accept"] == "application/vnd.github.v3.raw", self.headers["Accept"]
            assert "ref=main" in self.path
            return self._send(helpers.sample_manifest_json())
        if path == "/orgs/acme/teams/pet/members":
            return self._send([{"login": "Carol"}])
        if path == "/orgs/acme/teams/pet/repos":
            return self._send([{"full_name": "acme/pet-tools", "role_name": "admin"},
                               {"full_name": "acme/shared-lib", "role_name": "pull"}])
        self.send_error(404)


class IntegrationTest(unittest.TestCase):
    def test_run_report_end_to_end(self):
        server = HTTPServer(("127.0.0.1", 0), MockGitHub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        out = tempfile.mkdtemp()
        cfg = Path(out) / "teams.yml"
        cfg.write_text(helpers.config_text())     # manifest enabled -> fetched from the mock contents API
        env = {**os.environ, "GITHUB_TOKEN": "test-token", "OUT_DIR": out, "REPORT_CONFIG": str(cfg),
               "GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}", "PYTHON": sys.executable,
               "CONFLUENCE_PAGE_URL": "https://wiki.example/pages/1"}
        try:
            proc = subprocess.run(["bash", str(ROOT / "scripts" / "run_report.sh")], env=env,
                                  capture_output=True, text=True, timeout=120)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((Path(out) / "needs_action.txt").read_text(), "true")
        results = json.loads((Path(out) / "results.json").read_text())
        pet = results["teams"]["pet"]
        self.assertEqual(results["repos_scanned"], len(MockGitHub.repos))       # pagination worked
        self.assertIn("carol", pet["members"])                                  # REST team members merged
        self.assertEqual([r["full_name"] for r in pet["unregistered"]], ["acme/pet-web"])
        self.assertEqual([r["full_name"] for r in pet["missing_topic"]], ["acme/pet-legacy"])
        cands = {c["full_name"]: c for c in pet["candidates"]}
        self.assertEqual(cands["acme/pet-tools"]["bucket"], "high")             # team admin via REST
        self.assertEqual(cands["acme/dash-board"]["bucket"], "medium")          # CODEOWNERS via GraphQL
        self.assertIn("acme/new-thing", cands)                                  # enrichment path
        self.assertGreater(results["repos_enriched"], 0)
        # manifest stage: fetched over HTTP, merged into the registry, compared with GitHub
        self.assertIn("acme/pet-gone", pet["registry_not_found"])
        manifest = results["manifest"]
        self.assertEqual(manifest["source"], "acme/repo-downloader@main:repos.json")
        self.assertEqual(len(manifest["compare"]["topic_drift"]), 4)
        self.assertEqual(manifest["unmapped_teams"], ["platform"])
        self.assertTrue((Path(out) / "manifest_proposed.json").exists())
        self.assertIn("Manifest sync", (Path(out) / "confluence.html").read_text())
        self.assertIn("https://wiki.example/pages/1", (Path(out) / "email.html").read_text())

    def test_missing_token_fails_fast(self):
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
        proc = subprocess.run(["bash", str(ROOT / "scripts" / "run_report.sh")], env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("GITHUB_TOKEN", proc.stderr)


if __name__ == "__main__":
    unittest.main()
