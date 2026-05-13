set shell := ["bash", "-c"]

VAULT := "/home/jasper/Obsidian/aidenlabs"
DB := "/home/jasper/.hermes/state.db"
PIPELINE := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/pipeline.py"
HARVEST_JOURNALS := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/harvest_journals.py"

# ── Journal ────────────────────────────────────────────────────────────────
journal:
	python3 {{HARVEST_JOURNALS}} --vault {{VAULT}} --db {{DB}} --pipeline {{PIPELINE}}

prompt-journal date:
	python3 {{PIPELINE}} prompt journal --date {{date}} --vault {{VAULT}}

# ── Projects ───────────────────────────────────────────────────────────────
projects:
	python3 {{PIPELINE}} projects --vault {{VAULT}}

prompt-projects:
	python3 {{PIPELINE}} prompt projects --vault {{VAULT}}

# ── Synthesis ──────────────────────────────────────────────────────────────
synthesis:
	python3 {{PIPELINE}} synthesis --vault {{VAULT}}

prompt-synthesis:
	python3 {{PIPELINE}} prompt synthesis --vault {{VAULT}} --top 5

# ── Meta ───────────────────────────────────────────────────────────────────
meta:
	python3 {{PIPELINE}} update-meta --vault {{VAULT}}

# ── Finalize ───────────────────────────────────────────────────────────────
finalize:
	python3 {{PIPELINE}} finalize --vault {{VAULT}} --date "$(date -u '+%Y-%m-%d')"

# ── Full ───────────────────────────────────────────────────────────────────
full: journal projects synthesis meta finalize
