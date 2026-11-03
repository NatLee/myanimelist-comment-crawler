"""Dump the database to the two CSV files of the Kaggle dataset (``anime_list.csv``, ``reviews.csv``)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from .schema import ANIME_TABLE, EXPORT_DROPPED_REVIEW_COLUMNS, REVIEWS_TABLE

ANIME_CSV = "anime_list.csv"
REVIEWS_CSV = "reviews.csv"
CSV_ENCODING = "utf-8-sig"  # with a BOM, so Excel opens the Japanese titles correctly


def export_to_csv(database: str | Path, out_dir: str | Path = ".") -> tuple[Path, Path]:
    """Write both CSV files and return their paths. Reviews are sorted by post date, oldest first."""
    database, out_dir = Path(database), Path(out_dir)
    if not database.exists():
        raise FileNotFoundError(f"{database} does not exist; run the spiders first")
    with closing(sqlite3.connect(database)) as conn:
        anime = pd.read_sql_query(f'SELECT * FROM "{ANIME_TABLE}"', conn)
        reviews = pd.read_sql_query(f'SELECT * FROM "{REVIEWS_TABLE}"', conn)

    # postTime is text like "Sep 14, 2026"; sorting the text would put April before January.
    posted = pd.to_datetime(reviews["postTime"], format="mixed", errors="coerce")
    reviews = (reviews.assign(_posted=posted)
               .sort_values("_posted", kind="stable", na_position="last")
               .drop(columns=["_posted", *EXPORT_DROPPED_REVIEW_COLUMNS]))

    out_dir.mkdir(parents=True, exist_ok=True)
    anime_csv, reviews_csv = out_dir / ANIME_CSV, out_dir / REVIEWS_CSV
    anime.to_csv(anime_csv, index=False, encoding=CSV_ENCODING)
    reviews.to_csv(reviews_csv, index=False, encoding=CSV_ENCODING)
    return anime_csv, reviews_csv
