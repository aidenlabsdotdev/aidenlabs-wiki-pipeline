#!/usr/bin/env python3
"""harvest_journals.py — Iterate dates, harvest sessions, report which need journal generation."""

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=os.path.expanduser("~/Obsidian/aidenlabs"))
    parser.add_argument("--db", default=os.path.expanduser("~/.hermes/state.db"))
    parser.add_argument("--pipeline", default=os.path.join(os.path.dirname(__file__), "pipeline.py"))
    parser.add_argument("--start", default="2025-05-01")
    parser.add_argument("--end", default=None)  # None = yesterday
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)

    count = 0
    skipped = 0
    ready = []

    print(f"Harvesting {start} → {end} ...")
    d = start
    while d <= end:
        ds = str(d)
        jf = os.path.join(args.vault, "journal", f"{ds}.md")
        if os.path.exists(jf):
            skipped += 1
        elif subprocess.run(
            [sys.executable, args.pipeline, "harvest", "--date", ds, "--db", args.db],
            capture_output=True,
        ).returncode == 0:
            count += 1
            ready.append(ds)
            print(f"  {ds}: ready for ingest")
        d += timedelta(days=1)

    print(f"\nDone: {count} dates harvested, {skipped} skipped (exists)")
    if ready:
        print(f"\nDates needing journal generation:")
        for ds in ready:
            print(f"  just prompt-journal {ds}")


if __name__ == "__main__":
    main()
