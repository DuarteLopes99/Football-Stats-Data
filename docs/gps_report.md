# GPS Report — definitions, logic and assumptions

The GPS Report is the first page of `dashboards/gps_dashboard.py`. This document
explains every number on it. Every threshold, colour and column mapping named
here lives in [`src/football_stats/gps/config.py`](../src/football_stats/gps/config.py).

References: Ravé et al. (2020), *How to Use GPS Data to Monitor Training Load in
the "Real World" of Elite Soccer*, Front. Physiol. 11:944 · Reinhardt et al.
(2019), *Enhanced sprint performance analysis in soccer*, PLoS ONE · Gabbett
(2016), BJSM 50(5) · Williams et al. (2017), BJSM 51(3).

## 1. Pipeline

```
SATS_Football_GPS_Advanced.xlsx   (outside the repo — source of truth, read-only)
        │  python -m football_stats.gps.sync
        ▼
data/gps/gps_sessions.csv          (tidy sub-product, committed)
        │  gps.cleaning.prepare_sessions     typed, flagged, derived metrics
        │  gps.microcycle.add_md_labels      MD labels + microcycles
        ▼
gps.reference      Gref                     ┐
gps.weekly_change  % change                 ├─ derived metrics
gps.load_monitoring weekly load, ACWR       ┘
        │
gps.charts  (Plotly figures + HTML pieces)  → dashboards/gps_report.py (layout)
```

## 2. Column mapping

| Report metric | Source | Notes |
|---|---|---|
| Total Distance | `total_distance_m` | m |
| HSR & Sprint | `high_speed_distance_m` | STATSports high-speed distance is everything > 19.8 km/h, sprinting included. `HSR_INCLUDES_SPRINT = True`. |
| HSR (19.8–25.2) | `high_speed_distance_m − sprint_distance_m` | derived |
| Sprint distance | `sprint_distance_m` | > 25.2 km/h |
| Max Speed | `top_speed_kmh` | km/h; 0 on an unused-sub row becomes missing |
| Accelerations / Decelerations | `accelerations`, `decelerations` | counts beyond ±3 m/s² — confirmed by the workbook's sub-header (`Acc + 3m/s`). Counts only: a different threshold cannot be recomputed. |
| Sprints | `sprints_total` | count; for matches = 1st + 2nd half |
| High-Intensity Actions | acc + dec + sprints | |
| Distance per Minute | `total_distance_m ÷ duration_min` | recomputed: the export's own `distance_per_min` disagrees on 5 rows (up to 17 m/min) |
| Training Load | — | **not in the export** (no Player Load, DSL or HML). Calories are an energy estimate, not a load metric, so the slot shows Distance per Minute instead. |

Session type (`match_category`): `training` (session_kind = training),
`official_match` (game with competition_type Campeonato / Taça), `practice_match`
(any other game — friendlies, "Jogo Treino").

## 3. Data hygiene (code-side; the CSV is never edited)

| Row kind | Rule | This season |
|---|---|---|
| No GPS data | no core metric recorded → `has_gps = False`; all metrics missing, row kept | 3 trainings (3, 6, 20 Feb 2026) + 3 friendlies with duration only (23 Dec, 22 Jan, 5 Feb) |
| Unused substitute | game with 0 minutes by both clocks and only zeros → `unused_sub = True`; metrics **and duration** missing; still an MD anchor | 26 Oct, 14 Dec 2025, 8 Mar 2026 |
| Short appearance | match with < 20 official minutes → flagged; per-minute rates are extrapolation | 9 matches |
| Minutes played | match-sheet minutes where recorded, else GPS duration | |

## 4. MD labels and microcycles (`gps/microcycle.py`)

Per season, anchors = official-match dates (unused-sub matches included — the
team still played).

1. Anchor date → `MD`.
2. ≤ 2 days after the previous anchor → `MD+1` / `MD+2`.
3. Otherwise → `MD−n`, n = days to the next anchor.
4. Before the season's first anchor: `MD−n` within 6 days, else `PRE`.
5. After the season's last anchor: `MD+k`.

Usual week (Sunday match, Tue/Thu/Fri training) → MD+2, MD−3, MD−2. A Thursday
friendly before a Sunday match is an **MD−3 practice match**: friendlies never
anchor. A microcycle runs from an MD to the day before the next MD; longer than
10 days (winter break, free weekend) is flagged `microcycle_extended` and left out
of the microcycle profile.

## 5. Gref (`gps/reference.py`)

Mean of the best 5 official-match values **per metric**, for the selected season.
Excludes unused-sub matches; for rates (m/min) also appearances < 20 min (a
6-minute cameo at 104 m/min would otherwise set the intensity reference). Fewer
than 5 eligible → all used, warning shown. A season with no official matches yet
(e.g. 2026/27 pre-season) borrows the most recent earlier season's Gref, with a
warning. 2025/26: Total Distance 8 208 m, HSR & Sprint 1 512 m, Max Speed 32.7
km/h, HIA 138, m/min 115.4.

## 6. Weekly change % (`gps/weekly_change.py`)

`(current − basis) ÷ basis × 100` per metric. Basis, in order:

1. **Same MD label, previous microcycle, same session type** (a match → the
   previous match).
2. Otherwise the **previous session of the same type in the season** — marked ●.
3. Otherwise none (first session of its type in the season).

Never across types; sessions without GPS data are neither compared nor used as a
basis. Alternative mode **vs Gref** (sidebar → Report settings). Cell colour on
|change|: ≤ 10 % green, 10–20 % amber, 20–30 % orange, > 30 % red, interpolated
between band centres; the signed number is always printed.

## 7. KPI cards

Average session in the selected range (filters applied) for each metric; Max
Speed shows the peak. Gauge range 0 → max(2 × Gref, value); orange marker at
Gref. Averages rather than sums, so a range of any length reads on the scale of
one match.

## 8. Weekly load and ACWR (`gps/load_monitoring.py`)

- Weeks are **Sunday → Saturday** calendar weeks (`WEEK_FREQ = "W-SAT"`), not
  microcycles: microcycles here run 6–21 days, which would distort a ratio.
  Sunday starts line the week up with the usual match day.
- Weekly load = sum of the focus metric over **all** session types (the session
  filter fades bars, it doesn't remove load). Weeks containing sessions without
  GPS data are flagged as lower bounds (✕). A final week the data doesn't reach
  the Saturday of is `partial`: no week-on-week change, no ACWR.
- Week-on-week change flagged above +10 % (Ravé et al.'s progression guideline).
- ACWR (rolling, default) = this week ÷ mean of the previous 4 weeks (uncoupled).
  EWMA option: spans 7 / 28 days on daily loads, read at week end.
- No ratio for the first 4 weeks of a season or when chronic load is 0. Safe band
  0.8–1.5; outside → red points. **ACWR is a monitoring indicator, not an injury
  predictor.**

## 9. Validation

Recomputed by hand in plain pandas from the CSV (no package code) and matched
against the dashboard:

| Check | Hand | Dashboard |
|---|---|---|
| 24 Apr 2026 training (MD−2) vs 17 Apr MD−2: TD / HSR&S / Vmax / HIA / m/min | +136.8 / +99.1 / +13.4 / +64.6 / +34.0 % | +137 / +99 / +13 / +65 / +34 % |
| 12 Oct 2025 match vs 5 Oct match | −17.2 / −15.3 / −8.6 / −27.7 / +6.5 % | −17 / −15 / −9 / −28 / +7 % |
| Week of 3 May 2026 (TD) | 14 570 m, −25.4 %, ACWR 0.83 | 14 570 m, −25 %, 0.83 |
| KPI Total Distance (season) | 5 714 m, n = 128 | 5 714, n = 128 |

Edge cases are covered by `tests/test_report_metrics.py` and
`tests/test_load_monitoring.py`: weeks without a match, double-match weeks,
missing metrics, fewer than 5 matches, fewer than 4 weeks, partial weeks,
unused-sub match days, season boundaries.

## 10. Not possible with the current export

- **Training Load** (Player Load / DSL / HML) — not exported.
- **Time to 20 / 25 km/h and acceleration in the 5–20 / 20–25 km/h bands**
  (Reinhardt et al.) — need per-second velocity; the export has session totals.
- **Recomputing HSR / sprint / acc thresholds** (e.g. ±2 m/s²) — the device's
  bands are baked into the totals.
