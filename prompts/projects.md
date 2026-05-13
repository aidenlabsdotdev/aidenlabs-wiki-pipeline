---
name: projects-sync
description: >
  Create or update project pages in the vault. Reads the project manifest
  from mechanical scanning, then creates comprehensive project pages.
  Input: projects-manifest.json, existing journal entries, source repos.
  Output: projects/<slug>.md for each project
---

# Projects Sync Prompt

Create or update project pages in the Obsidian vault based on accumulated data.

## Context Files

Read these files first:
- `{{manifest_path}}` — Project manifest (repos discovered by mechanical scan)
- `{{vault_path}}/AGENTS.md` — Vault conventions and PII redaction rules
- All journal entries in `{{vault_path}}/journal/` — Timeline of activity per project

For each project, also read source code if available:
- README.md, package.json, pyproject.toml, key source files in `{{repos_path}}/`

## Output

For each real project (not throwaway experiments), create/update:
`{{vault_path}}/projects/{{slug}}.md`

Follow the project format in AGENTS.md:

```markdown
---
title: "Project Name"
summary: "≤200 char description of what the project is"
base_confidence: 0.75
lifecycle: draft
provenance:
  extracted: ~0.6
  inferred: ~0.35
  ambiguous: ~0.05
created: "{{iso_timestamp}}"
updated: "{{iso_timestamp}}"
tags: [project-tag-from-taxonomy]
---

# Project Name

One-paragraph overview: what it does, why it exists.

## Status

active | experimental | completed | paused

## Architecture / Tech Stack

Key technologies, dependencies, integrations.

## Key Components

File structure or component breakdown.

## Timeline

- **YYYY-MM-DD** — Milestone or decision

## Related Projects

- [[projects/related-project]] — connection description

## Known Issues

- Blockers, limitations, open questions ^[inferred]
```

## Rules

1. **Read actual source code** (README.md, package.json, key files) — don't just summarize journals
2. **Minimum 80 lines** — these are authoritative references, not stubs
3. **Status field required** — active/experimental/completed/paused
4. **Timeline traces decisions**, not just activity
5. **PII redacted** per AGENTS.md rules
6. **String values in YAML frontmatter must be double-quoted**.
   `tags` is a YAML list, NOT a string — write ``tags: [project, hermes]`` with
   no surrounding quotes. Writing ``tags: "[project, hermes]"`` produces a
   single tag literally named ``[project, hermes]``, which Obsidian renders
   incorrectly.
7. **Be conservative** — only create pages for real projects, not throwaway experiments
8. **If a page already exists**: read it, merge new information, preserve existing content
9. **Use kebab-case slugs** for folder and file names
10. **Wikilink to related projects** and relevant journal entries

## Existing Pages

Two kinds of pages already exist before you run:

1. **Stubs** — created by the journal phase via ``stub-projects``.  These
   pages have ``lifecycle: stub`` in frontmatter and one-line placeholder
   bodies.  They mark projects that journals have referenced but never
   had an authoritative page written for.  **These are your top priority**
   — read the journal references that triggered each stub, read the
   source repo if one exists, and replace the placeholder body with a
   real overview.  Set ``lifecycle`` to ``draft`` once you've enriched.
2. **Authored pages** — already-substantive entries (``lifecycle: draft``,
   ``active``, ``mature`` etc.).  Augment with new information from
   journals + repos; preserve existing timeline entries, relationships,
   and provenance markers.

**Always augment existing pages** — don't skip them. Merge new information
from journals and source code to keep them current.

## Detecting new significant projects

In addition to enriching stubs and existing pages, scan the project
manifest for repos that:

1. Have substantive code activity in recent journals (≥3 mentions across
   the past 14 days OR ongoing work referenced by name).
2. Have a real README / package metadata indicating it's not a throwaway.
3. Are not in ``~/Tasks/`` (Codex temp dirs — those are noise).

For each such repo that lacks a wiki page, create one following the
format above.  Err conservative — only promote to a project page if the
work is recognizable as a named effort, not just exploratory tinkering.
