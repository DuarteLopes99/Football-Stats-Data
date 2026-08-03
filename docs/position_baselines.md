# Position-specific baselines

`src/football_stats/gps/position_baselines.py`, used by the GPS dashboard's
**Baseline** tab. This replaces the old flat baseline that lived in the source
spreadsheet's `Reference_Baseline` sheet (a single set of numbers — total
distance 9000m, high-speed 1200m, sprint 300m, top speed 31, accelerations 40,
decelerations 40 — with no stated source and no position split). Every number
below is sourced from published research instead, and this doc is deliberately
an attribution ledger, same as `docs/skillcorner_metrics.md`: what's directly
measured, what's derived, and what's a rough estimate where the literature
didn't have a clean answer.

## Why per-90, not per-session

A baseline is meaningless without a shared basis — 8000m in a 60-minute
session and 8000m in a 90-minute one represent very different work rates.
Every baseline here is expressed **per 90 minutes** (i.e. a full match or a
full training session), and `PerformanceAnalyzer.compare_to_baseline()`
normalizes the current period's actual sessions to per-90 first
(`skillcorner_metrics.add_per90_columns`) before comparing — except
`top_speed_kmh`, which is a peak, not a cumulative rate, and is compared as a
session max instead.

**Caveat worth knowing**: per-90 extrapolation over a *short* session
(e.g. a 20-minute substitute appearance) can produce an inflated rate for
bursty metrics like sprint distance — a real 20-minute burst of high-intensity
play, linearly scaled to 90 minutes, overstates what sustaining that pace for
a full match would actually look like (intensity isn't constant across 90
minutes; players pace themselves). The Baseline tab shows each category's
average session length specifically so this can be judged in context, not
hidden.

## Official match baselines, by position

| Position | Total Distance (m) | High-Speed Distance (m, >19.8 km/h) | Sprint Distance (m, >25.2 km/h) | Accelerations (>3 m/s²) | Decelerations (>3 m/s²) | Top Speed (km/h) |
|---|---|---|---|---|---|---|
| Goalkeeper | 5000 | 30 | 10 | 15 | 15 | 26 |
| Center Back | 10627 | 612 | 215 | 26.5 | 50.9 | 32 |
| Full Back / Wing Back | 11410 | 1054 | 402 | 30.4 | 54.1 | 32 |
| Central Midfielder | 12027 | 875 | 248 | 27.1 | 54.8 | 32 |
| Wide Midfielder / Winger | 11990 | 1184 | 446 | 34.9 | 64.5 | 32 |
| Forward | 11254 | 1025 | 404 | 29.9 | 55.2 | 32 |

**Sources, and exactly what came from where:**

- **Total distance, high-speed distance, sprint distance** (all outfield
  positions): Di Salvo, V. et al. (2007). *Performance Characteristics
  According to Playing Position in Elite Soccer.* International Journal of
  Sports Medicine, 28(3), 222–227. 300 elite outfield players (goalkeepers
  excluded), 20 Spanish La Liga + 10 Champions League matches. The paper
  reports 5 speed zones (0–11, 11.1–14, 14.1–19, 19.1–23, >23 km/h) by
  position (CD/ED/CM/EM/F, mapped here to center_back/full_back/
  central_midfielder/wide_midfielder/forward); `high_speed_distance_m` here
  = their 19.1–23 + >23 km/h zones combined (approximating our >19.8 km/h
  threshold), `sprint_distance_m` = their >23 km/h zone (approximating our
  >25.2 km/h threshold). The zone boundaries don't line up exactly with the
  modern SkillCorner-style thresholds this repo otherwise uses (see
  `docs/skillcorner_metrics.md`) — close enough to be directionally correct,
  not exact.
- **Accelerations, decelerations** (high-intensity, >3 m/s², all outfield
  positions): a GPS-based study reporting `ACCHIGH`/`DECHIGH` by position
  (CD/FB/MF/WMF/FW) — table values used directly as per-match figures.
- **Goalkeeper**: a rough estimate, not a cited study. Goalkeeper physical
  demands are consistently reported as understudied — multiple
  position-specific papers (including Di Salvo et al. above) explicitly
  exclude goalkeepers. General reporting puts goalkeeper total distance at
  4–6km per match with under 1% of it at high intensity; 5000m total /
  30m high-speed / 10m sprint is a midpoint estimate from that qualitative
  range, not a measured value. Treat the goalkeeper row as directional only.
- **Top speed**: **not split by position.** No reliable published
  per-position *average peak match speed* dataset was found — what's
  published is almost entirely individual "fastest players" records, which
  aren't a position baseline. One outfield reference (32 km/h) and one
  goalkeeper reference (26 km/h, an estimate) are used instead of fabricating
  a per-position split the literature doesn't support.

## Training baselines: estimated, not measured

No position-specific *training-vs-match intensity ratio* study was found —
this is the least rigorous part of this module, and it's flagged as such
deliberately rather than presented with false precision. `TRAINING_RATIO`
applies one flat, estimated multiplier per metric (same ratio at every
position) to the match baseline above:

| Metric | Training ratio | Rationale |
|---|---|---|
| Total distance | 0.70 | Training generally covers meaningfully less ground than a full match. |
| High-speed distance | 0.45 | Literature consistently shows a bigger relative drop in high-speed running than total distance in training vs. match play. |
| Sprint distance | 0.35 | The biggest relative drop of any metric — true match-intensity sprinting is the hardest thing to replicate in training. |
| Accelerations / decelerations | 0.75 | Explosive actions still occur frequently in small-sided games and drills, so the drop is smaller than for sprinting. |
| Top speed | 0.95 | Players can still hit close to their match top speed in training sprints/finishing drills — this is a peak, not a volume metric. |

If a solid position-specific training/match ratio study turns up later, this
table should be replaced with real per-position figures rather than one flat
ratio — that's the known gap here.

## Practice matches

`get_baseline("practice_match", position)` returns the **official match**
baseline for that position. A "Jogo Treino" friendly's physical demands are
closer to a real match than to a training session, even against weaker
opposition — using a separate, unresearched practice-match baseline would add
false precision, not remove it.
