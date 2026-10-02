"""Match reference (Gref) — the denominator of every "% of match demand" figure.

**Gref = mean of the best ``GREF_TOP_N`` official-match values, per metric**
(Ravé et al. 2020). "Best" is per metric, so the five matches behind the
distance reference need not be the five behind the top-speed one.

What feeds it:

- official matches only — never friendlies, never training;
- matches with GPS data (an unused substitute's row of zeros is not a value);
- for per-minute **rates** only, appearances under ``SHORT_APPEARANCE_MIN``
  minutes are left out: a 6-minute cameo at 104 m/min would otherwise set the
  intensity reference for a 90-minute match. Totals don't need the guard — a
  cameo never makes a top five on volume.

Fewer than ``GREF_TOP_N`` eligible matches → all of them are used and the
result carries ``warning=True``. A season with no official matches yet (a new
pre-season) borrows the most recent earlier season's reference, and says so.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from football_stats.gps import config as cfg


@dataclass(frozen=True)
class MatchReference:
    values: dict[str, float]
    """metric -> Gref"""
    matches_used: dict[str, int]
    eligible: dict[str, int]
    season: str | None
    """Season the reference was computed from (differs from the requested one
    when it had to be borrowed)."""
    borrowed: bool = False

    def get(self, metric: str) -> float | None:
        value = self.values.get(metric)
        return None if value is None or pd.isna(value) else value

    @property
    def warning(self) -> bool:
        return self.borrowed or any(n < cfg.GREF_TOP_N for n in self.matches_used.values())

    def describe(self) -> str:
        if self.season is None:
            return "No official matches with GPS data — % of match demand cannot be computed."
        parts = []
        if self.borrowed:
            parts.append(f"no official matches yet in this season, so the {self.season} reference is used")
        short = {m: n for m, n in self.matches_used.items() if n < cfg.GREF_TOP_N}
        if short:
            n = min(short.values())
            parts.append(f"only {n} eligible official match(es) — Gref averages all of them instead of the best {cfg.GREF_TOP_N}")
        if not parts:
            return ""
        text = "; ".join(parts)
        return text[0].upper() + text[1:] + "."


def compute_gref(matches: pd.DataFrame, metrics: list[str], top_n: int = cfg.GREF_TOP_N) -> tuple[dict, dict, dict]:
    """Per-metric mean of the ``top_n`` largest eligible values.

    ``matches`` is any frame of prepared sessions; non-official, no-data and
    (for rates) short-appearance rows are excluded here.
    """
    official = matches[(matches["match_category"] == cfg.OFFICIAL_MATCH) & matches["has_gps"]]
    values, used, eligible = {}, {}, {}
    for metric in metrics:
        pool = official
        if cfg.METRICS[metric].rate:
            pool = pool[~pool["short_appearance"]]
        series = pd.to_numeric(pool[metric], errors="coerce").dropna()
        best = series.nlargest(top_n)
        values[metric] = float(best.mean()) if len(best) else float("nan")
        used[metric] = len(best)
        eligible[metric] = len(series)
    return values, used, eligible


def match_reference(sessions: pd.DataFrame, season: str, metrics: list[str] | None = None) -> MatchReference:
    """Gref for ``season``, borrowing the latest earlier season's if it has no matches.

    ``sessions`` must be the *unfiltered* prepared log: the reference belongs to
    the season, not to whatever date range or session type is on screen.
    """
    metrics = metrics or list(cfg.METRICS)
    has_matches = sessions[(sessions["match_category"] == cfg.OFFICIAL_MATCH) & sessions["has_gps"]]
    seasons_with_matches = sorted(has_matches["season"].unique())

    source, borrowed = season, False
    if season not in seasons_with_matches:
        earlier = [s for s in seasons_with_matches if s < season]
        if not earlier:
            return MatchReference({}, {}, {}, None)
        source, borrowed = earlier[-1], True

    values, used, eligible = compute_gref(sessions[sessions["season"] == source], metrics)
    return MatchReference(values, used, eligible, source, borrowed)


def pct_of_gref(sessions: pd.DataFrame, reference: MatchReference, metrics: list[str]) -> pd.DataFrame:
    """Add ``{metric}_pct_gref`` columns (100 = one Gref)."""
    df = sessions.copy()
    for metric in metrics:
        gref = reference.get(metric)
        df[f"{metric}_pct_gref"] = (pd.to_numeric(df[metric], errors="coerce") / gref * 100).round(1) if gref else float("nan")
    return df
