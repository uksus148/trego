#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
uv sync --project agent --frozen --extra test
npm ci --prefix frontend
npm ci --prefix tests/integration
(cd tests/integration && npx playwright install chromium)
uv run --project agent --frozen python tests/integration/run.py "$@"
