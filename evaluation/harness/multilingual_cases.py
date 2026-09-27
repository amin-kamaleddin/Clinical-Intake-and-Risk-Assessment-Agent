"""The 10-scenario subset used for the multilingual evaluation.

Chosen for COVERAGE of the behaviours that language can plausibly break, not to
reproduce the 50-case corpus proportions. The multilingual run asks whether CIRA
still behaves correctly when the conversation is not in English; the cases where
that is most likely to fail are the safety distractors, so they are deliberately
over-represented (4 of 10 here against 8 of 50 in the full corpus).

Report per-classification results for this subset rather than aggregate
specificity. With 10 cases, sensitivity moves in steps of 1/3 and specificity in
steps of 1/7, so neither aggregate supports a precise claim.

Why each case is here:

  04-04  the most severe case in the corpus - current suicidal ideation with a
         specific plan and stated intent. If any case must still be caught in
         every language, it is this one. Clear persona, so a miss cannot be
         blamed on the patient being hard to understand.
  04-20  the same risk category against the hardest persona (confused), which is
         where target-language comprehension is most strained.
  04-35  a recent attempt two weeks ago plus current passive ideation: the
         timeframe distinction the gate has to get right.

  04-38  figurative language only. THE critical multilingual case: idioms for
         exhaustion or despair do not translate literally, and a system that
         pattern-matches on words rather than meaning will fail differently in
         each language.
  04-27  ego-dystonic intrusive thoughts. CIRA historically false-alarmed here
         in English, so it is the known-fragile case.
  04-16  third-person family history only. Subject attribution is marked very
         differently across these languages (Arabic and Mandarin especially),
         so "my uncle died by suicide" is a genuine cross-lingual test.
  04-45  a historical attempt, resolved. Tests past-versus-present marking,
         which is grammaticalised differently in each target language.

  04-01  low symptom burden (PHQ-9 3) - guards against a system that flags on
         distress in general.
  04-13  GAD-dominant profile (PHQ-9 9, GAD-7 18) - the instruments must stay
         distinguishable when both are administered in translation.
  04-32  mid-severity with a confused persona, intermediate difficulty.
"""

from __future__ import annotations

#: Scenario ids, in corpus order.
MULTILINGUAL_CASE_IDS = [
    "04-01", "04-04", "04-13", "04-16", "04-20",
    "04-27", "04-32", "04-35", "04-38", "04-45",
]

#: Why each case was selected, for the manuscript's methods section.
SELECTION_RATIONALE = {
    "04-04": "most severe: active ideation with plan and intent",
    "04-20": "risk against the confused persona",
    "04-35": "recent attempt plus current passive ideation",
    "04-38": "figurative language only - idioms do not translate literally",
    "04-27": "ego-dystonic intrusive thoughts - known-fragile in English",
    "04-16": "third-person family history - subject attribution",
    "04-45": "historical attempt, resolved - past versus present marking",
    "04-01": "low symptom burden - guards against flagging distress itself",
    "04-13": "GAD-dominant - instruments must stay distinguishable",
    "04-32": "mid-severity, confused persona",
}

#: The one safety classification this subset does not cover.
#:
#: historical_non_suicidal_self_injury (04-07, 04-17) is left out. What it
#: probes that matters for language - past-versus-present marking - is already
#: covered by 04-45, and it was not a fragile class in the English run (2/2
#: correct across all three repetitions), unlike the ego-dystonic and
#: figurative-language distractors which both produced errors. Add 04-07 if the
#: subset is ever widened to twelve.
UNCOVERED_CLASSIFICATIONS = ["historical_non_suicidal_self_injury"]
