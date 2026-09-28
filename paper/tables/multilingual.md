# Multilingual evaluation - 10 scenarios per language

Cases: 04-01, 04-04, 04-13, 04-16, 04-20, 04-27, 04-32, 04-35, 04-38, 04-45


## Comparable across languages

| language | intakes | structured | elicit. | fall-through | sections |
|---|---|---|---|---|---|
| English | 30 | 1.0 | 0 | 0 | 30/30 |
| Mandarin Chinese | 30 | 0.9983 | 0 | 0 | 29/30 |
| French | 30 | 0.9983 | 0 | 0 | 30/30 |
| Arabic | 30 | 1.0 | 0 | 0 | 30/30 |
| Hindi | 30 | 0.9983 | 0 | 0 | 30/30 |
| Farsi | 30 | 1.0 | 0 | 0 | 28/30 |

### Safety

Read `missed` first: a missed risk case is the only failure this system must never produce. Sensitivity is structurally protected in every language by the PHQ-9 Q9 rule, which acts on the saved numeric score, so a miss here would mean the questionnaire itself was not administered. With three risk cases per language, sensitivity moves in steps of 1/3.

| language | balanced acc | sens | spec | distractor spec | missed | false alarm |
|---|---|---|---|---|---|---|
| English | 1.0 | 1.0 | 1.0 | 1.0 | none | none |
| Mandarin Chinese | 0.9762 | 1.0 | 0.9524 | 0.9167 | none | 04-38 |
| French | 0.9762 | 1.0 | 0.9524 | 0.9167 | none | 04-45 |
| Arabic | 1.0 | 1.0 | 1.0 | 1.0 | none | none |
| Hindi | 0.9762 | 1.0 | 0.9524 | 0.9167 | none | 04-45 |
| Farsi | 1.0 | 1.0 | 1.0 | 1.0 | none | none |

## Record-language compliance

Every value should be stored in English whatever the conversation language, because the record judge compares it against English ground truth. Latin-script leakage (a French answer left in French) is not detectable this way and needs a reader.

| language | leaked fields | text fields | rate | examples |
|---|---|---|---|---|
| English | 0 | 4492 | 0.0 | - |
| Mandarin Chinese | 0 | 896 | 0.0 | - |
| French | 0 | 898 | 0.0 | - |
| Arabic | 0 | 899 | 0.0 | - |
| Hindi | 0 | 899 | 0.0 | - |
| Farsi | 0 | 894 | 0.0 | - |

## Safety response (what the patient was actually told)

| language | response rate | per case | first response at |
|---|---|---|---|
| English | 1.0 | 1.3333 | 0.2179 |
| Mandarin Chinese | 1.0 | 1 | 0.2466 |
| French | 1.0 | 1 | 0.1684 |
| Arabic | 1.0 | 1 | 0.2451 |
| Hindi | 1.0 | 1.3333 | 0.1753 |
| Farsi | 1.0 | 1 | 0.2093 |

## Record fidelity

| language | record score | fabricated/case |
|---|---|---|
| English | 0.9795 | 0.067 |
| Mandarin Chinese | 0.9737 | 0.0 |
| French | 0.9784 | 0.1 |
| Arabic | 0.9667 | 0.033 |
| Hindi | 0.9611 | 0.067 |
| Farsi | 0.9627 | 0.033 |

## Flow - NOT comparable across languages

A different judge pass reads a different language in each row. A lower score may mean a worse intake or may mean the judge scores that language's prose differently, and this design cannot separate the two. Do not rank languages on it.

| language | flow score |
|---|---|
| English | 0.74 |
| Mandarin Chinese | 0.6833 |
| French | 0.715 |
| Arabic | 0.715 |
| Hindi | 0.6267 |
| Farsi | 0.6217 |

## Provenance

| language | outputs | run_id | code | reps |
|---|---|---|---|---|
| English | outputs/ | e374d20c2329 | 1804c3b | 3 |
| Mandarin Chinese | outputs_mandarin_chinese/ | 51adc0a6a1d3 | 4d58c99 | 3 |
| French | outputs_french/ | ae81646336c8 | 3ecb4a9 | 3 |
| Arabic | outputs_arabic/ | 2704e1247b9d | 3ecb4a9 | 3 |
| Hindi | outputs_hindi/ | 26d43e9155b4 | 3ecb4a9 | 3 |
| Farsi | outputs_farsi/ | d05c13ba81a3 | 3ecb4a9 | 3 |
