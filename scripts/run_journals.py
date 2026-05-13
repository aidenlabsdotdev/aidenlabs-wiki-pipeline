#!/usr/bin/env python3
"""run_journals.py — Iterate every missing day from first state.db activity
to yesterday, generating a journal entry for each.

Flow per missing day:

1. ``pipeline.py harvest --date X`` → produces digest.json.  Exit 1 means
   no sessions for that day — we skip it silently.
2. Dispatch ``journal`` LLM phase via codex-goal (writes the journal entry
   into ``vault/journal/X.md``).
3. ``pipeline.py stub-projects --journal-date X`` → creates project-page
   stubs for any new ``[[projects/Y]]`` wikilinks the journal introduced.

Stops at yesterday — today is never journaled (partial day).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
PIPELINE = SCRIPTS / "pipeline.py"

# Add scripts dir to path so we can import dispatch.run_phase.
sys.path.insert(0, str(SCRIPTS))
from dispatch import run_phase  # noqa: E402


def first_activity_date(db_path: Path) -> date:
  """Return the date of the earliest non-(cron/cli) session.

  We use the same filter as ``harvest.py`` so the iteration window matches
  what would actually produce journal content.
  """
  conn = sqlite3.connect(db_path)
  try:
    cur = conn.execute(
      "SELECT MIN(started_at) FROM sessions "
      "WHERE source NOT IN ('cron', 'cli')"
    )
    ts = cur.fetchone()[0]
  finally:
    conn.close()
  if not ts:
    # No journal-worthy sessions — fall back to today so the loop is empty.
    return date.today()
  return datetime.fromtimestamp(ts).date()


def journal_exists(vault: Path, d: date) -> bool:
  return (vault / "journal" / f"{d.isoformat()}.md").is_file()


def harvest_day(d: date, db: Path) -> bool:
  """Run mechanical harvest.  Returns True if sessions were found."""
  rc = subprocess.run(
    [str(VENV_PY), str(PIPELINE), "harvest", "--date", d.isoformat(), "--db", str(db)],
    capture_output=True,
  ).returncode
  return rc == 0


def stub_for_journal(vault: Path, d: date) -> None:
  """Create stubs for any [[projects/<slug>]] wikilinks in the new entry."""
  subprocess.run(
    [str(VENV_PY), str(PIPELINE), "stub-projects",
     "--vault", str(vault), "--journal-date", d.isoformat()],
    check=False,
  )


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--vault", default=os.path.expanduser("~/Obsidian/aidenlabs"))
  ap.add_argument("--db", default=os.path.expanduser("~/.hermes/state.db"))
  ap.add_argument("--start", default=None,
                  help="Override start date (YYYY-MM-DD). Default: earliest "
                       "non-cron/non-cli session in state.db.")
  ap.add_argument("--end", default=None,
                  help="Override end date (YYYY-MM-DD). Default: yesterday.")
  ap.add_argument("--max-iters", type=int, default=100,
                  help="Per-day codex-goal iteration cap (plenty of headroom; "
                       "model usually finishes in 1-3 iters)")
  ap.add_argument("--dry-run", action="store_true",
                  help="List dates that would be processed; don't dispatch")
  args = ap.parse_args()

  vault = Path(args.vault)
  db = Path(args.db)
  if not vault.is_dir():
    print(f"vault not found: {vault}", file=sys.stderr)
    return 2
  if not db.is_file():
    print(f"state.db not found: {db}", file=sys.stderr)
    return 2

  start = (date.fromisoformat(args.start) if args.start
           else first_activity_date(db))
  end = (date.fromisoformat(args.end) if args.end
         else date.today() - timedelta(days=1))

  print(f"run_journals: iterating {start} → {end}")

  generated = skipped_exists = skipped_empty = errored = 0
  d = start
  while d <= end:
    if journal_exists(vault, d):
      skipped_exists += 1
      d += timedelta(days=1)
      continue

    has_sessions = harvest_day(d, db)
    if not has_sessions:
      skipped_empty += 1
      d += timedelta(days=1)
      continue

    if args.dry_run:
      print(f"  [dry-run] would generate {d.isoformat()}")
      generated += 1
      d += timedelta(days=1)
      continue

    print(f"\n=== Generating journal for {d.isoformat()} ===")
    previous = d - timedelta(days=1)
    rc = run_phase(
      phase="journal",
      vault=str(vault),
      variables={"date": d.isoformat()},
      max_iters=args.max_iters,
    )
    if rc != 0:
      print(f"  ! codex-goal exited {rc} for {d.isoformat()}", file=sys.stderr)
      errored += 1
      d += timedelta(days=1)
      continue

    if not journal_exists(vault, d):
      print(
        f"  ! codex-goal finished but journal/{d.isoformat()}.md not present",
        file=sys.stderr,
      )
      errored += 1
      d += timedelta(days=1)
      continue

    stub_for_journal(vault, d)
    generated += 1
    d += timedelta(days=1)

  print(
    f"\nrun_journals done: generated={generated} "
    f"skipped_exists={skipped_exists} skipped_empty={skipped_empty} "
    f"errored={errored}"
  )
  return 0 if errored == 0 else 1


if __name__ == "__main__":
  sys.exit(main())
