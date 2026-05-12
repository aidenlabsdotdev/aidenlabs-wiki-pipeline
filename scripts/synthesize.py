#!/usr/bin/env python3
"""
synthesize.py — Analyze wiki links to find co-occurring concepts for synthesis.

Scans all markdown files in the vault, builds a co-occurrence matrix of wiki links,
and identifies pairs that have strong connections but no synthesis page yet.

Usage:
    python scripts/synthesize.py --vault PATH [--output PATH]
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Find synthesis candidates")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault")
    parser.add_argument("--output", default=None, help="Output JSON path (default: stdout)")
    parser.add_argument("--min-cooccurrence", type=int, default=2,
                        help="Minimum co-occurrences to consider (default: 2)")
    return parser.parse_args()


def extract_wiki_links(content):
    """Extract all [[wiki link]] targets from markdown content."""
    # Match [[target]] or [[target|alias]]
    pattern = r'\[\[([^\]|]+?)(?:\|[^]]*)?\]'
    matches = re.findall(pattern, content)
    # Clean up targets
    return [m.strip().rstrip('.md') for m in matches if m.strip()]


def scan_vault(vault_path):
    """Scan all markdown files and extract wiki links per page."""
    page_links = {}  # page_path -> set of linked targets
    
    for root, dirs, files in os.walk(vault_path):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for filename in files:
            if not filename.endswith('.md') or filename.startswith('.'):
                continue
            
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, vault_path)
            
            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except (IOError, OSError):
                continue
            
            links = extract_wiki_links(content)
            if links:
                page_links[rel_path] = set(links)
    
    return page_links


def build_cooccurrence(page_links):
    """Build co-occurrence matrix from page links."""
    cooccurrence = defaultdict(int)
    target_pages = defaultdict(set)  # target -> set of pages that link to it
    
    for page, links in page_links.items():
        for link in links:
            target_pages[link].add(page)
        
        # Count pairs that co-occur on the same page
        links_list = sorted(links)
        for a, b in combinations(links_list, 2):
            cooccurrence[(a, b)] += 1
    
    return cooccurrence, target_pages


def find_existing_synthesis(vault_path):
    """Find existing synthesis pages to exclude."""
    existing = set()
    synthesis_dir = os.path.join(vault_path, "synthesis")
    
    if os.path.isdir(synthesis_dir):
        for filename in os.listdir(synthesis_dir):
            if filename.endswith('.md'):
                # Extract A and B from "A-x-B.md" format
                name = filename[:-3]
                if 'x' in name:
                    parts = name.split('x', 1)
                    if len(parts) == 2:
                        existing.add((parts[0].strip(), parts[1].strip()))
    
    return existing


def find_candidates(cooccurrence, existing_synthesis, min_cooccurrence=2):
    """Find high-value synthesis candidates."""
    candidates = []
    
    for (a, b), count in cooccurrence.items():
        if count < min_cooccurrence:
            continue
        
        # Skip if already synthesized
        pair = (a, b)
        reverse = (b, a)
        if pair in existing_synthesis or reverse in existing_synthesis:
            continue
        
        # Skip if either is a system page
        if a.startswith('_') or b.startswith('_'):
            continue
        
        candidates.append({
            "pair": [a, b],
            "cooccurrences": count,
            "suggested_filename": f"{os.path.basename(a).replace('_', '-')}-x-{os.path.basename(b).replace('_', '-')}.md",
        })
    
    # Sort by co-occurrence count descending
    candidates.sort(key=lambda x: x["cooccurrences"], reverse=True)
    
    return candidates


def main():
    args = parse_args()
    
    page_links = scan_vault(args.vault)
    cooccurrence, target_pages = build_cooccurrence(page_links)
    existing_synthesis = find_existing_synthesis(args.vault)
    candidates = find_candidates(cooccurrence, existing_synthesis, args.min_cooccurrence)
    
    result = {
        "vault": args.vault,
        "pages_scanned": len(page_links),
        "existing_synthesis": len(existing_synthesis),
        "total_cooccurrences": len(cooccurrence),
        "candidates": candidates,
        "top_linked": dict(sorted(
            [(k, len(v)) for k, v in target_pages.items()],
            key=lambda x: x[1], reverse=True
        )[:20]),
    }
    
    output_json = json.dumps(result, indent=2, default=str)
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json)
        print(f"Synthesis analysis written to {output_path}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
