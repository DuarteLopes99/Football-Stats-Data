"""CLI: scrape fresh fixtures for a configured season.

Usage:
    python -m football_stats.scraping.cli mansores_2025_26
"""

from __future__ import annotations

import argparse
import sys

from football_stats.config import get_season, list_seasons
from football_stats.scraping.zerozero_client import scrape_season_fixtures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", help=f"One of: {', '.join(s.key for s in list_seasons())}")
    parser.add_argument("--no-headless", action="store_true", help="Show the browser window")
    args = parser.parse_args(argv)

    season = get_season(args.season)
    print(f"Scraping fixtures for {season.label} ({len(season.teams)} teams)...")
    results = scrape_season_fixtures(season, headless=not args.no_headless)
    for team_slug, df in results.items():
        print(f"  {team_slug}: {len(df)} fixtures -> {season.raw_dir / f'{team_slug}_fixtures.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
