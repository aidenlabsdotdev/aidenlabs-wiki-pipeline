set shell := ["bash", "-c"]

VAULT := "/home/jasper/Obsidian/aidenlabs"
DB := "/home/jasper/.hermes/state.db"
PYTHON := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/.venv/bin/python"
PIPELINE := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/pipeline.py"
RUN_JOURNALS := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/run_journals.py"
RUN_PROJECTS := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/run_projects.py"
RUN_SYNTHESIS := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/run_synthesis.py"
SCAN_SAFETY := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/scan_safety.py"
LINT := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/lint.py"

# ── Top-level pipelines ────────────────────────────────────────────────────
# Each target is self-driving: it iterates as needed, dispatches the LLM
# phase via codex-goal, and writes results into the vault.

# Iterate every missing day from first state.db activity to yesterday
# (full days only).  Per day: harvest → journal LLM → stub-projects.
journal:
	{{PYTHON}} {{RUN_JOURNALS}} --vault {{VAULT}} --db {{DB}}

# Hydrate stubs created by the journal phase, augment existing project
# pages, and scan for new significant projects worth promoting.
projects:
	{{PYTHON}} {{RUN_PROJECTS}} --vault {{VAULT}}

# Full synthesis pass: co-occurrence analysis + LLM write-up of top pairs
# following the llm-wiki (Karpathy) pattern.
synthesize:
	{{PYTHON}} {{RUN_SYNTHESIS}} --vault {{VAULT}}

# Mechanical lint pass: stale projects + missing-section data gaps.
# Writes _meta/lint.md (informational, doesn't block).  projects-sync
# can read this on its next run to prioritise pages needing attention.
lint:
	{{PYTHON}} {{LINT}} --vault {{VAULT}}

# Pre-publish safety scan: Presidio (PII) + detect-secrets (credentials)
# across every .md in the vault.  Blocks on US_SSN / US_ITIN /
# CREDIT_CARD / IBAN_CODE / US_BANK_NUMBER / CRYPTO / US_EIN, plus
# pattern-based detect-secrets matches (AWS, GitHub, Stripe, Slack,
# JWT, etc.).  Permissive by design — entropy heuristics off, low-
# confidence Presidio hits dropped — but available as a standalone
# audit (`just safety`) when you want a sanity check.  Not wired into
# the default daily run; the LLM phases self-redact per AGENTS.md.
safety:
	{{PYTHON}} {{SCAN_SAFETY}} --vault {{VAULT}}

# Daily full pipeline: journal → projects → synthesize → fix-links →
# update-meta → lint → finalize.  ``safety`` is intentionally not in
# the chain — see its target comment above.
full: journal projects synthesize fix-links meta lint finalize-today

# Friendly alias — `just run` is what you reach for daily.
run: full

# ── Lower-level mechanical phases ─────────────────────────────────────────
# These don't dispatch the LLM — they only prep input or do mechanical
# bookkeeping.  The top-level targets above invoke them as needed.

prompt-journal date:
	{{PYTHON}} {{PIPELINE}} prompt journal --date {{date}} --vault {{VAULT}}

prompt-projects:
	{{PYTHON}} {{PIPELINE}} prompt projects --vault {{VAULT}}

prompt-synthesis:
	{{PYTHON}} {{PIPELINE}} prompt synthesis --vault {{VAULT}} --top 5

stub-projects date:
	{{PYTHON}} {{PIPELINE}} stub-projects --vault {{VAULT}} --journal-date {{date}}

fix-links:
	{{PYTHON}} {{PIPELINE}} fix-links --vault {{VAULT}}

meta:
	{{PYTHON}} {{PIPELINE}} update-meta --vault {{VAULT}}

finalize-today:
	{{PYTHON}} {{PIPELINE}} finalize --vault {{VAULT}} --date "$(date -u '+%Y-%m-%d')"

# Dry-run preview: list dates that would be journaled without dispatching.
journal-dry:
	{{PYTHON}} {{RUN_JOURNALS}} --vault {{VAULT}} --db {{DB}} --dry-run
