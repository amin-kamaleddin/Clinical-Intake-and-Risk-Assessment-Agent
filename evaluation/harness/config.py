"""Single source of truth for the CIRA evaluation harness.

Everything that used to be scattered and inconsistent across scripts lives here:

* where files are read from and written to,
* how a case id maps to a filename,
* which .env files to load,
* the tunable model / temperature settings.

If you want to move the output tree or rename a report, change it *once* here
and every stage follows.

Layout produced by the harness
------------------------------
::

    evaluation/
      run_all.py                 <- the one entry point
      cira_scenarios.json
      harness/                   <- all library + stage code
      outputs/
        cira/
          transcripts/case_04_01.json
          records/case_04_01.json
        rule_based/
          transcripts/case_04_01.json
          records/case_04_01.json
        judge/
          cira/case_04_01.json
          rule_based/case_04_01.json
        reports/
          cira_deterministic.json
          rule_based_deterministic.json
          judge_comparison.json
          summary.json

Naming rules (used everywhere; no more per-script variants)
-----------------------------------------------------------
* ``safe_case_id("04-01")``  -> ``"04_01"``   (used in every filename)
* ``short_case_id("04-01")`` -> ``"01"``      (record metadata id)
* every per-case artifact is ``case_<safe_id>.json`` in a folder that names
  its own type, so the filename never has to encode the system or artifact
  kind again.
"""

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


def case_filename(case_id: str) -> str:
    return f"case_{safe_case_id(case_id)}.json"


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


def transcript_path(system: str, case_id: str) -> Path:
    return transcript_dir(system) / case_filename(case_id)


def record_path(system: str, case_id: str) -> Path:
    return record_dir(system) / case_filename(case_id)


def judge_dir(system: str) -> Path:
    return JUDGE_DIR / system


def judge_path(system: str, case_id: str) -> Path:
    return judge_dir(system) / case_filename(case_id)


# --------------------------------------------------------------------------- #
# Report paths
# --------------------------------------------------------------------------- #
def deterministic_report_path(system: str) -> Path:
    return REPORTS_DIR / f"{system}_deterministic.json"


JUDGE_REPORT_PATH = REPORTS_DIR / "judge_comparison.json"
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

# Each persona carries its own temperature (a confused patient needs looser
# sampling than a crisp one). Setting CIRA_EVAL_TEMPERATURE explicitly pins one
# temperature for every persona instead - useful when you want to isolate the
# effect of the prompt from the effect of sampling.
_PATIENT_TEMPERATURE_ENV = os.getenv("CIRA_EVAL_TEMPERATURE")
PATIENT_TEMPERATURE_IS_PINNED = _PATIENT_TEMPERATURE_ENV is not None
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
JUDGE_MAX_TOKENS = int(os.getenv("CIRA_JUDGE_MAX_TOKENS", "4000"))
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
