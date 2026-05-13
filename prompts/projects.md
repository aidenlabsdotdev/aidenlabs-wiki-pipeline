---
name: projects-sync
description: >
  Create or update project pages in the vault. Reads the project manifest
  from mechanical scanning, then creates comprehensive project pages.
  Input: projects-manifest.json, existing journal entries, source repos.
  Output: projects/<slug>/<slug>.md for each project
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

## Execution Model

This prompt is designed to be executed via `delegate_task` (not `hermes chat -q`).
- **delegate_task**: Subagent sessions are NOT recorded in state.db → won't pollute future journals
- **hermes chat -q**: Creates agent sessions in state.db → WILL be harvested as activity on next run

The orchestrator reads this prompt, fills in `{{variables}}`, and passes it as the `context` to a `delegate_task` call with toolsets `["file", "terminal", "web"]`.

## Rules

1. **Read actual source code** (README.md, package.json, key files) — don't just summarize journals
2. **Minimum 80 lines** — these are authoritative references, not stubs
3. **Status field required** — active/experimental/completed/paused
4. **Timeline traces decisions**, not just activity
5. **PII redacted** per AGENTS.md rules
6. **All string values in YAML frontmatter must be double-quoted**
7. **Be conservative** — only create pages for real projects, not throwaway experiments
8. **If a page already exists**: read it, merge new information, preserve existing content
9. **Use kebab-case slugs** for folder and file names
10. **Wikilink to related projects** and relevant journal entries

## Existing Pages

Check for existing project pages before creating new ones. If updating, preserve:
- Existing timeline entries
- Established relationships between projects
- Provenance markers already present

**Always augment existing pages** — don't skip them. Merge new information from journals and source code to keep them current.
