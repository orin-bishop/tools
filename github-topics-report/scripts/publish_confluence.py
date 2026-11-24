"""Update an existing Confluence page with out/confluence.html (storage format).

Use this if you'd rather not go through the Harness Confluence template.

Environment:
  CONFLUENCE_BASE_URL   Cloud: https://yourorg.atlassian.net/wiki   Data Center: https://confluence.example.com
  CONFLUENCE_PAGE_ID    numeric id of the page to overwrite
  CONFLUENCE_API_TOKEN  Cloud API token, or a Data Center personal access token
  CONFLUENCE_EMAIL      set for Cloud (basic auth); leave unset for a Data Center bearer PAT
  CONFLUENCE_TITLE      optional new title (default: keep the current one)
  REPORT_HTML           optional path (default out/confluence.html)
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def call(method: str, url: str, headers: dict, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        sys.exit(f"Confluence {method} {url} failed: HTTP {err.code} {err.read().decode('utf-8', 'replace')[:500]}")


def auth_headers() -> dict:
    token = os.environ["CONFLUENCE_API_TOKEN"]
    email = os.environ.get("CONFLUENCE_EMAIL")
    if email:
        auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
    else:
        auth = f"Bearer {token}"
    return {"Authorization": auth, "Accept": "application/json", "Content-Type": "application/json"}


def main() -> int:
    base = os.environ["CONFLUENCE_BASE_URL"].rstrip("/")
    page_id = os.environ["CONFLUENCE_PAGE_ID"]
    html_path = Path(os.environ.get("REPORT_HTML", "out/confluence.html"))
    headers = auth_headers()
    url = f"{base}/rest/api/content/{page_id}"

    current = call("GET", f"{url}?expand=version", headers)
    payload = {
        "id": page_id,
        "type": current["type"],
        "title": os.environ.get("CONFLUENCE_TITLE") or current["title"],
        "version": {"number": current["version"]["number"] + 1, "message": "Automated GitHub topics report"},
        "body": {"storage": {"value": html_path.read_text(encoding="utf-8"), "representation": "storage"}},
    }
    updated = call("PUT", url, headers, payload)

    links = updated.get("_links", {})
    page_url = links.get("base", base) + links.get("webui", "")
    print(f"Updated page {page_id} to version {updated['version']['number']}: {page_url}")
    Path(os.environ.get("OUT_DIR", "out")).mkdir(parents=True, exist_ok=True)
    (Path(os.environ.get("OUT_DIR", "out")) / "confluence_url.txt").write_text(page_url, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
