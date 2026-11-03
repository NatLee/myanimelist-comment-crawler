"""Jikan-Edge API mapping, checked against answers saved on 2026-11-04 (tests/fixtures/jikan_edge)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from malcrawler.schema import ANIME_COLUMNS, REVIEW_COLUMNS
from malcrawler.sources import HtmlSource, JikanEdgeSource, SourceError, WorkRef
from tests.conftest import FMAB, read_fixture
from tests.expected import FMAB_INFO, MADOKA_INFO


@pytest.fixture
def edge(settings) -> JikanEdgeSource:
    return JikanEdgeSource(settings)


def test_urls_come_from_settings(settings):
    custom = JikanEdgeSource(replace(settings, jikan_edge_base_url="http://localhost:8787/v1"))
    assert custom.ranking_url(0) == "http://localhost:8787/v1/top/anime?page=1"
    assert custom.info_url(WorkRef(5114)) == "http://localhost:8787/v1/anime/5114"
    assert custom.reviews_url(FMAB, 2) == ("http://localhost:8787/v1/anime/5114/reviews"
                                           "?page=2&preliminary=true&spoilers=true")


def test_ranking(edge):
    page = edge.parse_ranking(read_fixture("jikan_edge/top_anime_p1.json"), edge.ranking_url(0))
    assert [work.work_id for work in page.works] == [52991, 5114, 61316]
    assert page.has_next


@pytest.mark.parametrize(("work_id", "html_values"), [(5114, FMAB_INFO), (11979, MADOKA_INFO)])
def test_info_rows_match_the_html_source(edge, work_id, html_values):
    """Same title, same day: every column except the URL spelling matches the web page."""
    row = edge.parse_info(read_fixture(f"jikan_edge/anime_{work_id}.json"), edge.info_url(WorkRef(work_id)))
    assert list(row) == list(ANIME_COLUMNS)
    differing = {key for key in html_values if row[key] != html_values[key]}
    assert differing <= {"url"}
    assert row["url"].startswith(f"https://myanimelist.net/anime/{work_id}/")
    assert row["url"].isascii()


def test_info_fills_html_placeholders_for_missing_values(edge):
    payload = json.loads(read_fixture("jikan_edge/anime_11979.json"))
    payload["data"].update(episodes=None, score=None, rank=None, scoredBy=None)
    row = edge.parse_info(json.dumps(payload), "")
    assert (row["episodes"], row["score"], row["allRank"], row["scoredByUser"]) == ("Unknown", "N/A", "N/A", "")


def test_review_rows(edge):
    page = edge.parse_reviews(read_fixture("jikan_edge/reviews_5114_p1.json"), edge.reviews_url(FMAB, 1), FMAB)
    assert page.has_next
    first = page.reviews[0]
    assert list(first) == list(REVIEW_COLUMNS)
    assert first["episodesSeen"] == "(26/64 eps)"  # same text as the web page's preliminary tag
    assert first["reviewerProfileUrl"] == "https://myanimelist.net/profile/sample_user_1"
    assert first["url"] == "https://myanimelist.net/reviews.php?id=900001"
    assert first["workName"] == "Fullmetal_Alchemist__Brotherhood"
    assert first["postTime"] == "Oct 9, 2009"
    assert [row["recommendationStatus"] for row in page.reviews] == ["Recommended", "Not Recommended",
                                                                     "Mixed Feelings"]
    assert (first["nice"], first["confusing"]) == (214, 6)


def test_read_more_toggle_is_joined_like_the_html_source(edge, settings):
    edge_rows = edge.parse_reviews(read_fixture("jikan_edge/reviews_5114_p1.json"), "", FMAB).reviews
    html = HtmlSource(settings)
    html_rows = html.parse_reviews(read_fixture("html/reviews_5114_p1.html"), "", FMAB).reviews
    assert [row["review"] for row in edge_rows] == [row["review"] for row in html_rows]


def test_preliminary_review_of_a_title_with_unknown_length(edge):
    work = WorkRef(5114, FMAB.url, "Unknown")
    row = edge.parse_reviews(read_fixture("jikan_edge/reviews_5114_p1.json"), "", work).reviews[0]
    assert row["episodesSeen"] == "(26/? eps)"


def test_last_page(edge):
    page = edge.parse_reviews(read_fixture("jikan_edge/reviews_5114_p2.json"), "", FMAB)
    assert len(page.reviews) == 1 and not page.has_next


@pytest.mark.parametrize("body", ['{"error": {"code": "RATE_LIMITED"}}', "<html>Bad gateway</html>", "[]"])
def test_unexpected_answers_raise_a_readable_error(edge, body):
    with pytest.raises(SourceError, match="the API"):
        edge.parse_info(body, "https://example.test/v1/anime/1")
