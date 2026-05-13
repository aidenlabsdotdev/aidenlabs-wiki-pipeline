#!/usr/bin/env python3
"""lint.py — Mechanical health checks for the vault.

Follows the llm-wiki maintenance pattern: periodic lint over the corpus
to catch the kinds of rot that accumulate when the LLM compiles entries
incrementally.  Two passes today:

1. **Stale projects** — pages with ``Status: active`` (or no Status set)
   that haven't been mentioned in any journal in the last
   ``--stale-threshold-days`` days.  Such pages have likely drifted out
   of reality.  Either the work paused (Status should change) or the
   page is abandoned.
2. **Data gaps** — pages missing required sections per AGENTS.md.
   A project page without ``## Status`` or ``## Timeline`` is incomplete;
   a synthesis page without ``## Cross-cutting Insight`` is just a
   listing.

Output: writes findings to ``_meta/lint.md`` (auto-overwritten each
run) and prints a summary.  Exits 0 always — lint is informational,
not blocking.  ``projects-sync`` reads ``_meta/lint.md`` on its next
run and prioritises addressing flagged pages.

Future passes worth adding:
* Contradiction detection (LLM phase) — read pairs of pages and flag
  conflicting claims about the same entity.
* Confidence drift — pages whose ``base_confidence`` hasn't moved in
  months despite being touched.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Required sections per page type.  Missing → data-gap finding.
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = {
  "projects": ["Status", "Timeline"],
  "synthesis": ["Connection", "Cross-cutting Insight"],
  # Journals are short narrative records; we don't enforce shape beyond
  # what the journal prompt already validates.
}

# Page kinds we lint, keyed by top-level vault directory.
LINT_DIRS = ("projects", "synthesis")

# ``Status`` values that count as "live work" — these pages should have
# recent journal mentions or they're stale.
LIVE_STATUS = frozenset({"active", "experimental", "in-progress", "in progress"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
STATUS_LINE = re.compile(r"^Status:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
STATUS_HEADING_SCAN = re.compile(
  r"^##\s+Status\s*\n+([^\n].*?)$", re.MULTILINE | re.DOTALL,
)
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _read(p: Path) -> str:
  try:
    return p.read_text(encoding="utf-8", errors="replace")
  except OSError:
    return ""


def _h2_titles(content: str) -> set[str]:
  return {m.group(1).strip() for m in H2.finditer(content)}


def _detect_status(content: str) -> str | None:
  """Project pages express Status either as a frontmatter-adjacent line
  or under an `## Status` heading.  Try both."""
  m = STATUS_LINE.search(content)
  if m:
    return m.group(1).strip().lower()
  m = STATUS_HEADING_SCAN.search(content)
  if m:
    first_line = m.group(1).strip().splitlines()[0]
    return first_line.lower()
  return None


def _journal_mentions(
  journal_dir: Path,
  page_slug: str,
  page_title: str | None,
  since: date,
) -> tuple[int, date | None]:
  """Count journal entries dated >= ``since`` that mention this page,
  plus the most-recent mention date.

  A page is "mentioned" if its wikilink slug or any reasonable title
  variant appears in the journal text.
  """
  if not journal_dir.is_dir():
    return 0, None
  needle_slug = page_slug.lower()
  needle_title = (page_title or "").lower()
  count = 0
  latest: date | None = None
  for j in sorted(journal_dir.glob("*.md")):
    try:
      jd = date.fromisoformat(j.stem)
    except ValueError:
      continue
    if jd < since:
      continue
    text = _read(j).lower()
    if needle_slug in text or (needle_title and needle_title in text):
      count += 1
      if latest is None or jd > latest:
        latest = jd
  return count, latest


def _page_title_from_frontmatter(content: str) -> str | None:
  m = FRONTMATTER.search(content)
  if not m:
    return None
  for line in m.group(1).splitlines():
    if line.startswith("title:"):
      v = line.split(":", 1)[1].strip().strip('"').strip("'")
      return v
  return None


# ---------------------------------------------------------------------------
# Lint passes
# ---------------------------------------------------------------------------


def find_stale_projects(
  vault: Path, threshold_days: int
) -> list[dict]:
  """Pages with 'live'/no-Status that haven't been mentioned in N days."""
  findings: list[dict] = []
  cutoff = date.today() - timedelta(days=threshold_days)
  for p in sorted((vault / "projects").glob("*.md")):
    slug = p.stem
    content = _read(p)
    if not content:
      continue
    status = _detect_status(content)
    if status is not None and status not in LIVE_STATUS:
      # paused / completed / archived → not a stale candidate
      continue
    title = _page_title_from_frontmatter(content)
    count, latest = _journal_mentions(
      vault / "journal", slug, title, cutoff
    )
    if count == 0:
      findings.append(
        {
          "kind": "stale",
          "page": f"projects/{slug}.md",
          "status": status or "(missing)",
          "last_mention": latest.isoformat() if latest else None,
          "threshold_days": threshold_days,
        }
      )
  return findings


def find_data_gaps(vault: Path) -> list[dict]:
  """Pages missing required sections per page type."""
  findings: list[dict] = []
  for subdir, required in REQUIRED_SECTIONS.items():
    d = vault / subdir
    if not d.is_dir():
      continue
    for p in sorted(d.glob("*.md")):
      content = _read(p)
      if not content:
        continue
      have = _h2_titles(content)
      missing = [s for s in required if s not in have]
      if missing:
        findings.append(
          {
            "kind": "data-gap",
            "page": f"{subdir}/{p.stem}.md",
            "missing_sections": missing,
          }
        )
  return findings


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_lint_report(vault: Path, findings: list[dict]) -> Path:
  report = vault / "_meta" / "lint.md"
  report.parent.mkdir(parents=True, exist_ok=True)
  now = datetime.now().isoformat(timespec="seconds")
  lines: list[str] = [
    "---",
    'title: "Wiki Lint Report"',
    'summary: "Pages that may need attention — stale projects and missing sections."',
    "lifecycle: auto",
    f'updated: "{now}"',
    "tags: [meta, lint]",
    "---",
    "",
    "# Wiki Lint Report",
    "",
    f"Generated {now}.  Auto-overwritten each pipeline run.  ",
    "Mechanical checks only — no model judgement involved.",
    "",
  ]
  if not findings:
    lines += ["No findings — vault is clean.", ""]
  else:
    by_kind: dict[str, list[dict]] = {}
    for f in findings:
      by_kind.setdefault(f["kind"], []).append(f)

    stale = by_kind.get("stale", [])
    if stale:
      lines += [
        "## Stale projects",
        "",
        "Pages whose Status reads as live work but which haven't been "
        "mentioned in any journal for the configured threshold window.  "
        "Either the work paused (update Status) or the page has drifted.",
        "",
      ]
      for f in stale:
        last = f.get("last_mention") or f"never (window: {f['threshold_days']}d)"
        lines.append(
          f"- [[{f['page'].replace('.md','')}]] — status `{f['status']}`, "
          f"last journal mention: {last}"
        )
      lines.append("")

    gaps = by_kind.get("data-gap", [])
    if gaps:
      lines += [
        "## Data gaps",
        "",
        "Pages missing one or more required sections per AGENTS.md.  "
        "Project pages need `Status` and `Timeline`; synthesis pages "
        "need `Connection` and `Cross-cutting Insight`.",
        "",
      ]
      for f in gaps:
        miss = ", ".join(f"`{s}`" for s in f["missing_sections"])
        lines.append(f"- [[{f['page'].replace('.md','')}]] — missing: {miss}")
      lines.append("")

  report.write_text("\n".join(lines), encoding="utf-8")
  return report


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--vault", default=os.path.expanduser("~/Obsidian/aidenlabs"))
  ap.add_argument(
    "--stale-threshold-days",
    type=int,
    default=14,
    help="Days without a journal mention before a live project is flagged stale",
  )
  args = ap.parse_args()
  vault = Path(args.vault)
  if not vault.is_dir():
    print(f"vault not found: {vault}", file=sys.stderr)
    return 2

  findings: list[dict] = []
  findings.extend(find_stale_projects(vault, args.stale_threshold_days))
  findings.extend(find_data_gaps(vault))

  report = write_lint_report(vault, findings)
  rel = report.relative_to(vault)

  if not findings:
    print(f"lint: vault clean — wrote {rel}")
    return 0

  by_kind: dict[str, int] = {}
  for f in findings:
    by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
  print(f"lint: wrote {rel}; {len(findings)} finding(s):")
  for kind, n in sorted(by_kind.items()):
    print(f"  {kind:12s} {n}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
