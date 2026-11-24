"""Tiny GitHub client (stdlib only): GraphQL + paginated REST with retries.

Works with github.com and GitHub Enterprise Server:
  GITHUB_API_URL      default https://api.github.com   (GHES: https://HOST/api/v3)
  GITHUB_GRAPHQL_URL  default derived from GITHUB_API_URL
  GITHUB_TOKEN        read-only token (repo + read:org, or a GitHub App token)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from reportlib import log

MAX_RETRIES = 5
MAX_WAIT = 900  # never sleep longer than 15 minutes for a rate limit


class GitHubError(RuntimeError):
    pass


def derive_graphql_url(api_url: str) -> str:
    api_url = api_url.rstrip("/")
    if api_url == "https://api.github.com":
        return api_url + "/graphql"
    if api_url.endswith("/api/v3"):
        return api_url[: -len("/api/v3")] + "/api/graphql"
    return api_url + "/graphql"


class GitHubClient:
    def __init__(self, token=None, api_url=None, graphql_url=None, sleep=time.sleep):
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not self.token:
            raise GitHubError("GITHUB_TOKEN is not set")
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.graphql_url = graphql_url or os.environ.get("GITHUB_GRAPHQL_URL") or derive_graphql_url(self.api_url)
        self._sleep = sleep

    # ------------------------------------------------------------ transport
    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "info-reports-github-topics",
        }
        if self.api_url == "https://api.github.com":
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        return headers

    def _wait_for_reset(self, reset_epoch: int) -> None:
        wait = max(1, min(MAX_WAIT, reset_epoch - int(time.time()) + 2))
        log(f"  rate limit reached; sleeping {wait}s")
        self._sleep(wait)

    def _http(self, method: str, url: str, body: bytes | None = None, extra_headers: dict | None = None):
        for attempt in range(1, MAX_RETRIES + 1):
            headers = {**self._headers(), **(extra_headers or {})}
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    try:
                        return json.loads(resp.read().decode("utf-8")), resp.headers
                    except ValueError:
                        raise GitHubError(f"Response from {url} was not valid JSON") from None
            except urllib.error.HTTPError as err:
                detail = err.read().decode("utf-8", "replace")[:300]
                retry_after = err.headers.get("Retry-After")
                remaining = err.headers.get("X-RateLimit-Remaining")
                transient = err.code in (500, 502, 503, 504)
                limited = err.code in (403, 429) and (
                    retry_after or remaining == "0" or "rate limit" in detail.lower()
                )
                if attempt == MAX_RETRIES or not (transient or limited):
                    raise GitHubError(f"HTTP {err.code} for {url}: {detail}") from None
                if retry_after:
                    self._sleep(min(MAX_WAIT, int(retry_after)))
                elif remaining == "0" and err.headers.get("X-RateLimit-Reset"):
                    self._wait_for_reset(int(err.headers["X-RateLimit-Reset"]))
                else:
                    self._sleep(min(60, 2 ** attempt))
            except urllib.error.URLError as err:
                if attempt == MAX_RETRIES:
                    raise GitHubError(f"Network error for {url}: {err.reason}") from None
                self._sleep(min(60, 2 ** attempt))
        raise GitHubError(f"Gave up on {url}")  # pragma: no cover

    # -------------------------------------------------------------- GraphQL
    def graphql(self, query: str, variables: dict | None = None) -> dict:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        body, _ = self._http("POST", self.graphql_url, payload)
        errors = body.get("errors") or []
        if errors and not body.get("data"):
            raise GitHubError("GraphQL error: " + "; ".join(e.get("message", "?") for e in errors))
        for err in errors:
            log(f"  GraphQL warning: {err.get('message')}")
        data = body.get("data") or {}
        limit = data.get("rateLimit")
        if limit and limit.get("remaining", 1000) < 25:
            reset = datetime.fromisoformat(limit["resetAt"].replace("Z", "+00:00"))
            self._wait_for_reset(int(reset.replace(tzinfo=timezone.utc).timestamp()))
        return data

    # ----------------------------------------------------------------- REST
    def rest_paginated(self, path: str, per_page: int = 100) -> list:
        items, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            body, _ = self._http("GET", f"{self.api_url}{path}{sep}per_page={per_page}&page={page}")
            items.extend(body)
            if len(body) < per_page:
                return items
            page += 1

    # ------------------------------------------------------- repository file
    def get_file_json(self, repo: str, path: str, ref: str | None = None):
        """Fetch a JSON file from a repo via the contents API (raw media type, up to 100 MB)."""
        url = f"{self.api_url}/repos/{repo}/contents/{urllib.parse.quote(path.lstrip('/'))}"
        if ref:
            url += f"?ref={urllib.parse.quote(ref)}"
        body, _ = self._http("GET", url, extra_headers={"Accept": "application/vnd.github.v3.raw"})
        return body
