from __future__ import annotations

import sqlite3

import pytest

from malcrawler.config import Settings
from malcrawler.sources import HtmlSource
from malcrawler.storage import AnimeAccess, Database, Progress
from tests.conftest import FMAB, read_fixture

# Column order of the two tables as the 2023 crawler created them (the Kaggle CSV layout).
COLUMNS_2023 = {
    "animeList": ["id", "workId", "url", "jpName", "engName", "synonymsName", "workType", "episodes", "status",
                  "aired", "premiered", "producer", "broadcast", "licensors", "studios", "genres", "themes",
                  "demographic", "source", "duration", "rating", "score", "allRank", "popularityRank", "members",
                  "favorites", "scoredByUser", "lastUpdate"],
    "reviews": ["id", "workId", "url", "workName", "postTime", "episodesSeen", "overallRating", "author",
                "reviewId", "review", "reviewerProfileUrl", "reviewerImageUrl", "recommendationStatus", "nice",
                "loveIt", "funny", "confusing", "informative", "wellWritten", "creative"],
}


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "anime.db")
    yield AnimeAccess(db)
    db.close()


def columns(store: AnimeAccess, table: str) -> list[str]:
    return [row[1] for row in store.db.connection.execute(f'PRAGMA table_info("{table}")')]


def test_tables_keep_the_2023_layout(store):
    for table, expected in COLUMNS_2023.items():
        assert columns(store, table) == expected


def test_a_2023_database_opens_and_gains_the_progress_table(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE `animeList` (`id` INTEGER PRIMARY KEY, `workId` INTEGER UNIQUE, `url` TEXT, "
                     "`episodes` INTEGER)")
        conn.execute("INSERT INTO animeList (workId, url, episodes) VALUES (5114, 'https://x/anime/5114/FMAB', 64)")
    store = AnimeAccess(Database(path))
    assert store.get_works()[0].work_id == 5114
    assert store.get_progress("html") == {}
    store.db.close()


def test_saving_a_review_twice_keeps_one_row(store):
    html = HtmlSource(Settings())
    rows = html.parse_reviews(read_fixture("html/reviews_5114_p1.html"), "page-1", FMAB).reviews
    store.push_reviews_to_database(rows)
    store.push_reviews_to_database(rows[:1])
    assert store.db.connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 3


def test_works_come_back_in_saved_order_and_can_be_filtered(store):
    infos = [{column: "" for column in COLUMNS_2023["animeList"][1:]} | {"workId": str(i), "url": f"u/{i}",
                                                                           "episodes": "12"}
             for i in (30, 10, 20)]
    store.push_work_infos_to_database(infos)
    assert [work.work_id for work in store.get_works()] == [30, 10, 20]
    assert [work.work_id for work in store.get_works([20, 30, 99])] == [30, 20]
    assert store.get_works([10])[0].episodes == "12"
    assert store.get_all_work_urls() == ["u/30", "u/10", "u/20"]


def test_progress_is_kept_per_source(store):
    store.save_progress(5114, "html", 3, done=False)
    store.save_progress(5114, "html", 4, done=True)
    store.save_progress(5114, "jikan-edge", 1, done=False)
    assert store.get_progress("html") == {5114: Progress(4, True)}
    assert store.get_progress("jikan-edge") == {5114: Progress(1, False)}
