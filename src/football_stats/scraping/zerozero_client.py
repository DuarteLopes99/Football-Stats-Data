"""Selenium/BeautifulSoup scraping helpers for zerozero.pt.

Ported from the exploratory notebooks in ``StatsSports/`` (``dev.ipynb``,
``Dev_Mansores_Predict.ipynb``, ``dev_games_stats.ipynb``, ``dev_player_URL.ipynb``)
into reusable, season-agnostic functions. Every function takes an already-open
Selenium ``driver`` so callers control the browser lifecycle (see
``chrome_driver()``) instead of spinning up a new browser per request.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from football_stats.config import SeasonConfig

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
)

FIXTURE_COLUMNS = {
    0: "Result - abv",
    1: "Date",
    2: "Hour",
    3: "Location",
    4: "Team1",
    5: "Team2",
    6: "Result",
    7: "Competition",
    8: "Matchweek",
    9: "Played?",
}


@contextmanager
def chrome_driver(headless: bool = True):
    """Context-managed headless Chrome driver, quit automatically on exit."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument(f"user-agent={USER_AGENT}")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        driver.quit()


def _get_soup(driver, url: str, wait_seconds: float = 5.0) -> BeautifulSoup:
    driver.get(url)
    time.sleep(wait_seconds)
    return BeautifulSoup(driver.page_source, "html.parser")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def fetch_team_fixtures(
    driver,
    team_slug: str,
    team_url: str,
    team_name_mapping: dict[str, str],
    wait_seconds: float = 5.0,
) -> pd.DataFrame:
    """Scrape one team's zerozero.pt fixtures table (all competitions, unfiltered)."""
    soup = _get_soup(driver, team_url, wait_seconds)
    team_games_divs = soup.find_all("div", id="team_games")
    if len(team_games_divs) < 2:
        raise ValueError(f"Unexpected page layout for {team_url}: expected >=2 #team_games divs")
    table = team_games_divs[1]

    rows = [
        [td.get_text(strip=True) for td in tr.find_all("td")]
        for tr in table.find_all("tr")
    ]
    rows = [r for r in rows if r]

    df = pd.DataFrame(rows).rename(columns=FIXTURE_COLUMNS)
    df["Team1"] = team_slug
    df["Team2"] = df["Team2"].replace(team_name_mapping)
    df["Played?"] = df["Played?"].apply(lambda x: True if x == "" else (False if x == "h2h" else x))
    return df


def scrape_season_fixtures(
    season: SeasonConfig, headless: bool = True, wait_seconds: float = 5.0
) -> dict[str, pd.DataFrame]:
    """Scrape every team's fixtures for a season, filter to its competition, save raw CSVs."""
    results: dict[str, pd.DataFrame] = {}
    with chrome_driver(headless=headless) as driver:
        for team_slug, team_url in season.teams.items():
            df = fetch_team_fixtures(driver, team_slug, team_url, season.team_name_mapping, wait_seconds)
            df_filtered = df[df["Competition"] == season.competition_name].copy()
            df_filtered.to_csv(season.raw_dir / f"{team_slug}_fixtures.csv", index=False)
            results[team_slug] = df_filtered
    return results


# --------------------------------------------------------------------------- #
# Match reports (lineups + events)
# --------------------------------------------------------------------------- #

_EVENT_KEYS = ("Goals", "Assists", "Red Card", "Yellow Card", "Substitution OUT", "Substitution IN")


def _extract_player_events(events_div) -> dict[str, str]:
    events: dict[str, list[str]] = {key: [] for key in _EVENT_KEYS}
    if events_div is None:
        return {k: "" for k in _EVENT_KEYS}

    spans = events_div.find_all("span")
    minutes = events_div.find_all("div")
    for span, minute in zip(spans, minutes):
        title = span.get("title", "")
        cls = span.get("class", [])
        text = span.get_text(strip=True)
        minute_text = minute.get_text(strip=True)

        if "Assistência" in title:
            events["Assists"].append(minute_text)
        elif "Vermelhos" in title:
            events["Red Card"].append(minute_text)
        elif "Amarelos" in title:
            events["Yellow Card"].append(minute_text)
        elif "Golos" in title:
            events["Goals"].append(minute_text)
        elif "Entrou" in title or (text == "7" and "grey" in cls):
            events["Substitution IN"].append(minute_text)
        elif text == "8" and "grey" in cls:
            events["Substitution OUT"].append(minute_text)

    return {key: ", ".join(values) for key, values in events.items()}


def scrape_match_report(driver, match_url: str, wait_seconds: float = 5.0) -> pd.DataFrame:
    """Scrape one match's starters + substitutes with their in-game events.

    Raises ``ValueError`` if the match page has no lineup report available
    (common for older/lower-tier fixtures on zerozero.pt).
    """
    soup = _get_soup(driver, match_url, wait_seconds)
    game_reports = soup.find_all("div", class_="section_620 game_report")
    if len(game_reports) < 2:
        raise ValueError(f"No lineup report available for {match_url}")

    rows = []
    home_team = away_team = None

    for status, block in (("Starter", game_reports[0]), ("Suplente", game_reports[1])):
        for team_index, column in enumerate(block.find_all("div", class_="column_300"), start=1):
            team_name_div = column.find("div", class_="subtitle")
            if team_name_div is not None:
                team_name = team_name_div.get_text(strip=True)
                if team_index == 1:
                    home_team = team_name
                elif team_index == 2:
                    away_team = team_name
            else:
                team_name = home_team if team_index == 1 else away_team

            for player in column.find_all("div", class_="player"):
                number = player.find("div", class_="number")
                name = player.find("div", class_="name")
                rows.append(
                    {
                        "match_url": match_url,
                        "team": team_name,
                        "status": status,
                        "number": number.get_text(strip=True) if number else None,
                        "name": name.get_text(strip=True) if name else None,
                        **_extract_player_events(player.find("div", class_="events")),
                    }
                )

    return pd.DataFrame(rows)


def scrape_season_match_reports(
    match_urls: list[str], headless: bool = True, wait_seconds: float = 5.0
) -> pd.DataFrame:
    """Scrape lineups+events for a list of match URLs, skipping matches with no report."""
    frames = []
    with chrome_driver(headless=headless) as driver:
        for url in match_urls:
            try:
                frames.append(scrape_match_report(driver, url, wait_seconds))
            except ValueError:
                continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# --------------------------------------------------------------------------- #
# Squad + player stats
# --------------------------------------------------------------------------- #


def scrape_team_squad(driver, team_profile_url: str, wait_timeout: float = 10.0, settle_seconds: float = 1.0) -> pd.DataFrame:
    """Scrape a team's squad list: number, name, zerozero profile URL, photo URL."""
    driver.get(team_profile_url)
    WebDriverWait(driver, wait_timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.staff")))
    time.sleep(settle_seconds)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    players = []
    for staff in soup.select("div.staff"):
        number_tag = staff.find("div", class_="number")
        number = number_tag.get_text(strip=True) if number_tag else None

        photo_tag = staff.find("div", class_="photo")
        photo_url = None
        if photo_tag and photo_tag.has_attr("style"):
            match = re.search(r"url\(['\"]?(.*?)['\"]?\)", photo_tag["style"])
            if match:
                photo_url = match.group(1)

        name_tag = staff.find("div", class_="name")
        name = None
        profile_url = None
        if name_tag is not None:
            text_div = name_tag.select_one(".micrologo_and_text .text")
            if text_div is not None:
                link = text_div.find("a", href=True)
                if link is not None:
                    name = link.get_text(strip=True)
            if not name:
                name = name_tag.get_text(strip=True)

            nested_link = name_tag.select_one(".micrologo_and_text .text a[href]")
            if nested_link is not None:
                href = nested_link["href"]
                profile_url = f"https://www.zerozero.pt{href}" if href.startswith("/") else href

        if profile_url:
            players.append({"number": number, "name": name, "profile_url": profile_url, "photo_url": photo_url})

    return pd.DataFrame(players)


def build_player_team_stats_url(profile_url: str, team_slug: str, team_id: str) -> str | None:
    """Build the "stats while playing for this team" URL from a player's profile URL."""
    match = re.search(r"/jogador/([^/]+)/(\d+)", profile_url)
    if not match:
        return None
    slug, player_id = match.groups()
    return f"https://www.zerozero.pt/estatisticas/{slug}-{team_slug}/p{player_id}-t{team_id}?filter_match=in_with"


def scrape_player_team_stats(
    driver, player_name: str, stats_url: str, wait_timeout: float = 10.0, settle_seconds: float = 1.0
) -> pd.DataFrame:
    """Scrape a player's per-competition stats table (one row per competition + a Total row)."""
    driver.get(stats_url)
    WebDriverWait(driver, wait_timeout).until(EC.presence_of_element_located((By.ID, "team_games")))
    time.sleep(settle_seconds)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    table = soup.select_one("#team_games table.zztable")
    if table is None:
        return pd.DataFrame()

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr", {"role": "row"}):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cols:
            continue
        row = {"player": player_name, "url": stats_url}
        for i, header in enumerate(headers):
            colname = header if header else f"col_{i}"
            row[colname] = cols[i] if i < len(cols) else None
        rows.append(row)

    df = pd.DataFrame(rows)
    if "col_0" in df.columns:
        df["col_0"] = df["col_0"].replace("", "Total")
        df = df.rename(columns={"col_0": "Competition"})
    return df
