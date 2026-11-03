"""Tables and columns of the SQLite database.

The column names, order and types are the ones the 2023 crawler created; the Kaggle CSV files are
plain dumps of these tables, so changing them would break existing datasets and notebooks.
"""

from __future__ import annotations

ANIME_TABLE = "animeList"
REVIEWS_TABLE = "reviews"
PROGRESS_TABLE = "crawlProgress"

ANIME_COLUMNS: dict[str, str] = {
    "workId": "INTEGER UNIQUE",
    "url": "TEXT",
    "jpName": "TEXT",
    "engName": "TEXT",
    "synonymsName": "TEXT",
    "workType": "TEXT",
    "episodes": "INTEGER",
    "status": "TEXT",
    "aired": "TEXT",
    "premiered": "TEXT",
    "producer": "TEXT",
    "broadcast": "TEXT",
    "licensors": "TEXT",
    "studios": "TEXT",
    "genres": "TEXT",
    "themes": "TEXT",
    "demographic": "TEXT",
    "source": "TEXT",
    "duration": "TEXT",
    "rating": "TEXT",
    "score": "REAL",
    "allRank": "INTEGER",
    "popularityRank": "INTEGER",
    "members": "INTEGER",
    "favorites": "INTEGER",
    "scoredByUser": "INTEGER",
    "lastUpdate": "TEXT",
}

# Same order as the "count" array in MyAnimeList's data-reactions attribute.
REACTIONS: tuple[str, ...] = ("nice", "loveIt", "funny", "confusing", "informative", "wellWritten", "creative")

REVIEW_COLUMNS: dict[str, str] = {
    "workId": "INTEGER NOT NULL",
    "url": "TEXT",
    "workName": "TEXT",
    "postTime": "TEXT",
    "episodesSeen": "INTEGER",
    "overallRating": "INTEGER",
    "author": "TEXT",
    "reviewId": "INTEGER UNIQUE",
    "review": "TEXT",
    "reviewerProfileUrl": "TEXT",
    "reviewerImageUrl": "TEXT",
    "recommendationStatus": "TEXT",
    **{reaction: "INTEGER" for reaction in REACTIONS},
}

# Added in 2026 for --resume. Separate table, so the two tables above stay exactly as they were.
PROGRESS_COLUMNS: dict[str, str] = {
    "workId": "INTEGER NOT NULL",
    "source": "TEXT NOT NULL",
    "lastPage": "INTEGER NOT NULL",
    "done": "INTEGER NOT NULL",
    "updatedAt": "TEXT NOT NULL",
}
PROGRESS_KEY = ("workId", "source")

# Columns the CSV export leaves out (links to people's avatars and profiles).
EXPORT_DROPPED_REVIEW_COLUMNS = ("reviewerProfileUrl", "reviewerImageUrl")
