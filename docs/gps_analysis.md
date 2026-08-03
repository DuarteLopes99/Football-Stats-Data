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

Two more columns are **derived, never stored** — computed fresh every time a
`PerformanceAnalyzer` loads the CSV (see §4):

- **`match_category`** — `"training"` / `"official_match"` / `"practice_match"`.
- **`season`** — a `"2025/26"`-style label.

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
Setting **Competition type** correctly matters (see §4) — it's what decides
whether a `game` session counts as an official match or a practice match in
every chart and table.

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

## 4. Match category: official vs. practice vs. training

Every `session_kind == "game"` row used to be treated as "a match," full stop —
but the data already distinguishes a real competitive fixture from a practice
game ("Jogo Treino"), via `competition_type`. `gps.analyzer.add_match_category_column()`
derives a `match_category` column so analysis never conflates the two:

| `session_kind` | `competition_type` | `match_category` |
|---|---|---|
| `"training"` | *(n/a)* | `"training"` |
| `"game"` | `"Campeonato"` or `"Taça"` | `"official_match"` |
| `"game"` | `"Treino"` or missing | `"practice_match"` |

`match_category` — not `session_kind` — is the axis every comparison chart and
table in `gps/analyzer.py` uses (`monthly_summary`, `compare_to_baseline`,
`session_type_analysis`, `weekly_load`, and every `plot_*` method take a
`category` argument or plot all three series). The one exception is
`starter_vs_substitute()`, which still keys off `session_kind == "game"`
directly — starting-lineup status is meaningful for both official and practice
games, so it isn't split further.

`monthly_quality_metric()` folds `match_category == "official_match"` into its
40% "match" component and **ignores practice matches entirely** — a friendly
against weaker/rotated opposition isn't a reliable read on competitive
readiness.

Because `add_match_category_column` is a standalone function (not only computed
inside `PerformanceAnalyzer.__init__`), the dashboard applies it once right
after loading, so its sidebar filter can offer "official match" as a real,
independent choice before any analyzer is even constructed — the same pattern
already used for date-range filtering.

## 5. Seasons: why raw month numbers were wrong, and what replaced them

A football season runs roughly July/August through May — it crosses a
calendar-year boundary. Two consequences that the original
`FootballPerformanceAnalyzer` port got wrong:

1. **Sort order.** Grouping by a bare `month` (1–12) sorts January before
   September, even though September came first in the season.
2. **Cross-season mixing.** Once more than one season of data exists, grouping
   by bare month would silently merge e.g. two different Septembers together.

Both are fixed in `gps/analyzer.py`:

- **`monthly_summary(category, year=None)`** groups on
  `pd.Grouper(key="date", freq="MS")` — a real calendar timestamp — instead of
  `df["month"]`. This alone makes every monthly chart/table chronologically
  correct regardless of how many seasons are loaded. (`pd.Grouper` pads gaps
  between the first and last session with empty months; `monthly_summary` drops
  those by actual row count, not `duration_min`'s count specifically, so a
  session missing just its duration doesn't vanish too.)
- **`gps/seasons.py`** adds a `season` label per row (`season_label(date)` —
  July 1 is the cutover: date.month >= 7 → `f"{year}/{year+1}"`, else
  `f"{year-1}/{year}"`). The dashboard's season selector filters on this column
  *before* constructing a `PerformanceAnalyzer` — no analyzer method takes a
  `season` parameter, the instance is just scoped to whatever's selected,
  exactly like the existing date-range/category filters.
- **`season_summary()`** is the one method that intentionally spans every
  season: it groups by `season` and returns one row per season (session counts
  by category, total distance, peak official-match top speed, average quality
  score) — see §7.

`weekly_load()`'s `week` numbers are season-relative (they restart at 1 each
season) — the dashboard's "Season" filter must be applied (or the data must
already be single-season) before calling it, or week numbers from different
seasons will be summed together.

## 6. Analysis (`gps/analyzer.py`)

`PerformanceAnalyzer` wraps a sessions DataFrame (typically the output of
`load_sessions()`, already filtered to whatever scope you want — see §5) and
mirrors the original `FootballPerformanceAnalyzer`'s methods, parameterized by
`category` (`"training"` / `"official_match"` / `"practice_match"`, see §4)
instead of duplicating every method once per session kind:

- `monthly_summary(category, year=None)` — count/mean/sum/max per calendar
  month (see §5), plus a `month_label` column (`"Sep 2025"`) for display.
- `compare_to_baseline(category, position, month=None)` — current per-90 rate
  vs. a **researched, position-specific baseline** (`gps.position_baselines`
  — see [`docs/position_baselines.md`](position_baselines.md) for full
  sourcing), with a `Difference_%` column. Everything except `top_speed_kmh`
  is normalized to per-90-minutes first (`skillcorner_metrics.add_per90_columns`)
  before comparing, since sessions vary in length and baselines are per-full-match.
- `average_minutes(category)` — mean `duration_min` for one category; context
  for how far an average session sits from the baseline's 90-minute basis.
- `session_type_analysis(category)` — stats grouped by `session_type`
  (trainings) or `competition_type` (games).
- `weekly_load(week=None)` — training / official-match / practice-match load
  per week, plus `total_*` columns summing all three (see the season-scoping
  caveat in §5).
- `starter_vs_substitute()` — all games (official + practice): performance
  split by `was_starter`.
- `monthly_quality_metric(weights=None)` — a composite 0–100 score per calendar
  month, blending normalized (relative to that metric's max-across-months)
  distance/sprint/speed/accel/decel values, weighted 60% training / 40%
  official-match. Default weights live in the method; pass your own dict to
  emphasize different metrics (e.g. more weight on `top_speed_kmh` if you're
  specifically tracking speed development).
- `season_summary()` — one row per season (see §5).

Chart methods (`plot_monthly_comparison`, `plot_best_worst`,
`plot_intensity_radar`, `plot_performance_trends`, `plot_quality_evolution`)
all **return a `matplotlib.figure.Figure`** rather than calling `plt.show()`,
so the dashboard renders them with `st.pyplot(fig)`. **`plot_weekly_load_heatmap`
is the one exception** — it returns a `plotly.graph_objects.Figure`
(`st.plotly_chart(fig)`), because a season can span 30+ weeks and cramming an
on-cell number into that many narrow matplotlib columns made the text
overlap and become unreadable regardless of font size; Plotly's hover
tooltip shows the exact raw value instead, so no on-cell text is needed.
Call the matplotlib ones directly in a notebook or script too — just do
something with the returned figure (`fig.savefig(...)`, or let Jupyter
display it). Every comparison chart plots all three categories
(`gps.analyzer.CATEGORY_COLORS` /
`CATEGORY_MARKERS` keep the color/marker consistent across charts).

## 7. Display formatting (`gps/formatting.py`)

Raw schema columns (and the `_mean`/`_sum`/`_max`/`_count`-suffixed aggregate
columns the methods above produce from them) are snake_case — fine for code,
unreadable as a table header. `gps/formatting.py` centralizes the fix:

- `humanize_columns(df)` — returns a copy with Title Case column names. Handles
  plain schema columns, aggregate-suffixed columns (`total_distance_m_mean` →
  "Avg Total Distance (m)"), and `weekly_load`'s category-prefixed columns
  (`official_match_total_distance_m` → "Official Match – Total Distance (m)").
  Anything unmapped falls back to `.replace('_', ' ').title()`.
- `numeric_column_config(df)` — a `st.column_config.NumberColumn` format spec
  per float column, so numbers render with fixed, short decimal places instead
  of long raw floats.

## 7a. Performance Insights: per-90, percentiles, ACWR, gauges

`gps/skillcorner_metrics.py` and `gps/gauges.py` power the dashboard's
**Performance Insights** tab — per-90-minute normalization, percentile-rank
comparison against the player's own history, a PSV-99-inspired "robust top
speed," and the Acute:Chronic Workload Ratio, each with a Plotly gauge.
**Full attribution writeup (what's genuinely SkillCorner methodology, what's
adapted, what's general sports science) lives in
[`docs/skillcorner_metrics.md`](skillcorner_metrics.md) — read it before
extending this module or calling something "SkillCorner" in a chart label.**

**Apply both right before rendering, never to data you're about to compute
with** — `humanize_columns` renames columns, so a renamed frame can't be fed
back into another analyzer method. The dashboard's `_show_table()` helper is
the canonical example: `st.dataframe(humanize_columns(df), column_config=numeric_column_config(humanize_columns(df)), ...)`.

## 8. Dashboard

```bash
streamlit run dashboards/gps_dashboard.py
```

Sidebar: a **Season** selector (a specific season, or "All seasons"), a
**Match category** multiselect (training/official match/practice match), and a
date range. Tabs:

- **Overview** — raw session table + totals.
- **Monthly** — the 3-category monthly comparison chart.
- **Weekly Load** — four narrower tables (Training / Official Matches /
  Practice Matches / Overall) instead of one wide clipped one, plus the load
  heatmap. Shows a warning if "All seasons" is selected with more than one
  season loaded, since week numbers would otherwise be summed across seasons.
- **Intensity** — the 3-category radar chart + starter-vs-substitute table.
- **Trends** — scatter + rolling average per metric, and a best/worst-sessions
  bar chart (pick the match category).
- **Baseline** — current per-90 rate vs. a researched, position-specific
  reference (pick both the position and the match category), plus average
  session-length metrics for training/official/practice so you can judge how
  far a session sits from the baseline's 90-minute basis.
- **Quality** — the monthly quality-score chart.
- **Season Summary** — `season_summary()`'s table plus a per-season distance bar
  chart and quality-score line chart. **Always covers every season**,
  independent of the sidebar's Season selector — this is the career-wide view
  (see §5).
- **Performance Insights** — ACWR, Quality Score, and Robust Top Speed gauges;
  a percentile-rank gauge for a metric you pick; a High-Speed % intensity
  gauge; a per-90-minute table; and a "Methodology" expander with the
  SkillCorner attribution breakdown (see §7a).
- **Add Session** — the append-a-session form.
