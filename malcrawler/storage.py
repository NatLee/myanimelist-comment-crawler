"""SQLite storage for anime information, reviews and crawl progress."""

from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import (
    ANIME_COLUMNS,
    ANIME_TABLE,
    PROGRESS_COLUMNS,
    PROGRESS_KEY,
    PROGRESS_TABLE,
    REVIEW_COLUMNS,
    REVIEWS_TABLE,
)
from .sources.base import WorkRef


@dataclass(frozen=True)
class Progress:
    last_page: int
    done: bool


def _create_table_sql(table: str, columns: Mapping[str, str], primary_key: Collection[str] = ()) -> str:
    lines = [] if primary_key else ["id INTEGER PRIMARY KEY"]
    lines += [f'"{name}" {sql_type}' for name, sql_type in columns.items()]
    if primary_key:
        lines.append("PRIMARY KEY (" + ", ".join(f'"{name}"' for name in primary_key) + ")")
    return f'CREATE TABLE IF NOT EXISTS "{table}" (\n    ' + ",\n    ".join(lines) + "\n)"


def _upsert_sql(table: str, columns: Iterable[str]) -> str:
    names = list(columns)
    quoted = ", ".join(f'"{name}"' for name in names)
    marks = ", ".join("?" for _ in names)
    return f'INSERT OR REPLACE INTO "{table}" ({quoted}) VALUES ({marks})'


class Database:
    """One SQLite connection. ``path`` is created if it does not exist."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()


class AnimeAccess:
    """Reads and writes the crawler's tables (created on first use)."""

    def __init__(self, db: Database):
        self.db = db
        self.initialize_tables()

    def initialize_tables(self) -> None:
        with self.db.connection as conn:
            conn.execute(_create_table_sql(REVIEWS_TABLE, REVIEW_COLUMNS))
            conn.execute(_create_table_sql(ANIME_TABLE, ANIME_COLUMNS))
            conn.execute(_create_table_sql(PROGRESS_TABLE, PROGRESS_COLUMNS, primary_key=PROGRESS_KEY))

    # -- writes ------------------------------------------------------------------------------------

    def push_work_infos_to_database(self, work_infos: Iterable[Mapping[str, Any]]) -> int:
        return self._upsert(ANIME_TABLE, ANIME_COLUMNS, work_infos)

    def push_reviews_to_database(self, reviews: Iterable[Mapping[str, Any]]) -> int:
        return self._upsert(REVIEWS_TABLE, REVIEW_COLUMNS, reviews)

    def save_progress(self, work_id: int, source: str, last_page: int, done: bool) -> None:
        row = {
            "workId": work_id,
            "source": source,
            "lastPage": last_page,
            "done": int(done),
            "updatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._upsert(PROGRESS_TABLE, PROGRESS_COLUMNS, [row])

    def _upsert(self, table: str, columns: Mapping[str, str], rows: Iterable[Mapping[str, Any]]) -> int:
        names = list(columns)
        values = [tuple(row[name] for name in names) for row in rows]
        with self.db.connection as conn:
            conn.executemany(_upsert_sql(table, names), values)
        return len(values)

    # -- reads -------------------------------------------------------------------------------------

    def get_all_work_urls(self) -> list[str]:
        return [work.url for work in self.get_works() if work.url]

    def get_works(self, ids: Collection[int] | None = None) -> list[WorkRef]:
        """Titles in the order they were first saved, optionally only the given MAL IDs."""
        rows = self.db.connection.execute(f'SELECT workId, url, episodes FROM "{ANIME_TABLE}" ORDER BY id')
        works = [WorkRef(int(row["workId"]), row["url"], None if row["episodes"] is None else str(row["episodes"]))
                 for row in rows]
        if ids is not None:
            wanted = set(ids)
            works = [work for work in works if work.work_id in wanted]
        return works

    def get_progress(self, source: str) -> dict[int, Progress]:
        rows = self.db.connection.execute(
            f'SELECT workId, lastPage, done FROM "{PROGRESS_TABLE}" WHERE source = ?', (source,))
        return {int(row["workId"]): Progress(int(row["lastPage"]), bool(row["done"])) for row in rows}
