from __future__ import annotations

import csv

import pytest

from malcrawler.export import export_to_csv
from malcrawler.schema import ANIME_COLUMNS, REVIEW_COLUMNS
from malcrawler.storage import AnimeAccess, Database


def review(review_id: int, post_time: str) -> dict:
    row = {column: None for column in REVIEW_COLUMNS}
    row.update(workId=1, reviewId=review_id, postTime=post_time, review="text", reviewerProfileUrl="p",
               reviewerImageUrl="i")
    return row


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "anime.db"
    store = AnimeAccess(Database(path))
    store.push_work_infos_to_database([{column: "" for column in ANIME_COLUMNS} | {"workId": "1", "jpName": "鋼"}])
    store.push_reviews_to_database([review(1, "Sep 14, 2026"), review(2, "Apr 2, 2010"), review(3, "Jan 5, 2025"),
                                    review(4, "")])
    store.db.close()
    return path


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_reviews_are_sorted_by_date_not_by_text(database, tmp_path):
    # Regression: ORDER BY postTime sorted the text, so every "Apr ..." came before every "Jan ...".
    _, reviews_csv = export_to_csv(database, tmp_path / "out")
    assert [row["reviewId"] for row in read_csv(reviews_csv)] == ["2", "3", "1", "4"]


def test_csv_layout_matches_the_kaggle_dataset(database, tmp_path):
    anime_csv, reviews_csv = export_to_csv(database, tmp_path)
    assert anime_csv.name == "anime_list.csv" and reviews_csv.name == "reviews.csv"
    assert anime_csv.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM, for Excel
    reviews = read_csv(reviews_csv)
    expected = ["id", *[c for c in REVIEW_COLUMNS if c not in ("reviewerProfileUrl", "reviewerImageUrl")]]
    assert list(reviews[0]) == expected
    assert list(read_csv(anime_csv)[0]) == ["id", *ANIME_COLUMNS]
    assert read_csv(anime_csv)[0]["jpName"] == "鋼"


def test_missing_database_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="run the spiders first"):
        export_to_csv(tmp_path / "nope.db", tmp_path)
