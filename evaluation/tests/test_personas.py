"""Offline checks for the persona layer. No API keys, no network, no langchain.

Run from the evaluation folder::

    python -m tests.test_personas

These guard the two properties the persona layer is only useful if it has:

1. **Reproducibility.** One seed determines the whole assignment, filtering a
   run to one case does not change that case's persona, and every system sees
   the same patient on the same case.
2. **Ground-truth safety.** Making the patient harder must not corrupt the
   scores being measured. Questionnaire answers still converge to the exact
   stored response, deferral is bounded, and no deferral line can be misread as
   a real answer.

langchain is stubbed so the simulator can be exercised without dependencies or
credentials; nothing here calls a model.
"""

from __future__ import annotations

import sys
import types


# --------------------------------------------------------------------------- #
# Stub langchain so PatientSimulator can be constructed offline
# --------------------------------------------------------------------------- #
def _install_langchain_stubs() -> None:
    if "langchain_openai" not in sys.modules:
        module = types.ModuleType("langchain_openai")

        class ChatOpenAI:  # noqa: D401 - stand-in
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def invoke(self, messages):
                raise AssertionError(
                    "The model was called; these tests must stay offline."
                )

        module.ChatOpenAI = ChatOpenAI
        sys.modules["langchain_openai"] = module

    if "langchain_core" not in sys.modules:
        core = types.ModuleType("langchain_core")
        messages = types.ModuleType("langchain_core.messages")

        class _Message:
            def __init__(self, content=""):
                self.content = content

        messages.AIMessage = type("AIMessage", (_Message,), {})
        messages.HumanMessage = type("HumanMessage", (_Message,), {})
        messages.SystemMessage = type("SystemMessage", (_Message,), {})
        core.messages = messages
        sys.modules["langchain_core"] = core
        sys.modules["langchain_core.messages"] = messages


_install_langchain_stubs()

from harness import personas  # noqa: E402
from harness.patient_simulator import PatientSimulator  # noqa: E402


PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    PASSED += 1
    print(f"  ok  {label}")


def _scenario() -> dict:
    """Minimal scenario with the fields the simulator touches."""
    return {
        "case_id": "04-99",
        "patient_facts": {
            "phq9": {
                **{f"phq9_q{i}": (i % 4) for i in range(1, 10)},
                "phq9_difficulty": "Somewhat difficult",
            },
            "gad7": {
                **{f"gad7_q{i}": (i % 4) for i in range(1, 8)},
                "gad7_difficulty": "Very difficult",
            },
        },
    }


# --------------------------------------------------------------------------- #
def test_assignment_is_deterministic() -> None:
    print("\nassignment determinism")
    ids = [f"04-{n:02d}" for n in range(1, 13)]

    a = personas.assign_personas(ids, seed=42)
    b = personas.assign_personas(ids, seed=42)
    check(a == b, "same seed gives the same assignment")

    check(
        personas.assign_personas(list(reversed(ids)), seed=42) == a,
        "input order does not affect the assignment",
    )
    check(
        personas.assign_personas(ids, seed=43) != a,
        "a different seed gives a different assignment",
    )


def test_balanced_counts() -> None:
    print("\nbalanced strategy")
    for n in (3, 12, 13, 14, 20):
        ids = [f"04-{i:02d}" for i in range(1, n + 1)]
        assignment = personas.assign_personas(ids, seed=1, strategy="balanced")
        counts = [
            sum(1 for v in assignment.values() if v == pid)
            for pid in personas.PERSONA_IDS
        ]
        check(
            max(counts) - min(counts) <= 1,
            f"n={n}: counts within one of each other {counts}",
        )


def test_case_filter_stability() -> None:
    print("\nfilter stability")
    full = personas.resolve_assignment(seed=99)
    for case_id in list(full)[:3]:
        one = personas.persona_for_case(case_id, seed=99)
        check(
            one.id == full[case_id],
            f"{case_id}: single-case run matches full run ({one.id})",
        )


def test_deflection_lines_are_safe() -> None:
    print("\ndeflection line safety")
    for persona in personas.PERSONAS.values():
        for line in persona.deflection_lines:
            lowered = line.lower()
            check(
                not any(p in lowered for p in personas.CANONICAL_RESPONSES),
                f"{persona.id}: line is not a scorable answer - {line[:38]!r}",
            )


def test_clear_persona_never_deflects() -> None:
    print("\nclear persona (control)")
    patient = PatientSimulator(_scenario(), persona="clear")
    from harness.patient_simulator import SCORE_TO_RESPONSE

    answers = [patient.answer(f"PHQ-9 question {i}") for i in range(1, 10)]
    expected = [SCORE_TO_RESPONSE[i % 4] for i in range(1, 10)]
    check(answers == expected, "every item answered exactly, first time")
    check(
        patient.behaviour_summary()["questionnaire_deflections"] == 0,
        "no deferrals at all",
    )


def test_hard_personas_converge() -> None:
    print("\nhard personas converge and stay bounded")
    from harness.patient_simulator import SCORE_TO_RESPONSE

    for persona_id in ("moderate", "confused"):
        persona = personas.get_persona(persona_id)
        patient = PatientSimulator(_scenario(), persona=persona_id)

        for instrument, count in (("PHQ-9", 9), ("GAD-7", 7)):
            for item in range(1, count + 1):
                question = f"{instrument} question {item}"
                expected = SCORE_TO_RESPONSE[item % 4]
                # Ask until the item is answered; must converge within the
                # per-item ceiling plus one.
                for _ in range(persona.max_deflections_per_item + 1):
                    if patient.answer(question) == expected:
                        break
                else:
                    raise AssertionError(
                        f"{persona_id}: {instrument} item {item} never converged"
                    )

        summary = patient.behaviour_summary()
        budget = persona.deflection_budget_per_instrument
        check(
            all(n <= budget for n in summary["deflections_by_instrument"].values()),
            f"{persona_id}: each instrument within its budget "
            f"({summary['deflections_by_instrument']} vs {budget})",
        )
        check(
            len(summary["deflections_by_instrument"]) == 2,
            f"{persona_id}: difficulty spread across BOTH instruments, not just PHQ-9",
        )
        check(
            all(
                n <= persona.max_deflections_per_item
                for n in summary["deflections_by_item"].values()
            ),
            f"{persona_id}: no item exceeded its per-item ceiling",
        )
        check(
            summary["questionnaire_deflections"] > 0,
            f"{persona_id}: actually made the intake harder",
        )


def test_persona_behaviour_is_reproducible() -> None:
    print("\nsimulator reproducibility")
    runs = []
    for _ in range(2):
        patient = PatientSimulator(_scenario(), persona="confused", seed=2026)
        runs.append([patient.answer(f"PHQ-9 question {i}") for i in range(1, 10)])
    check(runs[0] == runs[1], "same seed reproduces the same deferral pattern")

    other = PatientSimulator(_scenario(), persona="confused", seed=7)
    check(
        [other.answer(f"PHQ-9 question {i}") for i in range(1, 10)] != runs[0],
        "a different seed produces a different pattern",
    )


def test_prompt_contains_persona() -> None:
    print("\nprompt wiring")
    for persona_id in personas.PERSONA_IDS:
        patient = PatientSimulator(_scenario(), persona=persona_id)
        prompt = patient.system_prompt
        check(
            personas.PERSONAS[persona_id].behaviour_block[:40] in prompt,
            f"{persona_id}: behaviour block reached the system prompt",
        )
        check(
            "GROUND-TRUTH RULE" in prompt,
            f"{persona_id}: ground-truth rule is present",
        )


def test_persona_block_comes_last() -> None:
    """The persona must sit AFTER the scenario's own simulator instructions.

    It used to sit in the middle, ahead of roughly 4,000 characters of scenario
    text telling the patient to answer only what was asked, briefly and
    precisely. Those came later and were more specific, so they won: a
    ``confused`` patient produced correctly formatted addresses and postal
    codes on the first ask. Order is what makes the persona bite.
    """
    print("\nprompt ordering")
    scenario = _scenario()
    scenario["patient_simulator_instructions"] = (
        "Answer only what CIRA asks, reveal information gradually, be concise."
    )
    prompt = PatientSimulator(scenario, persona="confused").system_prompt

    persona_at = prompt.find("COMMUNICATION STYLE: UNCLEAR")
    scenario_at = prompt.find("Answer only what CIRA asks")
    check(persona_at > scenario_at, "persona block follows the scenario instructions")
    check(
        prompt.find("PRECEDENCE") > persona_at,
        "an explicit precedence note follows the persona block",
    )
    check(
        "overrides any earlier" in prompt,
        "the persona is declared to win on style conflicts",
    )


def test_freetext_hedging_is_bounded() -> None:
    """Free-text hedging must add difficulty without preventing convergence."""
    print("\nfree-text hedging")
    questions = [f"Tell me about topic {i}." for i in range(1, 13)]

    from harness.patient_simulator import normalize_question

    for persona_id in ("moderate", "confused"):
        persona = personas.get_persona(persona_id)
        patient = PatientSimulator(_scenario(), persona=persona_id)

        # Two sections, so the per-section budget must refresh between them.
        hedged = []
        for section in ("general_information", "medications"):
            patient.begin_section(section)
            in_section = 0
            for question in questions * 3:
                if patient._should_hedge(question):
                    patient._hedges_used += 1
                    patient._hedges_this_section += 1
                    patient._hedged_questions.add(normalize_question(question))
                    hedged.append(f"{section}:{question}")
                    in_section += 1
            check(
                in_section <= persona.freetext_hedge_budget_per_section,
                f"{persona_id}/{section}: within per-section budget "
                f"({in_section}/{persona.freetext_hedge_budget_per_section})",
            )
        check(
            len(hedged) == len(set(hedged)),
            f"{persona_id}: no question hedged twice, so every field converges",
        )
        check(patient._hedges_used > 0, f"{persona_id}: hedging actually happens")
        check(
            len({h.split(":")[0] for h in hedged}) == 2,
            f"{persona_id}: budget refreshes per section, so late sections are "
            f"not run against a clear patient",
        )

    control = PatientSimulator(_scenario(), persona="clear")
    control.begin_section("general_information")
    check(
        not any(control._should_hedge(q) for q in questions * 3),
        "clear persona never hedges (control condition preserved)",
    )


def main() -> None:
    print("=" * 60)
    print("PERSONA LAYER SELF-TEST")
    print("=" * 60)
    test_assignment_is_deterministic()
    test_balanced_counts()
    test_case_filter_stability()
    test_deflection_lines_are_safe()
    test_clear_persona_never_deflects()
    test_hard_personas_converge()
    test_persona_behaviour_is_reproducible()
    test_prompt_contains_persona()
    test_persona_block_comes_last()
    test_freetext_hedging_is_bounded()
    print("\n" + "=" * 60)
    print(f"ALL {PASSED} CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
