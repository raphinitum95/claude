#!/bin/bash
# Cloud sessions (claude.ai/code) start from a fresh clone: build .venv so `.venv/bin/pytest` works like on the Mac.
# Local sessions already have their own .venv, so this does nothing there.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

if [ ! -x .venv/bin/pytest ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --disable-pip-version-check -e ".[dev]"
fi

# The cloud image ships one Chromium build and blocks downloads: pin the Playwright that matches it
# (build 1194 = Playwright 1.56). Only the cloud venv is pinned; pyproject.toml is untouched.
if [ -d /opt/pw-browsers/chromium_headless_shell-1194 ]; then
  .venv/bin/pip install -q --disable-pip-version-check "playwright==1.56.0"
fi
echo "regrunner dev env ready: .venv/bin/pytest"
