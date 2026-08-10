"""Run provenance - which exact configuration produced a set of results.

Why this exists
---------------
The reports recorded only the judge model. Nothing captured the CIRA model, the
naive model, the provider, the scenario file, the prompt text, or the code
revision, so it was impossible to establish afterwards which configuration
produced a committed number. Two runs with different models and different
prompts produced reports that looked identical.

This module writes ``outputs/reports/run_manifest.json`` at the start of every
run and stamps a ``run_id`` into it. Two things follow:

* **Attribution.** Every model name, the persona seed, and SHA-256 hashes of the
  scenario file and each prompt file are recorded. A hash changing between runs
  is proof the inputs changed.
* **Contamination detection.** Every artifact records the ``run_id`` that wrote
  it. ``check_artifact_freshness`` reports any artifact from a different run,
  which is how a one-case rerun scored against an eleven-case judge report gets
  caught instead of silently averaging.

Nothing here blocks a run. Mixing artifacts is sometimes deliberate - rescoring
without re-running the agents is the common case. The point is that it can no
longer happen without being visible in the report.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

from harness import config


MANIFEST_PATH = config.REPORTS_DIR / "run_manifest.json"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _git_revision() -> str | None:
    """Short commit hash, or None outside a repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(config.PROJECT_ROOT),
            capture_output=True, text=True, timeout=5, check=False,
        )
        revision = result.stdout.strip()
        if not revision:
            return None
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(config.PROJECT_ROOT),
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        return revision + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def _prompt_hashes() -> dict:
    """Hash every prompt file. A prompt edit is an input change."""
    prompts_dir = config.CIRA_DIR / "prompts"
    hashes = {}
    if prompts_dir.is_dir():
        for path in sorted(prompts_dir.glob("*.py")):
            if path.name != "__init__.py":
                hashes[path.name] = _sha256(path)
    return hashes


def build_manifest(run_id: str | None = None) -> dict:
    """Everything needed to reproduce a result set."""
    return {
        "run_id": run_id or uuid.uuid4().hex[:12],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "code_revision": _git_revision(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "models": {
            "cira": getattr(config, "CIRA_MODEL_NAME", None)
            or _cira_model_name(),
            "patient_simulator": config.PATIENT_MODEL_NAME,
            "naive_llm": config.NAIVE_MODEL_NAME,
            "judge": config.JUDGE_MODEL_NAME,
        },
        "endpoints": {
            "patient_simulator": config.OPENROUTER_BASE_URL,
            "judge": config.JUDGE_BASE_URL,
        },
        "judge_temperature": config.JUDGE_TEMPERATURE,
        "personas": {
            "seed": config.PERSONA_SEED,
            "strategy": config.PERSONA_ASSIGNMENT_STRATEGY,
            "override": config.PERSONA_OVERRIDE,
        },
        "inputs": {
            "scenario_file": config.SCENARIO_FILE.name,
            "scenario_sha256": _sha256(config.SCENARIO_FILE),
            "prompt_sha256": _prompt_hashes(),
        },
        "limits": {
            "max_turns_per_section": config.MAX_TURNS_PER_SECTION,
            "naive_max_turns": getattr(config, "NAIVE_MAX_TURNS", None),
        },
        # Set by whoever describes the baselines. "Generic LLM" overstates what
        # the naive arm is: it receives a full clinical intake prompt and a
        # second structured-extraction call, so it is an architecture ablation,
        # not an unconfigured model.
        "baseline_descriptions": {
            "rule_based": "Deterministic finite-state intake, no LLM.",
            "naive_llm": (
                "Prompt-only LLM architecture ablation: one clinical intake "
                "prompt plus a structured extraction call. NOT an unconfigured "
                "or 'generic' LLM."
            ),
        },
    }


def _cira_model_name() -> str | None:
    """Read CIRA's own configured model, if the package is importable."""
    try:
        sys.path.insert(0, str(config.CIRA_DIR))
        from core.config import MODEL_NAME  # type: ignore
        return MODEL_NAME
    except Exception:  # noqa: BLE001 - provenance must never break a run
        return None


def write_manifest(run_id: str | None = None) -> dict:
    manifest = build_manifest(run_id)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def load_manifest() -> dict | None:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def current_run_id() -> str | None:
    manifest = load_manifest()
    return manifest.get("run_id") if manifest else None


def check_artifact_freshness(systems=None) -> dict:
    """Find artifacts that were not written by the current run.

    Returns counts and the offending case ids per system. Scoring a mix of runs
    is sometimes intentional; doing it unknowingly is how a subset rerun ends up
    averaged with an older full judge report.
    """
    run_id = current_run_id()
    systems = list(systems) if systems else list(config.SYSTEMS)

    stale: dict[str, list[str]] = {}
    missing_id: dict[str, list[str]] = {}

    for system in systems:
        for path in sorted((config.OUTPUTS_DIR / system / "records").glob("case_*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            artifact_run = record.get("run_id")
            if artifact_run is None:
                missing_id.setdefault(system, []).append(path.stem)
            elif run_id and artifact_run != run_id:
                stale.setdefault(system, []).append(path.stem)

    return {
        "run_id": run_id,
        "stale_artifacts": stale,
        "artifacts_without_run_id": missing_id,
        "clean": not stale and not missing_id,
    }


def format_freshness(report: dict) -> str:
    if report["clean"]:
        return f"  artifacts: all from run {report['run_id']}"

    lines = []
    for system, cases in report["stale_artifacts"].items():
        lines.append(
            f"  WARNING {system}: {len(cases)} artifact(s) from an EARLIER run "
            f"({', '.join(cases[:4])}{'...' if len(cases) > 4 else ''})"
        )
    for system, cases in report["artifacts_without_run_id"].items():
        lines.append(
            f"  WARNING {system}: {len(cases)} artifact(s) with no run_id "
            f"(written before provenance tracking)"
        )
    lines.append("  Scores below therefore mix runs. Re-run, or note it.")
    return "\n".join(lines)
