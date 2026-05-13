# aidenlabs-wiki-pipeline

Self-maintaining LLM wiki pipeline for the Aiden Labs Obsidian vault.
Follows the [Karpathy llm-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
three layers — raw sources (Hermes session DB, repos), an LLM-maintained
wiki (`~/Obsidian/aidenlabs/`), and the conventions/schema (`AGENTS.md`).

Published downstream via [`aidenlabs-md`](../aidenlabs-md).

## Daily Use

```bash
just run                  # whole pipeline end-to-end
```

`just run` is the friendly alias for `just full`:

```
journal → projects → synthesize → fix-links → meta → lint → safety → finalize
```

Each phase reads / mutates the vault and either dispatches an LLM via
`codex-goal` or does mechanical bookkeeping.

## Top-Level Commands

| Command          | Phase     | What it does                                                                                                    |
| ---------------- | --------- | --------------------------------------------------------------------------------------------------------------- |
| `just journal`   | LLM       | Iterate missing days (first `state.db` activity → yesterday). Per day: harvest → journal LLM → stub-projects.   |
| `just projects`  | LLM       | Hydrate stubs created by journals, augment existing project pages, promote significant new repos.               |
| `just synthesize`| LLM       | Co-occurrence analysis + write/refresh cross-project synthesis pages.                                           |
| `just lint`      | mechanical| Stale projects + missing-section data gaps. Writes `_meta/lint.md` (informational, never blocks).               |
| `just safety`    | mechanical| Presidio (PII) + detect-secrets scan. **Trust boundary** — if anything sticks, the deploy halts.                |
| `just run`       | combined  | All of the above in order, then rsync to `aidenlabs-md`.                                                        |

Lower-level helpers (`prompt-journal`, `stub-projects`, `fix-links`,
`meta`, `finalize-today`, `journal-dry`) are documented in the `justfile`.

## Design Choices

### Dispatch via `codex-goal`, not `hermes chat -q`

LLM phases run through `codex-goal` (which routes via
`codex-responses-bridge` to LiteLLM). Reasons:

1. `codex-goal` sessions don't land in `~/.hermes/state.db`, so the next
   pipeline run won't harvest its own LLM activity into a journal.
2. `codex-goal` already supports `--max-iters`, `--cd`, MCP toolsets,
   and goal-tracking; we don't need to rebuild that loop.

`scripts/dispatch.py:run_phase` is the only place that invokes
`codex-goal`. Adding a new LLM phase = add a prompt under `prompts/`,
add a `run_*.py` script, wire it into the `justfile`.

### Synthesis: recency-weighted, bucketed selection

Synthesis follows the llm-wiki compounding pattern (knowledge compiled
once, kept current). Two failure modes the naïve "top-N by raw
co-occurrence" hits:

* Old high-count pairs monopolise top-N — new pairs starve.
* Co-occurrence ≠ insight — mechanical counts don't measure connection
  quality.

We address both in `scripts/synthesize.py`:

* **Recency-weighted co-occurrence.** Journal contributions decay with a
  60-day half-life; non-journal pages (projects, root, `_meta/`) stay
  weight 1.0 (evergreen baseline). Ancient journal activity fades;
  genuinely persistent connections — those also anchored in project
  pages — keep their score.
* **Bucketed selection.** Per run, 15 slots = 8 `fresh` (no synthesis
  page yet) + 7 `refresh` (page exists, has gained score since its last
  update). Buckets spill into each other if one is short, so total
  budget is preserved.
* **Delta tracking.** Each synthesis page records
  `last_cooccurrence_score` in frontmatter. Next run, refresh candidates
  are ranked by `current_score − last_score` — pages with no new
  momentum drop out via `min_refresh_delta` (default 0.5). No
  time-based cooldown; if a page got new co-occurrence today, it's
  eligible today.

### Safety scan as trust boundary

`just safety` runs Presidio + detect-secrets across every `.md` in the
vault and writes `~/.cache/wiki-pipeline/safety-report.json`. Allowed:
emails (publishable contact info), URLs. Blocked: phones, SSNs, EINs,
credit cards, IBANs, API keys, JWTs, private keys.

If safety finds anything, the pipeline halts before `finalize` /
`aidenlabs-md` deploy. The downstream repo has no second-pass gate.

### Mechanical lint, never blocking

`just lint` flags stale projects (live status, no journal mention in 14
days) and data gaps (missing required sections). Output goes to
`_meta/lint.md` so the next `just projects` run can read it and
prioritise. Lint never exits non-zero — it informs, doesn't gate.

## Repo Layout

```
prompts/
  journal.md           — Daily journal generation
  projects.md          — Project page hydration / augmentation
  synthesis.md         — Cross-project synthesis (fresh + refresh buckets)
scripts/
  pipeline.py          — Mechanical phases (harvest, synthesis, finalize…)
  dispatch.py          — codex-goal dispatcher (run_phase)
  run_journals.py      — Per-day journal driver (iterates missing dates)
  run_projects.py      — Single-phase projects driver
  run_synthesis.py     — Single-phase synthesis driver
  harvest.py           — Pulls Hermes sessions for a date (filters cron/cli)
  synthesize.py        — Recency-weighted co-occurrence + bucket selection
  stub_projects.py     — Creates empty stub pages for unresolved wikilinks
  fix_links.py         — Repairs broken wikilinks after LLM phases
  sanitize_frontmatter.py
  scan_safety.py       — Presidio + detect-secrets pre-publish scan
  lint.py              — Stale-project + data-gap lint pass
justfile               — Top-level commands
SKILL.md               — How to invoke this pipeline as a Hermes skill
```

## Setup

```bash
uv sync                                       # creates .venv with deps
just journal                                  # backfill journals
just run                                      # daily full pipeline
```

## Configuration

The vault path, state.db path, and Python interpreter are pinned in the
`justfile`. Most scripts accept `--vault PATH` overrides.

### `codex-goal` routing

`scripts/dispatch.py` invokes `codex-goal` directly. Make sure
`CODEX_BASE_URL=http://n1.lt3.co:4001` (the `codex-responses-bridge`)
is set, not LiteLLM directly — direct LiteLLM fails complex codex
prompts with `215 validation errors body.input.str`.

## Related

* [`aidenlabs-md`](../aidenlabs-md) — Cloudflare Worker that serves the
  vault publicly.
* `~/Obsidian/aidenlabs/AGENTS.md` — Vault conventions; LLM phases read
  this every run.
