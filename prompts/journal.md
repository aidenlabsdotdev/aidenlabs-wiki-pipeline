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

## Execution Model

This prompt is designed to be executed via `delegate_task` (not `hermes chat -q`).
- **delegate_task**: Subagent sessions are NOT recorded in state.db → won't pollute future journals
- **hermes chat -q**: Creates agent sessions in state.db → WILL be harvested as activity on next run

The orchestrator reads this prompt, fills in `{{variables}}`, and passes it as the `context` to a `delegate_task` call with toolsets `["file", "terminal"]`.

1. **Section names are fixed**: Summary → Activity → Learnings → Open Items → Related
2. **Activity subsections named by workstream**, not generic labels like "Key Activities"
3. **Every substantive claim gets provenance marker** if inferred or ambiguous
4. **Wikilink to every project touched** — minimum 2-3 links per journal
5. **Related section always links to previous journal** for temporal continuity
6. **No session-by-session listing** — group by theme, not chronology
7. **PII redacted** per AGENTS.md rules
8. **All string values in YAML frontmatter must be double-quoted** (especially `summary`)
9. **Only generate for completed calendar days** — never partial days
