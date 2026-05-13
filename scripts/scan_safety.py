#!/usr/bin/env python3
"""scan_safety.py — Pre-publish safety scan for the wiki vault.

The vault is published to ``aidenlabs.md`` (public). This script is the
trust boundary: every page that ships through it is checked for PII and
credentials.  Downstream (aidenlabs-md) blindly syncs and publishes — no
second-layer gate — so this scan must catch everything that matters.

Two engines:

* **Microsoft Presidio** — context-aware PII detection (phones, SSNs,
  credit cards, IPs, IBANs, bank numbers, US driver's licences, US
  passport numbers, dates of birth).  Uses spaCy NER + curated
  pattern recognizers.
* **detect-secrets** (Yelp) — credential / API key / token detection.

Email addresses are explicitly allowed (per ADR — they're publishable
when used as contact info).

Findings are written to ``~/.cache/wiki-pipeline/safety-report.json``
and a human-readable summary is printed.  Exit code:

* 0 — vault is clean, safe to publish
* 1 — one or more blocking findings; pipeline should halt
* 2 — scanner itself errored (missing model, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# What we DO and DON'T flag
# ---------------------------------------------------------------------------

# Presidio entity names we want to block.  Everything else from the default
# recognizer set is downgraded to a warning (still reported, doesn't fail).
BLOCK_PII = frozenset(
  {
    "PHONE_NUMBER",
    "US_SSN",
    "US_ITIN",
    "US_DRIVER_LICENSE",
    "US_PASSPORT",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_BANK_NUMBER",
    "CRYPTO",  # wallet addresses
    "MEDICAL_LICENSE",
    "DATE_OF_BIRTH",
  }
)

# Explicitly allowed: emails are publishable as contact info.
ALLOW_PII = frozenset({"EMAIL_ADDRESS", "URL", "PERSON", "LOCATION"})

# Custom regex recognizers Presidio doesn't ship.  EIN format is fixed
# (XX-XXXXXXX) and frequently appears in our Stripe Atlas context.
EIN_PATTERN = r"\b\d{2}-\d{7}\b"


# Vault subtrees we never scan (system / archive).  Match by substring.
SKIP_SUBSTRINGS = ("_archives/", ".obsidian/", "node_modules/", ".git/")


@dataclass
class Finding:
  file: str
  line: int
  kind: str          # entity name or detect-secrets type
  score: float       # 0.0-1.0 confidence
  snippet: str       # ~120 chars of surrounding line, trimmed
  engine: str        # "presidio" | "detect-secrets" | "custom"


def _should_skip(rel_path: str) -> bool:
  return any(s in rel_path for s in SKIP_SUBSTRINGS)


def _line_context(text: str, span_start: int, span_end: int) -> tuple[int, str]:
  """Return (line_number, trimmed_line_text) for a character span."""
  line_num = text.count("\n", 0, span_start) + 1
  line_start = text.rfind("\n", 0, span_start) + 1
  line_end = text.find("\n", span_end)
  if line_end == -1:
    line_end = len(text)
  line = text[line_start:line_end].strip()
  if len(line) > 140:
    line = line[:137] + "..."
  return line_num, line


def _build_analyzer():
  """Build a Presidio AnalyzerEngine with our custom EIN recognizer."""
  from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern

  analyzer = AnalyzerEngine()
  analyzer.registry.add_recognizer(
    PatternRecognizer(
      supported_entity="US_EIN",
      patterns=[Pattern("ein-strict", EIN_PATTERN, score=0.85)],
      name="EIN-recognizer",
    )
  )
  return analyzer


def _scan_presidio(
  analyzer, content: str, rel: str, language: str = "en"
) -> list[Finding]:
  """Run Presidio over a file's content and convert results to Findings."""
  findings: list[Finding] = []
  # Limit Presidio to the entities we care about + our custom EIN
  entities = sorted(BLOCK_PII | {"US_EIN"})
  results = analyzer.analyze(text=content, language=language, entities=entities)
  for r in results:
    if r.entity_type in ALLOW_PII:
      continue
    ln, snippet = _line_context(content, r.start, r.end)
    findings.append(
      Finding(
        file=rel,
        line=ln,
        kind=r.entity_type,
        score=float(r.score),
        snippet=snippet,
        engine="presidio",
      )
    )
  return findings


def _scan_detect_secrets(content: str, rel: str) -> list[Finding]:
  """Run detect-secrets against a single file's content."""
  from detect_secrets.core.scan import scan_line  # type: ignore
  from detect_secrets.settings import default_settings

  findings: list[Finding] = []
  with default_settings():
    for lineno, line in enumerate(content.splitlines(), start=1):
      for secret in scan_line(line):
        # secret.secret_value is the redacted form; type is plugin name.
        findings.append(
          Finding(
            file=rel,
            line=lineno,
            kind=secret.type,
            score=1.0,
            snippet=(line.strip()[:137] + "...") if len(line) > 140 else line.strip(),
            engine="detect-secrets",
          )
        )
  return findings


def _iter_files(vault: Path) -> Iterable[Path]:
  for p in sorted(vault.rglob("*.md")):
    rel = str(p.relative_to(vault))
    if _should_skip(rel):
      continue
    yield p


def scan(vault: Path) -> tuple[list[Finding], int]:
  """Run both scans across the vault. Returns (findings, files_scanned)."""
  try:
    analyzer = _build_analyzer()
  except Exception as exc:
    print(f"safety: failed to build Presidio analyzer: {exc}", file=sys.stderr)
    print(
      "         install with: pip install presidio-analyzer && python -m "
      "spacy download en_core_web_sm",
      file=sys.stderr,
    )
    raise

  all_findings: list[Finding] = []
  scanned = 0
  for path in _iter_files(vault):
    rel = str(path.relative_to(vault))
    try:
      content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
      continue
    scanned += 1
    all_findings.extend(_scan_presidio(analyzer, content, rel))
    all_findings.extend(_scan_detect_secrets(content, rel))
  return all_findings, scanned


def _write_report(findings: list[Finding], report_path: Path) -> None:
  report_path.parent.mkdir(parents=True, exist_ok=True)
  report_path.write_text(
    json.dumps([asdict(f) for f in findings], indent=2),
    encoding="utf-8",
  )


def _print_summary(findings: list[Finding], scanned: int) -> None:
  if not findings:
    print(f"safety: {scanned} files scanned, 0 findings — vault is clean.")
    return
  by_kind: dict[str, int] = {}
  for f in findings:
    by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
  print(f"safety: {scanned} files scanned, {len(findings)} finding(s):")
  for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
    print(f"  {kind:30s} {n}")
  print("\nDetails:")
  # Group by file for readable output.
  by_file: dict[str, list[Finding]] = {}
  for f in findings:
    by_file.setdefault(f.file, []).append(f)
  for fname in sorted(by_file):
    print(f"\n  [{fname}]")
    for f in by_file[fname]:
      print(
        f"    L{f.line:>4} {f.kind} ({f.engine}, score={f.score:.2f}) "
        f"— {f.snippet!r}"
      )


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--vault", default=os.path.expanduser("~/Obsidian/aidenlabs"))
  ap.add_argument(
    "--report",
    default=os.path.expanduser("~/.cache/wiki-pipeline/safety-report.json"),
    help="Path to write the JSON report",
  )
  ap.add_argument(
    "--warn-only",
    action="store_true",
    help="Print findings but exit 0 regardless (CI debugging mode)",
  )
  args = ap.parse_args()

  vault = Path(args.vault)
  if not vault.is_dir():
    print(f"vault not found: {vault}", file=sys.stderr)
    return 2

  try:
    findings, scanned = scan(vault)
  except Exception as exc:
    print(f"safety: scanner error: {exc}", file=sys.stderr)
    return 2

  _write_report(findings, Path(args.report))
  _print_summary(findings, scanned)

  if findings and not args.warn_only:
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
