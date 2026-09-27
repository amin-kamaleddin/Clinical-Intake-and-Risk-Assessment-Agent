
from __future__ import annotations

import hashlib
import os
import json
from datetime import datetime
import platform
import re
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


# The multilingual runs write to SIBLING trees - outputs_arabic/, outputs_farsi/
# and so on - which "evaluation/outputs/" does not match, so every non-English run
# marked ITSELF dirty the moment it created its own output directory. That is the
# same self-dirtying bug as before, reintroduced by a path the original filter
# never anticipated.
#
# Matched with a regex rather than a prefix so it requires a DIRECTORY: a source
# file that merely started with the same letters (evaluation/outputs_helper.py)
# would otherwise be excused as an artifact, and a change to it would let a run
# claim clean provenance while its source had moved. That is the one direction
# this filter must never fail in.
_LANGUAGE_OUTPUT_TREE = re.compile(r"^evaluation/outputs_[a-z_]+/")


def _is_artifact(status_line: str) -> bool:
    """True when a porcelain line refers to a file the run itself writes."""
    # "XY path" or "XY old -> new"; take the final path.
    path = status_line[3:].strip().strip('"')
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip().strip('"')
    return (
        path.startswith(_ARTIFACT_PREFIXES)
        or path.endswith(_ARTIFACT_SUFFIXES)
        or bool(_LANGUAGE_OUTPUT_TREE.match(path))
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


def new_run_id() -> str:
    """A fresh run id, minted before anything is written.

    Separate from build_manifest so the id can be claimed by the lock first;
    the manifest write is destructive and must be the last step, not the first.
    """
    return uuid.uuid4().hex[:12]


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
        # The conversation language. Without this an artifact cannot say which
        # language produced it, and the multilingual arms are indistinguishable
        # from the English one once the directory name is lost.
        "language": config.LANGUAGE,
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

# --------------------------------------------------------------------------- #
# Concurrency guard
# --------------------------------------------------------------------------- #
#
# Two runs sharing outputs/ is the single most damaging thing that can happen
# to this benchmark, and it is silent: each writes over the other's artifacts
# case by case, the reports end up mixing run ids, and every number is a blend
# of two configurations. That is exactly the contamination the freshness check
# was added to detect after the fact - this stops it happening at all.
#
# It is not hypothetical. A judge process from an earlier session was found
# still running after 1 day 18 hours, writing into a directory a new run had
# just been pointed at.

LOCK_PATH = config.REPORTS_DIR / ".run_lock"


def _process_alive(pid: int) -> bool:
    """True when a process with this pid exists (signal 0 probes, never kills)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but is owned by someone else.
        return True
    return True


def read_lock() -> dict | None:
    try:
        return json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def acquire_lock(run_id: str, force: bool = False) -> dict:
    """Claim outputs/ for this run, or refuse if another run holds it.

    A stale lock - one whose process is gone, e.g. after a crash or a kill -
    is reclaimed automatically and reported. Only a LIVE holder blocks.
    """
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = read_lock()
    if existing and not force:
        pid = existing.get("pid")
        if isinstance(pid, int) and pid != os.getpid() and _process_alive(pid):
            raise RuntimeError(
                f"another evaluation run is already using this outputs/ "
                f"directory:\n"
                f"    run_id  {existing.get('run_id')}\n"
                f"    pid     {pid}\n"
                f"    started {existing.get('started_at')}\n"
                f"    command {existing.get('command')}\n\n"
                f"Two runs sharing outputs/ silently mix their artifacts and "
                f"every reported number becomes a blend of both.\n"
                f"Stop it first:  kill {pid}\n"
                f"Then re-run. Use --force-lock only if you are certain that "
                f"process is not writing here."
            )
        if existing:
            print(
                f"[provenance] reclaiming stale lock from run "
                f"{existing.get('run_id')} (pid {existing.get('pid')} is gone)"
            )

    payload = {
        "run_id": run_id,
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "command": " ".join(sys.argv),
    }
    LOCK_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def release_lock() -> None:
    """Drop the lock if this process owns it. Never removes someone else's."""
    existing = read_lock()
    if existing and existing.get("pid") == os.getpid():
        LOCK_PATH.unlink(missing_ok=True)

def guard_completed_run(force: bool = False) -> None:
    """Refuse to overwrite the manifest of a run that already finished.

    The lock only protects a run while it is in progress. Once it exits and
    releases, any later `run_all` invocation writes a fresh manifest with a new
    run id - and every artifact of the completed run is instantly orphaned from
    the id that is supposed to identify it. Nothing warns, because from the
    code's point of view a new run is starting normally.

    This is not theoretical. It happened to a frozen, committed result set:
    the manifest was rewritten nine seconds before the summary, reassigning
    900 artifacts to a run that never produced them. It is also the most likely
    explanation for the original benchmark's `artifact_freshness.clean = false`
    with every artifact stale against the reported id.

    A run is treated as complete when both a manifest and a summary exist.
    Clearing outputs/ - the correct way to start fresh - removes both.
    """
    if force:
        return
    manifest = load_manifest()
    if not manifest or not config.SUMMARY_REPORT_PATH.exists():
        return
    raise RuntimeError(
        f"outputs/ already holds a COMPLETED run:\n"
        f"    run_id  {manifest.get('run_id')}\n"
        f"    code    {manifest.get('code_revision')}\n"
        f"    started {manifest.get('started_at')}\n\n"
        f"Starting here would write a new manifest and orphan every artifact "
        f"of that run from its own run id.\n\n"
        f"To start a fresh run:      rm -rf outputs\n"
        f"To re-score without a new id, use the stages directly - they inherit "
        f"the manifest's run id and never mint one:\n"
        f"    python -m harness.stages.score_records --system cira\n"
        f"    python -m harness.stages.run_judge\n"
        f"    python -c \"from run_all import stage_summary; "
        f"stage_summary(['cira','rule_based','naive_llm'], repetitions=3)\"\n\n"
        f"Override only if you intend to replace that run: --force-lock"
    )
