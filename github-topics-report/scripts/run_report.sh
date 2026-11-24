#!/usr/bin/env bash
# Runs the report pipeline end to end: inventory -> manifest -> enrich -> classify -> render.
# Publishing (Confluence) and email are separate Harness steps that consume ./out.
#
# Required env: GITHUB_TOKEN  (read-only; repo + read:org, or a GitHub App token)
# Optional env: GH_ORGS, LOOKBACK_MONTHS, SKIP_ENRICH=true, OUT_DIR, REPORT_CONFIG,
#               MANIFEST_FILE / MANIFEST_REPO / MANIFEST_PATH / MANIFEST_REF (override settings.manifest),
#               GITHUB_API_URL (GitHub Enterprise Server: https://HOST/api/v3)
set -euo pipefail

cd "$(dirname "$0")/.."
export OUT_DIR="${OUT_DIR:-out}"
PY="${PYTHON:-python3}"

: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set}"
mkdir -p "$OUT_DIR"

for stage in inventory manifest enrich classify render; do
  echo "==> ${stage}"
  "$PY" "scripts/${stage}.py"
done

echo "==> done: needs_action=$(cat "$OUT_DIR/needs_action.txt")"
ls -1 "$OUT_DIR"
