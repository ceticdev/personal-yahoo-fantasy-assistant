# Explosive-play calibration

The packaged default rates are an offline fit, not Yahoo data and not observed
player projections. The runtime exposes their provenance as:

`provided_slim_pbp_2020_2025_regular_seasons_v1`

## Input and filter contract

- Seasons: 2020 through 2025.
- Regular season only: weeks 1–17 for 2020 and 1–18 for 2021–2025.
- Explosive threshold: at least 40 yards.
- Completed passes require a passer, receiver, completion flag, and numeric
  passing/receiving yards.
- Rush attempts require a rusher and numeric rushing yards.
- Two-point attempts, quarterback kneels, and spikes are excluded.
- A long touchdown is counted only when the corresponding eligible 40+ play
  also carries its passing/rushing touchdown flag.

The raw slim files are deliberately omitted from source and release exports.
The tracked JSON artifact records each file's SHA-256, total rows, eligible
regular-season rows, game count, and maximum week so a holder of those inputs
can rerun `scripts/fit_explosive_play_rates.py --check ...`.

## Aggregate audit values

| Measure | Count |
|---|---:|
| Pass completions | 70,136 |
| Passing 40+ plays / TDs | 1,547 / 567 |
| Rush attempts | 84,447 |
| Rushing 40+ plays / TDs | 395 / 182 |
| Receptions | 70,136 |
| Receiving 40+ plays / TDs | 1,543 / 566 |

Derived rates are stored at full precision in
`src/yahoo_fantasy_mcp/projections/explosive_play_calibration.json`. Passing,
rushing, and receiving use separate long-touchdown shares; the combined share
remains present for backward-compatible caller-fitted models.

## Runtime safety

The artifact is package data and is validated during import. Missing fields,
invalid JSON, or rates outside `[0, 1]` fail closed. Estimation is still opt-in:
without `estimate_explosive_plays=true` and the relevant volume, 40+ fields are
reported unavailable rather than silently manufactured.
