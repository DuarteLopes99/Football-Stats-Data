# Match context: official minutes and the fixture link

Module: [`src/football_stats/gps/match_link.py`](../src/football_stats/gps/match_link.py) ·
Tests: [`tests/test_match_link.py`](../tests/test_match_link.py) ·
Dashboard: no tab of its own — see [§0](#0-where-this-lives-in-the-dashboard)

Two previously-unused pieces of the data get put to work here:
`minutes_game_zerozero` (parsed into the GPS schema since the original Excel
import, then never read by any analysis) and the season half of the repo, which
until now shared no code with the GPS half at all.

---

## 0. Where this lives in the dashboard

There was a **Match Context** tab. It has been removed: it was a tab organised
around *where the data came from* rather than around a question anyone opens a
dashboard to ask. Nobody wonders "what is my match context" — they wonder how
they played, and the fixture is part of the answer rather than a topic beside
it. Each piece now sits with the question it belongs to:

| What | Where it went | Why there |
| --- | --- | --- |
| Opponent, venue, result | **Overview** — merged onto the session rows, **read from the label** | "6260 m on 17 Jan" and "6260 m away to Vila Viçosa, won 3-2" are the same number with very different readability. Source changed — see §4. |
| Fixture-link coverage | **Removed** | It reported on a join the dashboard no longer performs. A coverage table for a thing nothing uses is not context, it is a leftover. |
| Output by result / by venue | **Intensity** — beside starter-vs-substitute, **off the labels** | That tab already asks whether output differs by the context a match was played in. These are two more splits of the same question — and off the labels they cover 25 matches instead of 5. |
| Per-90 on official minutes | **Performance Insights** — folded into the existing per-90 block | There were two per-90 tables on different denominators. Now there is one, on the right denominator per row. |
| Recording overhang | **Performance Insights** — an expander under that block | It is the *justification* for the denominator, not a finding. It belongs where the choice is made, one click down. |

`match_link` keeps the per-90, official-minutes and overhang machinery, which
the dashboard still uses. Its *fixture-join* functions are no longer wired into
any tab — see §4 for what replaced them and why.

---

## 1. Why the match sheet is the right per-90 denominator

Every match session carries two minute counts, and they measure different
things:

| Column | What it is |
| --- | --- |
| `duration_min` | How long the GPS unit was recording |
| `minutes_game_zerozero` | Official match-sheet time from zerozero.pt |

**The gap is instrumentation, not error.** The unit goes on before you come onto
the pitch and gets forgotten after the whistle, so a positive **overhang** is
the normal state — the median across 19 matches is **+7 minutes**, which is a
consistent habit rather than a data problem. Both numbers are honest about what
they measure.

| Date | GPS runtime | Match sheet | Overhang | Reading |
| --- | --- | --- | --- | --- |
| 2025-10-12 | 56 | 45 | +11 | Warm-down still recording — normal |
| 2026-03-01 | 77 | 65 | +12 | Normal |
| 2025-09-21 | 72 | 73 | −1 | Normal |
| **2025-11-16** | **54** | **65** | **−11** | **Unit under-recorded** — the GPS *totals* are missing 11 minutes of this match |

Only the last row costs you anything. A negative overhang means the unit missed
real playing time, so that session's distance and sprint **totals** are
undercounts and no choice of denominator fixes it. Exactly one match in the
current data is in that state; five have a wide-but-ordinary recording window.

For a per-90 rate the match sheet wins: it is the time actually spent playing,
which is what "per 90 minutes" means. The size of the correction is not
cosmetic — 6260 m over 45 minutes is 12 520 m/90, over 56 minutes it is
10 060 m/90, a 24 % difference on the same session.

`add_match_per90` produces `{metric}_per90_official` columns using
`official_minutes`, which prefers the match sheet and falls back to the GPS
runtime when the sheet wasn't recorded (22 of the current file's sessions have
it; the rest don't). `minutes_source` records which was used, so a fallback
never passes as an official figure.

This is deliberately **separate from** `skillcorner_metrics.add_per90_columns`,
which divides by `duration_min` and applies to every session type. Training
sessions have no match sheet; the two normalizations answer different questions
and both stay available.

### Zero minutes is not zero output

An unused substitute (three such matches in the current data) has
`duration_min = 0` and `minutes_game_zerozero = 0`. `official_minutes` returns
NaN there rather than 0, so the per-90 rate is blank instead of a
divide-by-zero artifact.

### Reading the overhang

`minutes_overhang` lists every session with both counts and separates the two
readings that matter:

| `note` | Threshold | Meaning |
| --- | --- | --- |
| `unit under-recorded` | overhang < `UNDER_RECORDING_MIN` (−5) | Playing time was missed; **totals are undercounts**. The only lossy case. |
| `wide recording window` | overhang > `LARGE_OVERHANG_MIN` (+10) | Ordinary warm-up/warm-down, but a big enough per-90 correction to be worth knowing about. |

Neither threshold is validated against anything; the second is roughly where a
per-90 rate on a typical appearance shifts by a fifth. Matches the player didn't
appear in (0 vs 0 minutes) are excluded — there is no match to overhang.

### The cameo problem the right denominator creates

Switching the per-90 denominator from GPS runtime to match-sheet minutes is
correct, and it makes short appearances read as absurd. 2070 m in 9 official
minutes is **20 700 m per 90**; on the old denominator the same session showed
9315 m/90, because 20 minutes of runtime quietly damped it. The old number was
not better — it was wrong in a way that looked plausible, which is worse.

`MINUTES_FLOOR` (20 minutes) marks where a per-90 rate stops being a
measurement and becomes an extrapolation. A cameo is spent chasing a game at an
intensity nobody sustains for 90 minutes, so scaling it up describes a match
that cannot happen. Two different treatments, deliberately:

- **Aggregates** (`output_by_result`, `output_by_venue`) **exclude** those rows.
  With four matches in a bucket, one 20 700 m/90 cameo decides the ordering.
- **Per-session listings** **keep** them and set `short_appearance`. The session
  happened; deleting a row from a log is worse than labelling one that doesn't
  compare.

Both read the same constant, so the two views can never disagree about what
counts as too short.

---

## 2. The fixture link

`link_sessions_to_fixtures` attaches opponent, venue, scoreline and team result
to official match sessions.

### It reads the raw scrape, not the processed table

`data/seasons/<key>/processed/fixtures_played.csv` has no date column — only a
matchweek — so it cannot be joined to dated GPS sessions. The link therefore
reads `raw/<primary_team>_fixtures.csv`, which does carry `Date`, `Location`
and `Result`.

### The home/away trap, again

`Result` is always `"home score-away score"` regardless of which side the
tracked team is on; `Location` only says whether the tracked team is home. This
is exactly the trap behind the score-swap bug fixed in `season/fixtures.py`
(see [`season_prediction.md`](season_prediction.md#known-bugs-fixed)), so
`load_primary_team_fixtures` assigns goals via `Location` and never by reading
the score left to right. `test_result_is_read_as_home_away_not_tracked_team_first`
pins it with an away win whose naive reading would be a loss.

### One-day tolerance, always labelled

The GPS file logs one match a day after its fixture date (2025-10-26 vs. the
fixture's 2025-10-25 away trip to Espinho B — same opponent, same 1-3
scoreline). An exact-date join silently drops it. The join uses a ±1 day
tolerance and records how each row resolved in `fixture_match`:

| `fixture_match` | Meaning |
| --- | --- |
| `exact` | Session date equals fixture date |
| `+1d` / `-1d` | Matched within tolerance — a near miss, not a confirmed link |
| `unmatched` | Official match with no fixture within tolerance |
| `not an official match` | Practice match or training — never eligible |

Practice matches (`competition_type = "Treino"`) are excluded before the join,
so a friendly played a day either side of a real fixture cannot be absorbed
into it.

### Coverage is bounded by the scraper, not the join

Current state: **13 of 26** official GPS sessions link. The other 13 are matches
played after the last fixture scrape, which stops at 2026-01-17. Re-running the
scraper and reprocessing (step 3 of the season-prediction doc) fills them.

That group includes the two **Apuramento de Campeão** play-off rounds against
Calvão and Gafanha. Those are now declared in `config.py` — the opponents are in
`team_name_mapping`, and the competition is listed in the new
`extra_competitions` field alongside the Taça — so they will link as soon as the
scrape catches up. `extra_competitions` is deliberately **not** read by the
league table or the predictor: those are defined over `competition_name`'s
round-robin alone, and folding a cup tie or a play-off round into a league table
would corrupt both.

`link_coverage` reports the breakdown, so the gap stays visible rather than being
inferred from a short table.

---

## 3. What the join does *not* license

**Fixture rows describe the team. GPS rows describe one player.** A fixture says
Mansores lost 1-3 at home to AD Sanjoanense; the GPS row says how far this
player ran during the 19 minutes he was on the pitch for it. Joining them adds
*context* to a session. It does not turn a team result into a measure of
individual performance.

`output_by_result` and `output_by_venue` exist because the split is genuinely
interesting to look at, and they are built so it cannot be over-read:

- **`n` is always the first column after the group.** With the current data the
  result split is 4 wins against 1 loss. That is not a finding about anything.
- **Cameos are dropped** below `minutes_floor` (default 20 official minutes). A
  6-minute stint extrapolates to a per-90 rate no full match sustains, and with
  buckets this small one of those decides the ordering.
- The player is one of eleven, the opponent quality varies enormously (7-0 and
  1-3 in the same month), and minutes played range from 0 to 98. Any of those
  explains a difference in output more readily than the result does.

Treat these tables as "what happened", never as "why".


---

## 4. Why the fixture join was replaced by parsing the label

The join worked. It was still the wrong source, and the dashboard showed it:
the Overview columns it fed were **blank on almost every row**.

Every game session already carries its own context in `session_type`:

```
Jornada 11 - Vila Viçosa (FORA) 2-3
Jogo Treino Paivense (CASA) 1-3
Jogo Taça - Sangedo (Fora) 3-0
Jornada 1 Ap.Campeão - Calvão (CASA) 1-0
```

[`gps/match_label.py`](../src/football_stats/gps/match_label.py) reads it.

| | Fixture join | Label parse |
| --- | --- | --- |
| Official matches resolved | 13 of 26 | 26 of 26 |
| Practice matches resolved | 0 — they are in no fixture list | 12 of 12 |
| Goes stale | Yes — the scrape stops at 2026-01-17 | No |
| Needs a season config | Yes | No |
| Can mis-join | Yes (±1 day tolerance) | No |

The join's coverage was bounded by when the scraper last ran, which is why the
columns read empty: every match after 2026-01-17, and every friendly ever, had
nothing to join to.

### The score is home-first, and that is checked rather than assumed

`Jornada 9 - União Mata (FORA) 0-2` is a **win**. Under a "player's team first"
reading it would be a 2-0 defeat — the same string, the opposite result. The
convention is pinned against the 13 matches the fixture scrape independently
recorded, three of which discriminate between the two readings:

| Agreement | Result |
| --- | --- |
| Venue | 13 / 13 |
| Result | 13 / 13 |
| Scoreline | 12 / 13 |

The one scoreline disagreement is **2025-11-02**: the label says `5-1`, the
scrape says `5-0`. Both agree it was a win, so nothing downstream changes, but
one of the two records has a typo in it and it is worth a glance next time that
match comes up.

### What the label does not carry

`competition` and `matchweek` as the *league* records them. The label has the
round number ("Jornada 11") but not the competition's own naming. The fixture
functions in `match_link` remain for that, tested and documented — they are just
not what the dashboard asks for match context any more.

### Writing new labels

The add-session form no longer takes the label as freehand text for games. It
takes **opponent, venue, home goals, away goals and matchweek** as fields and
composes the label with `build_match_label()`, which round-trips through
`parse_match_label()` — there is a test asserting exactly that, because a writer
and a reader that drift apart are worse than no writer at all. Leave the goals
blank and the label records `?-?`: the row keeps its opponent and venue, and
only the result is missing.
