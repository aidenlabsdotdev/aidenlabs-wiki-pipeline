---
name: synthesis-generation
description: >
  Draft synthesis pages for co-occurring concepts.  Reads bucketed
  candidates from mechanical analysis (fresh + refresh), then creates or
  updates cross-project synthesis pages.
  Input: synthesis-candidates.json, source project/concept pages.
  Output: synthesis/<A>-x-<B>.md
---

# Synthesis Generation Prompt

Draft and refresh synthesis pages for the bucketed candidates listed in
the candidates file.

## Context Files

Read these files first:
- `{{candidates_path}}` — bucketed synthesis candidates
- `{{vault_path}}/AGENTS.md` — Vault conventions
- For each candidate, read the two source pages it links

## Candidate Buckets

The candidates file groups picks under `buckets.fresh` and
`buckets.refresh`.  Treat them differently:

- **`bucket: "fresh"`** — no synthesis page exists yet.  Create one from
  scratch at `synthesis/<suggested_filename>` (the file value is already
  the correct slug).
- **`bucket: "refresh"`** — a synthesis page already exists at
  `existing_path`.  The candidate has `delta_score > 0`, meaning new
  co-occurrence has accumulated since the page was last updated.
  **Read the existing page first, then merge** — preserve prior
  analysis, timeline entries, and provenance markers.  Add the new
  co-occurrences under "Where They Co-occur", and update
  "Cross-cutting Insight" with whatever the new mentions actually
  reveal.  Don't rewrite; augment.  This is the llm-wiki compounding
  pattern.

Process every entry in both buckets unless rule 1 disqualifies it.

## Page Format

```markdown
---
title: "{{A Name}} × {{B Name}}"
summary: "How A and B connect and what that reveals"
base_confidence: 0.6
lifecycle: draft
provenance:
  extracted: ~0.5
  inferred: ~0.4
  ambiguous: ~0.1
created: "{{iso_timestamp}}"
updated: "{{iso_timestamp}}"
last_cooccurrence_score: <weighted_score from the candidate>
tags: [synthesis]
---

# {{A Name}} × {{B Name}}

## Connection

How these two topics relate to each other.  What's the fundamental link?

## Where They Co-occur

Pages that reference both topics:
- [[page-one]] — context of co-occurrence
- [[page-two]] — context of co-occurrence

## Cross-cutting Insight

What does this connection reveal?  Patterns, synergies, shared principles.

## Tensions

Contradictions, trade-offs, or areas where the two concepts conflict.

## Open Questions

Unresolved areas at the intersection of these topics.
```

## Rules

1. **Only synthesize pairs with genuine connections.**  The mechanical
   scan can't tell insight from incidental adjacency.  If two pages co-
   occur only because they were both worked on in the same week, skip —
   just don't create or update the page for that pair.
2. **Back-link from source pages.**  After writing the synthesis page,
   add a wikilink to it from each of the two source pages (typically
   under their "Related" or "Related Projects" section).
3. **Refresh = augment, never rewrite.**  For `bucket: "refresh"`
   candidates, read the existing page first.  Preserve prior analysis,
   timeline, and provenance markers.  Add new co-occurrences and update
   the Cross-cutting Insight only with the new evidence.  Bump
   `updated:` to `{{iso_timestamp}}`.
4. **Record `last_cooccurrence_score` in frontmatter.**  Set it to the
   candidate's `weighted_score`.  The next pipeline run reads this to
   compute delta_score and decide whether the page needs another
   refresh.  Omitting it forces the next run to treat the page as if it
   has never been refreshed (false positive refresh).
5. **PII redacted** per AGENTS.md rules.
6. **YAML frontmatter conventions.**  String values use double quotes.
   `tags` is a YAML list — write `tags: [synthesis, X, Y]` with no
   surrounding quotes (quoting collapses the list into a single literal
   tag).
7. **Use provenance markers**: ^[inferred] for synthesized connections,
   ^[ambiguous] for contested interpretations.
8. **Focus on insight**, not commonality listing.
