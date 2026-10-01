"""Season/competition configuration.

Each season is described declaratively (team slugs, their zerozero.pt fixtures-page
URLs, and the exact competition name to filter on) so the scraping/processing/
prediction pipeline in the rest of ``football_stats`` never hardcodes a team or
season — new seasons or divisions are added here, not by editing pipeline code.
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
    """Exact zerozero.pt competition string used to filter scraped fixture rows.

    This is the **league** only. It drives the table and the Monte Carlo
    prediction, which are defined over a single round-robin competition — cup
    ties and play-off rounds would corrupt both. Other competitions the team
    played in the same season are declared in ``extra_competitions``.
    """

    primary_team: str
    """Slug (key into ``teams``) of the team this season's data collection is centered on."""

    teams: dict[str, str] = field(default_factory=dict)
    """Team slug -> zerozero.pt "jogos" (fixtures) page URL."""

    team_name_mapping: dict[str, str] = field(default_factory=dict)
    """zerozero.pt display name (as it appears in scraped tables) -> team slug."""

    extra_competitions: tuple[str, ...] = ()
    """Other competitions the primary team played this season — cup runs and
    play-off rounds.

    Deliberately **not** used by the league table or the predictor: those are
    defined over ``competition_name``'s round-robin alone. This exists so that
    GPS match sessions from those competitions can still be recognised as
    official matches and linked to a fixture (see ``gps/match_link.py``) rather
    than being silently unmatchable.
    """

    @property
    def dir(self) -> Path:
        return DATA_ROOT / "seasons" / self.key

    @property
    def raw_dir(self) -> Path:
        path = self.dir / "raw"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def processed_dir(self) -> Path:
        path = self.dir / "processed"
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

FERMEDO_2024_25 = SeasonConfig(
    key="fermedo_2024_25",
    label="UD Fermedo — AF Aveiro 2ª Divisão Zona Norte 24/25",
    competition_name="AF Aveiro 2ª Divisão Zona Norte 24/25",
    primary_team="fermedo",
    teams={
        "fermedo": "https://www.zerozero.pt/equipa/ud-fermedo/37219/jogos?grp=1&epoca_id=154",
        "caldas_sjorge": "https://www.zerozero.pt/equipa/caldas-s-jorge/16113/jogos?grp=1",
        "macieira_cambra": "https://www.zerozero.pt/equipa/macieira-cambra/10975/jogos?grp=1&epoca_id=154",
        "nege": "https://www.zerozero.pt/equipa/nege/329973/jogos?grp=1",
        "sanguedo": "https://www.zerozero.pt/equipa/sanguedo/6472/jogos?grp=1&epoca_id=154",
        "valega": "https://www.zerozero.pt/equipa/ccr-valega/18244/jogos?grp=1&epoca_id=154",
        "macieirense": "https://www.zerozero.pt/equipa/macieirense/10970/jogos?grp=1&epoca_id=154",
        "são_martinho": "https://www.zerozero.pt/equipa/ccr-sao-martinho/16114/jogos?grp=1&epoca_id=154",
        "vila_viçosa": "https://www.zerozero.pt/equipa/ccr-vila-vicosa/216307/jogos?grp=1&epoca_id=154",
        "rocas_vouga": "https://www.zerozero.pt/equipa/rocas-do-vouga/327358/jogos?grp=1&epoca_id=154",
        "são_vicente_pereira": "https://www.zerozero.pt/equipa/s-vicente-pereira/312991/jogos?grp=1&epoca_id=154",
        "fajoes": "https://www.zerozero.pt/equipa/gd-fajoes/6476/jogos?grp=1",
        "milheiroense": "https://www.zerozero.pt/equipa/milheiroense/3607/jogos?grp=1&epoca_id=154",
        "flograde_b": "https://www.zerozero.pt/equipa/florgrade-fc/275834/jogos?grp=1&epoca_id=154",
        "santiais": "https://www.zerozero.pt/equipa/santiais/11520/jogos?grp=1&epoca_id=154",
        "cucujaes": "https://www.zerozero.pt/equipa/at-cucujaes/312992/jogos?grp=1",
    },
    team_name_mapping={
        "UD Fermedo": "fermedo",
        "Caldas S. Jorge": "caldas_sjorge",
        "Macieira Cambra": "macieira_cambra",
        "NEGES23": "nege",
        "Sanguedo": "sanguedo",
        "CCR Válega": "valega",
        "Macieirense": "macieirense",
        "CCR São Martinho": "são_martinho",
        "CCR Vila Viçosa": "vila_viçosa",
        "Rocas do VougaS23": "rocas_vouga",
        "S. Vicente PereiraS23": "são_vicente_pereira",
        "S. Vicente Pereira": "são_vicente_pereira",
        "Milheiroense": "milheiroense",
        "Florgrade FCB": "flograde_b",
        "Florgrade FC": "flograde_b",
        "Santiais": "santiais",
        "At. CucujãesS23": "cucujaes",
        "GD Fajões": "fajoes",
    },
)

SEASONS: dict[str, SeasonConfig] = {
    MANSORES_2025_26.key: MANSORES_2025_26,
    FERMEDO_2024_25.key: FERMEDO_2024_25,
}


def get_season(key: str) -> SeasonConfig:
    try:
        return SEASONS[key]
    except KeyError as exc:
        available = ", ".join(sorted(SEASONS))
        raise KeyError(f"Unknown season '{key}'. Available: {available}") from exc


def list_seasons() -> list[SeasonConfig]:
    return list(SEASONS.values())
