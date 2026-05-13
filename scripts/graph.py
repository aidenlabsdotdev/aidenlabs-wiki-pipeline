#!/usr/bin/env python3
"""
Wiki Knowledge Graph — Build a NetworkX graph from the Obsidian vault.

Nodes: markdown pages (excluding _meta/, journal/)
Edges: wikilinks between pages, weighted by co-occurrence count
Edge metadata: categories, shared tags, existing synthesis page

Usage:
    python scripts/pipeline.py graph --vault ~/Obsidian/aidenlabs/
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

try:
    import networkx as nx
except ImportError:
    print("networkx not installed: pip install networkx", file=sys.stderr)
    sys.exit(1)


def parse_frontmatter(content):
    """Extract YAML frontmatter from markdown content."""
    fm = {}
    if not content.startswith("---"):
        return fm
    parts = content.split("---", 2)
    if len(parts) < 3:
        return fm
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "tags" and val.startswith("[") and val.endswith("]"):
                # Parse tag list
                val = [t.strip().strip('"').strip("'") for t in val[1:-1].split(",")]
            elif key in ("created", "updated", "lifecycle_changed"):
                pass  # keep as string
            fm[key] = val
    return fm


def extract_wikilinks(content):
    """Extract [[wikilinks]] from markdown content."""
    links = []
    for match in re.finditer(r"\[\[([^]|]+?)(?:\|[^]]+?)?\]\]", content):
        target = match.group(1).strip()
        # Remove .md extension for normalization
        if target.endswith(".md"):
            target = target[:-3]
        links.append(target)
    return links


def scan_vault(vault_path):
    """Scan vault for all markdown files, returning {path: {content, fm, links}}."""
    pages = {}
    skip_dirs = {"_meta", ".git", "node_modules"}

    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, vault_path)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            fm = parse_frontmatter(content)
            links = extract_wikilinks(content)
            pages[rel] = {
                "content": content,
                "fm": fm,
                "links": links,
                "folder": os.path.dirname(rel),
            }
    return pages


def build_graph(pages):
    """Build a NetworkX graph from pages and their wikilinks."""
    G = nx.DiGraph()

    # Add nodes with metadata
    for path, info in pages.items():
        slug = path.replace("/", "-").replace(".md", "")
        folder = info["folder"]
        fm = info["fm"]
        title = fm.get("title", path.split("/")[-1].replace(".md", "").replace("-", " ").title())
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        G.add_node(path, title=title, folder=folder, tags=tags, **fm)

    # Track edge weights (co-occurrence)
    edge_weight = defaultdict(int)

    # Add edges from direct wikilinks
    for path, info in pages.items():
        for link_target in info["links"]:
            # Normalize: try to find matching page
            matched = None
            for p in pages:
                p_normalized = p.replace(".md", "")
                if p_normalized == link_target or p_normalized.endswith("/" + link_target):
                    matched = p
                    break
            if matched and matched != path:
                edge_weight[(path, matched)] += 1
                G.add_edge(path, matched)

    # Compute co-occurrence: how many other pages link to BOTH A and B
    backlinks = defaultdict(set)
    for path, info in pages.items():
        for link_target in info["links"]:
            for p in pages:
                p_normalized = p.replace(".md", "")
                if p_normalized == link_target or p_normalized.endswith("/" + link_target):
                    backlinks[p].add(path)

    # Co-occurrence: pages that share common backlink sources
    node_list = list(G.nodes())
    for i in range(len(node_list)):
        for j in range(i + 1, len(node_list)):
            a, b = node_list[i], node_list[j]
            shared = backlinks[a] & backlinks[b]
            if shared:
                weight = len(shared)
                # Only add co-occurrence edge if no direct edge exists
                if not G.has_edge(a, b) and not G.has_edge(b, a):
                    G.add_edge(a, b, co_occurrence=weight)
                    edge_weight[(a, b)] = max(edge_weight.get((a, b), 0), weight)

    # Set edge weights
    for u, v in G.edges():
        w = edge_weight.get((u, v), 1)
        if w > 1:
            G[u][v]["weight"] = w

    return G


def compute_synthesis_candidates(G, existing_synthesis):
    """Identify top synthesis candidates based on edge scores."""
    candidates = []

    for u, v, data in G.edges(data=True):
        # Skip if already synthesized
        slug_a = u.replace("/", "-").replace(".md", "")
        slug_b = v.replace("/", "-").replace(".md", "")
        pair_slug = f"{slug_a}-x-{slug_b}"
        reverse_slug = f"{slug_b}-x-{slug_a}"

        already_done = False
        for syn in existing_synthesis:
            syn_base = os.path.splitext(os.path.basename(syn))[0]
            if syn_base == pair_slug or syn_base == reverse_slug:
                already_done = True
                break
        if already_done:
            continue

        # Skip journal-to-journal edges
        if "/journal/" in u and "/journal/" in v:
            continue

        weight = data.get("weight", data.get("co_occurrence", 1))

        # Score with bonuses
        score = min(weight, 5)  # cap raw weight at 5

        # Cross-domain bonus
        folder_a = G.nodes[u].get("folder", "")
        folder_b = G.nodes[v].get("folder", "")
        if folder_a and folder_b and folder_a != folder_b:
            score += 2

        # Hub bonus
        deg_a = G.degree(u)
        deg_b = G.degree(v)
        if deg_a >= 5 or deg_b >= 5:
            score += 1

        # Shared tags bonus
        tags_a = set(G.nodes[u].get("tags", []) or [])
        tags_b = set(G.nodes[v].get("tags", []) or [])
        if tags_a & tags_b:
            score += 1

        candidates.append({
            "source": u,
            "target": v,
            "title_a": G.nodes[u].get("title", u),
            "title_b": G.nodes[v].get("title", v),
            "weight": weight,
            "score": score,
            "folder_a": folder_a,
            "folder_b": folder_b,
            "shared_tags": list(tags_a & tags_b),
        })

    # Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def export_graph(G, pages, candidates, output_path):
    """Export graph as JSON for consumption by other tools."""
    nodes = []
    for path, data in G.nodes(data=True):
        nodes.append({
            "id": path,
            "title": data.get("title", path),
            "folder": data.get("folder", ""),
            "tags": data.get("tags", []),
            "in_degree": G.in_degree(path),
            "out_degree": G.out_degree(path),
            "total_degree": G.degree(path),
        })

    edges = []
    for u, v, data in G.edges(data=True):
        edges.append({
            "source": u,
            "target": v,
            "weight": data.get("weight", data.get("co_occurrence", 1)),
        })

    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "nodes": sorted(nodes, key=lambda n: n["total_degree"], reverse=True),
        "edges": sorted(edges, key=lambda e: e["weight"], reverse=True),
        "synthesis_candidates": candidates[:20],  # top 20
        "stats": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "density": round(nx.density(G), 4),
            "avg_degree": round(sum(d for _, d in G.degree()) / max(G.number_of_nodes(), 1), 2),
        },
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="Build wiki knowledge graph")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault")
    args = parser.parse_args()

    vault = os.path.expanduser(args.vault)
    meta_dir = os.path.join(vault, "_meta")
    os.makedirs(meta_dir, exist_ok=True)

    # Scan pages
    pages = scan_vault(vault)
    print(f"Scanned {len(pages)} pages")

    # Find existing synthesis pages
    synthesis_dir = os.path.join(vault, "synthesis")
    existing_synthesis = []
    if os.path.isdir(synthesis_dir):
        for f in os.listdir(synthesis_dir):
            if f.endswith(".md"):
                existing_synthesis.append(f)

    # Build graph
    G = build_graph(pages)
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Compute candidates
    candidates = compute_synthesis_candidates(G, existing_synthesis)
    print(f"Synthesis candidates: {len(candidates)}")

    # Export
    output = os.path.join(meta_dir, "graph.json")
    result = export_graph(G, pages, candidates, output)

    print(f"\nGraph exported → {output}")
    print(f"Stats: density={result['stats']['density']}, avg_degree={result['stats']['avg_degree']}")

    if candidates:
        print(f"\nTop 5 synthesis candidates:")
        for i, c in enumerate(candidates[:5]):
            print(f"  {i+1}. {c['title_a']} × {c['title_b']} (score={c['score']}, weight={c['weight']})")


if __name__ == "__main__":
    main()
