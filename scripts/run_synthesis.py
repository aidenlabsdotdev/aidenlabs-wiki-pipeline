#!/usr/bin/env python3
"""run_synthesis.py — One-pass synthesis.

Two steps:

1. Mechanical analysis via ``pipeline.py synthesis`` — recency-weighted
   co-occurrence + bucketed selection (fresh + refresh).  Writes
   ``~/.cache/wiki-pipeline/synthesis-candidates.json``.
2. Dispatch the ``synthesis`` LLM phase via codex-goal.  The phase
   processes every candidate in both buckets: creates pages for
   ``fresh``, augments existing pages for ``refresh``.
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
  ap.add_argument("--n-fresh", type=int, default=8,
                  help="Slots reserved for new (unsynthesised) pairs")
  ap.add_argument("--n-refresh", type=int, default=7,
                  help="Slots reserved for refreshing existing synthesis pages")
  ap.add_argument("--half-life-days", type=int, default=60,
                  help="Recency half-life for journal co-occurrence")
  ap.add_argument("--max-iters", type=int, default=100,
                  help="codex-goal iteration cap")
  args = ap.parse_args()

  vault = Path(args.vault)

  print("=== Mechanical synthesis-candidate scan ===")
  rc = subprocess.run(
    [
      str(VENV_PY), str(PIPELINE), "synthesis",
      "--vault", str(vault),
      "--half-life-days", str(args.half_life_days),
      "--n-fresh", str(args.n_fresh),
      "--n-refresh", str(args.n_refresh),
    ],
    check=False,
  ).returncode
  if rc != 0:
    print(f"  ! pipeline.py synthesis exited {rc}", file=sys.stderr)
    return 1

  print("\n=== Dispatching synthesis-generation LLM ===")
  rc = run_phase(
    phase="synthesis",
    vault=str(vault),
    variables={},
    max_iters=args.max_iters,
  )
  return 0 if rc == 0 else 1


if __name__ == "__main__":
  sys.exit(main())
