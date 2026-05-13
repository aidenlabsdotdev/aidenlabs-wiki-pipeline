#!/usr/bin/env python3
"""run_projects.py — One-pass projects sync.

Two steps:

1. Mechanical scan via ``pipeline.py projects`` — writes
   ``~/.cache/wiki-pipeline/projects-manifest.json`` with every repo +
   any existing project page for context.
2. Dispatch the ``projects`` LLM phase via codex-goal.  The phase enriches
   every stub created by ``run_journals``, augments existing project
   pages with new info from journals + source code, and promotes any
   significant unpaged repo to a new project page.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
PIPELINE = SCRIPTS / "pipeline.py"

sys.path.insert(0, str(SCRIPTS))
from dispatch import run_phase  # noqa: E402


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--vault", default=os.path.expanduser("~/Obsidian/aidenlabs"))
  ap.add_argument("--max-iters", type=int, default=100,
                  help="codex-goal iteration cap (projects touch many pages — "
                       "every stub + every existing page is a separate edit)")
  args = ap.parse_args()

  vault = Path(args.vault)

  print("=== Mechanical projects scan ===")
  rc = subprocess.run(
    [str(VENV_PY), str(PIPELINE), "projects", "--vault", str(vault)],
    check=False,
  ).returncode
  if rc != 0:
    print(f"  ! pipeline.py projects exited {rc}", file=sys.stderr)
    return 1

  print("\n=== Dispatching projects-sync LLM ===")
  rc = run_phase(
    phase="projects",
    vault=str(vault),
    variables={},
    max_iters=args.max_iters,
  )
  return 0 if rc == 0 else 1


if __name__ == "__main__":
  sys.exit(main())
