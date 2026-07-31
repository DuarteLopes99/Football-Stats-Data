# Season stats & prediction

Pipeline: **scrape → process into tidy fixtures → league table → team strength →
Monte Carlo prediction → dashboard**. Every stage is a plain function in
`src/football_stats`, driven by a `SeasonConfig` — nothing is hardcoded to one
team or season.

## 1. Declaring a season

Everything about a season lives in one `SeasonConfig` in
[`src/football_stats/config.py`](../src/football_stats/config.py):

```python
SeasonConfig(
    key="mansores_2025_26",                 # directory-safe id -> data/seasons/<key>/
    label="Mansores — AF Aveiro II Divisão Zona Norte 25/26",
    competition_name="AF Aveiro II Divisão Zona Norte 25/26",  # exact zerozero.pt competition string
    primary_team="mansores",                # the team this season's collection is centered on
    teams={...},                            # team slug -> zerozero.pt "jogos" (fixtures) page URL
    team_name_mapping={...},                # zerozero.pt display name -> team slug
)
```

**To add a new season or division**: find each team's zerozero.pt team page, grab
the `/equipa/<slug>/<id>/jogos?grp=1[&epoca_id=...]` URL, and add a new
`SeasonConfig` to the `SEASONS` registry at the bottom of `config.py`. Nothing
else needs to change — the scraper, processor, and both dashboards pick it up
automatically via `list_seasons()` / `get_season()`.

`competition_name` matters: a team's zerozero.pt fixtures page can list several
competitions (league, cup, friendlies). Every stage filters rows down to exactly
this string, so get it right (copy it from a scraped row rather than guessing).

## 2. Scraping fixtures

```bash
python -m football_stats.scraping.cli mansores_2025_26
```

This drives `football_stats.scraping.zerozero_client.scrape_season_fixtures()`,
which opens one headless Chrome session (`chrome_driver()`) and, for every team in
`season.teams`, calls `fetch_team_fixtures()` — it grabs zerozero.pt's second
`#team_games` table (the first is a season-totals summary row, not fixtures),
tags `Played?` as `True`/`False`/keeps `"h2h"` sentinel matches as unplayed, and
writes `data/seasons/<key>/raw/<team_slug>_fixtures.csv`.

The same module also has `scrape_match_report()` (starters/subs + goals/assists/
cards for one match — used by the player-stats side, see below) and
`scrape_team_squad()` / `scrape_player_team_stats()` (a team's roster and each
player's per-competition stats).

zerozero.pt rate-limits aggressively (a burst of requests returns HTTP 429 with a
"Serviço Temporariamente Suspenso" page) — if a scrape comes back empty, wait a
few minutes before retrying rather than looping immediately.

## 3. Processing raw fixtures into a season table

```python
from football_stats.config import get_season
from football_stats.season.fixtures import load_raw_team_fixtures, split_played_remaining, save_processed

season = get_season("mansores_2025_26")
raw = load_raw_team_fixtures(season)                       # {team_slug: DataFrame}
played, remaining = split_played_remaining(raw)
save_processed(season, played, remaining)                  # -> data/seasons/<key>/processed/*.csv
```

`split_played_remaining` does three things `dev_model.ipynb` used to do by hand,
per team, in notebook cells:

1. Split each team's raw export into played vs. not-yet-played rows.
2. Turn `Location` (`(C)`/`(F)`, casa/fora) into explicit `Home Team`/`Away Team`
   columns, and `Result` into `Home Goals`/`Away Goals` — **`Result` is always
   "home score-away score"**, regardless of which side is the tracked team
   (see [Known bugs](#known-bugs-fixed) below).
3. Dedupe: every match appears once in each participating team's raw export, so
   combining all teams double-counts every match — `dedupe_fixtures()` keys on
   `(Matchweek, sorted(home, away))` and keeps one row per match.

If you only scrape one team (as with the seeded `mansores_2025_26` data — see
[Data completeness](#data-completeness)), `raw` just has one entry and the output
is that team's own fixtures, which is still correct for that team's own record.

## 4. League table & team strength

```python
from football_stats.season.league_table import compute_league_table
from football_stats.season.team_strength import compute_team_strength

table = compute_league_table(played)      # Points, W/D/L, GF/GA, GD, Played — sorted
strength = compute_team_strength(played)  # .attack, .defense dicts + .table for display
```

`compute_team_strength` centers both attack and defense around 1.0 for an
average team:

- **Attack strength** = team's average goals scored ÷ league average goals per game.
- **Defense strength** = league average ÷ (team's average goals conceded + 0.1).
  The `+0.1` smoothing means a defense that's conceded nothing yet doesn't
  produce a division-by-zero or an unbounded strength value.

## 5. Monte Carlo prediction

```python
from football_stats.season.predictor import simulate_season

prediction = simulate_season(played, remaining, n_simulations=1000, seed=42)
prediction.actual_table              # standings from played matches only
prediction.predicted_table           # actual + remaining, averaged over all simulations
prediction.position_probabilities    # per team: Title %, Top 3 %, Bottom 3 %
```

Each simulated remaining fixture is scored with `simulate_match()`: goals are
drawn from a Poisson distribution parameterized by both teams' attack/defense
strength and the league's average goals per game, with a fixed 1.15× home-advantage
multiplier on the home team's expected goals. For every simulation, the *entire*
season (played + that simulation's remaining results) is run back through
`compute_league_table`, and each team's final rank and full stat line are
recorded. Averaging those N full stat lines — once — gives `predicted_table`;
counting how often each team lands in each rank gives `position_probabilities`.

If `remaining` is empty (season complete), `simulate_season` short-circuits:
`predicted_table` is just `actual_table`, and `position_probabilities` reflects
the real final positions with 100%/0% probabilities.

### Known bugs fixed

Both were found by testing this port against real season data, not by
inspection — see `tests/test_fixtures.py` and `tests/test_predictor.py` for the
regression tests.

1. **Home/away score swap.** The source notebooks (`dev_model.ipynb`,
   `Dev_Mansores_Predict.ipynb`) read the `Result` column as if it were
   "tracked-team score-opponent score" when the tracked team played away, when
   it's actually always "home score-away score" regardless of which side Team1
   is on. This silently turned some away wins into recorded home wins for the
   *opponent*. Confirmed against `mansores_matches.csv`'s own W/D/L markers:
   before the fix, Mansores' 11-game record computed as 4W-0D-7L (12 pts);
   after, it's the correct 10W-0D-1L (30 pts).
2. **Double-averaging in the predictor.** The source notebook's final merge (cell
   14 of `dev_model.ipynb`) divided `Points_Predicted`/`GD_Predicted`/etc. by
   `N_SIMULATIONS` a second time, after `groupby.mean()` had already averaged
   them — producing values like `Draws_Predicted: 965.36` for a team that plays
   a handful of remaining games (visible in the legacy
   `StatsSports/_archive/FINAL_PREDICTIONS_EXCEL_5000.xlsx`). `simulate_season`
   sums each team's per-simulation stats once and divides by `n_simulations`
   once.

## 6. Player & match-event stats

Separate from the league-table side: `players/match_events.py` and
`players/player_stats.py` turn scraped match lineups into per-player season
stats (goals, assists, cards, minutes played, starts vs. substitute appearances).

```python
from football_stats.scraping.zerozero_client import scrape_season_match_reports
from football_stats.players.match_events import build_events_table, build_player_season_stats

match_players = scrape_season_match_reports(list_of_match_urls)   # one row per player per match
events = build_events_table(match_players)                        # long-format goal/assist/card events
player_stats = build_player_season_stats(match_players, team_name="mansores")
```

Minutes played is estimated, not scraped directly: starters are assumed to play
until subbed off (else the full 90), substitutes from their sub-in minute to 90
(else 0 if they never entered) — see `estimate_minutes_played()`.

## 7. Dashboard

```bash
streamlit run dashboards/season_dashboard.py
```

Season selector in the sidebar, a simulation-count slider (100–5000) and a
random seed (for reproducible predictions). Four tabs: current table, team
strength, season prediction (table + finish probabilities + a bar chart of
title-win probability), and upcoming fixtures. An in-app banner warns when the
loaded season has fewer matches than a full double round-robin implies — see
below.

## Data completeness

- **`fermedo_2024_25`** is fully seeded: all 16 teams, all 240 matches (a
  complete double round-robin), zero remaining fixtures. Good as a worked
  example and as the basis for the `tests/test_data_seed.py` regression check.
- **`mansores_2025_26`** is *partially* seeded: only Mansores' own 22 fixtures
  (11 played, 11 remaining) are loaded — the other 11 teams' games against
  *each other* haven't been scraped. Mansores' own table row, remaining-fixture
  list, and win/loss record are fully accurate; other teams' rows only reflect
  their single game against Mansores, and the Monte Carlo attack/defense
  strengths for those teams are estimated off a 1-match sample (noisy). Run
  `python -m football_stats.scraping.cli mansores_2025_26` and re-run step 3
  above to backfill full league coverage.
