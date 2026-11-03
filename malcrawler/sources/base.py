"""What every data source provides: where to fetch pages and how to turn them into table rows.

A source knows nothing about Scrapy. It builds URLs and parses response bodies into plain dicts
whose keys are the database columns (see ``malcrawler.schema``), so the spiders, the database and
the CSV export are the same whichever source the data came from.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import quote, urlsplit

from ..config import Settings

# Characters that stay as they are when a URL is made ASCII-only (the rest is percent-encoded,
# the same way Scrapy encodes the URLs it requests).
_URL_SAFE = "!#$%&'()*+,/:;=?@[]~"


class SourceError(Exception):
    """The response is not what the source expected (layout change, block page, API error)."""


@dataclass(frozen=True)
class WorkRef:
    """One anime title. ``url`` is its MyAnimeList page, when known."""

    work_id: int
    url: str | None = None
    episodes: str | None = None

    @property
    def name(self) -> str:
        """The title part of the MyAnimeList URL, e.g. ``Fullmetal_Alchemist__Brotherhood``."""
        return work_name_from_url(self.url)


@dataclass
class RankingPage:
    works: list[WorkRef] = field(default_factory=list)
    has_next: bool = False


@dataclass
class ReviewPage:
    reviews: list[dict[str, Any]] = field(default_factory=list)
    has_next: bool = False


def ascii_url(url: str) -> str:
    return quote(url, safe=_URL_SAFE)


def work_name_from_url(url: str | None) -> str:
    """``https://myanimelist.net/anime/5114/Fullmetal_Alchemist__Brotherhood/...`` -> the title part."""
    if not url:
        return ""
    parts = urlsplit(url).path.split("/")  # ['', 'anime', '5114', 'Fullmetal_Alchemist__Brotherhood', ...]
    return parts[3] if len(parts) > 3 else ""


def clean_text(text: str) -> str:
    """Strip every line and keep at most one empty line between paragraphs."""
    lines = (line.strip() for line in text.replace("\r\n", "\n").split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class Source(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    # Seconds between two requests, per spider kind ("info", "reviews").
    download_delay: ClassVar[Mapping[str, float]]
    # Whether requests go through Scrapy's robots.txt check.
    obey_robots_txt: ClassVar[bool]

    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def ranking_url(self, page_index: int) -> str:
        """URL of the ``page_index``-th (0-based) page of the all-time anime ranking."""

    @abstractmethod
    def parse_ranking(self, body: str, url: str) -> RankingPage: ...

    @abstractmethod
    def info_url(self, work: WorkRef) -> str: ...

    @abstractmethod
    def parse_info(self, body: str, url: str) -> dict[str, str]:
        """One ``animeList`` row (every column except ``id``)."""

    @abstractmethod
    def reviews_url(self, work: WorkRef, page: int) -> str:
        """URL of review page ``page`` (1-based) of ``work``."""

    @abstractmethod
    def parse_reviews(self, body: str, url: str, work: WorkRef) -> ReviewPage:
        """``reviews`` rows (every column except ``id``) and whether another page follows."""
