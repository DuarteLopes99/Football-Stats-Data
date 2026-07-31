# GPS performance analysis

Training and match GPS data (distance, sprints, top speed, load, etc.) in one
tidy, appendable CSV, analyzed with a ported-and-cleaned-up version of the
original `football_performance_analysis.py` script.

## 1. Data model

Everything lives in **`data/gps/gps_sessions.csv`** — one row per session
(training *or* game), distinguished by a `session_kind` column. The original
source spreadsheet (`SATS_Football_GPS_Advanced.xlsx`) kept games and trainings
in two separate sheets with different columns; unifying them into one long table
with one schema is what makes "just append a row" possible.

| Column | Meaning | Applies to |
|---|---|---|
| `date` | Session date | both |
| `session_kind` | `"game"` or `"training"` | both |
| `week`, `month` | Calendar week/month number | both |
| `session_type` | Free-text label, e.g. `"Treino Terça-Feira"` or `"Jornada 2 Ap.Campeão - Gafanha (FORA) 1-1"` | both |
| `competition_type` | `"Campeonato"` / `"Taça"` / `"Treino"` | games only |
| `was_starter` | Started the match (bool) | games only |
| `duration_min` | Session duration | both |
| `minutes_game_zerozero` | Minutes played, cross-referenced from zerozero.pt | games only |
| `total_distance_m`, `sprint_distance_m`, `high_speed_distance_m` | GPS distance metrics | both |
| `distance_per_min` | Total distance ÷ duration | both |
| `top_speed_kmh` | Peak speed reached | both |
| `sprints_1st_half`, `sprints_2nd_half`, `sprints_total` | Sprint counts (half-split only recorded for games) | both |
| `accelerations`, `decelerations` | Explosive-effort counts | both |
| `calories` | Estimated calories burned | both |
| `notes` | Free text | both |

## 2. Where the schema came from — and what it fixed

`gps.data_store.build_from_excel()` is the one-time conversion from the original
`SATS_Football_GPS_Advanced.xlsx` (now in `StatsSports/_archive/`). It cleans up
two real issues in that source file, both invisible unless you inspect the raw
cells directly:

1. **A merged-header artifact.** The `Jogos` (games) sheet's `Nº Sprints` and
   `Unnamed: 14` columns are actually a merged "Sprints" header that Excel split
   into two sub-columns, `1ª Half` / `2ª Half` — but those sub-labels ended up in
   the *first data row* instead of a header row, and every real session's data
   started one row below that. `build_from_excel` renames the columns to
   `sprints_1st_half` / `sprints_2nd_half` and drops the artifact row (any row
   where `Date` doesn't actually parse as a date).
2. **Free-text marker rows.** Two rows in the `Jogos` sheet aren't real sessions
   at all — `"FIM DE EPOCA"` (end of season) and `"Peladinhas Terça"` — sitting in
   the `Date` column where a real date should be. Coercing `Date` with
   `errors="coerce"` and dropping non-dates filters these out.

If you ever need to re-import from a similarly-shaped spreadsheet, run:

```python
from football_stats.gps.data_store import build_from_excel, save_sessions

sessions = build_from_excel("path/to/export.xlsx")
save_sessions(sessions)   # overwrites data/gps/gps_sessions.csv
```

## 3. Adding new sessions

**Preferred**: use the dashboard's "Add Session" tab — it's a form, not a spreadsheet
edit, so there's no risk of breaking a column's dtype or misaligning a row.

**Programmatic**:

```python
from football_stats.gps.data_store import append_session

append_session({
    "date": "2026-08-01",
    "session_kind": "training",
    "session_type": "Treino Segunda-Feira",
    "duration_min": 90,
    "total_distance_m": 8200,
    "sprint_distance_m": 310,
    "high_speed_distance_m": 950,
    "top_speed_kmh": 29.4,
    "sprints_total": 12,
    "accelerations": 35,
    "decelerations": 48,
    "calories": 780,
})
```

Only `date` and `session_kind` are required; everything else defaults to missing.
The CSV is small (a season is ~150 rows) — appending and re-writing the whole
file on every call is intentional, not a performance concern here.

## 4. Analysis (`gps/analyzer.py`)

`PerformanceAnalyzer` wraps a sessions DataFrame (typically the output of
`load_sessions()`) and mirrors the original `FootballPerformanceAnalyzer`'s
methods, but parameterized by `session_kind` instead of duplicating every method
once for "treinos" and once for "jogos":

- `monthly_summary(session_kind, month=None, year=None)` — count/mean/sum/max
  per month for every core metric.
- `compare_to_baseline(session_kind, month=None)` — current average vs.
  `DEFAULT_BASELINE` (typical distance/sprint/speed/accel/decel values), with a
  `Difference_%` column.
- `session_type_analysis(session_kind)` — stats grouped by `session_type`
  (trainings) or `competition_type` (games).
- `weekly_load(week=None, month=None)` — training vs. match load per week, plus
  a `total_*` column summing both.
- `starter_vs_substitute()` — games only: performance split by `was_starter`.
- `monthly_quality_metric(weights=None)` — a composite 0–100 score per month,
  blending normalized (relative to that metric's max-across-months)
  distance/sprint/speed/accel/decel values, weighted 60% training / 40% match.
  Default weights live in the method; pass your own dict to emphasize different
  metrics (e.g. more weight on `top_speed_kmh` if you're specifically tracking
  speed development).

Chart methods (`plot_monthly_comparison`, `plot_best_worst`,
`plot_weekly_load_heatmap`, `plot_intensity_radar`, `plot_performance_trends`,
`plot_quality_evolution`) all **return a `matplotlib.figure.Figure`** rather than
calling `plt.show()`, so the dashboard renders them with `st.pyplot(fig)`. Call
them directly in a notebook or script too — just do something with the returned
figure (`fig.savefig(...)`, or let Jupyter display it).

## 5. Dashboard

```bash
streamlit run dashboards/gps_dashboard.py
```

Sidebar filters: session kind (training/game/both) and a date range. Tabs:
Overview (raw session table + totals), Monthly, Weekly Load, Intensity (radar
chart + starter-vs-substitute table), Trends (scatter + rolling average, and a
best/worst-sessions bar chart), Baseline, Quality, and Add Session.

## 6. Extending to multi-year analysis

Because everything is one CSV keyed by `date`, comparing across seasons or years
is just a filter — no separate "per-season" files to reconcile. The `month`
column repeats across years (e.g. `9` for every September), so month-based
aggregations like `monthly_summary()` mix years together by default; filter by
`year=` when you want a single season's monthly breakdown, or add a `year`
column upstream if you want year-aware grouping without manual filtering.
