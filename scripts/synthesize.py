#!/usr/bin/env python3
"""synthesize.py — Candidate selection for synthesis pages.

Single source of truth for the mechanical candidate scan.  `pipeline.py
synthesis` calls into this module; the standalone CLI here is for
debugging.

## Scoring model

A pair's score is the sum of weighted contributions from every page that
co-mentions both:

* Journal pages (``journal/YYYY-MM-DD.md``): weight =
  ``exp(-(today - date).days / half_life_days)``.  Default half-life 60
  days, so a journal halves in ~2 months and is at ~6% after 6 months.
* Non-journal pages (projects, synthesis, root, _meta): weight = 1.0
  (evergreen baseline — an explicit cross-reference in a project page
  always counts as a strong signal).

This addresses the "old high-count pair monopolises top-N" failure mode:
ancient journal co-occurrence fades, while genuinely persistent
connections (re-mentioned in recent journals, or anchored in project
pages) keep their score.

## Bucketed selection

Top-N is split into two buckets so new pairs aren't starved by always-on
refreshes of existing pages:

* ``fresh`` — pairs with no synthesis page yet.  Default 8 slots.
* ``refresh`` — pairs with an existing synthesis page that has gained
  score since its last update.  Default 7 slots.

Each bucket is ranked independently:

* ``fresh`` by absolute weighted score.
* ``refresh`` by *delta_score* = current_score − last_recorded_score.
  Reading current and last from the synthesis page's frontmatter
  (``last_cooccurrence_score``).  Missing last_score (legacy pages)
  → delta_score = current_score, so legacy pages get picked once and
  then tracked.

Refresh has no time-based cooldown — ``min_refresh_delta`` does the
real work.  A page only qualifies for refresh when its weighted score
has grown by at least ``min_refresh_delta`` (default 0.5) since the
``last_cooccurrence_score`` recorded in its frontmatter.  If nothing
new has happened, delta is near zero and the candidate drops out
without needing a separate timer.

If either bucket is short of its target, the remainder spills into the
other so the total budget is preserved.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import combinations
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Page scanning
# ---------------------------------------------------------------------------

_JOURNAL_DATE = re.compile(r"^(?:journal/)?(\d{4}-\d{2}-\d{2})$")
_WIKILINK = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


@dataclass
class PageInfo:
  rel_path: str
  links: set[str]
  is_journal: bool
  journal_date: date | None  # YYYY-MM-DD parsed from filename for journals


def _extract_wiki_links(content: str) -> list[str]:
  out: list[str] = []
  for m in _WIKILINK.finditer(content):
    target = m.group(1).strip()
    if not target:
      continue
    if target.endswith(".md"):
      target = target[:-3]
    out.append(target)
  return out


def _journal_date_for(rel_path: str) -> date | None:
  stem = os.path.basename(rel_path)
  if stem.endswith(".md"):
    stem = stem[:-3]
  m = _JOURNAL_DATE.match(stem)
  if m:
    try:
      return date.fromisoformat(m.group(1))
    except ValueError:
      return None
  return None


def scan_vault(vault: Path) -> dict[str, PageInfo]:
  """Walk the vault and collect wikilinks + journal-date metadata."""
  pages: dict[str, PageInfo] = {}
  for root, dirs, files in os.walk(vault):
    dirs[:] = [d for d in dirs if not d.startswith(".")]
    for filename in files:
      if not filename.endswith(".md") or filename.startswith("."):
        continue
      filepath = Path(root) / filename
      rel_path = str(filepath.relative_to(vault))
      try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
      except OSError:
        continue
      links = set(_extract_wiki_links(content))
      if not links:
        continue
      jdate = _journal_date_for(rel_path)
      pages[rel_path] = PageInfo(
        rel_path=rel_path,
        links=links,
        is_journal=jdate is not None,
        journal_date=jdate,
      )
  return pages


# ---------------------------------------------------------------------------
# Co-occurrence scoring
# ---------------------------------------------------------------------------


def _page_weight(page: PageInfo, today: date, half_life_days: int) -> float:
  if not page.is_journal or page.journal_date is None:
    return 1.0  # evergreen
  age_days = max(0, (today - page.journal_date).days)
  return math.exp(-age_days / half_life_days)


@dataclass
class PairScore:
  raw_count: int = 0
  weighted_score: float = 0.0
  contributing_pages: list[tuple[str, float]] = field(default_factory=list)


def build_cooccurrence(
  pages: dict[str, PageInfo],
  today: date,
  half_life_days: int = 60,
) -> dict[tuple[str, str], PairScore]:
  cooc: dict[tuple[str, str], PairScore] = defaultdict(PairScore)
  for page in pages.values():
    w = _page_weight(page, today, half_life_days)
    if w <= 0:
      continue
    for a, b in combinations(sorted(page.links), 2):
      ps = cooc[(a, b)]
      ps.raw_count += 1
      ps.weighted_score += w
      ps.contributing_pages.append((page.rel_path, w))
  return cooc


# ---------------------------------------------------------------------------
# Existing synthesis pages
# ---------------------------------------------------------------------------


@dataclass
class SynthesisMeta:
  rel_path: str
  basenames: frozenset[str]
  updated: date | None
  last_score: float | None


def _parse_frontmatter_kv(content: str) -> dict[str, str]:
  m = _FRONTMATTER.search(content)
  if not m:
    return {}
  out: dict[str, str] = {}
  for line in m.group(1).splitlines():
    if ":" in line and not line.lstrip().startswith("-"):
      k, v = line.split(":", 1)
      out[k.strip()] = v.strip().strip('"').strip("'")
  return out


def _parse_updated(value: str | None) -> date | None:
  if not value:
    return None
  # ISO datetime or bare date
  try:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
  except ValueError:
    try:
      return date.fromisoformat(value[:10])
    except ValueError:
      return None


def load_existing_synthesis(vault: Path) -> dict[frozenset, SynthesisMeta]:
  """Returns ``{frozenset({base_a, base_b}): SynthesisMeta}``.

  Basenames (slug only — no folder prefix) are used because filenames
  are flat slugs while cooc keys may carry directory prefixes.
  """
  out: dict[frozenset, SynthesisMeta] = {}
  synth_dir = vault / "synthesis"
  if not synth_dir.is_dir():
    return out
  for p in synth_dir.iterdir():
    if not p.is_file() or p.suffix != ".md":
      continue
    name = p.stem
    if "-x-" not in name:
      continue
    a, b = name.split("-x-", 1)
    key = frozenset({a.strip(), b.strip()})
    try:
      content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
      content = ""
    fm = _parse_frontmatter_kv(content)
    updated = _parse_updated(fm.get("updated"))
    last_score = None
    raw = fm.get("last_cooccurrence_score")
    if raw:
      try:
        last_score = float(raw)
      except ValueError:
        pass
    out[key] = SynthesisMeta(
      rel_path=f"synthesis/{p.name}",
      basenames=key,
      updated=updated,
      last_score=last_score,
    )
  return out


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _is_journal_token(name: str) -> bool:
  """Identify journal-date page references — they should never be in a
  synthesis pair because every journal mechanically co-occurs with every
  project mentioned that day."""
  basename = os.path.basename(name)
  return bool(
    _JOURNAL_DATE.match(name) or _JOURNAL_DATE.match(basename),
  )


@dataclass
class Candidate:
  pair: tuple[str, str]
  base_a: str
  base_b: str
  weighted_score: float
  raw_cooccurrence: int
  existing: bool
  existing_path: str | None = None
  last_updated: date | None = None
  days_since_update: int | None = None
  last_score: float | None = None
  delta_score: float | None = None
  bucket: str = ""  # fresh | refresh | cooldown | excluded
  excluded_reason: str | None = None

  @property
  def suggested_filename(self) -> str:
    return f"{self.base_a}-x-{self.base_b}.md"

  def to_dict(self) -> dict:
    out: dict = {
      "pair": list(self.pair),
      "weighted_score": round(self.weighted_score, 3),
      "raw_cooccurrence": self.raw_cooccurrence,
      "existing": self.existing,
      "suggested_filename": self.suggested_filename,
      "bucket": self.bucket,
    }
    if self.existing:
      out["existing_path"] = self.existing_path
      out["last_updated"] = self.last_updated.isoformat() if self.last_updated else None
      out["days_since_update"] = self.days_since_update
      out["last_score"] = (
        round(self.last_score, 3) if self.last_score is not None else None
      )
      out["delta_score"] = (
        round(self.delta_score, 3) if self.delta_score is not None else None
      )
    if self.excluded_reason:
      out["excluded_reason"] = self.excluded_reason
    return out


def _build_candidate(
  pair: tuple[str, str],
  score: PairScore,
  existing_map: dict[frozenset, SynthesisMeta],
  today: date,
) -> Candidate:
  a, b = pair
  base_a = os.path.basename(a).replace("_", "-")
  base_b = os.path.basename(b).replace("_", "-")
  key = frozenset({base_a, base_b})
  cand = Candidate(
    pair=pair,
    base_a=base_a,
    base_b=base_b,
    weighted_score=score.weighted_score,
    raw_cooccurrence=score.raw_count,
    existing=key in existing_map,
  )
  if cand.existing:
    meta = existing_map[key]
    cand.existing_path = meta.rel_path
    cand.last_updated = meta.updated
    if meta.updated is not None:
      cand.days_since_update = (today - meta.updated).days
    cand.last_score = meta.last_score
    # Delta: how much new momentum since the page was last refreshed.
    # If no recorded last_score (legacy page), treat current score as
    # the delta so it gets picked once and then tracked thereafter.
    if meta.last_score is None:
      cand.delta_score = cand.weighted_score
    else:
      cand.delta_score = cand.weighted_score - meta.last_score
  return cand


def find_candidates(
  cooc: dict[tuple[str, str], PairScore],
  existing_map: dict[frozenset, SynthesisMeta],
  today: date,
  min_score: float = 1.5,
  n_fresh: int = 8,
  n_refresh: int = 7,
  min_refresh_delta: float = 0.5,
) -> dict:
  fresh_pool: list[Candidate] = []
  refresh_pool: list[Candidate] = []
  excluded: list[Candidate] = []

  for pair, score in cooc.items():
    a, b = pair
    cand = _build_candidate(pair, score, existing_map, today)

    if a.startswith("_") or b.startswith("_"):
      cand.bucket = "excluded"
      cand.excluded_reason = "system-page"
      excluded.append(cand)
      continue
    if _is_journal_token(a) or _is_journal_token(b):
      cand.bucket = "excluded"
      cand.excluded_reason = "journal-pair"
      excluded.append(cand)
      continue
    # Synthesis pages themselves can be linked to, but pairing a project
    # with an existing synthesis to make a new "tri-synthesis" is meta-
    # noise.  Skip any pair where one side is already in synthesis/.
    if a.startswith("synthesis/") or b.startswith("synthesis/"):
      cand.bucket = "excluded"
      cand.excluded_reason = "synthesis-as-target"
      excluded.append(cand)
      continue
    if score.weighted_score < min_score:
      cand.bucket = "excluded"
      cand.excluded_reason = "below-min-score"
      excluded.append(cand)
      continue

    if not cand.existing:
      cand.bucket = "fresh"
      fresh_pool.append(cand)
      continue

    # Existing — refresh path.  Gate on momentum: a page only qualifies
    # for refresh when its weighted score has grown by at least
    # ``min_refresh_delta`` since the recorded last_cooccurrence_score.
    # Pages with no recorded last_score (legacy / first-time) get
    # delta_score = full current score, so they always qualify once.
    if (
      cand.delta_score is not None
      and cand.delta_score < min_refresh_delta
    ):
      cand.bucket = "no-delta"
      cand.excluded_reason = (
        f"delta_score {cand.delta_score:.2f} < {min_refresh_delta}"
      )
      excluded.append(cand)
      continue

    cand.bucket = "refresh"
    refresh_pool.append(cand)

  fresh_pool.sort(key=lambda c: c.weighted_score, reverse=True)
  refresh_pool.sort(
    key=lambda c: (c.delta_score or 0.0, c.weighted_score),
    reverse=True,
  )

  fresh = fresh_pool[:n_fresh]
  refresh = refresh_pool[:n_refresh]

  # Spill: if one bucket can't fill its budget, the other gets the
  # remainder.  Total budget = n_fresh + n_refresh always.
  fresh_short = n_fresh - len(fresh)
  refresh_short = n_refresh - len(refresh)
  if fresh_short and len(refresh_pool) > n_refresh:
    refresh += refresh_pool[n_refresh : n_refresh + fresh_short]
  if refresh_short and len(fresh_pool) > n_fresh:
    fresh += fresh_pool[n_fresh : n_fresh + refresh_short]

  return {
    "fresh": fresh,
    "refresh": refresh,
    "fresh_pool_size": len(fresh_pool),
    "refresh_pool_size": len(refresh_pool),
    "excluded": excluded,
  }


# ---------------------------------------------------------------------------
# Top-level analysis (called by pipeline.py and CLI)
# ---------------------------------------------------------------------------


def analyse(
  vault: Path,
  today: date | None = None,
  half_life_days: int = 60,
  min_score: float = 1.5,
  n_fresh: int = 8,
  n_refresh: int = 7,
  min_refresh_delta: float = 0.5,
) -> dict:
  today = today or date.today()
  pages = scan_vault(vault)
  cooc = build_cooccurrence(pages, today, half_life_days)
  existing_map = load_existing_synthesis(vault)
  selection = find_candidates(
    cooc=cooc,
    existing_map=existing_map,
    today=today,
    min_score=min_score,
    n_fresh=n_fresh,
    n_refresh=n_refresh,
    min_refresh_delta=min_refresh_delta,
  )

  # Page-link target popularity, useful for the prompt and for debugging.
  target_pages: dict[str, set[str]] = defaultdict(set)
  for page in pages.values():
    for link in page.links:
      target_pages[link].add(page.rel_path)

  candidates_dicts = [c.to_dict() for c in selection["fresh"] + selection["refresh"]]
  return {
    "vault": str(vault),
    "today": today.isoformat(),
    "half_life_days": half_life_days,
    "pages_scanned": len(pages),
    "existing_synthesis": len(existing_map),
    "total_pairs": len(cooc),
    "buckets": {
      "fresh": [c.to_dict() for c in selection["fresh"]],
      "refresh": [c.to_dict() for c in selection["refresh"]],
    },
    "pool_sizes": {
      "fresh": selection["fresh_pool_size"],
      "refresh": selection["refresh_pool_size"],
    },
    # Flat list for backward compatibility with anything that read
    # ``result["candidates"]`` (the prompt template, mostly).  Same
    # objects, both buckets, fresh first then refresh.
    "candidates": candidates_dicts,
    "excluded_sample": [c.to_dict() for c in selection["excluded"][:30]],
    "top_linked": dict(
      sorted(
        [(k, len(v)) for k, v in target_pages.items()],
        key=lambda x: x[1],
        reverse=True,
      )[:20]
    ),
  }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
  ap = argparse.ArgumentParser(description="Synthesis candidate scan")
  ap.add_argument("--vault", required=True, help="Path to Obsidian vault")
  ap.add_argument("--output", default=None, help="Output JSON path (default: stdout)")
  ap.add_argument("--half-life-days", type=int, default=60)
  ap.add_argument("--min-score", type=float, default=1.5)
  ap.add_argument("--n-fresh", type=int, default=8)
  ap.add_argument("--n-refresh", type=int, default=7)
  ap.add_argument("--min-refresh-delta", type=float, default=0.5)
  args = ap.parse_args()

  result = analyse(
    vault=Path(args.vault),
    half_life_days=args.half_life_days,
    min_score=args.min_score,
    n_fresh=args.n_fresh,
    n_refresh=args.n_refresh,
    min_refresh_delta=args.min_refresh_delta,
  )
  output_json = json.dumps(result, indent=2, default=str)
  if args.output:
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_json)
    print(f"Synthesis analysis → {output_path}", file=sys.stderr)
  else:
    print(output_json)
  return 0


if __name__ == "__main__":
  sys.exit(main())
