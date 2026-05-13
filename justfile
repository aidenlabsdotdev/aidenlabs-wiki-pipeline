set shell := ["bash", "-c"]

VAULT := "/home/jasper/Obsidian/aidenlabs"
DB := "/home/jasper/.hermes/state.db"
PIPELINE := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/pipeline.py"
HARVEST_JOURNALS := "/home/jasper/Repositories/aidenlabs-wiki-pipeline/scripts/harvest_journals.py"

# ── Journal ────────────────────────────────────────────────────────────────
journal:
	python {{HARVEST_JOURNALS}} --vault {{VAULT}} --db {{DB}} --pipeline {{PIPELINE}}

prompt-journal date:
	python {{PIPELINE}} prompt journal --date {{date}} --vault {{VAULT}}

# ── Projects ───────────────────────────────────────────────────────────────
projects:
	python {{PIPELINE}} projects --vault {{VAULT}}

prompt-projects:
	python {{PIPELINE}} prompt projects --vault {{VAULT}}

# ── Synthesis ──────────────────────────────────────────────────────────────
synthesis:
	python {{PIPELINE}} synthesis --vault {{VAULT}}

prompt-synthesis:
	python {{PIPELINE}} prompt synthesis --vault {{VAULT}} --top 5

# ── Meta ───────────────────────────────────────────────────────────────────
meta:
	python {{PIPELINE}} update-meta --vault {{VAULT}}

# ── Finalize ───────────────────────────────────────────────────────────────
finalize:
	python {{PIPELINE}} finalize --vault {{VAULT}} --date "$(date -u '+%Y-%m-%d')"

# ── Full ───────────────────────────────────────────────────────────────────
full: journal projects synthesis meta finalize
