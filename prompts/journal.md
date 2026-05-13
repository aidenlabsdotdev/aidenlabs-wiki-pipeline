---
name: journal-generation
description: >
  Generate a daily journal entry from harvested session data.
  Input: digest.json (session transcripts), existing vault context.
  Output: journal/{date}.md
---

# Journal Generation Prompt

Generate a daily journal entry for **{{date}}** from the harvested session data.

## Context Files

Read these files first:
- `{{digest_path}}` — Session digest (titles, messages, tool calls)
- `{{vault_path}}/AGENTS.md` — Vault conventions and PII redaction rules
- `{{vault_path}}/index.md` — Current vault map
- `{{vault_path}}/_meta/hot.md` — Recent activity snapshot

If previous journals exist, read the most recent one for continuity:
- `{{vault_path}}/journal/{{previous_date}}.md`

## Output

Write `{{vault_path}}/journal/{{date}}.md` following the journal format in AGENTS.md:

```markdown
---
title: "{{date}}"
summary: "≤200 char summary of the day's main work"
base_confidence: 0.5
lifecycle: draft
provenance:
  extracted: ~0.7
  inferred: ~0.25
  ambiguous: ~0.05
created: "{{iso_timestamp}}"
updated: "{{iso_timestamp}}"
tags: [journal]
---

# {{date}}

## Summary

One paragraph: what happened today, major outcomes.

## Activity

Group sessions by workstream/theme — NOT chronologically. Each subsection named after the workstream:

### <workstream name> [[project-link-if-applicable]]

- Outcome or decision
- What was done
- Blockers encountered ^[inferred if synthesized]

## Learnings

- Technical observations, patterns discovered, lessons learned ^[inferred]

## Open Items

- Unresolved blockers carried forward
- Decisions pending

## Related

- [[journal/{{previous_date}}]]
- [[projects/relevant-project]]
```

1. **Section names are fixed**: Summary → Activity → Learnings → Open Items → Related
2. **Activity subsections named by workstream**, not generic labels like "Key Activities"
3. **Every substantive claim gets provenance marker** if inferred or ambiguous
4. **Wikilink to every project touched** — minimum 2-3 links per journal.
   **Don't worry whether the target page exists** — pipeline's `stub-projects`
   step runs immediately after journal generation and creates a stub at
   `projects/<slug>.md` for any new reference.  Just use the slug
   you think the project should have (kebab-case, descriptive).
5. **Related section always links to previous journal** for temporal continuity
6. **No session-by-session listing** — group by theme, not chronology
7. **PII redacted** per AGENTS.md rules
8. **String values in YAML frontmatter must be double-quoted** (especially `summary`).
   **`tags` is a YAML LIST, not a string** — write it as ``tags: [journal]``
   with no surrounding quotes.  Writing ``tags: "[journal]"`` produces a
   single tag literally named ``[journal]`` (with brackets), which
   Obsidian renders incorrectly.
9. **Only generate for completed calendar days** — never partial days

## Scope: what this journal IS and IS NOT

**IS** — a narrative record of what happened on this specific day.
A reader scanning past journals can reconstruct the timeline of work,
decisions, and learnings.  Workstream subsections are short (3-6 bullets);
project pages and synthesis pages are where details live.

**IS NOT** — an authoritative reference for any project.  Don't write
multi-paragraph project explanations, architecture overviews, status
updates, or roadmaps in this journal.  Those belong in `projects/<slug>.md`
(written by the projects-sync phase).  When you'd be tempted to elaborate
on a project's design or current state, link to the project page and let
projects-sync render that detail there.

The journal is "what we did on {{date}}"; project pages are "what this
project is."  Keep them separated.
