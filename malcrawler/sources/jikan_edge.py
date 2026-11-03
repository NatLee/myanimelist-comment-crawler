"""Jikan-Edge: an open-source, Jikan-style JSON API over public MyAnimeList data.

Why this one: the public Jikan v4 API (api.jikan.moe) shut down on 2026-10-01 and its maintainer
pointed to Jikan-Edge as a replacement (https://github.com/jikan-me/jikan-rest/issues/613).
Jikan-Edge is not schema-identical to Jikan v4 (camelCase fields), so it has its own mapper here.

The public instance allows 60 requests a minute (30 per 10 s burst) and answers 429 with a
Retry-After header beyond that. Point ``[JIKAN_EDGE] BaseUrl`` in setting.ini at your own instance
for large crawls. Its robots.txt keeps search engines out of /v1/ (the API), so API calls here do
not go through the robots.txt check; the published rate limit is what this source follows.

Values are written the way MyAnimeList's own pages show them ("#2", "3,752,360", "9.10"), so rows
look the same whichever source filled the table.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterable, Mapping
from typing import Any

from ..schema import REACTIONS
from .base import RankingPage, ReviewPage, Source, SourceError, WorkRef, ascii_url, clean_text


def _payload(body: str, url: str) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise SourceError(f"{url}: the API did not answer with JSON") from error
    if not isinstance(payload, dict) or "data" not in payload:
        detail = payload.get("error", payload) if isinstance(payload, dict) else payload
        raise SourceError(f"{url}: the API answered without data: {detail}")
    return payload


def _join_read_more_toggle(text: str) -> str:
    """Jikan-Edge keeps the "..." of MyAnimeList's Read more toggle as a line of its own, in the
    middle of a sentence ("cut in the\\n...\\nmiddle"). Join the two halves like the html source does.
    Remove this once Jikan-Edge stops returning the toggle (checked 2026-11-04: it still does)."""
    return text.replace("\n...\n", " ", 1)


def _names(items: Iterable[Mapping[str, Any]] | None) -> str:
    return ", ".join(item["name"] for item in items or [])


def _rank(value: int | None) -> str:
    return f"#{value}" if value else "N/A"


def _count(value: int | None) -> str:
    return f"{value:,}" if value is not None else ""


class JikanEdgeSource(Source):
    name = "jikan-edge"
    description = "Jikan-Edge JSON API (community replacement for the retired public Jikan API)"
    download_delay = {"info": 2.0, "reviews": 2.0}  # 30 a minute, half the published limit
    obey_robots_txt = False

    @property
    def base_url(self) -> str:
        return self.settings.jikan_edge_base_url

    # -- ranking -----------------------------------------------------------------------------------

    def ranking_url(self, page_index: int) -> str:
        return f"{self.base_url}/top/anime?page={page_index + 1}"

    def parse_ranking(self, body: str, url: str) -> RankingPage:
        payload = _payload(body, url)
        works = [WorkRef(int(item["malId"])) for item in payload["data"]]
        has_next = bool(payload.get("meta", {}).get("pagination", {}).get("hasNextPage"))
        return RankingPage(works=works, has_next=has_next)

    # -- anime information -------------------------------------------------------------------------

    def info_url(self, work: WorkRef) -> str:
        return f"{self.base_url}/anime/{work.work_id}"

    def parse_info(self, body: str, url: str) -> dict[str, str]:
        d = _payload(body, url)["data"]
        season, year = d.get("season"), d.get("year")
        score = d.get("score")
        return {
            "workId": str(d["malId"]),
            "url": ascii_url(d.get("url") or f"{self.settings.mal_base_url}/anime/{d['malId']}"),
            "jpName": d.get("titleJapanese") or "",
            "engName": d.get("titleEnglish") or "",
            "synonymsName": ", ".join(d.get("titleSynonyms") or []),
            "workType": d.get("type") or "",
            "episodes": str(d["episodes"]) if d.get("episodes") is not None else "Unknown",
            "status": d.get("status") or "",
            "aired": (d.get("aired") or {}).get("string") or "",
            "premiered": f"{season.capitalize()} {year}" if season and year else "",
            "producer": _names(d.get("producers")),
            "broadcast": (d.get("broadcast") or {}).get("string") or "",
            "licensors": _names(d.get("licensors")),
            "studios": _names(d.get("studios")),
            "genres": _names(d.get("genres")),
            "themes": _names(d.get("themes")),
            "demographic": _names(d.get("demographics")),
            "source": d.get("source") or "",
            "duration": d.get("duration") or "",
            "rating": d.get("rating") or "",
            "score": f"{score:.2f}" if score is not None else "N/A",
            "allRank": _rank(d.get("rank")),
            "popularityRank": _rank(d.get("popularity")),
            "members": _count(d.get("members")),
            "favorites": _count(d.get("favorites")),
            "scoredByUser": str(d["scoredBy"]) if d.get("scoredBy") is not None else "",
            "lastUpdate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # -- reviews -----------------------------------------------------------------------------------

    def reviews_url(self, work: WorkRef, page: int) -> str:
        return f"{self.base_url}/anime/{work.work_id}/reviews?page={page}&preliminary=true&spoilers=true"

    def parse_reviews(self, body: str, url: str, work: WorkRef) -> ReviewPage:
        payload = _payload(body, url)
        reviews = [self._review(item, work) for item in payload["data"]]
        has_next = bool(payload.get("meta", {}).get("pagination", {}).get("hasNextPage"))
        return ReviewPage(reviews=reviews, has_next=has_next)

    def _review(self, item: Mapping[str, Any], work: WorkRef) -> dict[str, Any]:
        watched = item.get("episodesWatched")
        total = work.episodes if work.episodes and work.episodes != "Unknown" else "?"
        reactions = item.get("reactions") or {}
        username = item.get("username") or ""
        row: dict[str, Any] = {
            "workId": work.work_id,
            "url": item.get("url"),
            "workName": work.name,
            "postTime": item.get("date") or "",
            # Same text MyAnimeList shows on a preliminary review, e.g. "(26/64 eps)".
            "episodesSeen": f"({watched}/{total} eps)" if item.get("isPreliminary") and watched is not None else None,
            "overallRating": item.get("score"),
            "author": username,
            "reviewId": int(item["reviewId"]),
            "review": _join_read_more_toggle(clean_text(item.get("reviewText") or "")),
            "reviewerProfileUrl": f"{self.settings.mal_base_url}/profile/{username}" if username else None,
            "reviewerImageUrl": item.get("imageUrl"),
            "recommendationStatus": item.get("tag") or None,
        }
        row.update((name, int(reactions.get(name) or 0)) for name in REACTIONS)
        return row
