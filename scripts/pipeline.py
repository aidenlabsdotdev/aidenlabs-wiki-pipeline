#!/usr/bin/env python3
"""
pipeline.py — Mechanical phases of the daily wiki pipeline.

Handles: harvest (DB query), projects scan, synthesis candidates,
update-meta (index.md, hot.md, insights.md), finalize (rsync + notes.json).

All LLM phases use prompt templates from prompts/ directory.

Usage:
    python scripts/pipeline.py harvest --date 2026-05-04
    python scripts/pipeline.py projects --vault PATH
    python scripts/pipeline.py synthesis --vault PATH
    python scripts/pipeline.py update-meta --vault PATH
    python scripts/pipeline.py finalize --vault PATH --date 2026-05-04
    python scripts/pipeline.py prompt journal --date 2026-05-04
    python scripts/pipeline.py prompt projects
    python scripts/pipeline.py prompt synthesis --top 5
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

VAULT_DEFAULT = os.path.expanduser("~/Obsidian/aidenlabs")
TMP_DIR = os.path.expanduser("~/.cache/wiki-pipeline")
PUBLIC_DIR = os.path.expanduser("~/Repositories/aidenlabs-md/public")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(SCRIPTS_DIR, "..", "prompts")


def cmd_harvest(args):
    """Harvest sessions from state.db for a given date."""
    import sys as _sys
    _sys.path.insert(0, SCRIPTS_DIR)
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
    _sys.path.insert(0, SCRIPTS_DIR)
    from sync_projects import scan_tasks_dir, scan_vault_projects, find_github_org_repos, build_manifest

    vault = args.vault
    os.makedirs(TMP_DIR, exist_ok=True)
    output = os.path.join(TMP_DIR, "projects-manifest.json")

    tasks_repos = scan_tasks_dir(getattr(args, 'tasks_dir', None) or os.path.expanduser("~/Repositories"))
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
    """Analyze wiki links to find co-occurring concepts for synthesis.

    Thin wrapper around ``synthesize.analyse`` — the scoring + bucket
    logic lives there.  Keeping this file out of that logic means there's
    only one place to change selection behaviour.
    """
    import sys as _sys
    _sys.path.insert(0, SCRIPTS_DIR)
    from synthesize import analyse  # noqa: E402

    vault = Path(args.vault)
    os.makedirs(TMP_DIR, exist_ok=True)
    output = os.path.join(TMP_DIR, "synthesis-candidates.json")

    result = analyse(
        vault=vault,
        half_life_days=getattr(args, "half_life_days", 60),
        min_score=getattr(args, "min_score", 1.5),
        n_fresh=getattr(args, "n_fresh", 8),
        n_refresh=getattr(args, "n_refresh", 7),
        min_refresh_delta=getattr(args, "min_refresh_delta", 0.5),
    )

    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    fresh = len(result["buckets"]["fresh"])
    refresh = len(result["buckets"]["refresh"])
    print(f"Synthesis candidates → {output}")
    print(f"  Pages scanned: {result['pages_scanned']}")
    print(f"  Existing synthesis: {result['existing_synthesis']}")
    print(f"  Selected: {fresh} fresh + {refresh} refresh = {fresh + refresh}")
    print(
        f"  Pool sizes: fresh={result['pool_sizes']['fresh']}, "
        f"refresh={result['pool_sizes']['refresh']}"
    )


def cmd_update_meta(args):
    """Regenerate index.md, _meta/hot.md, _meta/insights.md from vault state."""
    vault = args.vault

    # Collect all pages with frontmatter
    pages = []
    for md_file in sorted(Path(vault).rglob('*.md')):
        rel = md_file.relative_to(vault)
        if str(rel).startswith('_meta/') or str(rel).startswith('.') or rel.name.startswith('.'):
            continue
        content = md_file.read_text(encoding='utf-8')
        # Extract frontmatter
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        fm = {}
        if fm_match:
            for line in fm_match.group(1).split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    fm[k.strip()] = v.strip().strip('"')
        folder = str(rel.parent)
        slug = rel.stem
        title = fm.get('title', slug)
        summary = fm.get('summary', '')
        tags = fm.get('tags', '')
        category = folder.split('/')[0] if folder != '.' else 'root'
        pages.append({
            'path': str(rel),
            'slug': slug,
            'title': title,
            'summary': summary,
            'tags': tags,
            'category': category,
            'folder': folder,
        })

    # Generate index.md
    sections = defaultdict(list)
    for p in pages:
        cat = p['category'].capitalize() if p['category'] != 'root' else 'Root'
        sections[cat].append(p)

    index_lines = ['---', 'title: "Aiden Labs Wiki"', '---', '', '# Aiden Labs Wiki', '']
    for section_name in ['Root', 'Company', 'Journal', 'Projects', 'Synthesis']:
        if section_name not in sections:
            continue
        items = sections[section_name]
        index_lines.append(f'## {section_name}')
        index_lines.append('')
        for item in sorted(items, key=lambda x: x['title'].lower()):
            link = item['path'].replace('.md', '')
            index_lines.append(f'- [[{link}|{item["title"]}]]')
            if item['summary']:
                index_lines.append(f'  - {item["summary"]}')
        index_lines.append('')

    index_path = os.path.join(vault, 'index.md')
    with open(index_path, 'w') as f:
        f.write('\n'.join(index_lines))
    print(f"Generated {index_path} ({len(pages)} pages)")

    # Generate _meta/hot.md — recent activity snapshot
    journals = [p for p in pages if p['folder'] == 'journal']
    journals.sort(key=lambda x: x['slug'], reverse=True)
    hot_lines = ['---', 'title: "Recent Activity"', '---', '', '# Recent Activity', '']
    for j in journals[:7]:
        link = j['path'].replace('.md', '')
        hot_lines.append(f"- **[[{link}|{j['title']}]]** — {j['summary']}")
    hot_lines.append('')

    hot_path = os.path.join(vault, '_meta', 'hot.md')
    with open(hot_path, 'w') as f:
        f.write('\n'.join(hot_lines))
    print(f"Generated {hot_path}")

    # Generate _meta/insights.md — graph analysis
    # Build adjacency from wikilinks
    adj = defaultdict(set)  # source -> targets
    backlinks = defaultdict(set)  # target -> sources
    for md_file in sorted(Path(vault).rglob('*.md')):
        rel = str(md_file.relative_to(vault))
        if rel.startswith('_meta/') or rel.startswith('.'):
            continue
        content = md_file.read_text(encoding='utf-8')
        links = re.findall(r'\[\[([^\]|]+?)(?:\|[^]]*)?\]', content)
        for link in links:
            link = link.strip().rstrip('.md')
            adj[rel].add(link)
            backlinks[link].add(rel)

    # Hubs (most outbound links)
    hubs = sorted(adj.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    # Authorities (most inbound links)
    authorities = sorted(backlinks.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    # Orphans (no inbound links, excluding system pages)
    all_pages = set(str(p.relative_to(vault)) for p in Path(vault).rglob('*.md')
                     if not str(p.relative_to(vault)).startswith('_meta/'))
    linked_targets = set()
    for targets in adj.values():
        linked_targets.update(targets)
    orphans = [p for p in all_pages if p not in linked_targets and p not in adj]

    insights_lines = ['---', 'title: "Graph Insights"', '---', '', '# Graph Insights', '']
    insights_lines.append('## Hubs (most outbound links)')
    insights_lines.append('')
    for page, targets in hubs:
        insights_lines.append(f"- **{page}** → {len(targets)} links")
    insights_lines.append('')

    insights_lines.append('## Authorities (most inbound links)')
    insights_lines.append('')
    for page, sources in authorities:
        insights_lines.append(f"- **{page}** ← {len(sources)} backlinks")
    insights_lines.append('')

    insights_lines.append('## Orphans (no inbound links)')
    insights_lines.append('')
    if orphans:
        for o in orphans:
            insights_lines.append(f"- {o}")
    else:
        insights_lines.append("- None")
    insights_lines.append('')

    insights_path = os.path.join(vault, '_meta', 'insights.md')
    with open(insights_path, 'w') as f:
        f.write('\n'.join(insights_lines))
    print(f"Generated {insights_path}")


def render_prompt(name, **kwargs):
    """Load a prompt template and fill in variables."""
    prompt_path = os.path.join(PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(prompt_path):
        print(f"Error: prompt template not found: {prompt_path}", file=sys.stderr)
        sys.exit(1)

    content = Path(prompt_path).read_text(encoding='utf-8')

    # Fill in {{variable}} placeholders
    for key, value in kwargs.items():
        content = content.replace('{{' + key + '}}', str(value))

    return content


def cmd_prompt(args):
    """Render a prompt template with variables filled in."""
    now = datetime.now(timezone.utc).isoformat()
    vault = getattr(args, 'vault', VAULT_DEFAULT)

    if args.prompt_name == 'journal':
        date = args.date
        # Find previous journal
        prev_date = None
        journal_dir = os.path.join(vault, 'journal')
        if os.path.isdir(journal_dir):
            journals = sorted([f for f in os.listdir(journal_dir)
                              if f.endswith('.md') and f != f'{date}.md'])
            if journals:
                prev_date = journals[-1].replace('.md', '')
        digest_path = os.path.join(TMP_DIR, "digest.json")
        prompt = render_prompt('journal',
            date=date,
            digest_path=digest_path,
            vault_path=vault,
            previous_date=prev_date or 'NONE',
            iso_timestamp=now,
        )
    elif args.prompt_name == 'projects':
        manifest_path = os.path.join(TMP_DIR, "projects-manifest.json")
        repos_path = os.path.expanduser("~/Repositories")
        prompt = render_prompt('projects',
            manifest_path=manifest_path,
            vault_path=vault,
            repos_path=repos_path,
            iso_timestamp=now,
        )
    elif args.prompt_name == 'synthesis':
        candidates_path = os.path.join(TMP_DIR, "synthesis-candidates.json")
        top_n = getattr(args, 'top', 5)
        prompt = render_prompt('synthesis',
            candidates_path=candidates_path,
            vault_path=vault,
            top_n=top_n,
            iso_timestamp=now,
        )
    else:
        print(f"Unknown prompt: {args.prompt_name}", file=sys.stderr)
        sys.exit(1)

    print(prompt)


def cmd_stub_projects(args):
    """Create stub project pages for journal wikilink targets."""
    import sys as _sys
    _sys.path.insert(0, SCRIPTS_DIR)
    from stub_projects import (
      journal_paths as _jp, referenced_project_slugs as _refs,
      stub_path as _sp, write_stub as _ws,
    )

    vault = Path(args.vault)
    files = _jp(vault, args.journal_date, args.all_journals)
    if not files:
        print("stub-projects: no journal files matched")
        return
    slugs = _refs(files)
    created = 0
    for slug in sorted(slugs):
        path = _sp(vault, slug)
        if _ws(path, slug):
            created += 1
            print(f"stub-projects: created {path.relative_to(vault)}")
    print(
        f"stub-projects: {len(files)} journal(s), {len(slugs)} project ref(s), "
        f"{created} stub(s) created"
    )


def cmd_fix_links(args):
    """Repair broken wikilinks in the vault."""
    import sys as _sys
    _sys.path.insert(0, SCRIPTS_DIR)
    from fix_links import build_index as _bi, fix_links_in_file as _fl

    vault = Path(args.vault)
    index = _bi(vault)

    total = 0
    files_changed = 0
    for md_file in sorted(vault.rglob('*.md')):
        if str(md_file.relative_to(vault)).startswith('_meta/'):
            continue
        changes = _fl(md_file, index, args.dry_run)
        if changes > 0:
            rel = md_file.relative_to(vault)
            print(f"[{'DRY RUN' if args.dry_run else 'FIXED'}] {rel} ({changes} link(s))")
            total += changes
            files_changed += 1

    print(f"\nDone: {files_changed} file(s), {total} link(s) fixed.")


def cmd_finalize(args):
    """Append log, sanitize frontmatter, rsync to public/, regenerate notes.json."""
    vault = args.vault
    date = args.date

    # Append to _meta/log.md
    log_path = os.path.join(vault, "_meta", "log.md")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(log_path, "a") as f:
        f.write(f"- [{timestamp}] PIPELINE-RUN date={date}\n")
    print(f"Logged to {log_path}")

    # Sanitize frontmatter (ensure YAML-safe quoting)
    import sys as _sys
    _sys.path.insert(0, SCRIPTS_DIR)
    from sanitize_frontmatter import sanitize_frontmatter as _sf
    sf_count = 0
    for md_file in sorted(Path(vault).rglob('*.md')):
        try:
            content = md_file.read_text(encoding='utf-8')
        except Exception:
            continue
        new_content, changes = _sf(content)
        if changes > 0:
            md_file.write_text(new_content, encoding='utf-8')
            sf_count += changes
    if sf_count:
        print(f"Sanitized {sf_count} frontmatter field(s)")

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
    p_projects.add_argument("--tasks-dir", default=os.path.expanduser("~/Repositories"))
    p_projects.set_defaults(func=cmd_projects)

    # Synthesis candidates
    p_synthesis = subparsers.add_parser("synthesis", help="Find synthesis candidates")
    p_synthesis.add_argument("--vault", default=VAULT_DEFAULT)
    p_synthesis.add_argument("--half-life-days", type=int, default=60,
                             help="Journal recency half-life for co-occurrence scoring")
    p_synthesis.add_argument("--min-score", type=float, default=1.5,
                             help="Weighted-score floor for any candidate")
    p_synthesis.add_argument("--n-fresh", type=int, default=8,
                             help="Slots reserved for unsynthesised pairs")
    p_synthesis.add_argument("--n-refresh", type=int, default=7,
                             help="Slots reserved for refreshing existing pages")
    p_synthesis.add_argument("--min-refresh-delta", type=float, default=0.5,
                             help="Required score gain since last update to qualify for refresh. "
                                  "Pages with no new co-occurrence drop out via this gate — "
                                  "no time-based cooldown needed.")
    p_synthesis.set_defaults(func=cmd_synthesis)

    # Update meta
    p_update = subparsers.add_parser("update-meta", help="Regenerate index.md, hot.md, insights.md")
    p_update.add_argument("--vault", default=VAULT_DEFAULT)
    p_update.set_defaults(func=cmd_update_meta)

    # Prompt rendering
    p_prompt = subparsers.add_parser("prompt", help="Render a prompt template")
    p_prompt.add_argument("prompt_name", choices=["journal", "projects", "synthesis"])
    p_prompt.add_argument("--date", default=None)
    p_prompt.add_argument("--vault", default=VAULT_DEFAULT)
    p_prompt.add_argument("--top", type=int, default=5)
    p_prompt.set_defaults(func=cmd_prompt)

    # Stub projects (mechanical — create empty project pages for journal refs)
    p_stub = subparsers.add_parser(
      "stub-projects",
      help="Create stub project pages for [[projects/X]] wikilinks in journals",
    )
    p_stub.add_argument("--vault", default=VAULT_DEFAULT)
    g_stub = p_stub.add_mutually_exclusive_group()
    g_stub.add_argument("--journal-date", help="Stub for one date (YYYY-MM-DD)")
    g_stub.add_argument("--all-journals", action="store_true",
                        help="Scan every journal entry")
    p_stub.set_defaults(func=cmd_stub_projects)

    # Fix links (mechanical wikilink repair)
    p_fixlinks = subparsers.add_parser("fix-links", help="Repair broken wikilinks")
    p_fixlinks.add_argument("--vault", default=VAULT_DEFAULT)
    p_fixlinks.add_argument("--dry-run", action="store_true")
    p_fixlinks.set_defaults(func=cmd_fix_links)

    # Finalize
    p_finalize = subparsers.add_parser("finalize", help="Log, sync, regenerate manifest")
    p_finalize.add_argument("--vault", default=VAULT_DEFAULT)
    p_finalize.add_argument("--date", required=True)
    p_finalize.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
