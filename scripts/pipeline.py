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

    # Append to _meta/log.md
    log_path = os.path.join(vault, "_meta", "log.md")
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


def cmd_update_meta(args):
    """Regenerate index.md, hot.md, insights.md from current vault state."""
    import re
    from collections import defaultdict

    vault = args.vault

    # Collect all pages (excluding _meta/)
    pages = {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '_meta']
        for f in files:
            if f.endswith('.md') and not f.startswith('.'):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, vault)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
                    size = os.path.getsize(path)
                except OSError:
                    mtime = "unknown"
                    size = 0
                pages[rel] = {"mtime": mtime, "size": size}

    # Extract wiki links per page
    page_links = defaultdict(set)
    link_count = defaultdict(int)
    for rel, _ in pages.items():
        path = os.path.join(vault, rel)
        try:
            with open(path, 'r', errors='replace') as f:
                content = f.read()
        except IOError:
            continue
        for match in re.finditer(r'\[\[([^\]|]+?)(?:\|[^]]*)?\]', content):
            target = match.group(1).strip().rstrip('.md')
            page_links[rel].add(target)
            link_count[target] += 1

    # === Generate index.md ===
    sections = {"company": [], "projects": [], "synthesis": [], "journal": []}
    for rel in sorted(pages.keys()):
        if rel.startswith("company/"):
            name = rel.replace(".md", "")
            sections["company"].append(name)
        elif rel.startswith("projects/"):
            slug = rel.split("/")[1]
            if slug not in [s.split("/")[-1] for s in sections["projects"]]:
                main_page = f"projects/{slug}/{slug}"
                sections["projects"].append(main_page)
        elif rel.startswith("synthesis/"):
            sections["synthesis"].append(rel.replace(".md", ""))
        elif rel.startswith("journal/"):
            sections["journal"].append(rel.replace(".md", ""))

    index_lines = ["---", "title: Aiden Labs Wiki", "---", "", "# Aiden Labs Wiki", ""]
    index_lines.append("## Company")
    for p in sections["company"]:
        index_lines.append(f"- [[{p}]]")
    index_lines.append("")
    index_lines.append("## Projects")
    for p in sections["projects"]:
        index_lines.append(f"- [[{p}]]")
    index_lines.append("")
    if sections["synthesis"]:
        index_lines.append("## Synthesis")
        for p in sections["synthesis"]:
            index_lines.append(f"- [[{p}]]")
    else:
        index_lines.append("## Synthesis")
        index_lines.append("_Cross-project insights generated from accumulated knowledge._")
    index_lines.append("")
    if sections["journal"]:
        index_lines.append("## Journal")
        for p in sorted(sections["journal"], reverse=True)[:10]:
            index_lines.append(f"- [[{p}]]")
        if len(sections["journal"]) > 10:
            index_lines.append(f"_... and {len(sections['journal']) - 10} more entries_")
    else:
        index_lines.append("## Journal")
        index_lines.append("_Daily activity records._")
    index_lines.append("")

    with open(os.path.join(vault, "index.md"), 'w') as f:
        f.write("\n".join(index_lines))
    print(f"Updated index.md ({sum(len(v) for v in sections.values())} entries)")

    # === Generate insights.md ===
    hubs = [(k, v) for k, v in link_count.items() if v >= 3]
    hubs.sort(key=lambda x: x[1], reverse=True)
    orphans = [p for p in pages if p not in link_count and p.replace('.md', '') not in link_count and not p.startswith('_meta/') and p not in ('AGENTS.md', 'index.md')]

    insights_lines = [
        "---",
        "title: Vault Insights",
        f"updated: \"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\"",
        "---",
        "",
        "# Vault Insights",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Total pages:** {len(pages)}",
        f"**Total links:** {sum(link_count.values())}",
        "",
        "## Hub Pages (most linked)",
        "",
    ]
    if hubs:
        insights_lines.append("| Page | Linked From |")
        insights_lines.append("|------|-------------|")
        for page, count in hubs[:10]:
            insights_lines.append(f"| [[{page}]] | {count} |")
    else:
        insights_lines.append("_No hub pages yet (need ≥3 inbound links)._")

    insights_lines.extend(["", "## Orphan Pages (no inbound links)", ""])
    if orphans:
        for p in sorted(orphans):
            insights_lines.append(f"- [[{p}]]")
    else:
        insights_lines.append("_No orphan pages — all pages are linked from somewhere._")

    insights_lines.extend(["", "## Clusters", ""])
    # Simple cluster detection: pages that link to each other
    clusters = defaultdict(set)
    for page, links in page_links.items():
        for link in links:
            if link in pages:
                pair = tuple(sorted([page, link]))
                clusters[pair].add(page)
    # Show top connected pairs
    top_pairs = sorted(clusters.items(), key=lambda x: len(x[0]), reverse=True)[:5]
    if top_pairs:
        insights_lines.append("| Connection | Strength |")
        insights_lines.append("|------------|----------|")
        for (a, b), _ in top_pairs:
            count_a = link_count.get(a, 0)
            count_b = link_count.get(b, 0)
            insights_lines.append(f"| [[{a}]] ↔ [[{b}]] | {count_a + count_b} |")

    insights_lines.append("")
    with open(os.path.join(vault, "_meta", "insights.md"), 'w') as f:
        f.write("\n".join(insights_lines))
    print(f"Updated _meta/insights.md ({len(hubs)} hubs, {len(orphans)} orphans)")

    # === Generate hot.md ===
    # Find the 10 most recently modified pages
    recent = sorted(pages.items(), key=lambda x: x[1]["mtime"], reverse=True)[:10]

    hot_lines = [
        "---",
        "title: Hot Topics",
        f"updated: \"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\"",
        "---",
        "",
        "# Hot Topics",
        "",
        f"_Semantic snapshot of what the wiki covers, updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## Recently Updated",
        "",
    ]
    for rel, info in recent:
        hot_lines.append(f"- [[{rel}]] (updated {info['mtime'][:16]})")

    hot_lines.extend(["", "## Active Areas", ""])
    # Group recent pages by category
    active_areas = defaultdict(list)
    for rel, _ in recent:
        if "/" in rel:
            area = rel.split("/")[0]
        else:
            area = "root"
        active_areas[area].append(rel)
    for area, pages_list in sorted(active_areas.items(), key=lambda x: -len(x[1])):
        hot_lines.append(f"### {area.replace('-', ' ').title()}")
        for p in pages_list:
            hot_lines.append(f"- [[{p}]]")
        hot_lines.append("")

    with open(os.path.join(vault, "_meta", "hot.md"), 'w') as f:
        f.write("\n".join(hot_lines))
    print(f"Updated _meta/hot.md ({len(recent)} recent pages)")


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

    # Update meta
    p_meta = subparsers.add_parser("update-meta", help="Regenerate index.md, hot.md, insights.md")
    p_meta.add_argument("--vault", default=VAULT_DEFAULT)
    p_meta.set_defaults(func=cmd_update_meta)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
