"""Run the whole-issue baseline and the Sonnet arms in one cmeval run, on one shared index.

Usage: python run_aug.py TASKS.jsonl CONFIG.toml RUN_ID REPO [LIMIT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

tasks, config, run_id, repo = sys.argv[1:5]
limit = int(sys.argv[5]) if len(sys.argv) > 5 else None
os.environ["AUG_TASKS"] = str(Path(tasks).resolve())

from cmeval.run import run  # noqa: E402
from cmeval.systems import ADAPTERS  # noqa: E402

ADAPTERS["llm"] = "aug_retriever:AugRetriever"
summary = run(tasks, config, run_id, split="dev", repo_filter=[repo], limit_per_repo=limit, index_mode="update", k=50,
              keep_indexes=True, progress=lambda message: print(message, flush=True))
print(f"run {run_id}: {summary.tasks} tasks x {summary.systems} systems, {summary.searched} searches, "
      f"{summary.skipped} already done, {summary.index_calls} index calls, {summary.seconds:.1f} s", flush=True)
