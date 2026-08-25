
from __future__ import annotations

import os
import re
from pathlib import Path


# --------------------------------------------------------------------------- #
# Directory layout
# --------------------------------------------------------------------------- #
# This file lives at   evaluation/harness/config.py
EVALUATION_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = EVALUATION_DIR.parent          # dir that holds evaluation/ and cira/
CIRA_DIR = PROJECT_ROOT / "cira"              # the real CIRA package (sibling folder)

SCENARIO_FILE = EVALUATION_DIR / "cira_scenarios.json"

OUTPUTS_DIR = EVALUATION_DIR / "outputs"
REPORTS_DIR = OUTPUTS_DIR / "reports"
JUDGE_DIR = OUTPUTS_DIR / "judge"

# The intake systems the harness knows how to run and score.
#   cira       - the full LangGraph agent (the system under test)
#   rule_based - deterministic finite-state floor (control)
#   naive_llm  - one big prompt + a plain chat loop, no architecture (ablation)
SYSTEMS = ("cira", "rule_based", "naive_llm")

# The canonical intake sections, in order. Shared by the rule-based engine and
# the deterministic scorer so the two can never drift.
CANONICAL_SECTIONS = [
    "general_information",
    "current_concerns",
    "past_psychiatric_history",
    "medications",
    "medical_history",
    "medication_allergies",
    "family_psychiatric_history",
    "substance_use",
    "education_employment_legal_history",
    "personal_history",
    "phq9",
    "gad7",
]


# --------------------------------------------------------------------------- #
# Case-id / filename helpers  (ONE definition, used by every stage)
# --------------------------------------------------------------------------- #
def safe_case_id(case_id: str) -> str:
    """Filename-safe id: ``"04-01"`` -> ``"04_01"``."""
    return str(case_id).replace("-", "_")


def short_case_id(case_id: str) -> str:
    """Record metadata id: the trailing two digits, e.g. ``"04-01"`` -> ``"01"``."""
    match = re.search(r"(\d{2})$", str(case_id))
    if not match:
        raise ValueError(f"Invalid case_id: {case_id!r}")
    return match.group(1)


# --------------------------------------------------------------------------- #
# Repetitions
# --------------------------------------------------------------------------- #
# One interaction per scenario is a single realisation of a stochastic process,
# so a difference like 0.9308 vs 0.9285 cannot be distinguished from sampling
# noise. Repeating each scenario independently gives a distribution instead.
#
# Repetition 0 keeps the original filename (case_04_01.json) so existing
# artifacts, single-run behaviour and every downstream path stay valid; later
# repetitions add a _r01, _r02 ... suffix.
REPETITIONS = int(os.getenv("CIRA_REPETITIONS", "1"))


# Upper bound when discovering repetitions from the filesystem. Scoring reads
# what exists rather than what config says, so an older single-run output set
# still scores and a partially finished repeated run scores what it has.
MAX_REPETITION_SCAN = int(os.getenv("CIRA_MAX_REPETITION_SCAN", "200"))


def repetition_indices(repetitions: int | None = None) -> range:
    return range(repetitions if repetitions is not None else REPETITIONS)


def case_filename(case_id: str, repetition: int = 0) -> str:
    """``case_04_01.json`` for repetition 0, ``case_04_01_r01.json`` after.

    Repetition 0 deliberately keeps the unsuffixed name so that a single-run
    evaluation produces byte-identical paths to before repetitions existed.
    """
    suffix = "" if not repetition else f"_r{repetition:02d}"
    return f"case_{safe_case_id(case_id)}{suffix}.json"


# --------------------------------------------------------------------------- #
# Per-system artifact paths
# --------------------------------------------------------------------------- #
def _system_dir(system: str) -> Path:
    if system not in SYSTEMS:
        raise ValueError(f"Unknown system {system!r}; expected one of {SYSTEMS}")
    return OUTPUTS_DIR / system


def transcript_dir(system: str) -> Path:
    return _system_dir(system) / "transcripts"


def record_dir(system: str) -> Path:
    return _system_dir(system) / "records"


def transcript_path(system: str, case_id: str, repetition: int = 0) -> Path:
    return transcript_dir(system) / case_filename(case_id, repetition)


def record_path(system: str, case_id: str, repetition: int = 0) -> Path:
    return record_dir(system) / case_filename(case_id, repetition)


def judge_dir(system: str) -> Path:
    """Judge output directory, namespaced by judge label.

    A second judge writes to outputs/judge_<label>/ so both verdict sets exist
    side by side and inter-rater agreement can be computed from artifacts
    rather than by re-judging. The primary judge keeps the original unlabelled
    path, so older output sets still score.
    """
    root = JUDGE_DIR if not JUDGE_LABEL else JUDGE_DIR.with_name(
        f"{JUDGE_DIR.name}_{JUDGE_LABEL}"
    )
    return root / system


def judge_path(system: str, case_id: str, repetition: int = 0) -> Path:
    return judge_dir(system) / case_filename(case_id, repetition)


# --------------------------------------------------------------------------- #
# Report paths
# --------------------------------------------------------------------------- #
def deterministic_report_path(system: str) -> Path:
    return REPORTS_DIR / f"{system}_deterministic.json"


def judge_report_path(label: str | None = None) -> Path:
    """Judge comparison report, namespaced by judge label."""
    label = JUDGE_LABEL if label is None else label
    name = "judge_comparison" + (f"_{label}" if label else "")
    return REPORTS_DIR / f"{name}.json"


JUDGE_REPORT_PATH = REPORTS_DIR / "judge_comparison.json"
JUDGE_AGREEMENT_PATH = REPORTS_DIR / "judge_agreement.json"
SUMMARY_REPORT_PATH = REPORTS_DIR / "summary.json"
# Provenance for the seeded persona assignment: which patient style each case
# was run against. Written once per run so a result set can always be traced
# back to the patients that produced it.
PERSONA_ASSIGNMENT_PATH = REPORTS_DIR / "persona_assignment.json"


def ensure_output_dirs() -> None:
    """Create the full output tree so stages never race on mkdir."""
    for system in SYSTEMS:
        transcript_dir(system).mkdir(parents=True, exist_ok=True)
        record_dir(system).mkdir(parents=True, exist_ok=True)
        judge_dir(system).mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Environment / .env loading
# --------------------------------------------------------------------------- #
def load_env() -> None:
    """Load .env files if python-dotenv is available.

    Looks in the evaluation folder and in the sibling cira/ folder, so keys can
    live wherever the project already keeps them. Safe to call repeatedly and
    safe when python-dotenv is not installed.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for env_file in (EVALUATION_DIR / ".env", CIRA_DIR / ".env"):
        if env_file.exists():
            load_dotenv(env_file)


# --------------------------------------------------------------------------- #
# Tunable settings (all LLM knobs in one place)
# --------------------------------------------------------------------------- #
load_env()

# Patient simulator (routed through OpenRouter).
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPEN_ROUTER")
PATIENT_MODEL_NAME = os.getenv("CIRA_PATIENT_MODEL", "openai/gpt-5.4-mini")

# One temperature for every persona, pinned by DEFAULT.
#
# The personas used to carry their own sampling temperatures (clear 0.0,
# moderate 0.4, confused 0.8). That made communication difficulty and sampling
# temperature vary together, so any difference between persona strata mixed the
# effect of the persona PROMPT with the effect of looser decoding and neither
# could be attributed. A persona is defined by how it is instructed to speak,
# not by how randomly it is decoded.
#
# Set CIRA_PERSONA_OWN_TEMPERATURE=1 to restore the old per-persona behaviour;
# the persona definitions still carry their temperatures for that path.
_PATIENT_TEMPERATURE_ENV = os.getenv("CIRA_EVAL_TEMPERATURE")
_PERSONA_OWN_TEMPERATURE = (
    os.getenv("CIRA_PERSONA_OWN_TEMPERATURE", "").strip().lower() in {"1", "true", "yes"}
)
PATIENT_TEMPERATURE_IS_PINNED = not _PERSONA_OWN_TEMPERATURE
PATIENT_TEMPERATURE = float(_PATIENT_TEMPERATURE_ENV or "0")

# --------------------------------------------------------------------------- #
# Patient personas
# --------------------------------------------------------------------------- #
# One seed drives the whole persona assignment. Change it to re-randomise which
# patient style each scenario faces; keep it to reproduce a previous run
# exactly. The assignment is always computed over the full scenario file, so
# --case runs agree with full runs and every system faces the same patient.
PERSONA_SEED = int(os.getenv("CIRA_PERSONA_SEED", "20260804"))

# "balanced" deals personas in equal counts then shuffles (12 cases -> 4/4/4).
# "random" draws i.i.d. per case, so counts come out uneven.
PERSONA_ASSIGNMENT_STRATEGY = os.getenv("CIRA_PERSONA_STRATEGY", "balanced")

# Force every case onto one persona (e.g. "confused") for a stress ablation.
# Empty/unset means use the seeded assignment.
PERSONA_OVERRIDE = os.getenv("CIRA_PERSONA_OVERRIDE") or None

# LLM-as-a-judge.
# Defaults to Gemini 3.1 Flash Lite (GA) routed through OpenRouter. Override the
# model, endpoint, or key per-variable if you want the judge somewhere else.
JUDGE_MODEL_NAME = os.getenv("CIRA_JUDGE_MODEL", "google/gemini-3.1-flash-lite")

# A second, independent judge for inter-rater reliability. record_score and
# flow_score otherwise rest on one model and one pass, which is the first thing
# a reviewer asks about. Deliberately a different family from the primary judge:
# two checkpoints of the same model agreeing tells you very little.
#
#   CIRA_JUDGE_MODEL=$CIRA_JUDGE_MODEL_B CIRA_JUDGE_LABEL=b \
#       python -m harness.stages.run_judge --system cira
#   python -m tools.judge_agreement
#
JUDGE_MODEL_B = os.getenv("CIRA_JUDGE_MODEL_B", "x-ai/grok-4-fast")

# Namespaces judge artifacts so two judges can coexist. Empty = primary judge.
JUDGE_LABEL = os.getenv("CIRA_JUDGE_LABEL", "").strip()
JUDGE_BASE_URL = os.getenv("CIRA_JUDGE_BASE_URL", OPENROUTER_BASE_URL)
JUDGE_API_KEY = os.getenv("CIRA_JUDGE_API_KEY", OPENROUTER_API_KEY)
JUDGE_TEMPERATURE = float(os.getenv("CIRA_JUDGE_TEMPERATURE", "0"))
# Gemini Flash Lite is a thinking-capable model; reasoning is on by default and
# is the main latency/token sink for a judge. "minimal" keeps it fast. Set to
# "default" to leave the provider's default reasoning untouched.
JUDGE_REASONING_EFFORT = os.getenv("CIRA_JUDGE_REASONING_EFFORT", "minimal")
# Robustness / speed knobs. A per-request timeout is what stops one stalled
# upstream from hanging the whole run; retries recover transient failures;
# workers judge several cases concurrently.
JUDGE_TIMEOUT = float(os.getenv("CIRA_JUDGE_TIMEOUT", "90"))
JUDGE_MAX_RETRIES = int(os.getenv("CIRA_JUDGE_MAX_RETRIES", "2"))
# Raised from 4000: record-judge responses were truncated mid-JSON on cases
# with many contested fields, failing schema validation and dropping the whole
# case from every mean. Batching in llm_judge.py is the real bound; this is a
# second layer.
JUDGE_MAX_TOKENS = int(os.getenv("CIRA_JUDGE_MAX_TOKENS", "8000"))
JUDGE_MAX_WORKERS = int(os.getenv("CIRA_JUDGE_MAX_WORKERS", "4"))

# Live-CIRA driver.
MAX_TURNS_PER_SECTION = int(os.getenv("CIRA_MAX_TURNS_PER_SECTION", "30"))

# Naive-LLM baseline (ablation). To be a fair ablation of CIRA's architecture it
# must use the SAME underlying model CIRA uses; only the complexity differs.
# Defaults therefore mirror CIRA: same model string, same reasoning setting,
# same (default OpenAI) endpoint. Override per-variable only if you must.
NAIVE_MODEL_NAME = os.getenv("CIRA_NAIVE_MODEL", os.getenv("CIRA_MODEL", "gpt-5.6-luna"))
NAIVE_BASE_URL = os.getenv("CIRA_NAIVE_BASE_URL")   # None -> default OpenAI, like CIRA
NAIVE_API_KEY = os.getenv("CIRA_NAIVE_API_KEY")     # None -> default key
NAIVE_REASONING_EFFORT = os.getenv("CIRA_NAIVE_REASONING_EFFORT", "none")
NAIVE_TEMPERATURE = float(os.getenv("CIRA_NAIVE_TEMPERATURE", "0"))
NAIVE_MAX_TURNS = int(os.getenv("CIRA_NAIVE_MAX_TURNS", "90"))


# ── Conditional fields ──────────────────────────────────────────────────
# Mirrors cira/prompts/builder.py. A field listed here is not required
# when its controlling boolean holds the hidden value, so "complete"
# means the same thing for every system being compared.
CONDITIONAL_FIELDS = {
    "family_doctor_name":                 ("has_family_doctor", False),
    "psychiatrist_name":                  ("has_psychiatrist", False),
    "assessment_details":                 ("previously_assessed", False),
    "hospital_details":                   ("hospital_admission", False),
    "self_harm_details":                  ("self_harm_history", False),
    "current_medications":                ("has_current_medications", False),
    "past_medication_details":            ("has_past_medications", False),
    "medical_conditions":                 ("has_medical_conditions", False),
    "surgical_history":                   ("has_surgical_history", False),
    "medication_allergies":               ("has_medication_allergies", False),
    "family_psychiatric_history_details": ("has_family_psychiatric_history", False),
    "legal_case_details":                 ("active_legal_cases", False),
}