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

## Repo Setup

```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
```

## Orchestrating a Day

Run these steps sequentially for each date. Mechanical phases via `terminal`,
LLM phases via `delegate_task`.

### Phase 0: Harvest (mechanical)

```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
python scripts/pipeline.py harvest --date 2026-05-04
```

Output: `~/.cache/wiki-pipeline/digest.json`
Exit code 1 = no sessions for that date → skip remaining phases.

### Phase 1: Journal Generation (delegate_task)

Delegate with toolsets `["file", "terminal"]`:

```
goal: Generate journal entry for {date}
context: |
  Read ~/.cache/wiki-pipeline/digest.json (session digest).
  Read /home/jasper/Obsidian/aidenlabs/index.md and company/company.md for context.
  
  Write /home/jasper/Obsidian/aidenlabs/journal/{date}.md with:
  - YAML frontmatter: title, summary (≤200 chars), lifecycle: draft,
    provenance: pipeline/daily-update, created, updated, tags: [journal]
  - Sections: Summary, Sessions, Projects Touched, Decisions,
    Learnings & Insights, Artifacts
  - Use wiki links [[like this]] for references
```

Skip if journal file already exists (use `--force` concept).

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
  It contains tasks_repos, github_org_repos, vault_projects.
  
  Decide which repos are actual projects vs throwaway experiments.
  Criteria: active development, business relevance, meaningful content.
  
  For each real project, create/update:
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

If candidates exist, delegate with toolsets `["file", "terminal"]`:

```
goal: Draft synthesis pages for top candidates
context: |
  Read ~/.cache/wiki-pipeline/synthesis-candidates.json.
  Vault at /home/jasper/Obsidian/aidenlabs/.
  
  For top 3 candidates, create synthesis/<A>-x-<B>.md:
  1. Connection — how topics relate
  2. Where They Co-occur — pages linking to both
  3. Cross-cutting Insight — what the connection reveals
  4. Tensions — contradictions or trade-offs
  5. Open Questions — unresolved areas
  
  Add frontmatter: title, summary, lifecycle: draft, tags.
  Back-link from source pages where appropriate.
```

### Phase 4: Finalize (mechanical)

```bash
cd ~/Tasks/aidenlabs-wiki-pipeline && source .venv/bin/activate
python scripts/pipeline.py finalize --date {date} --vault /home/jasper/Obsidian/aidenlabs/
```

Does: append to log.md, rsync to public/, regenerate notes.json.

## Retroactive Sequential Run

For multiple dates, run phases sequentially. Each day builds on the previous:

```
for date in 2026-05-04 2026-05-05 2026-05-06:
  Phase 0: harvest --date $date
  Phase 1: delegate journal (skip if exists)
  Phase 2: projects scan + delegate
  Phase 3: synthesis scan + delegate
  Phase 4: finalize
```

## Key Design Decision

LLM phases use `delegate_task` NOT `hermes chat -q` subprocesses. This avoids
creating agent sessions in state.db that would be harvested as "activity" on
subsequent runs, creating a feedback loop.
