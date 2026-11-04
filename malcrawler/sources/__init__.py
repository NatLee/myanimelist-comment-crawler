"""Data sources the spiders can read from (``-a source=<name>`` / ``--source <name>``)."""

from __future__ import annotations

from ..config import Settings
from .base import RankingPage, ReviewPage, Source, SourceError, WorkRef
from .html import HtmlSource
from .jikan_edge import JikanEdgeSource

SOURCES: dict[str, type[Source]] = {cls.name: cls for cls in (JikanEdgeSource, HtmlSource)}
# jikan-edge since 2026-11-04 (owner's decision): MyAnimeList's robots.txt blocks Scrapy, so the
# original html source stops at its first request. html stays available with --source html.
DEFAULT_SOURCE = JikanEdgeSource.name


def make_source(name: str, settings: Settings) -> Source:
    try:
        return SOURCES[name](settings)
    except KeyError:
        known = ", ".join(SOURCES)
        raise ValueError(f"Unknown source {name!r}. Choose one of: {known}.") from None


__all__ = [
    "DEFAULT_SOURCE", "SOURCES", "HtmlSource", "JikanEdgeSource", "RankingPage", "ReviewPage", "Source",
    "SourceError", "WorkRef", "make_source",
]
