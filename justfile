set shell := ["bash", "-c"]

VAULT := "/home/jasper/Obsidian/aidenlabs"
DB := "/home/jasper/.hermes/state.db"
PYTHON := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/.venv/bin/python"
PIPELINE := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/pipeline.py"
HARVEST_JOURNALS := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/harvest_journals.py"

# ── Journal ────────────────────────────────────────────────────────────────
journal:
	{{PYTHON}} {{HARVEST_JOURNALS}} --vault {{VAULT}} --db {{DB}} --pipeline {{PIPELINE}}

prompt-journal date:
	{{PYTHON}} {{PIPELINE}} prompt journal --date {{date}} --vault {{VAULT}}

# ── Projects ───────────────────────────────────────────────────────────────
projects:
	{{PYTHON}} {{PIPELINE}} projects --vault {{VAULT}}

prompt-projects:
	{{PYTHON}} {{PIPELINE}} prompt projects --vault {{VAULT}}

# ── Synthesis ──────────────────────────────────────────────────────────────
synthesis:
	{{PYTHON}} {{PIPELINE}} synthesis --vault {{VAULT}}

prompt-synthesis:
	{{PYTHON}} {{PIPELINE}} prompt synthesis --vault {{VAULT}} --top 5

# ── Meta ───────────────────────────────────────────────────────────────────
meta:
	{{PYTHON}} {{PIPELINE}} update-meta --vault {{VAULT}}

# ── Finalize ───────────────────────────────────────────────────────────────
finalize:
	{{PYTHON}} {{PIPELINE}} finalize --vault {{VAULT}} --date "$(date -u '+%Y-%m-%d')"

# ── Full ───────────────────────────────────────────────────────────────────
full: journal projects synthesis meta finalize
