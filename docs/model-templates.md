# Mineral-system model templates

Templates live in `model_templates/` as versioned JSON with geological rationale and
references per evidence layer. The UI loads them in Models; every run stores the
resolved config + weights + seed + code version.

## `gold_orogenic_draft.json` (DRAFT — requires geologist review)
Orogenic / structurally-controlled gold, Chitipa pilot defaults:

| Layer | Weight | Rationale |
|---|---|---|
| `dist_structure` | 0.35 | fluid pathways along shears/second-order faults; exp decay 1500 m |
| `fault_density` | 0.20 | intersections/dilation zones; Gaussian kernel r=2000 m |
| `lithology` | 0.25 | competency/chemical traps; per-unit scores 0..1 assigned by user |
| `geochem_au` | 0.20 | Au (+As pathfinder) anomalies; median+MAD thresholds, log-IDW |

Method defaults: weighted baseline; fuzzy gamma 0.85; grid 100 m; target p90,
min area 40 000 m². Scores are relative rankings, never deposit probabilities.
Missing layers are excluded (renormalised), counted in the coverage layer.

## Adding a commodity
Copy the gold template, rewrite system (source/pathway/trap/preservation) with
references, set weights, mark DRAFT, and get a geologist sign-off before REVIEWED.
WofE/ML methods additionally require ≥10 known occurrences (enforced).
