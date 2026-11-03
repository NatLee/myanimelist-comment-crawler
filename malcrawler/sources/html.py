"""MyAnimeList web pages: the way this crawler has always collected data.

Heads-up (checked 2026-11-04): MyAnimeList's robots.txt disallows the whole site for Scrapy
crawlers, so with robots.txt respected this source stops at its first request. The parsers still
match the pages as they looked on that day (see tests/fixtures/html).
"""

from __future__ import annotations

import datetime
import json
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from parsel import Selector

from ..schema import REACTIONS
from .base import RankingPage, ReviewPage, Source, SourceError, WorkRef, ascii_url, clean_text, work_name_from_url

# Reviews page query: newest first, including preliminary and spoiler reviews.
REVIEWS_QUERY = "sort=newest&filter_check=&filter_hide=&preliminary=on&spoiler=on&p={page}"
# The three recommendation tags a review can carry (CSS class names on the tag).
RECOMMENDATION_TAG_CLASSES = ("recommended", "not-recommended", "mixed-feelings")
# The "..." MyAnimeList shows where a long review is folded behind "Read more".
READ_MORE_TOGGLE_CLASS = "js-visible"
_TOGGLE_MARK = ""  # private-use character: never part of real review text, accepted by lxml


def _has_class(name: str) -> str:
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def _label(*labels: str) -> str:
    """XPath of the sidebar label span with one of these texts, e.g. ``Genres:``."""
    return "//span[" + " or ".join(f'normalize-space()="{label}"' for label in labels) + "]"


class HtmlSource(Source):
    name = "html"
    description = "MyAnimeList web pages (original method; MAL's robots.txt currently blocks it)"
    download_delay = {"info": 7.0, "reviews": 4.0}  # the pace the 2023 spiders used
    obey_robots_txt = True

    # -- ranking -----------------------------------------------------------------------------------

    def ranking_url(self, page_index: int) -> str:
        return f"{self.settings.mal_base_url}/topanime.php?limit={page_index * self.settings.rank_increment}"

    def parse_ranking(self, body: str, url: str) -> RankingPage:
        sel = Selector(text=body)
        works = []
        for row in sel.css("tr.ranking-list"):
            href = row.css("a.hoverinfo_trigger.fl-l.ml12.mr8::attr(href)").get()
            if href:
                works.append(WorkRef(int(urlsplit(href).path.split("/")[2]), href))
        return RankingPage(works=works, has_next=bool(works))

    # -- anime information -------------------------------------------------------------------------

    def info_url(self, work: WorkRef) -> str:
        return work.url or f"{self.settings.mal_base_url}/anime/{work.work_id}"

    def parse_info(self, body: str, url: str) -> dict[str, str]:
        sel = Selector(text=body)
        if not sel.xpath(_label("Type:")):
            raise SourceError(f"{url} does not look like an anime page (no 'Type:' field); "
                              "MyAnimeList may have changed its layout or answered with a block page.")
        if not work_name_from_url(url):  # e.g. /anime/5114 requested by ID: use the page's full address
            url = ascii_url(sel.css('meta[property="og:url"]::attr(content)').get() or url)

        def text(label: str) -> str:
            """First non-blank text after the label, whether it is plain text or a link."""
            return sel.xpath(_label(label) + "/following::text()[normalize-space()][1]").get(default="").strip()

        def links(word: str) -> str:
            """Comma-separated link texts after the label; matches ``Genre:`` and ``Genres:``."""
            values = sel.xpath(_label(f"{word}:", f"{word}s:") + "/following-sibling::a/text()").getall()
            return ", ".join(value.strip() for value in values)

        return {
            "workId": urlsplit(url).path.split("/")[2],
            "url": url,
            "jpName": text("Japanese:"),
            "engName": text("English:"),
            "synonymsName": text("Synonyms:"),
            "workType": links("Type"),
            "episodes": text("Episodes:"),
            "status": text("Status:"),
            "aired": text("Aired:"),
            "premiered": links("Premiered"),
            "producer": links("Producer"),
            "broadcast": text("Broadcast:"),
            "licensors": links("Licensor"),
            "studios": links("Studio"),
            "genres": links("Genre"),
            "themes": links("Theme"),
            "demographic": links("Demographic"),
            "source": text("Source:"),
            "duration": text("Duration:"),
            "rating": text("Rating:"),
            "score": sel.css("span.score-label::text").get(default="").strip(),
            "allRank": text("Ranked:"),
            "popularityRank": text("Popularity:"),
            "members": text("Members:"),
            "favorites": text("Favorites:"),
            "scoredByUser": sel.xpath('//span[@itemprop="ratingCount"]/text()').get(default="").strip(),
            "lastUpdate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # -- reviews -----------------------------------------------------------------------------------

    def reviews_url(self, work: WorkRef, page: int) -> str:
        return f"{self.info_url(work)}/reviews?" + REVIEWS_QUERY.format(page=page)

    def parse_reviews(self, body: str, url: str, work: WorkRef) -> ReviewPage:
        sel = Selector(text=body)
        reviews = [self._review(element, url, work) for element in sel.css("div.review-element")]
        more = sel.css('a.ga-click[data-ga-click-type="review-more-reviews"]')
        return ReviewPage(reviews=reviews, has_next=bool(more))

    def _review(self, el: Selector, url: str, work: WorkRef) -> dict[str, Any]:
        review_id = el.css("div.open a::attr(href)").re_first(r"[?&]id=(\d+)")  # .../reviews.php?id=<id>
        if review_id is None:
            raise SourceError(f"{url}: a review has no permalink; the page layout may have changed.")
        rating = el.css("div.rating span.num::text").get()
        episodes_seen = el.css(".tag.preliminary span::text").get()
        row: dict[str, Any] = {
            "workId": work.work_id,
            "url": url,
            "workName": work.name,
            "postTime": el.css("div.update_at::text").get(default="").strip(),
            "episodesSeen": episodes_seen.strip() if episodes_seen else None,
            "overallRating": int(rating) if rating and rating.strip().isdigit() else None,
            "author": el.css("div.username a::text").get(default="").strip(),
            "reviewId": int(review_id),
            "review": _review_text(el),
            "reviewerProfileUrl": el.css("div.thumb a::attr(href)").get(),
            "reviewerImageUrl": el.css("div.thumb a img::attr(src)").get(),
            "recommendationStatus": _recommendation(el),
        }
        row.update(zip(REACTIONS, _reaction_counts(el.attrib.get("data-reactions", ""), url), strict=True))
        return row


def _recommendation(el: Selector) -> str | None:
    condition = " or ".join(_has_class(name) for name in RECOMMENDATION_TAG_CLASSES)
    tag = el.xpath(f'.//div[{_has_class("tag")}][{condition}]')
    if not tag:
        return None
    return " ".join(part.strip() for part in tag[0].xpath(".//text()").getall() if part.strip()) or None


def _reaction_counts(raw: str, url: str) -> list[int]:
    if not raw:
        return [0] * len(REACTIONS)
    try:
        counts = [int(count) for count in json.loads(raw)["count"]]
    except (ValueError, KeyError, TypeError) as error:
        raise SourceError(f"{url}: unreadable reaction counts {raw!r}") from error
    if len(counts) != len(REACTIONS):
        raise SourceError(f"{url}: expected {len(REACTIONS)} reaction counts, got {len(counts)}; "
                          "MyAnimeList may have changed its reactions")
    return counts


def _review_text(el: Selector) -> str:
    """Review text without the "..." of the Read more toggle, joined where the toggle was."""
    found = el.css("div.text")
    if not found:
        return ""
    node = deepcopy(found[0].root)
    for toggle in node.xpath(f".//span[{_has_class(READ_MORE_TOGGLE_CLASS)}]"):
        for child in list(toggle):
            toggle.remove(child)
        toggle.text = _TOGGLE_MARK
    before, mark, after = "".join(node.itertext()).partition(_TOGGLE_MARK)
    text = f"{before.rstrip()} {after.lstrip()}" if mark else before
    return clean_text(text.replace(_TOGGLE_MARK, ""))
