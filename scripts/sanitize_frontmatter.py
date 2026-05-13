#!/usr/bin/env python3
"""Sanitize YAML frontmatter in wiki .md files.

Ensures string fields that contain YAML-special characters (colons, commas,
semicolons, quotes, etc.) are properly double-quoted. Runs as a post-process
step after LLM-generated content to guarantee valid frontmatter.

Usage:
    python sanitize_frontmatter.py /path/to/vault [--dry-run]
"""

import argparse
import re
import sys
from pathlib import Path

# Fields that should always be quoted strings if they contain special chars
STRING_FIELDS = {"title", "summary", "aliases"}

# Characters that require quoting in YAML scalar values
SPECIAL_CHARS = re.compile(r'[:#,`{}\[\]\&\*!\|>\|%@"\'\n]')


def needs_quoting(value: str) -> bool:
    """Check if a YAML scalar value needs quoting."""
    return bool(SPECIAL_CHARS.search(value))


def sanitize_frontmatter(content: str) -> tuple[str, int]:
    """Parse and sanitize the frontmatter block at the top of the file.

    Returns (new_content, change_count).
    """
    # Find frontmatter delimiters
    fm_match = re.match(r'^(---\n)(.*?)(\n---\n)', content, re.DOTALL)
    if not fm_match:
        return content, 0

    start = fm_match.start(2)
    end = fm_match.end(2)
    fm_text = fm_match.group(2)

    changes = 0
    lines = fm_text.split('\n')
    new_lines = []

    for line in lines:
        # Match key: value (non-indented top-level keys only)
        m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)', line)
        if m:
            key = m.group(1)
            value = m.group(2).strip()

            # Skip if value is empty, a number, a boolean, or already quoted
            if not value:
                new_lines.append(line)
                continue

            if value.startswith('"') or value.startswith("'"):
                new_lines.append(line)
                continue

            # Skip YAML inline-list values like ``tags: [a, b, c]`` — quoting
            # them turns the list into a single string literal named "[a, b, c]",
            # which Obsidian then misrenders.  Also skip flow-mapping values.
            if value.startswith('[') or value.startswith('{'):
                new_lines.append(line)
                continue

            # Check if it looks like a number or boolean
            if re.match(r'^[~]?-?\d+\.?\d*$', value):
                new_lines.append(line)
                continue
            if value.lower() in ('true', 'false', 'null', 'yes', 'no', 'on', 'off'):
                new_lines.append(line)
                continue

            # Quote if it contains special chars or is in STRING_FIELDS
            if key in STRING_FIELDS or needs_quoting(value):
                # Escape existing double quotes
                escaped = value.replace('\\', '\\\\').replace('"', '\\"')
                new_line = f'{key}: "{escaped}"'
                if new_line != line:
                    changes += 1
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    new_fm = '\n'.join(new_lines)
    new_content = content[:start] + new_fm + content[end:]
    return new_content, changes


def main():
    parser = argparse.ArgumentParser(description='Sanitize YAML frontmatter in wiki files')
    parser.add_argument('vault', help='Path to vault directory')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without writing')
    args = parser.parse_args()

    vault = Path(args.vault)
    total_changes = 0
    files_fixed = 0

    for md_file in sorted(vault.rglob('*.md')):
        try:
            content = md_file.read_text(encoding='utf-8')
        except Exception:
            continue

        new_content, changes = sanitize_frontmatter(content)
        if changes > 0:
            if args.dry_run:
                print(f"[DRY RUN] {md_file.relative_to(vault)} ({changes} field(s) quoted)")
            else:
                md_file.write_text(new_content, encoding='utf-8')
                print(f"[FIXED] {md_file.relative_to(vault)} ({changes} field(s) quoted)")
            total_changes += changes
            files_fixed += 1

    print(f"\nDone: {files_fixed} file(s) fixed, {total_changes} field(s) quoted.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
