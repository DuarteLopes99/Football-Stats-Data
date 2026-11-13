"""Paths, plus the fixture-context configuration used by ``gps/match_link.py``.

The league side (zerozero.pt scraping, league tables, the Monte Carlo season
model) moved to its own repository, **football-data-analysis**. What stays here
is only what the GPS dashboard's fixture link needs: where the primary team's
raw fixture export lives (``data/seasons/<key>/raw/<primary_team>_fixtures.csv``),
which competitions count as official, and how zerozero display names map to
slugs. That raw file is produced by football-data-analysis's pipeline and copied
in; nothing in this repo scrapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"


@dataclass(frozen=True)
class SeasonConfig:
    key: str
    """Directory-safe identifier, e.g. ``mansores_2025_26``."""

    label: str
    """Human-readable name shown in dashboards."""

    competition_name: str
    """Exact zerozero.pt league competition string. Cup ties and play-off
    rounds the team also played are declared in ``extra_competitions``."""

    primary_team: str
    """Slug of the team whose raw fixture export the GPS fixture link reads."""

    teams: dict[str, str] = field(default_factory=dict)
    """Team slug -> zerozero.pt "jogos" (fixtures) page URL."""

    team_name_mapping: dict[str, str] = field(default_factory=dict)
    """zerozero.pt display name (as it appears in scraped tables) -> team slug."""

    extra_competitions: tuple[str, ...] = ()
    """Other competitions the primary team played this season (cup runs,
    play-off rounds), so GPS match sessions from them can still be recognised
    as official matches and linked to a fixture (see ``gps/match_link.py``)
    rather than being silently unmatchable."""

    @property
    def dir(self) -> Path:
        return DATA_ROOT / "seasons" / self.key

    @property
    def raw_dir(self) -> Path:
        path = self.dir / "raw"
        path.mkdir(parents=True, exist_ok=True)
        return path


MANSORES_2025_26 = SeasonConfig(
    key="mansores_2025_26",
    label="Mansores — AF Aveiro II Divisão Zona Norte 25/26",
    competition_name="AF Aveiro II Divisão Zona Norte 25/26",
    primary_team="mansores",
    teams={
        "mansores": "https://www.zerozero.pt/equipa/mansores/10972/jogos?grp=1",
        "ad_sanjoanense": "https://www.zerozero.pt/equipa/ad-sanjoanense/263339/jogos?grp=1",
        "milheiroense": "https://www.zerozero.pt/equipa/milheiroense/3607/jogos?grp=1&epoca_id=155",
        "são_martinho": "https://www.zerozero.pt/equipa/ccr-sao-martinho/16114/jogos?grp=1&epoca_id=155",
        "vila_viçosa": "https://www.zerozero.pt/equipa/ccr-vila-vicosa/216307/jogos?grp=1",
        "uniao_da_mata": "https://www.zerozero.pt/equipa/uniao-da-mata/106047/jogos?grp=1&epoca_id=155",
        "espinho_b": "https://www.zerozero.pt/equipa/sc-espinho/359178/jogos?grp=1&epoca_id=155",
        "caldas_sjorge": "https://www.zerozero.pt/equipa/caldas-s-jorge/16113/jogos?grp=1&epoca_id=155",
        "crc_vale": "https://www.zerozero.pt/equipa/crc-vale/51040/jogos?grp=1&epoca_id=155",
        "cd_tarei": "https://www.zerozero.pt/equipa/cd-tarei/363742/jogos?grp=1&epoca_id=155",
        "ef_rui_dolores": "https://www.zerozero.pt/equipa/ef-rui-dolores/364010/jogos?grp=1",
        "mosteiro_fc": "https://www.zerozero.pt/equipa/mosteiro-fc/363741/jogos?grp=1&epoca_id=155",
    },
    team_name_mapping={
        "Mansores": "mansores",
        "AD SanjoanenseB": "ad_sanjoanense",
        "CCR São Martinho": "são_martinho",
        "CCR Vila Viçosa": "vila_viçosa",
        "Milheiroense": "milheiroense",
        "União da Mata": "uniao_da_mata",
        "SC EspinhoB": "espinho_b",
        "Caldas S. Jorge": "caldas_sjorge",
        "CRC Vale": "crc_vale",
        "CD TareiS23": "cd_tarei",
        "EF Rui DoloresS23": "ef_rui_dolores",
        "Mosteirô FCS23": "mosteiro_fc",
        # Apuramento de Campeão opponents. No fixtures-page URL is declared for
        # them: they are only ever seen from Mansores' own scrape, which is all
        # the GPS fixture link reads.
        "Calvão": "calvao",
        "Gafanha": "gafanha",
        "AD Calvão": "calvao",
        "Gafanha B": "gafanha",
    },
    extra_competitions=(
        "Taça Pecol - Prof. José Valente Pinho Leão 25/26",
        "Apuramento de Campeão",
    ),
)

SEASONS: dict[str, SeasonConfig] = {
    MANSORES_2025_26.key: MANSORES_2025_26,
}


def get_season(key: str) -> SeasonConfig:
    try:
        return SEASONS[key]
    except KeyError as exc:
        available = ", ".join(sorted(SEASONS))
        raise KeyError(f"Unknown season '{key}'. Available: {available}") from exc


def list_seasons() -> list[SeasonConfig]:
    return list(SEASONS.values())
