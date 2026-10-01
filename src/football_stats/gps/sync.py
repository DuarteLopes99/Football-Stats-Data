"""Rebuild ``data/gps/gps_sessions.csv`` from the STATSports workbook.

The workbook (``gps.config.SOURCE_XLSX``) is the source of truth and lives
outside the repo; the CSV is its tidy sub-product, committed so the dashboard
runs from a fresh clone. Run this after updating the workbook::

    python -m football_stats.gps.sync            # rebuild and report the diff
    python -m football_stats.gps.sync --check    # report only, write nothing

The workbook is only ever read.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from football_stats.gps.config import SOURCE_XLSX
from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, build_from_excel, load_sessions, save_sessions

_KEY = ["date", "session_kind", "session_type"]


@dataclass
class SyncReport:
    rows_before: int
    rows_after: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed) or self.rows_before != self.rows_after

    def lines(self) -> list[str]:
        out = [f"rows: {self.rows_before} -> {self.rows_after}"]
        out += [f"  + {row}" for row in self.added]
        out += [f"  - {row}" for row in self.removed]
        return out


def _describe(df: pd.DataFrame) -> list[str]:
    return [f"{r.date:%Y-%m-%d} {r.session_kind:<8} {r.session_type}" for r in df.itertuples()]


def diff(old: pd.DataFrame, new: pd.DataFrame) -> SyncReport:
    """Rows present in only one of the two frames, keyed on date + kind + label."""
    merged = old[_KEY].merge(new[_KEY], on=_KEY, how="outer", indicator=True)
    return SyncReport(
        rows_before=len(old),
        rows_after=len(new),
        added=_describe(merged[merged["_merge"] == "right_only"]),
        removed=_describe(merged[merged["_merge"] == "left_only"]),
    )


def source_is_newer(xlsx: Path = SOURCE_XLSX, csv: Path = DEFAULT_SESSIONS_PATH) -> bool:
    """True when the workbook was saved after the CSV was last written."""
    return xlsx.exists() and csv.exists() and xlsx.stat().st_mtime > csv.stat().st_mtime


def sync(xlsx: Path = SOURCE_XLSX, csv: Path = DEFAULT_SESSIONS_PATH, write: bool = True) -> SyncReport:
    if not Path(xlsx).exists():
        raise FileNotFoundError(f"Workbook not found: {xlsx} (set FOOTBALL_GPS_XLSX to point at it)")
    new = build_from_excel(xlsx)
    report = diff(load_sessions(csv), new)
    if write:
        save_sessions(new, csv)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xlsx", type=Path, default=SOURCE_XLSX)
    parser.add_argument("--csv", type=Path, default=DEFAULT_SESSIONS_PATH)
    parser.add_argument("--check", action="store_true", help="report the differences without writing")
    args = parser.parse_args()
    report = sync(args.xlsx, args.csv, write=not args.check)
    print("\n".join(report.lines()))
    print("(check only — nothing written)" if args.check else f"wrote {args.csv}")


if __name__ == "__main__":
    main()
