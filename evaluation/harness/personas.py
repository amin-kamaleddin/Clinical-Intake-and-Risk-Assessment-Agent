"""Patient personas and their seeded assignment to test cases.

Why this exists
---------------
Until now every simulated patient behaved the same way: cooperative, on-topic,
one clean answer per question. That measures CIRA against an unrealistically
easy interlocutor and hides the capability the agent actually exists for -
*guiding* a patient who cannot self-report cleanly.

This module adds three personas that vary **how** a patient communicates while
leaving **what** they know completely untouched:

===============  =========================================================
``clear``        Organised, literal, answers exactly what was asked. This is
                 the control condition and reproduces the previous
                 (persona-less) behaviour, so old results stay comparable.
``moderate``     Cooperative but imprecise. Occasionally hedges, bundles two
                 facts together, drifts one step off-topic, needs the odd
                 nudge before committing to a questionnaire answer.
``confused``     Genuinely hard. Rambling, tangential, answers the previous
                 question, misunderstands the frequency scale, asks CIRA to
                 repeat itself, discloses in the wrong order. CIRA has to do
                 the work of steering.
===============  =========================================================

The ground-truth invariant
--------------------------
A persona changes *delivery*, never *content*. A confused patient may hedge,
digress, or momentarily blank on a detail, but any concrete fact they finally
state is exactly the fact in ``patient_facts``. They never assert a concrete
detail that contradicts the scenario. Without this rule, record-accuracy
scoring would be measuring the simulator's improvisation instead of CIRA.

The same rule shapes questionnaire handling. A hard persona *defers* a PHQ-9 or
GAD-7 item (see ``deflection_lines``) rather than answering it off-scale, so
CIRA must re-ask or re-explain the options; when the item is finally answered
it still carries the exact stored score. Deflection lines are therefore
deliberately non-committal and contain no numbers - an ambiguous answer forces
a re-ask, whereas "maybe three days a week" would invite CIRA to guess a score
that ground truth cannot adjudicate.

Assignment
----------
``resolve_assignment()`` maps every case id to a persona from a single seed.
Two properties matter and are both guaranteed:

* **Stable under filtering.** The assignment is always computed over *every*
  case id in the scenario file, then filtered. ``--case 04-01`` gets the same
  persona it would get in a full run.
* **Stable across systems.** CIRA, the rule-based baseline and the naive-LLM
  ablation all derive the assignment the same way, so the three systems face
  the identical patient on the identical case. Comparisons stay paired.

Default strategy is ``balanced``: personas are dealt out in equal counts and
then shuffled, so 12 cases give exactly 4-4-4 rather than whatever an i.i.d.
draw happens to produce. ``random`` (i.i.d.) is available when you explicitly
want sampling noise.

CLI
---
Inspect an assignment without running anything::

    python -m harness.personas                    # default seed
    python -m harness.personas --seed 7
    python -m harness.personas --strategy random
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from typing import Iterable

from harness import config


# --------------------------------------------------------------------------- #
# The fixed PHQ-9 / GAD-7 frequency phrases.
#
# No deflection line may contain one of these: CIRA's parser would read it as a
# real answer and the deferral would silently become a scored response.
# ``_validate_personas()`` enforces this at import time.
# --------------------------------------------------------------------------- #
CANONICAL_RESPONSES = (
    "not at all",
    "several days",
    "more than half the days",
    "nearly every day",
)


@dataclass(frozen=True)
class Persona:
    """One patient communication style.

    Attributes
    ----------
    id, label, description, difficulty_rank
        Identity and reporting metadata. ``difficulty_rank`` (1 = easiest)
        gives reports a stable ordering.
    temperature
        Sampling temperature for the simulator's free-text answers. Higher =
        looser, more meandering speech. Ignored if ``CIRA_EVAL_TEMPERATURE`` is
        pinned in the environment.
    questionnaire_deflection_probability
        Chance that a PHQ-9/GAD-7 item is deferred instead of answered on the
        first ask.
    max_deflections_per_item
        Ceiling on deferrals for any single item, so one item can never loop.
    deflection_budget_per_instrument
        Ceiling on deferrals within each instrument (PHQ-9 and GAD-7 counted
        separately). Per-instrument rather than per-intake so a hard persona
        does not spend its whole allowance on PHQ-9 and then sail through
        GAD-7. Also bounds turn inflation against
        ``config.MAX_TURNS_PER_SECTION``: PHQ-9's 10 items plus this budget
        must stay under that cap.
    deflection_lines
        Non-committal replies used when deferring an item.
    freetext_hedge_probability, freetext_hedge_budget_per_section
        The free-text analogue of questionnaire deferral. The budget is PER
        SECTION, not per intake: a global budget was exhausted inside the first
        three sections, so everything from medications onward faced a
        completely clear patient. Same failure the questionnaire budget had
        before it was made per-instrument. Persona behaviour in a
        free-text answer depends on the model obeying a prompt, which it does
        unevenly; these make a bounded amount of it deterministic. On a hedged
        turn the simulator injects a one-turn directive telling the patient to
        stall rather than commit. A question is never hedged twice, so every
        field still converges.
    behaviour_block
        Persona instructions injected into the simulator's system prompt.
    """

    id: str
    label: str
    difficulty_rank: int
    description: str
    temperature: float
    questionnaire_deflection_probability: float
    max_deflections_per_item: int
    deflection_budget_per_instrument: int
    deflection_lines: tuple[str, ...]
    freetext_hedge_probability: float
    freetext_hedge_budget_per_section: int
    behaviour_block: str

    def metadata(self) -> dict:
        """Small dict for stamping into transcripts, records and reports."""
        return {
            "id": self.id,
            "label": self.label,
            "difficulty_rank": self.difficulty_rank,
            "description": self.description,
            "temperature": self.temperature,
            "questionnaire_deflection_probability": (
                self.questionnaire_deflection_probability
            ),
            "max_deflections_per_item": self.max_deflections_per_item,
            "deflection_budget_per_instrument": self.deflection_budget_per_instrument,
            "freetext_hedge_probability": self.freetext_hedge_probability,
            "freetext_hedge_budget_per_section": self.freetext_hedge_budget_per_section,
        }


# --------------------------------------------------------------------------- #
# Persona definitions
# --------------------------------------------------------------------------- #
_SHARED_GROUND_TRUTH_RULE = """
GROUND-TRUTH RULE (overrides every style instruction below)
Your persona controls HOW you speak, never WHAT is true. Every concrete detail
you state - a drug name, a dose, a date, a duration, a diagnosis, a number of
sessions - must match the supplied patient facts exactly. You may hedge, stall,
misunderstand the question, or describe something loosely ("one of those
antidepressants", "the small white one") before committing. You may never state
a concrete detail that contradicts the facts, and you may never invent one. If
you do not have a fact, say you do not know. Being vague is always allowed;
being wrong never is.
""".strip()


CLEAR = Persona(
    id="clear",
    label="Clear communicator",
    difficulty_rank=1,
    description=(
        "Organised and literal. Answers precisely the question asked, in one "
        "pass, with the right level of detail. Control condition."
    ),
    temperature=0.0,
    questionnaire_deflection_probability=0.0,
    max_deflections_per_item=0,
    deflection_budget_per_instrument=0,
    deflection_lines=(),
    freetext_hedge_probability=0.0,
    freetext_hedge_budget_per_section=0,
    behaviour_block=f"""
COMMUNICATION STYLE: CLEAR
You are an articulate, well-organised historian of your own health.

1. Answer exactly the question asked, then stop.
2. Give the detail the question calls for on the first pass; no hedging.
3. Use plain, direct sentences. One or two sentences is usually right.
4. Stay strictly on topic. Do not volunteer unrelated material.
5. When you do not know something, say so plainly and immediately.
6. For questionnaire items, reply with the exact frequency phrase, nothing else.
7. For identity details - name, date of birth, address, postal code, phone,
   email - give the complete, correctly formatted value on the first ask.

{_SHARED_GROUND_TRUTH_RULE}
""".strip(),
)


MODERATE = Persona(
    id="moderate",
    label="Somewhat unclear",
    difficulty_rank=2,
    description=(
        "Cooperative but imprecise. Hedges, bundles facts, occasionally drifts "
        "one step off-topic, sometimes needs a nudge to commit."
    ),
    temperature=0.4,
    questionnaire_deflection_probability=0.35,
    max_deflections_per_item=1,
    deflection_budget_per_instrument=2,
    deflection_lines=(
        "Hmm, that one's hard to say. What were the choices again?",
        "Sort of, I guess? It really depends on the week.",
        "I'm not sure how to put that. Can you ask it a different way?",
        "That's a tough one to pin down.",
        "Depends what you mean exactly - over what stretch of time?",
    ),
    freetext_hedge_probability=0.25,
    freetext_hedge_budget_per_section=2,
    behaviour_block=f"""
COMMUNICATION STYLE: SOMEWHAT UNCLEAR
You are cooperative and willing, but not a precise reporter.

1. Answer the question, but often only partially on the first pass. Give the
   headline and hold back the specifics until asked again ("I'm on something
   for my mood" before naming the drug).
2. Hedge and qualify: "I think", "maybe around", "something like that".
3. Roughly one answer in four, add a short tangent that is related but not
   what was asked, then return to the point if pressed.
4. Occasionally answer a slightly different question than the one asked - the
   adjacent, easier one. If the interviewer re-asks, answer properly.
5. Sometimes bundle two facts into one sentence rather than waiting to be asked
   for the second.
6. Ask a brief clarifying question now and then instead of answering.
7. Stay polite and engaged throughout. You want to be helpful; you are just not
   crisp.
8. Identity details come out imprecisely at first. Give a date as "March 2003"
   or "I think it's the 9th of February", an address without the province, a
   phone number in the wrong grouping, a doctor as "Dr. Chu" without a first
   name. Supply the missing or correctly formatted part when asked.

{_SHARED_GROUND_TRUTH_RULE}
""".strip(),
)


CONFUSED = Persona(
    id="confused",
    label="Unclear and disorganised",
    difficulty_rank=3,
    description=(
        "Hard to interview. Rambles, misreads questions, needs the frequency "
        "scale re-explained, discloses out of order. Tests whether the agent "
        "can actively guide rather than merely transcribe."
    ),
    temperature=0.8,
    questionnaire_deflection_probability=0.8,
    max_deflections_per_item=2,
    deflection_budget_per_instrument=5,
    deflection_lines=(
        "Sorry, I don't follow. Do you mean how often, or how bad it gets?",
        "Uh... some weeks more than others, I suppose.",
        "Can you say that again? I lost the thread.",
        "That depends. Are you asking about now or about back then?",
        "I really don't know how to answer that one.",
        "Which of those was the middle one? I've forgotten the list.",
        "Hm. Hard to say. My days all run together lately.",
    ),
    freetext_hedge_probability=0.5,
    freetext_hedge_budget_per_section=4,
    behaviour_block=f"""
COMMUNICATION STYLE: UNCLEAR AND DISORGANISED
You find this interview hard. You are not obstructive - you genuinely struggle
to organise your thoughts and to work out what is being asked.

1. Ramble. Answers often run long and wander into a story, a complaint about
   something unrelated, or a detail about a family member.
2. Frequently bury the actual answer in the middle or end of the reply, rather
   than leading with it.
3. Misread questions. Sometimes answer the previous question again, or a
   different one you assumed was being asked.
4. Ask the interviewer to repeat or rephrase reasonably often.
5. Struggle with the frequency scale. Say the options are confusing, or ask
   which one fits, rather than picking one straight away.
6. Disclose out of order: mention something from a much later part of the
   history unprompted, then need to be brought back.
7. Trail off, self-interrupt, and correct yourself mid-sentence.
8. When a clear, well-scaffolded question is put to you - one option at a time,
   or a plain restatement - you CAN answer it properly. Reward good
   interviewing: if the interviewer breaks the question down or repeats it
   simply, give the real answer.
9. Identity details are where your disorganisation shows most. Do NOT recite a
   formatted address, postal code, phone number or date of birth on the first
   ask. Give them in pieces, in the wrong order, or in the wrong format: the
   street without the city, the month as a word, a phone number read as
   "four one six, then five five five...", a doctor as "Dr. Chu I think, or
   maybe Chiu". Supply the rest when the interviewer asks for the missing part
   or explains the format. Every piece you eventually give must still be the
   supplied fact.
10. Never state a fact you were not given. Your confusion shows up as vagueness,
   digression, mis-ordering and bad formatting, never as invented detail.

{_SHARED_GROUND_TRUTH_RULE}
""".strip(),
)


PERSONAS: dict[str, Persona] = {p.id: p for p in (CLEAR, MODERATE, CONFUSED)}

# Ordered easiest -> hardest. Used for balanced dealing and report ordering.
PERSONA_IDS: tuple[str, ...] = tuple(
    p.id for p in sorted(PERSONAS.values(), key=lambda p: p.difficulty_rank)
)

DEFAULT_PERSONA_ID = CLEAR.id

ASSIGNMENT_STRATEGIES = ("balanced", "random")


def _validate_personas() -> None:
    """Fail loudly at import if a deflection line could be read as an answer."""
    for persona in PERSONAS.values():
        for line in persona.deflection_lines:
            lowered = line.lower()
            for phrase in CANONICAL_RESPONSES:
                if phrase in lowered:
                    raise ValueError(
                        f"Persona {persona.id!r} deflection line contains the "
                        f"canonical response {phrase!r}, which CIRA would score "
                        f"as a real answer: {line!r}"
                    )
        if persona.deflection_lines and persona.max_deflections_per_item <= 0:
            raise ValueError(
                f"Persona {persona.id!r} has deflection lines but cannot use them."
            )
        if persona.max_deflections_per_item > 0 and not persona.deflection_lines:
            raise ValueError(
                f"Persona {persona.id!r} may deflect but has no lines to deflect with."
            )


_validate_personas()


def get_persona(persona_id: str | Persona | None) -> Persona:
    """Look up a persona by id. ``None`` yields the default (``clear``)."""
    if isinstance(persona_id, Persona):
        return persona_id
    if persona_id is None:
        return PERSONAS[DEFAULT_PERSONA_ID]
    try:
        return PERSONAS[str(persona_id).strip().lower()]
    except KeyError:
        raise ValueError(
            f"Unknown persona {persona_id!r}; expected one of {PERSONA_IDS}"
        ) from None


# --------------------------------------------------------------------------- #
# Seeded assignment
# --------------------------------------------------------------------------- #
def assign_personas(
    case_ids: Iterable[str],
    seed: int,
    strategy: str = "balanced",
) -> dict[str, str]:
    """Map every case id to a persona id deterministically from ``seed``.

    ``case_ids`` is sorted first, so the result depends only on the *set* of
    ids and the seed - never on the order they arrived in.

    balanced
        Deal each persona ``n // k`` times, top up the remainder with a
        without-replacement sample (so no persona is systematically favoured by
        the leftover), then shuffle. 12 cases give exactly 4-4-4.
    random
        Independent uniform draw per case. Counts will be uneven; use when you
        specifically want that noise.
    """
    if strategy not in ASSIGNMENT_STRATEGIES:
        raise ValueError(
            f"Unknown strategy {strategy!r}; expected one of {ASSIGNMENT_STRATEGIES}"
        )

    ordered_ids = sorted({str(case_id) for case_id in case_ids})
    # Namespacing the seed string keeps this stream independent of any other
    # RNG that happens to use the same integer seed.
    rng = random.Random(f"cira-persona-assignment::{seed}::{strategy}")

    if strategy == "random":
        return {case_id: rng.choice(PERSONA_IDS) for case_id in ordered_ids}

    count = len(ordered_ids)
    kinds = len(PERSONA_IDS)
    pool = list(PERSONA_IDS) * (count // kinds)
    pool += rng.sample(PERSONA_IDS, count % kinds)
    rng.shuffle(pool)
    return dict(zip(ordered_ids, pool))


def _all_case_ids() -> list[str]:
    """Every case id in the scenario file.

    Read directly rather than taking a caller's (possibly filtered) list: this
    is what makes a ``--case`` run agree with a full run.
    """
    scenarios = json.loads(config.SCENARIO_FILE.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list):
        raise ValueError("cira_scenarios.json must contain a list.")
    return [str(s["case_id"]) for s in scenarios]


def resolve_assignment(
    seed: int | None = None,
    strategy: str | None = None,
    override: str | None = None,
) -> dict[str, str]:
    """The persona assignment every stage should use.

    ``override`` forces one persona onto every case - the ablation knob for
    "run all 12 scenarios against a confused patient".
    """
    if override:
        forced = get_persona(override).id
        return {case_id: forced for case_id in sorted(_all_case_ids())}

    return assign_personas(
        _all_case_ids(),
        seed=config.PERSONA_SEED if seed is None else seed,
        strategy=config.PERSONA_ASSIGNMENT_STRATEGY if strategy is None else strategy,
    )


def persona_for_case(
    case_id: str,
    seed: int | None = None,
    strategy: str | None = None,
    override: str | None = None,
) -> Persona:
    """Resolve one case's persona (falls back to the default if unlisted)."""
    assignment = resolve_assignment(seed=seed, strategy=strategy, override=override)
    return get_persona(assignment.get(str(case_id), DEFAULT_PERSONA_ID))


# --------------------------------------------------------------------------- #
# Reporting / provenance
# --------------------------------------------------------------------------- #
def assignment_report(
    seed: int | None = None,
    strategy: str | None = None,
    override: str | None = None,
) -> dict:
    """Full provenance for an assignment, safe to write to disk."""
    effective_seed = config.PERSONA_SEED if seed is None else seed
    effective_strategy = (
        config.PERSONA_ASSIGNMENT_STRATEGY if strategy is None else strategy
    )
    assignment = resolve_assignment(
        seed=effective_seed, strategy=effective_strategy, override=override
    )

    counts = {pid: 0 for pid in PERSONA_IDS}
    for persona_id in assignment.values():
        counts[persona_id] += 1

    return {
        "seed": effective_seed,
        "strategy": "override" if override else effective_strategy,
        "override": get_persona(override).id if override else None,
        "total_cases": len(assignment),
        "counts": counts,
        "personas": {pid: PERSONAS[pid].metadata() for pid in PERSONA_IDS},
        "assignment": dict(sorted(assignment.items())),
    }


def write_assignment(
    seed: int | None = None,
    strategy: str | None = None,
    override: str | None = None,
) -> dict:
    """Persist the assignment next to the other reports and return it."""
    report = assignment_report(seed=seed, strategy=strategy, override=override)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    config.PERSONA_ASSIGNMENT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def format_assignment_table(report: dict) -> str:
    lines = [
        "-" * 60,
        f"PERSONA ASSIGNMENT  (seed={report['seed']}, "
        f"strategy={report['strategy']})",
        "-" * 60,
    ]
    for case_id, persona_id in report["assignment"].items():
        lines.append(f"  {case_id:<8} -> {persona_id}")
    counts = ", ".join(f"{pid}={n}" for pid, n in report["counts"].items())
    lines.append("-" * 60)
    lines.append(f"  counts: {counts}")
    lines.append("-" * 60)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show the persona assignment for the current scenario set."
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--strategy", choices=ASSIGNMENT_STRATEGIES, default=None)
    parser.add_argument("--persona", choices=PERSONA_IDS, default=None,
                        help="Force this persona onto every case.")
    parser.add_argument("--write", action="store_true",
                        help="Also save to outputs/reports/persona_assignment.json")
    args = parser.parse_args()

    report = (write_assignment if args.write else assignment_report)(
        seed=args.seed, strategy=args.strategy, override=args.persona
    )
    print(format_assignment_table(report))
    if args.write:
        print("Saved to:", config.PERSONA_ASSIGNMENT_PATH)


if __name__ == "__main__":
    main()
