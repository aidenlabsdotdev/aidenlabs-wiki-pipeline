---
name: wiki-daily-pipeline
description: >
  Run the daily wiki pipeline for Aiden Labs Obsidian vault. Harvests Hermes sessions,
  generates journal entries, syncs projects, and runs synthesis. Supports retroactive
  runs on any date. Use when triggered by cron or when user says "run the daily pipeline",
  "update the wiki", "process day YYYY-MM-DD".
---

# Wiki Daily Pipeline

Orchestrates the daily wiki update pipeline. Mechanical scripts live in
`~/Tasks/aidenlabs-wiki-pipeline/` (uv-managed). LLM phases use `delegate_task`
to avoid polluting state.db with pipeline agent sessions.

## Vault Layout

```
company/              — Company info
projects/<name>/      — Active projects
synthesis/            — Cross-project synthesis
journal/              — Daily records
_meta/                — System context (index.md, hot.md, log.md, _insights.md, taxonomy.md)
AGENTS.md             — Conventions (tags, style, visibility)
```

## Repo Setup

```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
```

## Orchestrating a Day

Run these steps sequentially. Mechanical phases via `terminal`, LLM phases via `delegate_task`.

Always pass `_meta/AGENTS.md` (conventions) and `_meta/index.md` (vault map) as context to LLM phases.

### Phase 0: Harvest (mechanical)

```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
python scripts/pipeline.py harvest --date 2026-05-04
```

Output: `~/.cache/wiki-pipeline/digest.json`
Exit code 1 = no sessions → skip remaining phases.

### Phase 1: Journal Generation (delegate_task)

Delegate with toolsets `["file", "terminal"]`:

```
goal: Generate journal entry for {date}
context: |
  Read ~/.cache/wiki-pipeline/digest.json (session digest).
  Read /home/jasper/Obsidian/aidenlabs/AGENTS.md (conventions).
  Read /home/jasper/Obsidian/aidenlabs/_meta/index.md (vault map).
  Read /home/jasper/Obsidian/aidenlabs/company/company.md.

  Write /home/jasper/Obsidian/aidenlabs/journal/{date}.md with:
  - YAML frontmatter: title, summary (≤200 chars), lifecycle: draft,
    provenance: pipeline/daily-update, created, updated, tags: [journal]
  - Sections: Summary, Sessions, Projects Touched, Decisions,
    Learnings & Insights, Artifacts
  - Use wiki links [[like this]] for references
```

Skip if journal file already exists.

### Phase 2: Projects Sync (mechanical + delegate_task)

Mechanical scan:
```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
python scripts/pipeline.py projects --vault /home/jasper/Obsidian/aidenlabs/
```

Output: `~/.cache/wiki-pipeline/projects-manifest.json`

Then delegate with toolsets `["file", "terminal", "web"]`:

```
goal: Sync project pages in the Obsidian vault
context: |
  Read ~/.cache/wiki-pipeline/projects-manifest.json.
  Read /home/jasper/Obsidian/aidenlabs/AGENTS.md (conventions).

  Decide which repos are actual projects vs throwaway experiments.
  For each real project, create:
  /home/jasper/Obsidian/aidenlabs/projects/<slug>/<slug>.md

  Include: overview, linked repos, current status, related concepts.
  Use kebab-case slugs. Be conservative.
```

### Phase 3: Synthesis (mechanical + delegate_task)

Mechanical analysis:
```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
python scripts/pipeline.py synthesis --vault /home/jasper/Obsidian/aidenlabs/
```

Output: `~/.cache/wiki-pipeline/synthesis-candidates.json`

If ≥3 candidates exist, delegate with toolsets `["file", "terminal"]`:

```
goal: Draft synthesis pages for top candidates
context: |
  Read ~/.cache/wiki-pipeline/synthesis-candidates.json.
  Read /home/jasper/Obsidian/aidenlabs/AGENTS.md (conventions).
  Vault at /home/jasper/Obsidian/aidenlabs/.

  For top 3 candidates, create synthesis/<A>-x-<B>.md:
  1. Connection — how topics relate
  2. Where They Co-occur — pages linking to both
  3. Cross-cutting Insight — what the connection reveals
  4. Tensions — contradictions or trade-offs
  5. Open Questions — unresolved areas

  Add frontmatter: title, summary, lifecycle: draft, tags.
```

### Phase 4: Finalize (mechanical)

```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
python scripts/pipeline.py finalize --date {date} --vault /home/jasper/Obsidian/aidenlabs/
```

Does: append to `_meta/log.md`, rsync to public/, regenerate notes.json.

## Key Design

- **LLM phases use `delegate_task`** NOT `hermes chat -q` subprocesses — avoids creating agent sessions in state.db that would be harvested as "activity"
- **`_meta/` is read-only context** — conventions, index, hot snapshot, insights, taxonomy. Pipeline reads from it, doesn't write to it (except log.md appends)
- **Idempotent** — journal entries skipped if they exist, projects additive, synthesis skips existing pairs
