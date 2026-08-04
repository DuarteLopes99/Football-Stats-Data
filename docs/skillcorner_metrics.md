# SkillCorner-inspired metrics & gauges

`src/football_stats/gps/skillcorner_metrics.py` and `gps/gauges.py`, surfaced in
the GPS dashboard's **Performance Insights** tab. Written after actually
researching SkillCorner's real open-source tooling and published methodology
— not generic "sports metrics" badged with their name. This doc is the
attribution ledger: what's genuinely theirs, what's an adaptation, and what's
general sports science that happens to pair well with this kind of data.

## What SkillCorner actually publishes

Two separate things carry the SkillCorner name, and only one is relevant here:

- **[`skillcorner`](https://pypi.org/project/skillcorner/)** (PyPI) — their API
  client SDK, for pulling data from SkillCorner's own broadcast-tracking
  service. Not usable here — we have no SkillCorner API access, only our own
  session-level GPS CSV.
- **[`skillcornerviz`](https://github.com/liamMichaelBailey/skillcornerviz)**
  (PyPI: `skillcornerviz`) — their actual open-source physical-data-analysis +
  visualization toolkit, built by their data analysis team. This is the one
  that's relevant, and the one this doc borrows from.

`skillcornerviz`'s `utils/skillcorner_physical_utils.py` centers on:
- **`add_standard_metrics()`** — computes per-90-minute rates for distance,
  acceleration/deceleration counts, and sprint frequency, plus percentile
  rankings (their docs call out **`psv99`**, peak sprint velocity at the 99th
  percentile).
- Their standard plots (`summary_table.py`, `table_grid.py`) color tables by
  **percentile or z-score against a peer group**, not raw values.

SkillCorner's published methodology (their site + Medium engineering posts)
defines the underlying thresholds:
- **High-Intensity (HI) distance** = distance covered above **5.5 m/s (19.8 km/h)**.
- **Sprint distance** = distance covered above **7.0 m/s (25.2 km/h)**.
- **PSV-99** = the 99th percentile of a player's speed *samples* within a
  match — deliberately percentile-based rather than a raw max, so one noisy
  GPS sample doesn't distort "true top speed."

## What's directly borrowed

| This repo | SkillCorner source | Adaptation |
|---|---|---|
| `add_per90_columns()` | `add_standard_metrics()`'s per-90 normalization | None — same idea, same formula (`value / minutes * 90`). |
| `percentile_rank()` | percentile-colored tables in `summary_table.py`/`table_grid.py` | SkillCorner ranks a player against **peers**; we have one player, so this ranks a session/week against **that player's own season-to-date history**. |
| — (validated, not recomputed) | HI distance >19.8 km/h, Sprint distance >25.2 km/h | This repo's `high_speed_distance_m` / `sprint_distance_m` fields (from the source GPS device, not recomputed from raw speed) already match these standard definitions — stated here for credibility, not implemented as a threshold function. |

## What's inspired by SkillCorner but explicitly *not* the same metric

**`robust_top_speed(df, window=10, percentile=95)`** is inspired by PSV-99 —
same motivation (a percentile is more robust to one bad reading than a raw
max) — but it is **not** PSV-99, for a granularity reason worth being precise
about:

- Real PSV-99 pools **thousands of raw speed samples** from within a single
  match (multiple readings per second). The 99th percentile of a huge sample
  is a stable, meaningful cutoff.
- We only have **one already-aggregated max speed per session** (whatever the
  GPS device/app computed). A "99th percentile" over a 10-session window has
  only 10 data points — it mathematically collapses to roughly the window's
  max, which defeats the entire point of using a percentile
  (see `tests/test_skillcorner_metrics.py::test_robust_top_speed_default_percentile_not_99_over_small_window`,
  which asserts this degenerate behavior directly).
- Using the **95th percentile of the last 10 sessions'** top speeds instead
  still meaningfully discounts a single outlier session while keeping the
  window's information — the closest honest adaptation to the *spirit* of
  PSV-99 at session-level granularity, not match-level.

If this repo ever ingests raw point-level GPS traces instead of pre-aggregated
per-session rows, a literal PSV-99 (99th percentile of speed samples within
one session) would become directly implementable and should replace this.

## General sports science lives elsewhere, on purpose

ACWR, Training Monotony, and Training Strain are **not** SkillCorner metrics —
they used to live in this module (mislabeling them as SkillCorner-adjacent by
association), and have since moved to `gps/load_monitoring.py`, with their own
attribution ledger in **`docs/load_monitoring.md`**. Nothing SkillCorner-sourced
was removed from this module by that move.

## Gauges/meters

Not a SkillCorner chart type — their standard plots
(`skillcornerviz/standard_plots/`) are bar, radar, scatter, swarm-violin, and
table-based. Gauges were a separate, explicit ask; `gps/gauges.py` builds them
with `plotly.graph_objects.Indicator` (`mode="gauge+number"`), since
matplotlib has no clean equivalent and Streamlit has first-class
`st.plotly_chart` support. The Performance Insights tab groups them into
**Load monitoring** (ACWR, Monotony, Strain — see `docs/load_monitoring.md`)
and **Form** (Quality Score, Robust Top Speed), plus a percentile-rank gauge
and High-Speed%/Sprint% intensity gauges for the latest session.

## Sources

- [SkillCorner Python SDK docs](https://skillcorner.readthedocs.io/en/latest/)
- [skillcornerviz on PyPI](https://pypi.org/project/skillcornerviz/)
- [skillcornerviz on GitHub](https://github.com/liamMichaelBailey/skillcornerviz)
- [SkillCorner Releases New Peak Velocity Metric](https://skillcorner.com/articles/skillcorner-releases-new-peak-velocity-metric)
- [SkillCorner Physical Data product page](https://skillcorner.com/products/football/physical-data)
