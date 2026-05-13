#!/usr/bin/env python3
"""
stub_projects.py — Create minimal project pages for journal wikilink targets.

Journal entries reference projects via ``[[projects/<slug>]]`` wikilinks.
If the target page doesn't exist yet, Obsidian shows a broken link.  This
script walks a journal entry (or the whole journal/ tree) and creates a
minimal stub at the referenced path so links resolve.  The projects-sync
phase later enriches these stubs with real content.

Stubs are intentionally thin: title + lifecycle=stub + a one-line
placeholder.  They exist purely so wikilinks aren't broken and so the
projects phase has a clear list of what to enrich (lifecycle=stub
becomes a search key).

Usage:
    python scripts/stub_projects.py --vault PATH [--journal-date YYYY-MM-DD]
    python scripts/stub_projects.py --vault PATH --all-journals
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
PROJECT_REF = re.compile(r"^projects/([^/]+)(?:/[^/]+)?$")


def journal_paths(vault: Path, date: str | None, all_journals: bool):
    j = vault / "journal"
    if not j.is_dir():
        return []
    if date:
        f = j / f"{date}.md"
        return [f] if f.is_file() else []
    if all_journals:
        return sorted(j.glob("*.md"))
    # Default: just the most recent
    files = sorted(j.glob("*.md"))
    return [files[-1]] if files else []


def referenced_project_slugs(journal_files: list[Path]) -> set[str]:
    """Return the set of project slugs referenced by ``[[projects/<slug>]]``.

    Strips a trailing ``.md`` if the model wrote the wikilink with an
    explicit extension (Obsidian renders either form identically).
    """
    slugs: set[str] = set()
    for f in journal_files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in WIKILINK.finditer(text):
            target = m.group(1).strip()
            pm = PROJECT_REF.match(target)
            if pm:
                slug = pm.group(1)
                if slug.endswith(".md"):
                    slug = slug[:-3]
                slugs.add(slug)
    return slugs


def stub_path(vault: Path, slug: str) -> Path:
    """Canonical stub location: ``projects/<slug>.md`` (flat).

    The vault keeps project pages flat — no per-project directories — so
    a ``[[projects/foo]]`` wikilink resolves to ``projects/foo.md``.
    """
    return vault / "projects" / f"{slug}.md"


# Slugs whose display name doesn't fall out of simple kebab-→-Title Case.
# Mirrored in AGENTS.md.  Add a row here when introducing a new condensed
# slug; the projects-sync phase reads AGENTS.md and will pick up the right
# display name regardless, but seeding the stub with the correct title
# keeps the page-list looking right even before enrichment runs.
_SLUG_DISPLAY_OVERRIDES: dict[str, str] = {
    "aidenlabs": "Aiden Labs",
    "aidenlabs-landing-page": "Aiden Labs Landing Page",
    "aidenlabs-branding": "Aiden Labs Branding",
    "aidenlabs-infrastructure": "Aiden Labs Infrastructure",
}


def title_from_slug(slug: str) -> str:
    """Reasonable default title — projects-sync will overwrite this anyway.

    Honours :data:`_SLUG_DISPLAY_OVERRIDES` for condensed slugs whose
    display form doesn't trivially fall out of kebab-→-Title Case.
    """
    if slug in _SLUG_DISPLAY_OVERRIDES:
        return _SLUG_DISPLAY_OVERRIDES[slug]
    return " ".join(part.capitalize() for part in slug.split("-"))


def write_stub(path: Path, slug: str) -> bool:
    """Create the stub.  Returns True if newly written, False if skipped."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = (
      f"---\n"
      f'title: "{title_from_slug(slug)}"\n'
      f'summary: "Stub created from journal wikilink — needs enrichment."\n'
      f"lifecycle: stub\n"
      f'created: "{iso}"\n'
      f'updated: "{iso}"\n'
      f"tags: [project, stub]\n"
      f"---\n"
      f"\n"
      f"# {title_from_slug(slug)}\n"
      f"\n"
      f"*This page is a stub created automatically when a journal entry "
      f"first referenced `[[projects/{slug}]]`. The next projects-sync "
      f"phase will replace this placeholder with a real overview "
      f"(status, architecture, timeline, related work) drawn from "
      f"journals and source code.*\n"
    )
    path.write_text(body, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", required=True, type=Path)
    g = ap.add_mutually_exclusive_group()
    g.add_argument(
      "--journal-date",
      help="Stub for one specific journal date (YYYY-MM-DD)",
    )
    g.add_argument(
      "--all-journals",
      action="store_true",
      help="Scan every journal entry (use to backfill after a fresh import)",
    )
    args = ap.parse_args()

    files = journal_paths(args.vault, args.journal_date, args.all_journals)
    if not files:
      print("stub-projects: no journal files to scan", file=sys.stderr)
      return 0

    slugs = referenced_project_slugs(files)
    if not slugs:
      print(f"stub-projects: 0 project refs across {len(files)} journal(s)")
      return 0

    created = 0
    for slug in sorted(slugs):
      path = stub_path(args.vault, slug)
      if write_stub(path, slug):
        created += 1
        print(f"stub-projects: created {path.relative_to(args.vault)}")
    print(
      f"stub-projects: scanned {len(files)} journal(s), "
      f"referenced {len(slugs)} project(s), created {created} stub(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
