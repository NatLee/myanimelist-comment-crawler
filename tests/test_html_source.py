"""MyAnimeList page parsing, checked against pages saved on 2026-11-04 (tests/fixtures/html)."""

from __future__ import annotations

import pytest

from malcrawler.schema import ANIME_COLUMNS, REACTIONS, REVIEW_COLUMNS
from malcrawler.sources import HtmlSource, SourceError, WorkRef
from tests.conftest import FMAB, read_fixture
from tests.expected import FMAB_INFO, MADOKA_INFO, MADOKA_URL


@pytest.fixture
def html(settings) -> HtmlSource:
    return HtmlSource(settings)


def without_timestamp(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "lastUpdate"}


# -- ranking ---------------------------------------------------------------------------------------

def test_ranking_lists_titles_and_asks_for_next_page(html):
    page = html.parse_ranking(read_fixture("html/topanime_limit0.html"), html.ranking_url(0))
    assert [work.work_id for work in page.works] == [52991, 5114, 61316]
    assert page.works[1].url == FMAB.url
    assert page.has_next


def test_ranking_ends_on_an_empty_page(html):
    page = html.parse_ranking(read_fixture("html/topanime_empty.html"), html.ranking_url(600))
    assert page.works == [] and not page.has_next


def test_ranking_pages_step_by_rank_increment(html):
    assert html.ranking_url(0) == "https://myanimelist.net/topanime.php?limit=0"
    assert html.ranking_url(2) == "https://myanimelist.net/topanime.php?limit=100"


# -- anime information -----------------------------------------------------------------------------

@pytest.mark.parametrize(("fixture", "url", "expected"), [
    ("html/anime_5114.html", FMAB.url, FMAB_INFO),
    ("html/anime_11979.html", MADOKA_URL, MADOKA_INFO),
])
def test_info_page_fields(html, fixture, url, expected):
    row = html.parse_info(read_fixture(fixture), url)
    assert list(row) == list(ANIME_COLUMNS)
    assert without_timestamp(row) == expected


def test_info_source_that_is_a_link_is_read(html):
    # Regression: "Source: <a>Manga</a>" came out as "" because only plain text was read.
    assert html.parse_info(read_fixture("html/anime_5114.html"), FMAB.url)["source"] == "Manga"


def test_info_requested_by_id_uses_the_pages_own_address(html):
    row = html.parse_info(read_fixture("html/anime_11979.html"), "https://myanimelist.net/anime/11979")
    assert row["url"] == ("https://myanimelist.net/anime/11979/"
                          "Mahou_Shoujo_Madoka%E2%98%86Magica_Movie_2__Eien_no_Monogatari")


def test_info_handles_missing_fields_and_plural_labels(html):
    page = """<html><body>
      <div><span class="dark_text">Type:</span> <a href="#">TV</a></div>
      <div><span class="dark_text">Demographics:</span> <a href="#">Shounen</a>, <a href="#">Seinen</a></div>
      <div><span class="dark_text">Genre:</span> <a href="#">Drama</a></div>
    </body></html>"""
    row = html.parse_info(page, FMAB.url)
    assert row["rating"] == ""  # the 2023 parser crashed here when a title had no rating
    assert row["demographic"] == "Shounen, Seinen"
    assert row["genres"] == "Drama"


def test_info_refuses_a_page_that_is_not_an_anime_page(html):
    with pytest.raises(SourceError, match="does not look like an anime page"):
        html.parse_info("<html><body>Please verify you are a human</body></html>", FMAB.url)


# -- reviews ---------------------------------------------------------------------------------------

@pytest.fixture
def page_one(html):
    return html.parse_reviews(read_fixture("html/reviews_5114_p1.html"), html.reviews_url(FMAB, 1), FMAB)


def test_reviews_url_asks_for_newest_first_with_preliminary_and_spoilers(html):
    assert html.reviews_url(FMAB, 3) == (FMAB.url + "/reviews?sort=newest&filter_check=&filter_hide="
                                         "&preliminary=on&spoiler=on&p=3")


def test_review_rows_have_every_column(page_one):
    assert page_one.has_next
    assert len(page_one.reviews) == 3
    for row in page_one.reviews:
        assert list(row) == list(REVIEW_COLUMNS)


def test_first_review_fields(page_one, html):
    row = page_one.reviews[0]
    assert row == {
        "workId": 5114,
        "url": html.reviews_url(FMAB, 1),
        "workName": "Fullmetal_Alchemist__Brotherhood",
        "postTime": "Sep 14, 2026",
        "episodesSeen": "(40/64 eps)",
        "overallRating": 9,
        "author": "sample_user_1",
        "reviewId": 900001,
        "review": "Sample review one, first paragraph.\n\nSecond paragraph that MAL cuts in the middle of a "
                  "sentence with a read more toggle.\n\nLast line of review one.",
        "reviewerProfileUrl": "https://myanimelist.net/profile/sample_user_1",
        "reviewerImageUrl": "https://cdn.myanimelist.net/images/kaomoji_mal_white.png",
        "recommendationStatus": "Recommended",
        "nice": 0, "loveIt": 0, "funny": 0, "confusing": 0, "informative": 1, "wellWritten": 0, "creative": 0,
    }


def test_review_id_is_read_from_the_id_parameter(html):
    # The 2023 code took the first number in the permalink, which breaks on any host with digits.
    page = read_fixture("html/reviews_5114_p1.html").replace("https://myanimelist.net", "http://127.0.0.1:8080")
    rows = html.parse_reviews(page, "", FMAB).reviews
    assert [row["reviewId"] for row in rows] == [900001, 900002, 900003]


def test_all_three_recommendation_tags_are_kept(page_one):
    # Regression: only "Recommended" was read; the other two were stored as NULL.
    statuses = [row["recommendationStatus"] for row in page_one.reviews]
    assert statuses == ["Recommended", "Not Recommended", "Mixed Feelings"]


def test_read_more_toggle_is_not_part_of_the_text(page_one):
    # Regression: every long review had "..." spliced into the middle of a sentence.
    for row in page_one.reviews:
        assert "..." not in row["review"]
    assert "the hidden half" in page_one.reviews[1]["review"]


def test_reactions_follow_mals_order(page_one):
    second = page_one.reviews[1]
    assert [second[name] for name in REACTIONS] == [0, 2, 5, 1, 1, 0, 0]


def test_last_review_page_has_no_next_page(html):
    page = html.parse_reviews(read_fixture("html/reviews_5114_p2.html"), html.reviews_url(FMAB, 2), FMAB)
    assert len(page.reviews) == 1 and not page.has_next


def test_changed_reaction_list_is_reported(html):
    page = read_fixture("html/reviews_5114_p1.html").replace('"count":["0","0","0","0","1","0","0"]', '"count":["0"]')
    with pytest.raises(SourceError, match="expected 7 reaction counts"):
        html.parse_reviews(page, "", FMAB)


def test_page_without_reviews_ends_the_title(html):
    page = html.parse_reviews("<html><body></body></html>", html.reviews_url(FMAB, 1), FMAB)
    assert page.reviews == [] and not page.has_next


def test_works_without_a_known_url_are_addressed_by_id(html):
    assert html.info_url(WorkRef(5114)) == "https://myanimelist.net/anime/5114"
