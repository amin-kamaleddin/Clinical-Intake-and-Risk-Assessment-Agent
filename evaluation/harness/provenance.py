
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


# Paths a run produces itself. Changes here say nothing about whether the code
# that produced a result is reproducible.
_ARTIFACT_PREFIXES = (
    "evaluation/outputs/",
    "evaluation/records/",
    "cira/records/",
    "paper/tables/",
)
_ARTIFACT_SUFFIXES = (".log",)


def _is_artifact(status_line: str) -> bool:
    """True when a porcelain line refers to a file the run itself writes."""
    # "XY path" or "XY old -> new"; take the final path.
    path = status_line[3:].strip().strip('"')
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip().strip('"')
    return (
        path.startswith(_ARTIFACT_PREFIXES)
        or path.endswith(_ARTIFACT_SUFFIXES)
    )


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
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(config.PROJECT_ROOT),
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
        # A run writes its own artifacts, so a plain porcelain check marks the
        # tree dirty the moment the first output file lands - the run would
        # brand itself unreproducible before it had finished starting, and no
        # run could ever record a clean revision.
        #
        # Only files that could CHANGE the result count. Artifacts are output,
        # not input.
        dirty = [
            line for line in status.splitlines()
            if line.strip() and not _is_artifact(line)
        ]
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


def build_manifest(run_id: str | None = None, repetitions: int | None = None) -> dict:
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
        # Every sampling temperature in the pipeline, recorded together so a
        # reader can see at a glance that the arms were matched. CIRA used to
        # send none at all and ran at the provider default while the baseline
        # was pinned at 0; that is not visible unless it is written down.
        "temperatures": {
            "cira": cira_temperature(),
            "naive_llm": config.NAIVE_TEMPERATURE,
            "patient_simulator": config.PATIENT_TEMPERATURE,
            "judge": config.JUDGE_TEMPERATURE,
            "patient_temperature_pinned": config.PATIENT_TEMPERATURE_IS_PINNED,
        },
        "judge_temperature": config.JUDGE_TEMPERATURE,
        # The EFFECTIVE count, not the environment default. --repetitions N used
        # to run N repetitions while the manifest recorded config.REPETITIONS,
        # so a repeated run could be filed as a single realisation.
        "repetitions": (
            repetitions if repetitions is not None else config.REPETITIONS
        ),
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


def cira_temperature():
    """CIRA's own sampling temperature, or None if the agent cannot be imported."""
    try:
        import sys
        cira_root = str(config.PROJECT_ROOT.parent / "cira")
        if cira_root not in sys.path:
            sys.path.insert(0, cira_root)
        from core.config import TEMPERATURE
        return TEMPERATURE
    except Exception:  # noqa: BLE001 - provenance must never block a run
        return None


def write_manifest(run_id: str | None = None, repetitions: int | None = None) -> dict:
    manifest = build_manifest(run_id, repetitions)
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
