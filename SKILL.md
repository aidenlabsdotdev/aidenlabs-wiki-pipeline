---
name: wiki-daily-pipeline
description: >
  Run the daily wiki pipeline for Aiden Labs Obsidian vault. Harvests Hermes sessions,
  generates journal entries, syncs projects, and runs synthesis. Supports retroactive
  runs on any date. Use when triggered by cron or when user says "run the daily pipeline",
  "update the wiki", "process day YYYY-MM-DD".
---

# Wiki Daily Pipeline

Orchestrates the daily wiki update pipeline using scripts in `~/Tasks/aidenlabs-wiki-pipeline/`
and spawns `hermes agent` subprocesses for LLM-heavy phases.

## Configuration

```bash
VAULT="/home/jasper/Obsidian/aidenlabs"
PIPELINE="/home/jasper/Tasks/aidenlabs-wiki-pipeline"
TMP_DIR="$HOME/.cache/wiki-pipeline"
mkdir -p "$TMP_DIR"
```

## Usage

```bash
python "$PIPELINE/scripts/harvest.py" --date YYYY-MM-DD --output "$TMP_DIR/digest.json"
```

Then spawn hermes agent subprocesses for each LLM phase.

## Pipeline Steps

### Phase 0: Harvest (mechanical)

```bash
python "$PIPELINE/scripts/harvest.py" --date "$DATE" --output "$TMP_DIR/digest.json"
```

If no sessions found for the date, log and exit early.

### Phase 1: Journal Generation (LLM via hermes agent)

Spawn a new `hermes agent` subprocess with a prompt that:
- Reads `$TMP_DIR/digest.json`
- Reads existing vault context (`$VAULT/index.md`, `$VAULT/company/company.md`)
- Writes `$VAULT/journal/YYYY-MM-DD.md` following the template in `templates/journal.md.j2`

The prompt should instruct the agent to:
1. Read the digest JSON
2. Summarize the day's activity across all sessions
3. Identify projects/repos touched
4. Extract decisions made, learnings, and insights
5. List artifacts created (files, commits, deployments)
6. Write the journal entry with proper frontmatter and wiki links

Command:
```bash
hermes agent "Generate journal entry for $DATE. Read $TMP_DIR/digest.json, summarize sessions, extract learnings, write to $VAULT/journal/$DATE.md"
```

### Phase 2: Projects Sync (mechanical + LLM)

Run mechanical scan:
```bash
python "$PIPELINE/scripts/sync_projects.py" --vault "$VAULT" --output "$TMP_DIR/projects-manifest.json"
```

Then spawn `hermes agent` to:
- Read the manifest
- Decide which repos are actual "projects" vs throwaway experiments
- Create/update project pages under `$VAULT/projects/<slug>/`
- Link repos to projects appropriately

Command:
```bash
hermes agent "Sync projects. Read $TMP_DIR/projects-manifest.json, decide what's a real project, create/update pages in $VAULT/projects/"
```

### Phase 3: Synthesis (mechanical + LLM)

Run mechanical analysis:
```bash
python "$PIPELINE/scripts/synthesize.py" --vault "$VAULT" --output "$TMP_DIR/synthesis-candidates.json"
```

Then spawn `hermes agent` to:
- Read candidates
- Draft synthesis pages for top candidates
- Follow Karpathy-style synthesis pattern: Connection → Co-occurrence → Insight → Tensions → Open Questions

Command:
```bash
hermes agent "Run synthesis pass. Read $TMP_DIR/synthesis-candidates.json, draft synthesis pages in $VAULT/synthesis/"
```

### Phase 4: Finalize (mechanical)

After all phases complete:
1. Regenerate `notes.json` in the deploy directory
2. Append to `$VAULT/log.md`
3. Sync vault to deploy directory:
   ```bash
   rsync -av --delete --exclude='.obsidian' --exclude='*.tmp' "$VAULT/" ~/Tasks/aidenlabs-vault/public/
   ```

## Retroactive Mode

To run retroactively through multiple days:
```bash
for date in 2026-05-04 2026-05-05 2026-05-06; do
  echo "=== Processing $date ==="
  # Run all phases for this date
done
```

Each day builds incrementally — journal entries accumulate, projects grow, synthesis compounds.

## Idempotency

- If `$VAULT/journal/YYYY-MM-DD.md` already exists, skip Phase 1 (or offer to overwrite)
- Projects sync is additive — only creates missing pages, updates existing ones
- Synthesis skips pairs that already have synthesis pages
