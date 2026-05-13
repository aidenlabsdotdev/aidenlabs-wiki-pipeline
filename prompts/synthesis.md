---
name: synthesis-generation
description: >
  Draft synthesis pages for co-occurring concepts. Reads synthesis candidates
  from mechanical analysis, then creates cross-project synthesis pages.
  Input: synthesis-candidates.json, source project/concept pages.
  Output: synthesis/<A>-x-<B>.md for top candidates
---

# Synthesis Generation Prompt

Draft synthesis pages for the top co-occurring concept pairs in the vault.

## Context Files

Read these files first:
- `{{candidates_path}}` — Synthesis candidates (co-occurrence analysis)
- `{{vault_path}}/AGENTS.md` — Vault conventions and PII redaction rules
- For each candidate pair, read the source pages being synthesized

## Output

For the **top {{top_n}}** candidates (that don't already have synthesis pages), create:
`{{vault_path}}/synthesis/{{A_slug}}-x-{{B_slug}}.md`

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
tags: [synthesis]
---

# {{A Name}} × {{B Name}}

## Connection

How these two topics relate to each other. What's the fundamental link?

## Where They Co-occur

Pages that reference both topics:
- [[page-one]] — context of co-occurrence
- [[page-two]] — context of co-occurrence

## Cross-cutting Insight

What does this connection reveal? Patterns, synergies, shared principles.

## Tensions

Contradictions, trade-offs, or areas where the two concepts conflict.

## Open Questions

Unresolved areas at the intersection of these topics.
```

## Execution Model

This prompt is designed to be executed via `delegate_task` (not `hermes chat -q`).
- **delegate_task**: Subagent sessions are NOT recorded in state.db → won't pollute future journals
- **hermes chat -q**: Creates agent sessions in state.db → WILL be harvested as activity on next run

The orchestrator reads this prompt, fills in `{{variables}}`, and passes it as the `context` to a `delegate_task` call with toolsets `["file", "terminal"]`.

## Rules

1. **Only synthesize pairs with genuine connections** — not just coincidental co-occurrence
2. **Back-link from source pages** — add wikilinks to the synthesis page from the original pages
3. **Skip existing synthesis** — if `synthesis/A-x-B.md` already exists, skip it
4. **PII redacted** per AGENTS.md rules
5. **All string values in YAML frontmatter must be double-quoted**
6. **Focus on insight**, not just listing commonalities
7. **Use provenance markers**: ^[inferred] for synthesized connections, ^[ambiguous] for contested interpretations
8. **Minimum 3 co-occurrences** to qualify as a candidate (unless the connection is obvious)

## Existing Synthesis Pages

Check `{{vault_path}}/synthesis/` for existing pages. If a pair already has a synthesis page, **augment it** — read the existing content, merge new insights, update timeline and connections. Don't skip; keep them current.
