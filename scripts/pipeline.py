#!/usr/bin/env python3
"""
pipeline.py — Mechanical phases of the daily wiki pipeline.

Handles: harvest (DB query), projects scan, synthesis analysis, finalize (rsync).
LLM phases (journal generation, project decisions, synthesis drafting) are handled
by the orchestrator skill using delegate_task to avoid polluting state.db.

Usage:
    python scripts/pipeline.py harvest --date 2026-05-04
    python scripts/pipeline.py projects --vault PATH
    python scripts/pipeline.py synthesis --vault PATH
    python scripts/pipeline.py finalize --vault PATH --date 2026-05-04
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


VAULT_DEFAULT = os.path.expanduser("~/Obsidian/aidenlabs")
PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.expanduser("~/.cache/wiki-pipeline")
PUBLIC_DIR = os.path.expanduser("~/Tasks/aidenlabs-vault/public")


def cmd_harvest(args):
    """Harvest sessions from state.db for a given date."""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from harvest import get_day_bounds, harvest, build_digest

    date = args.date
    os.makedirs(TMP_DIR, exist_ok=True)
    output = os.path.join(TMP_DIR, "digest.json")

    start_ts, end_ts = get_day_bounds(date)
    sessions = harvest(args.db, start_ts, end_ts, getattr(args, 'max_content_chars', 8000))
    digest = build_digest(date, sessions)

    with open(output, 'w') as f:
        json.dump(digest, f, indent=2, default=str)

    count = digest["summary"]["session_count"]
    print(f"Harvested {count} sessions for {date} → {output}")
    sys.exit(0 if count > 0 else 1)


def cmd_projects(args):
    """Scan repos and vault, output project manifest."""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sync_projects import scan_tasks_dir, scan_vault_projects, find_github_org_repos, build_manifest

    vault = args.vault
    os.makedirs(TMP_DIR, exist_ok=True)
    output = os.path.join(TMP_DIR, "projects-manifest.json")

    tasks_repos = scan_tasks_dir(getattr(args, 'tasks_dir', None) or os.path.expanduser("~/Tasks"))
    vault_projects = scan_vault_projects(vault)
    github_repos = find_github_org_repos()
    manifest = build_manifest(tasks_repos, vault_projects, github_repos)

    with open(output, 'w') as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"Project manifest → {output}")
    print(f"  Tasks repos: {len(manifest['tasks_repos'])}")
    print(f"  Vault projects: {len(manifest['vault_projects'])}")
    print(f"  GitHub org repos: {len(manifest['github_org_repos'])}")


def cmd_synthesis(args):
    """Analyze wiki links for synthesis candidates."""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from synthesize import scan_vault, build_cooccurrence, find_existing_synthesis, find_candidates

    vault = args.vault
    os.makedirs(TMP_DIR, exist_ok=True)
    output = os.path.join(TMP_DIR, "synthesis-candidates.json")

    page_links = scan_vault(vault)
    cooccurrence, target_pages = build_cooccurrence(page_links)
    existing = find_existing_synthesis(vault)
    candidates = find_candidates(cooccurrence, existing, getattr(args, 'min_cooccurrence', 2))

    result = {
        "vault": vault,
        "pages_scanned": len(page_links),
        "existing_synthesis": len(existing),
        "candidates": candidates,
        "top_linked": dict(sorted(
            [(k, len(v)) for k, v in target_pages.items()],
            key=lambda x: x[1], reverse=True
        )[:20]),
    }

    with open(output, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Synthesis analysis → {output}")
    print(f"  Pages scanned: {result['pages_scanned']}")
    print(f"  Existing synthesis: {result['existing_synthesis']}")
    print(f"  New candidates: {len(candidates)}")


def cmd_finalize(args):
    """Regenerate notes.json, update log, sync to public."""
    vault = args.vault
    date = args.date

    # Append to log
    log_path = os.path.join(vault, "log.md")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(log_path, "a") as f:
        f.write(f"- [{timestamp}] PIPELINE-RUN date={date}\n")
    print(f"Logged to {log_path}")

    # Sync to public
    result = subprocess.run(
        ["rsync", "-av", "--delete", "--exclude=.obsidian", "--exclude=*.tmp",
         vault + "/", PUBLIC_DIR + "/"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"Synced vault → {PUBLIC_DIR}/")
    else:
        print(f"rsync failed: {result.stderr[:200]}")

    # Regenerate notes.json
    notes = []
    for root, dirs, files in os.walk(PUBLIC_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.md') and not f.startswith('.'):
                rel = os.path.relpath(os.path.join(root, f), PUBLIC_DIR)
                notes.append(rel)
    notes.sort()

    with open(os.path.join(PUBLIC_DIR, "notes.json"), 'w') as fh:
        json.dump({"notes": notes}, fh, indent=2)
    print(f"Regenerated notes.json ({len(notes)} pages)")


def main():
    parser = argparse.ArgumentParser(description="Wiki daily pipeline — mechanical phases")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Harvest
    p_harvest = subparsers.add_parser("harvest", help="Harvest sessions for a date")
    p_harvest.add_argument("--date", required=True)
    p_harvest.add_argument("--db", default=os.path.expanduser("~/.hermes/state.db"))
    p_harvest.add_argument("--max-content-chars", type=int, default=8000)
    p_harvest.set_defaults(func=cmd_harvest)

    # Projects
    p_projects = subparsers.add_parser("projects", help="Scan repos and vault")
    p_projects.add_argument("--vault", default=VAULT_DEFAULT)
    p_projects.add_argument("--tasks-dir", default=os.path.expanduser("~/Tasks"))
    p_projects.set_defaults(func=cmd_projects)

    # Synthesis
    p_synthesis = subparsers.add_parser("synthesis", help="Find synthesis candidates")
    p_synthesis.add_argument("--vault", default=VAULT_DEFAULT)
    p_synthesis.add_argument("--min-cooccurrence", type=int, default=2)
    p_synthesis.set_defaults(func=cmd_synthesis)

    # Finalize
    p_finalize = subparsers.add_parser("finalize", help="Log, sync, regenerate manifest")
    p_finalize.add_argument("--vault", default=VAULT_DEFAULT)
    p_finalize.add_argument("--date", required=True)
    p_finalize.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
