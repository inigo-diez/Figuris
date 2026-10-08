"""Versioned evaluation runs (research/experiments.md, "Reproducibilidad").

Each run is saved under ``evaluation/runs/<run-id>/``:

- ``manifest.json``: what was run (script, arguments, component versions and
  configuration, reference version, splits, git commit, Python and platform);
- ``metrics.json``: the summary the report quotes;
- ``predictions.jsonl``: one line per article or item, to recompute the metrics.

The run id is ``<UTC date-time>-<component>-<version>-<config hash>``. Outputs hold
labels, scores and coordinates only, never article text.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "evaluation" / "runs"


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    commit = out.stdout.strip() or None
    return f"{commit}+dirty" if commit and dirty.stdout.strip() else commit


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:8]


def save_run(
    component: str,
    version: str,
    config: dict,
    metrics: dict,
    predictions: list[dict],
    extra: dict | None = None,
    runs_dir: Path = RUNS,
) -> Path:
    now = dt.datetime.now(dt.UTC)
    run_id = f"{now:%Y%m%d-%H%M%S}-{component}-{version}-{config_hash(config)}"
    target = runs_dir / run_id
    target.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "component": component,
        "version": version,
        "config": config,
        "script": Path(sys.argv[0]).name,
        "arguments": sys.argv[1:],
        "git_commit": git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        **(extra or {}),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (target / "metrics.json").write_text(
        json.dumps(metrics, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (target / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target
