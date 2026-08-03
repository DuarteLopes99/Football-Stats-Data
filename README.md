# Football Stats Data

Two things live in this repo:

1. **Season stats & prediction** — scrape fixtures/results/player stats from
   zerozero.pt, compute league tables, and run a Monte Carlo simulation of the
   remaining fixtures to predict the final table.
2. **GPS performance analysis** — track training/match GPS data (distance, sprints,
   top speed, load, etc.) and analyze trends over a season and across seasons.

Both have a Streamlit dashboard. Everything else is a small, tested Python
package (`src/football_stats`) that the dashboards call into — the goal is that
analysis logic lives in reusable functions, not only inside notebook cells.

📖 **Read the full docs before making changes:**
[`docs/season_prediction.md`](docs/season_prediction.md) ·
[`docs/gps_analysis.md`](docs/gps_analysis.md) ·
[`docs/skillcorner_metrics.md`](docs/skillcorner_metrics.md) ·
[`docs/position_baselines.md`](docs/position_baselines.md)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Quickstart

```bash
streamlit run dashboards/season_dashboard.py   # league table + Monte Carlo prediction
streamlit run dashboards/gps_dashboard.py      # GPS trends + add-session form
pytest tests/                                   # 30 tests, ~2.5s
```

## Repository layout

```
Football-Stats-Data/
├── docs/                    # detailed docs — start here for anything beyond a quick run
├── src/football_stats/      # the package: scraping, season, players, gps
├── dashboards/               # the two Streamlit apps
├── data/
│   ├── seasons/<key>/{raw,processed}/   # per-season fixture data
│   └── gps/gps_sessions.csv             # every training + match GPS session, one tidy file
└── tests/                    # pytest — includes regression tests for two bugs found while porting
```

## Important instructions

- **Don't hand-edit `data/gps/gps_sessions.csv`'s structure.** Add sessions
  through the dashboard's "Add Session" tab, or `gps.data_store.append_session()`
  — both validate the minimum required fields and keep the schema (documented in
  [`docs/gps_analysis.md`](docs/gps_analysis.md)) consistent. Editing values in
  place (e.g. correcting a typo) is fine.
- **Adding a season/division is a config change, not a code change** — see
  "Declaring a season" in [`docs/season_prediction.md`](docs/season_prediction.md).
  Don't hardcode a new team or competition name into `season/*.py`.
- **After scraping fresh fixtures**, you still need to re-run the processing step
  (`split_played_remaining` + `save_processed`) to refresh
  `data/seasons/<key>/processed/` — the scraper only writes `raw/`. See step 3 of
  the season-prediction doc.
- **`mansores_2025_26` is only partially seeded** (Mansores' own games only, not
  other teams' games against each other) — the season dashboard shows an in-app
  banner about this. Don't treat other teams' standings rows as accurate until
  you've run the scraper for full coverage.
- **Chart functions in `gps/analyzer.py` return a `matplotlib.figure.Figure`**,
  they don't call `plt.show()`. If you use them outside the dashboard, do
  something with the returned figure.
- **A GPS "game" session's `competition_type` decides whether it's an official
  match or a practice match** (`"Campeonato"`/`"Taça"` → official,
  `"Treino"`/missing → practice) — get it right when adding a session, since
  every chart/table in the GPS dashboard splits on this, not on `session_kind`
  alone. See "Match category" in [`docs/gps_analysis.md`](docs/gps_analysis.md#4-match-category-official-vs-practice-vs-training).
- **GPS analysis is season-scoped** (a season = Jul 1–Jun 30) — `weekly_load()`
  sums across seasons incorrectly if called on multi-season data without first
  filtering to one season, since week numbers restart each season. The
  dashboard's Season selector handles this; new code calling `weekly_load()`
  directly needs to filter first. See §5 of
  [`docs/gps_analysis.md`](docs/gps_analysis.md#5-seasons-why-raw-month-numbers-were-wrong-and-what-replaced-them).
- **`.venv/` is gitignored on purpose** — don't commit it. Regenerate with the
  Setup steps above on a fresh clone.
- **Don't badge a metric as "SkillCorner" without checking
  [`docs/skillcorner_metrics.md`](docs/skillcorner_metrics.md) first.** Only
  per-90 normalization and percentile-based comparison are directly borrowed
  from their actual open-source toolkit; `robust_top_speed` is explicitly an
  *adaptation* of PSV-99, not the metric itself; ACWR is general sports
  science (Gabbett 2016), not theirs. Keep that distinction when extending
  `gps/skillcorner_metrics.py`.
- **`gps/position_baselines.py` replaced the old spreadsheet baseline** (a
  single unsourced set of numbers) with position-specific figures from
  published research. Training baselines are *estimated* from the match
  baseline (one flat ratio per metric, not position-specific — no study was
  found for that), and top speed isn't split by position at all (no reliable
  per-position data found) — both gaps are deliberate, not oversights. See
  [`docs/position_baselines.md`](docs/position_baselines.md) before adding a
  number here; don't add position-specific figures without a citation.

## Known bugs fixed while porting

Both were caught by testing against real data, not by inspection — see
`tests/test_fixtures.py` and `tests/test_predictor.py`.

1. **Home/away score swap** — the source notebooks read `Result` (always
   "home score-away score") as if it were "tracked-team score-opponent score",
   silently flipping the outcome of every away fixture. Fixed in `season/fixtures.py`.
2. **Double-averaging in the predictor** — the source notebook's final merge
   divided already-averaged simulation stats by `n_simulations` a second time,
   producing nonsensical predicted values (e.g. `Draws_Predicted: 965`). Fixed in
   `season/predictor.py`.

Full explanation of both, with the exact numbers, in
[`docs/season_prediction.md`](docs/season_prediction.md#known-bugs-fixed).

## What's outside this repo

The parent `StatsSports/` folder (this repo lives inside it) still has:

- **`Logos/`**, **`champions_analysys.ipynb`**, **`champions_utils.py`**,
  **`Jogos_Vitoias_Fermedo.xlsx`** — a multi-season "champions" comparison across
  years, built on a hand-formatted spreadsheet. Not part of either focus area
  above and not ported here; a reasonable future extension once there's a
  reproducible (non-hand-edited) source for multi-season historical data.
- **`_archive/`** — the original exploratory notebooks and intermediate xlsx/csv
  exports this repo's `src/football_stats` package was built from (scraping
  notebooks, `football_performance_analysis.py`, the original
  `SATS_Football_GPS_Advanced.xlsx`, etc.). Kept for reference; nothing in this
  repo depends on it.
