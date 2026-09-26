#!/bin/bash
# Double-click this file to start QA Regression. It opens in a window of its own; closing this Terminal window stops it.
# The first time, it sets itself up inside this folder (a few minutes, needs the internet). No admin rights are needed.
# To start over, delete the .venv folder.
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD/src"
VENV_PY=".venv/bin/python"

failed() {
  echo
  echo "QA Regression could not start. The messages above say why."
  read -r -p "Press Enter to close this window."
  exit 1
}

if [ ! -x "$VENV_PY" ]; then
  echo "Setting up QA Regression in this folder. This happens once and takes a few minutes."
  BASE_PY=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
      BASE_PY="$candidate"; break
    fi
  done
  if [ -z "$BASE_PY" ]; then
    echo "Python 3.9 or newer is needed and was not found. Get it from https://www.python.org/downloads/ then try again."
    failed
  fi
  "$BASE_PY" -m venv .venv || failed
fi

# A new version of the folder may need new packages: reinstall when pyproject.toml differs from the one last installed.
if ! cmp -s pyproject.toml .venv/installed-pyproject.toml; then
  echo "Installing what QA Regression needs. This needs the internet."
  "$VENV_PY" -m pip install --disable-pip-version-check --quiet --upgrade pip || failed
  "$VENV_PY" -m pip install --disable-pip-version-check --quiet -e . || failed
  cp pyproject.toml .venv/installed-pyproject.toml
fi

echo "QA Regression is running and opens in its own window."
echo "Keep this window open while you use it. Close this window to stop QA Regression."
"$VENV_PY" -m regrunner serve --app || failed
