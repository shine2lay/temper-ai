# Retrieval operating tables

## Lead L0 and Worker Turn-1
Macro recall@5; topic-cluster bootstrap 95% CI in results.json (2,000 draws, seed 21).
Noise is negative-query injection, not irrelevant-hit fraction. Server scores are NOT raw cosines.
G=canonical lexical gate; B=+0.15/token ranking bonus capped +0.30; raw score still gates.
Baseline is the frozen current search policy plus v2 active/access filter.
| Slice | Policy | Threshold | G | B | Recall | Memory | Resource | Noise | Retired / cross-role | Starved |
|---|---|---:|---|---|---:|---:|---:|---|---|---:|
| lead | baseline | 0.35 | 0 | 0 | 0.571 | 0.571 | 0.571 | 10/16 | 0 / 0 | 0 |
| lead | baseline | 0.45 | 0 | 0 | 0.571 | 0.571 | 0.571 | 10/16 | 0 / 0 | 0 |
| lead | baseline | 0.50 | 0 | 0 | 0.571 | 0.571 | 0.571 | 10/16 | 0 / 0 | 0 |
| lead | baseline | 0.55 | 0 | 0 | 0.571 | 0.571 | 0.571 | 10/16 | 0 / 0 | 0 |
| lead | baseline | 0.60 | 0 | 0 | 0.571 | 0.571 | 0.571 | 10/16 | 0 / 0 | 0 |
| lead | baseline | 0.65 | 0 | 0 | 0.571 | 0.571 | 0.571 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.35 | 0 | 0 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.35 | 0 | 1 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.35 | 1 | 0 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.35 | 1 | 1 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.45 | 0 | 0 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.45 | 0 | 1 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.45 | 1 | 0 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.45 | 1 | 1 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.50 | 0 | 0 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.50 | 0 | 1 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.50 | 1 | 0 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.50 | 1 | 1 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.55 | 0 | 0 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.55 | 0 | 1 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.55 | 1 | 0 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.55 | 1 | 1 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.60 | 0 | 0 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.60 | 0 | 1 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.60 | 1 | 0 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.60 | 1 | 1 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.65 | 0 | 0 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.65 | 0 | 1 | 1.000 | 1.000 | 1.000 | 10/16 | 0 / 0 | 0 |
| lead | candidate | 0.65 | 1 | 0 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| lead | candidate | 0.65 | 1 | 1 | 1.000 | 1.000 | 1.000 | 0/16 | 0 / 0 | 0 |
| worker | baseline | 0.35 | 0 | 0 | 0.333 | 0.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | baseline | 0.45 | 0 | 0 | 0.333 | 0.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | baseline | 0.50 | 0 | 0 | 0.333 | 0.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | baseline | 0.55 | 0 | 0 | 0.333 | 0.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | baseline | 0.60 | 0 | 0 | 0.333 | 0.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | baseline | 0.65 | 0 | 0 | 0.333 | 0.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.35 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.35 | 0 | 1 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.45 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.45 | 0 | 1 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.50 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.50 | 0 | 1 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.55 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.55 | 0 | 1 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.60 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.60 | 0 | 1 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.65 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
| worker | candidate | 0.65 | 0 | 1 | 1.000 | 1.000 | 1.000 | 0/0 | 0 / 0 | 0 |
