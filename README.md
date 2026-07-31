# Football Stats Data

Two things live in this repo:

1. **Season stats & prediction** — scrape fixtures/results/player stats from
   zerozero.pt, compute league tables, and run a Monte Carlo simulation of the
   remaining fixtures to predict the final table.
2. **GPS performance analysis** — track training/match GPS data (distance, sprints,
   top speed, load, etc.) and analyze trends over a season and across seasons.

Both have a Streamlit dashboard. Everything else is a small, testable Python
package (`src/football_stats`) that the dashboards and any future notebooks/scripts
call into — the goal is that no analysis logic lives only inside a notebook cell.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Season stats & prediction

```bash
streamlit run dashboards/season_dashboard.py
```

Pick a season, see the current table, each team's attack/defense strength, and run
a Monte Carlo simulation (Poisson-distributed goals per match, home-advantage
factor) of the remaining fixtures. The prediction tab shows the expected final
table plus each team's probability of finishing 1st / in the top 3 / in the
bottom 3.

Seasons are declared in [`src/football_stats/config.py`](src/football_stats/config.py)
as a `SeasonConfig` (team slugs, their zerozero.pt fixtures URLs, and the exact
competition name to filter on) — the scraping/processing/prediction pipeline is
generic and driven entirely by this config, so adding a new season or division
means adding a `SeasonConfig`, not touching pipeline code.

Two seasons are seeded today:

- **`fermedo_2024_25`** — UD Fermedo's 2024/25 season, fully played (16 teams,
  240 matches). Good as a complete worked example and as the regression fixture in
  `tests/`.
- **`mansores_2025_26`** — Mansores' current, in-progress season. **Only Mansores'
  own 22 fixtures are seeded** (11 played + 11 remaining) — the other 11 teams'
  results against *each other* haven't been scraped yet, so their table rows only
  reflect their game against Mansores. Mansores' own row, and its remaining
  fixture list, are accurate. Run the scraper to backfill full league coverage:

  ```bash
  python -m football_stats.scraping.cli mansores_2025_26
  ```

  then re-run the fixture-processing step (`football_stats.season.fixtures.split_played_remaining`
  over all scraped team files, saved with `save_processed`) to refresh
  `data/seasons/mansores_2025_26/processed/`.

### Package layout

- `season/fixtures.py` — turn raw per-team scrape exports into deduped played/remaining fixture tables
- `season/league_table.py` — standings from match results
- `season/team_strength.py` — attack/defense strength relative to league average
- `season/predictor.py` — Monte Carlo season simulation
- `players/match_events.py` — goals/assists/cards event parsing, minutes-played estimation, per-player season stats
- `players/player_stats.py` — aggregate scraped per-competition player stats
- `scraping/zerozero_client.py` — Selenium/BeautifulSoup scraping helpers (fixtures, match reports, squads, player stats)

## GPS performance analysis

```bash
streamlit run dashboards/gps_dashboard.py
```

All GPS sessions (games + trainings) live in one tidy, appendable file:
`data/gps/gps_sessions.csv`. The dashboard has a tab to add a new session through
a form — it appends a row to that CSV and the charts update immediately. No more
editing the spreadsheet by hand.

This file was originally seeded from `SATS_Football_GPS_Advanced.xlsx`
(`gps.data_store.build_from_excel`), which cleans up two issues in that source
file: a merged-header artifact row in the `Jogos` sheet (where "1ª Half"/"2ª Half"
sprint sub-column labels had landed in the first data row instead of the header),
and a couple of free-text marker rows ("FIM DE EPOCA", a pickup-game placeholder)
that aren't real Date-indexed sessions.

Dashboard tabs: monthly comparison, weekly load, training-vs-match intensity
(radar chart), performance trends over time, baseline comparison (against
`gps.analyzer.DEFAULT_BASELINE`), and a monthly composite quality score. The
analysis logic (`gps/analyzer.py`) is ported from the original
`StatsSports/football_performance_analysis.py` script, adapted to the unified
`session_kind` schema instead of two separate training/match DataFrames.

## Tests

```bash
pytest tests/
```

Covers the league table computation, the Monte Carlo predictor, and two
regressions found while porting the original notebooks:

1. **Home/away score swap** — the source notebooks read `Result` (always
   "home score-away score") as if it were "tracked-team score-opponent score",
   silently flipping the outcome of every away fixture. Fixed in
   `season/fixtures.py`; see `tests/test_fixtures.py`.
2. **Double-averaging in the predictor** — the source notebook's final merge
   divided already-averaged simulation stats by `n_simulations` a second time,
   producing nonsensical predicted values. Fixed in `season/predictor.py`; see
   `tests/test_predictor.py`.

## Not yet migrated

`StatsSports/champions_analysys.ipynb`, `champions_utils.py`, and
`Jogos_Vitoias_Fermedo.xlsx` (a multi-season "champions" comparison across
years, built on a hand-formatted spreadsheet) weren't brought into this repo —
they're a reasonable future extension of the season-stats side once there's a
reproducible, non-hand-edited source for multi-season historical data.
