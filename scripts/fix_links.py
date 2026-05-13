#!/usr/bin/env python3
"""
fix_links.py — Repair broken wikilinks in the vault.

Scans all .md files for [[wikilinks]], resolves them against the actual
file tree, and auto-fixes broken or ambiguous links. Purely mechanical —
no LLM involved.

Resolution strategy:
1. Exact match: [[projects/hermes-agents]] → projects/hermes-agents.md exists? ✓
2. Fuzzy match: [[hermes-agents]] → search for matching slugs across vault
3. Dead link: no match found → leave as-is (flag in report)

Usage:
    python scripts/fix_links.py --vault PATH [--dry-run]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


def build_index(vault_path):
    """Build a mapping of slug → file path for all .md files."""
    index = {}
    for md_file in sorted(Path(vault_path).rglob('*.md')):
        rel = str(md_file.relative_to(vault_path))
        if rel.startswith('_meta/') or rel.startswith('.'):
            continue
        # Index by various forms of the path
        slug = rel.replace('.md', '')
        index[slug] = rel
        # Also index by basename
        basename = Path(slug).stem
        index[basename] = rel
    return index


def resolve_link(link_target, index):
    """Try to resolve a wikilink target to an actual file path."""
    # Strip .md if present
    target = link_target.rstrip('.md')

    # Exact match
    if target in index:
        return index[target]

    # Try with common prefixes stripped
    for prefix in ['projects/', 'journal/', 'synthesis/', 'company/']:
        if target.startswith(prefix):
            remainder = target[len(prefix):]
            candidate = prefix + remainder
            if candidate in index:
                return index[candidate]

    # Fuzzy: search for partial matches
    parts = target.split('/')
    last_part = parts[-1]
    candidates = [k for k in index if last_part in k]
    if len(candidates) == 1:
        return index[candidates[0]]

    return None


def fix_links_in_file(filepath, index, dry_run=False):
    """Fix broken wikilinks in a single file. Returns change count."""
    content = filepath.read_text(encoding='utf-8')
    original = content
    changes = 0

    def replace_link(match):
        nonlocal changes
        full = match.group(0)
        inner = match.group(1)

        # Split on | for alias: [[path|Display]]
        if '|' in inner:
            path_part, display = inner.split('|', 1)
        else:
            path_part = inner
            display = None

        resolved = resolve_link(path_part, index)
        if resolved and resolved != path_part:
            changes += 1
            if display:
                return f'[[{resolved}|{display}]' + ']'
            return f'[[{resolved}]' + ']'
        return full

    # Match [[link]] or [[link|alias]]
    new_content = re.sub(r'\[\[([^\]]+)\]\]', replace_link, content)

    if new_content != original and not dry_run:
        filepath.write_text(new_content, encoding='utf-8')

    return changes


def main():
    parser = argparse.ArgumentParser(description='Fix broken wikilinks in vault')
    parser.add_argument('--vault', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    vault = Path(args.vault)
    index = build_index(vault)

    total_changes = 0
    files_changed = 0

    for md_file in sorted(vault.rglob('*.md')):
        if str(md_file.relative_to(vault)).startswith('_meta/'):
            continue
        changes = fix_links_in_file(md_file, index, args.dry_run)
        if changes > 0:
            rel = md_file.relative_to(vault)
            print(f"[{'DRY RUN' if args.dry_run else 'FIXED'}] {rel} ({changes} link(s))")
            total_changes += changes
            files_changed += 1

    print(f"\nDone: {files_changed} file(s), {total_changes} link(s) fixed.")


if __name__ == '__main__':
    main()
