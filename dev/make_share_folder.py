"""Build the folder that is handed to other people: ``share/QA Regression/`` plus ``share/QA Regression.zip``.

It holds only what is needed to run the tool (launchers, ``src/``, config, the user manual and, unless ``--no-workbooks``,
the workbooks). Everything for developers and AI agents stays behind: ``dev/`` (agent instructions, hand-off briefs, designs),
``tests/``, ``.claude/``, and anything personal or machine-specific (``secrets.env``, ``.auth/``, ``runs/``, ``.venv/``).
The launchers set the tool up on each computer the first time they are double-clicked, so no ``.venv`` is ever copied.

    python3 dev/make_share_folder.py                # from the repository root
    python3 dev/make_share_folder.py --no-workbooks
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "QA Regression"

FILES = ["Start QA Regression.bat", "Start QA Regression.command", "README.md", "config.yaml", "selectors.yaml",
         "secrets.env.example", "pyproject.toml"]
JUNK = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "*.egg-info", "~$*")
WORKBOOK_JUNK = shutil.ignore_patterns(".trash", "__pycache__", ".DS_Store", "~$*", "*.numbers")


def build(out_dir: Path, include_workbooks: bool) -> Path:
    target = out_dir / NAME
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)            # copy2 keeps the .command file executable
    shutil.copy2(ROOT / "dev" / "share" / "START HERE.txt", target / "START HERE.txt")
    shutil.copytree(ROOT / "src", target / "src", ignore=JUNK)
    if include_workbooks:
        shutil.copytree(ROOT / "workbooks", target / "workbooks", ignore=WORKBOOK_JUNK)
    else:
        (target / "workbooks").mkdir()
    archive = shutil.make_archive(str(out_dir / NAME), "zip", root_dir=out_dir, base_dir=NAME)
    return Path(archive)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT / "share"), help="where to build it (default: share/, which git ignores)")
    parser.add_argument("--no-workbooks", action="store_true", help="leave workbooks/ empty")
    args = parser.parse_args(argv)
    archive = build(Path(args.out), include_workbooks=not args.no_workbooks)
    print(f"Folder: {archive.with_suffix('')}\nZip:    {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
