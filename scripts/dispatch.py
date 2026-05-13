#!/usr/bin/env python3
"""dispatch.py — Run a wiki-pipeline LLM phase via codex-goal.

The pipeline's mechanical phases (harvest, projects, synthesis) prep input
files and render prompts.  The LLM phases (journal, projects-sync,
synthesis-generation) need a goal-driven agent with tool access.  We use
``codex-goal`` because:

* It doesn't write to ``state.db`` (so journal harvests won't pick up the
  pipeline's own LLM activity as user "sessions").
* It already has the right env, MCPs, and qwen3.6-27b-codex routing.
* Goal-driven loop semantics match each phase ("produce file X following
  these rules"); it stops on its own.

Usage::

    from dispatch import run_phase
    run_phase(
      phase="journal",
      vault="/home/jasper/Obsidian/aidenlabs",
      variables={"date": "2026-05-04", "previous_date": "2026-05-03"},
      max_iters=20,
    )
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE = REPO_ROOT / "scripts" / "pipeline.py"
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
CODEX_GOAL = "codex-goal"  # on PATH (via ~/.local/bin)

# Canonical env source for the Hermes/agent stack.  ``systemd --user`` loads
# this at session start, but freshly-added keys aren't picked up by shells
# started before the edit — so we re-source it here.  Local env always wins.
SYSTEMD_ENV_DIR = Path.home() / ".config" / "environment.d"


def _load_systemd_env() -> None:
  """Populate any missing keys from ``~/.config/environment.d/*.conf``.

  We don't override values already in ``os.environ`` — the active shell's
  configuration wins.  Only keys that are entirely absent get filled in.
  This means stale shells (started before a new key was added to the conf
  files) still see the new value, without overriding any ad-hoc overrides
  the user has set for this specific session.
  """
  if not SYSTEMD_ENV_DIR.is_dir():
    return
  for conf in sorted(SYSTEMD_ENV_DIR.glob("*.conf")):
    try:
      text = conf.read_text(encoding="utf-8")
    except OSError:
      continue
    for raw in text.splitlines():
      line = raw.strip()
      if not line or line.startswith("#") or "=" not in line:
        continue
      key, _, value = line.partition("=")
      key = key.strip()
      if key and key not in os.environ:
        os.environ[key] = value.strip()


_load_systemd_env()


def _strip_frontmatter(text: str) -> str:
  """Remove a leading ``---\\n...\\n---\\n`` YAML block, if present.

  codex-goal's argv parser rejects anything that starts with ``--`` as an
  unknown flag (codex-goal-v2.ts:56).  Our prompt templates begin with
  ``---\\n`` YAML frontmatter (informational only — name, description).
  Stripping it before dispatch leaves a clean instruction body that
  starts with a heading or paragraph.
  """
  if not text.startswith("---\n"):
    return text
  # Find the closing ``---`` on its own line.
  rest = text[4:]
  closer = rest.find("\n---\n")
  if closer == -1:
    return text  # malformed — leave it alone
  return rest[closer + len("\n---\n") :].lstrip()


def render_prompt(
  phase: str,
  variables: dict[str, str],
) -> str:
  """Invoke ``pipeline.py prompt <phase>`` with arguments and return rendered text."""
  cmd = [str(VENV_PY), str(PIPELINE), "prompt", phase]
  for k, v in variables.items():
    cmd.extend([f"--{k.replace('_', '-')}", str(v)])
  result = subprocess.run(cmd, capture_output=True, text=True, check=False)
  if result.returncode != 0:
    raise RuntimeError(
      f"pipeline.py prompt {phase} failed (exit {result.returncode})\n"
      f"stderr: {result.stderr}"
    )
  return result.stdout


def run_phase(
  phase: str,
  vault: str,
  variables: dict[str, str],
  max_iters: int = 20,
  extra_goal_prefix: Optional[str] = None,
) -> int:
  """Render the phase prompt and dispatch it via codex-goal.

  Returns the codex-goal exit code (0 = goal completed, non-zero = stopped
  early or errored).
  """
  prompt_text = _strip_frontmatter(render_prompt(phase, variables))

  goal_text = prompt_text
  if extra_goal_prefix:
    goal_text = f"{extra_goal_prefix}\n\n{prompt_text}"

  # codex-goal expects the goal as a single positional CLI argument.  Long
  # prompts work fine — codex internally writes them into the conversation
  # history.  We strip the prompt template's YAML frontmatter above so the
  # goal doesn't start with ``--`` (which codex-goal would reject as a
  # flag, codex-goal-v2.ts:56).
  cmd = [CODEX_GOAL, "--cd", vault, "--max-iters", str(max_iters), goal_text]
  print(
    f"dispatch: {phase} → codex-goal "
    f"(vault={vault}, max_iters={max_iters}, "
    f"prompt_len={len(goal_text)})",
    file=sys.stderr,
    flush=True,
  )
  # Inherit stdout/stderr so the operator sees progress live.
  rc = subprocess.run(cmd, check=False).returncode
  print(f"dispatch: {phase} → exit {rc}", file=sys.stderr, flush=True)
  return rc


if __name__ == "__main__":
  # CLI shim: dispatch.py <phase> --vault PATH --var key=value ...
  import argparse

  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("phase", choices=["journal", "projects", "synthesis"])
  ap.add_argument("--vault", required=True)
  ap.add_argument(
    "--var",
    action="append",
    default=[],
    help="key=value pairs forwarded to pipeline.py prompt (repeatable)",
  )
  ap.add_argument("--max-iters", type=int, default=20)
  args = ap.parse_args()
  variables: dict[str, str] = {}
  for pair in args.var:
    if "=" not in pair:
      ap.error(f"--var must be key=value, got {pair!r}")
    k, v = pair.split("=", 1)
    variables[k] = v
  sys.exit(run_phase(args.phase, args.vault, variables, args.max_iters))
