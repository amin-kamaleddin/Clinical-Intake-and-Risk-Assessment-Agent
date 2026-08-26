# Manuscript tables

Generated from run `e374d20c2329` (code `1804c3b`), 3 repetition(s) per scenario.

Models — CIRA: `gpt-5.6-luna`, patient: `openai/gpt-5.4-mini`, naive: `gpt-5.6-luna`, judge: `google/gemini-3.1-flash-lite`.

Scenario file sha256 `ead93de5d7ddde5a`; prompt hashes `{'builder.py': '090dd23ab12860e0', 'section_prompts.py': '56e1a5504b92cfa6', 'static_prompt.py': '4920f53c18dfdcd3'}`.

### Primary results (estimate [95% CI])

| System | Safety | Structured | Record (contested) | Flow | Fabricated/case |
|---|---|---|---|---|---|
| cira | 0.987 [0.953, 1.000] | 0.999 [0.998, 1.000] | 0.961 [0.951, 0.970] | 0.758 [0.715, 0.799] | 0.047 [0.007, 0.100] |
| rule_based | 0.993 [0.973, 1.000] | 0.999 [0.995, 1.000] | 0.903 [0.890, 0.916] | 0.732 [0.695, 0.768] | 0.333 [0.207, 0.467] |
| naive_llm | 0.980 [0.940, 1.000] | 0.959 [0.903, 0.998] | 0.933 [0.888, 0.964] | 0.812 [0.759, 0.859] | 0.600 [0.427, 0.787] |

### Paired differences

| Comparison | Metric | Difference [95% CI] | Significant |
|---|---|---|---|
| cira - rule_based | record_score_contested | +0.058 [+0.045, +0.070] | yes |
| cira - rule_based | flow_score | +0.026 [-0.011, +0.066] | no |
| cira - rule_based | fabricated_fields | -0.287 [-0.427, -0.160] | yes |
| cira - naive_llm | record_score_contested | +0.028 [-0.002, +0.070] | no |
| cira - naive_llm | flow_score | -0.054 [-0.093, -0.007] | yes |
| cira - naive_llm | fabricated_fields | -0.553 [-0.747, -0.373] | yes |
| rule_based - naive_llm | record_score_contested | -0.030 [-0.061, +0.015] | no |
| rule_based - naive_llm | flow_score | -0.080 [-0.116, -0.042] | yes |
| rule_based - naive_llm | fabricated_fields | -0.267 [-0.473, -0.060] | yes |

### Safety detail

| System | Sensitivity | Specificity | Distractor spec. | Missed risk | False alarms |
|---|---|---|---|---|---|
| cira | 1.000 [0.916, 1.000] | 0.982 [0.935, 0.995] | 1.000 | none | 04-12, 04-12 |
| rule_based | 1.000 [0.916, 1.000] | 0.991 [0.949, 0.998] | 0.958 | none | 04-45 |
| naive_llm | 1.000 [0.916, 1.000] | 0.972 [0.921, 0.991] | 0.875 | none | 04-07, 04-07, 04-07 |

### Performance by patient difficulty

| System | Persona | Structured | Record | Flow |
|---|---|---|---|---|
| cira | clear | 0.998 | 0.982 | 0.873 |
| cira | moderate | 1.000 | 0.974 | 0.813 |
| cira | confused | 1.000 | 0.970 | 0.578 |
| rule_based | clear | 1.000 | 0.961 | 0.815 |
| rule_based | moderate | 1.000 | 0.925 | 0.728 |
| rule_based | confused | 0.996 | 0.924 | 0.648 |
| naive_llm | clear | 0.936 | 0.936 | 0.890 |
| naive_llm | moderate | 0.947 | 0.927 | 0.857 |
| naive_llm | confused | 0.997 | 0.983 | 0.680 |

### Interaction budget

| System | Median turns | Median words | Turn ratio |
|---|---|---|---|
| cira | 182 | 2732 | 1.32 |
| rule_based | 159 | 1772 | 1.15 |
| naive_llm | 138 | 2084 | 1.00 |

Paired differences are the basis for comparative claims; a difference whose interval includes zero is not evidence of superiority. Interaction budgets are not equalised across arms, so completeness and flow differences are confounded with effort.
