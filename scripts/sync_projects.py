#!/usr/bin/env python3
"""
sync_projects.py — Discover projects from repos and session activity, output project manifest.

Scans ~/Tasks/ for repos, checks GitHub org (aidenlabsdotdev), and cross-references
with existing project pages in the vault. Outputs a JSON manifest of discovered projects
and their metadata.

Usage:
    python scripts/sync_projects.py --vault PATH [--tasks-dir PATH] [--output PATH]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_TASKS_DIR = os.path.expanduser("~/Repositories")


def parse_args():
    parser = argparse.ArgumentParser(description="Discover and sync projects")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault")
    parser.add_argument("--tasks-dir", default=DEFAULT_TASKS_DIR, help="Path to ~/Tasks/")
    parser.add_argument("--output", default=None, help="Output JSON path (default: stdout)")
    return parser.parse_args()


def scan_tasks_dir(tasks_dir):
    """Scan ~/Tasks/ for git repos and extract metadata."""
    projects = {}
    
    if not os.path.isdir(tasks_dir):
        return projects
    
    for entry in sorted(os.listdir(tasks_dir)):
        repo_path = os.path.join(tasks_dir, entry)
        if not os.path.isdir(repo_path):
            continue
        
        # Check if it's a git repo
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            continue
        
        # Extract remote URL
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5
            )
            remote = result.stdout.strip() if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            remote = None
        
        # Extract last commit info
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", "-1", "--format=%ai|%s"],
                capture_output=True, text=True, timeout=5
            )
            last_commit = result.stdout.strip() if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            last_commit = None
        
        # Skip file count — not needed for manifest
        
        projects[entry] = {
            "path": repo_path,
            "remote": remote,
            "last_commit": last_commit,
            "is_git": True,
        }
    
    return projects


def scan_vault_projects(vault_path):
    """Scan existing project pages in the vault."""
    projects = {}
    projects_dir = os.path.join(vault_path, "projects")
    
    if not os.path.isdir(projects_dir):
        return projects
    
    for entry in os.listdir(projects_dir):
        project_dir = os.path.join(projects_dir, entry)
        if not os.path.isdir(project_dir):
            continue
        
        # Check for main project page
        main_page = None
        for ext in [f"{entry}.md", f"{entry.replace('-', '_')}.md"]:
            path = os.path.join(project_dir, ext)
            if os.path.exists(path):
                main_page = ext
                break
        
        # Count sub-pages
        page_count = sum(
            1 for root, dirs, files in os.walk(project_dir)
            for f in files if f.endswith('.md')
        )
        
        # List subdirs
        subdirs = [d for d in os.listdir(project_dir) 
                   if os.path.isdir(os.path.join(project_dir, d))]
        
        projects[entry] = {
            "path": project_dir,
            "main_page": main_page,
            "page_count": page_count,
            "subdirs": subdirs,
        }
    
    return projects


def find_github_org_repos():
    """Use gh CLI to list repos in aidenlabsdotdev org."""
    repos = []
    try:
        result = subprocess.run(
            ["gh", "repo", "list", "aidenlabsdotdev", "--json", "name,url,updatedAt,isPrivate"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            repos = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    
    return repos


def build_manifest(tasks_repos, vault_projects, github_repos):
    """Cross-reference and build the final manifest. LLM decides what's a project."""
    manifest = {
        "tasks_repos": {},
        "vault_projects": {},
        "github_org_repos": [],
    }

    # Tasks repos with metadata
    for name, info in tasks_repos.items():
        slug = name.lower().replace("_", "-")
        remote = info.get("remote", "")
        manifest["tasks_repos"][slug] = {
            "path": info["path"],
            "remote": remote,
            "last_commit": info.get("last_commit"),
            "is_github_org": "aidenlabsdotdev" in remote if remote else False,
        }

    # Existing vault projects
    manifest["vault_projects"] = vault_projects

    # GitHub org repos
    for repo in github_repos:
        manifest["github_org_repos"].append({
            "name": repo.get("name"),
            "url": repo.get("url"),
            "updated_at": repo.get("updatedAt"),
            "private": repo.get("isPrivate"),
        })

    return manifest


def main():
    args = parse_args()
    
    tasks_repos = scan_tasks_dir(args.tasks_dir)
    vault_projects = scan_vault_projects(args.vault)
    github_repos = find_github_org_repos()
    
    manifest = build_manifest(tasks_repos, vault_projects, github_repos)
    
    output_json = json.dumps(manifest, indent=2, default=str)
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json)
        print(f"Manifest written to {output_path}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
