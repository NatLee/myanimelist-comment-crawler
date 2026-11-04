"""The two spiders: anime information (``info_spider``) and reviews (``review_spider``).

Both take the same spider arguments (``scrapy runspider ... -a name=value`` or the script options):

- ``source``: where to read from, ``jikan-edge`` (default) or ``html``; see ``malcrawler.sources``.
- ``ids``: comma-separated MyAnimeList IDs to crawl instead of everything, e.g. ``5114,11979``.
- ``config``: path of the settings file (default ``setting.ini``).
- ``resume`` (reviews only): skip titles finished in an earlier run and continue unfinished ones.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, ClassVar

import scrapy
from loguru import logger
from scrapy.crawler import Crawler
from scrapy.exceptions import CloseSpider, IgnoreRequest
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.python.failure import Failure

from .config import CONFIG_FILE, USER_AGENT, load_settings
from .sources import DEFAULT_SOURCE, SourceError, WorkRef, make_source
from .storage import AnimeAccess, Database

# Stop after this many titles in a row failed: the network or the site is probably down.
MAX_CONSECUTIVE_FAILURES = 5

COMMON_SETTINGS: dict[str, Any] = {
    "ROBOTSTXT_OBEY": True,  # sources that are APIs opt out per request (Source.obey_robots_txt)
    "USER_AGENT": USER_AGENT,
    "CONCURRENT_REQUESTS": 1,  # one request at a time; backoff waits pause the whole crawl
    "SCHEDULER_MEMORY_QUEUE": "scrapy.squeues.FifoMemoryQueue",  # titles in ranking order, not reversed
    "COOKIES_ENABLED": False,
    "RETRY_TIMES": 4,
    "DOWNLOADER_MIDDLEWARES": {"malcrawler.middlewares.BackoffRetryMiddleware": 560},
}


def parse_ids(ids: str | None) -> list[int] | None:
    if not ids:
        return None
    try:
        return [int(part) for part in str(ids).replace(" ", "").split(",") if part]
    except ValueError:
        raise ValueError(f"ids must be comma-separated numbers, e.g. 5114,11979 (got {ids!r})") from None


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class _MalSpider(scrapy.Spider):
    kind: ClassVar[str]
    custom_settings = COMMON_SETTINGS

    def __init__(self, source: str = DEFAULT_SOURCE, ids: str | None = None, config: str = CONFIG_FILE,
                 *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.config = load_settings(config)
        self.source = make_source(source, self.config)
        self.ids = parse_ids(ids)
        self.db = Database(self.config.database_name)
        self.store = AnimeAccess(self.db)
        self.failed = 0
        self.problem: str | None = None  # why the crawl had to stop early; the scripts then exit with 1
        logger.info(f"{self.name}: source {self.source.name} ({self.source.description}), "
                    f"database {self.config.database_name}")

    @classmethod
    def from_crawler(cls, crawler: Crawler, *args: Any, **kwargs: Any) -> _MalSpider:
        spider = super().from_crawler(crawler, *args, **kwargs)
        # Each source has its own polite pace. "spider" priority loses to a DOWNLOAD_DELAY given on
        # the command line (-s / --delay), so users can still slow down or speed up.
        crawler.settings.set("DOWNLOAD_DELAY", spider.source.download_delay[cls.kind], priority="spider")
        return spider

    def request(self, url: str, callback: Any, **kwargs: Any) -> scrapy.Request:
        meta = {"dont_obey_robotstxt": not self.source.obey_robots_txt}
        return scrapy.Request(url, callback=callback, errback=self.on_error, meta=meta, **kwargs)

    def stop(self, reason: str, message: str) -> CloseSpider:
        """Record and log why the crawl cannot go on; returns the exception that ends it."""
        self.problem = reason
        logger.error(f"Stopping: {message}")
        return CloseSpider(reason)

    def explain_failure(self, failure: Failure) -> str:
        if failure.check(IgnoreRequest) and not failure.check(HttpError):
            message = f"Scrapy refused to send {failure.request.url} ({failure.value})."
            if self.source.obey_robots_txt:
                message += (" The site's robots.txt does not allow this crawler there."
                            " Try another source, e.g. --source jikan-edge (see README).")
            raise self.stop("request_refused", message)
        if failure.check(HttpError):
            return f"HTTP {failure.value.response.status}"
        return f"{type(failure.value).__name__}: {failure.value}"

    def on_error(self, failure: Failure) -> Iterator[Any]:
        """Errback: the request failed (network, HTTP status, refused by robots.txt)."""
        url = failure.request.url if hasattr(failure, "request") else "?"
        return self.request_failed(url, self.explain_failure(failure))

    def request_failed(self, url: str, reason: str) -> Iterator[Any]:
        """A page could not be fetched or understood; log it and carry on with the rest."""
        self.failed += 1
        logger.error(f"Failed {url}: {reason}")
        return iter(())

    def closed(self, reason: str) -> None:
        self.db.close()


class InfoSpider(_MalSpider):
    """Anime information: the whole ranking, or only ``ids``. Writes ``animeList`` and tmp JSON files."""

    name = "info_spider"
    kind = "info"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.saved = 0
        self.skipped = 0

    async def start(self) -> AsyncIterator[scrapy.Request]:
        if self.ids:
            for work_id in self.ids:
                request = self.info_request(WorkRef(work_id))
                if request:
                    yield request
        else:
            yield self.ranking_request(0)

    def json_path(self, work_id: int | str) -> Path:
        return self.config.temp_info_folder / f"{str(work_id).zfill(6)}.json"

    def ranking_request(self, page_index: int) -> scrapy.Request:
        # Lower priority than the title pages, so each ranking page's titles are saved first.
        return self.request(self.source.ranking_url(page_index), self.parse_ranking, priority=-1,
                            cb_kwargs={"page_index": page_index})

    def info_request(self, work: WorkRef) -> scrapy.Request | None:
        if self.json_path(work.work_id).exists():  # saved in an earlier run
            self.skipped += 1
            logger.debug(f"[{work.work_id}] JSON file exists, skipping")
            return None
        return self.request(self.source.info_url(work), self.parse_info)

    def parse_ranking(self, response: scrapy.http.Response, page_index: int) -> Iterator[scrapy.Request]:
        try:
            page = self.source.parse_ranking(response.text, response.url)
        except SourceError as error:
            raise self.stop("unreadable_ranking", f"cannot read ranking page {page_index + 1}: {error}") from error
        logger.info(f"Ranking page {page_index + 1}: {len(page.works)} titles")
        for work in page.works:
            request = self.info_request(work)
            if request:
                yield request
        if page.has_next and page.works:
            yield self.ranking_request(page_index + 1)

    def parse_info(self, response: scrapy.http.Response) -> Iterator[Any]:
        try:
            data = self.source.parse_info(response.text, response.url)
        except SourceError as error:
            yield from self.request_failed(response.url, str(error))
            return
        path = self.json_path(data["workId"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        self.store.push_work_infos_to_database([data])
        self.saved += 1
        logger.info(f"[{self.saved}] saved {data['workId']} {data['engName'] or data['jpName']}")
        yield data

    def closed(self, reason: str) -> None:
        logger.info(f"info_spider finished ({reason}): {self.saved} saved, {self.skipped} already saved, "
                    f"{self.failed} failed")
        super().closed(reason)


class ReviewSpider(_MalSpider):
    """Reviews of every title in ``animeList`` (or only ``ids``), one title at a time, page by page."""

    name = "review_spider"
    kind = "reviews"

    def __init__(self, *args: Any, resume: str | bool | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.resume = is_true(resume)
        self.queue: deque[tuple[WorkRef, int]] = deque()
        self.total = 0
        self.position = 0
        self.reviews_saved = 0
        self.consecutive_failures = 0

    async def start(self) -> AsyncIterator[scrapy.Request]:
        works = self.store.get_works(self.ids)
        if self.ids:
            missing = sorted(set(self.ids) - {work.work_id for work in works})
            if missing:
                logger.warning(f"Not in {self.config.database_name} yet, run info_spider for them first: "
                               + ",".join(map(str, missing)))
        if not works:
            self.stop("nothing_to_crawl", f"no titles to crawl in {self.config.database_name}. "
                      "Run info_spider first (e.g. python info_spider.py --ids 5114).")
            return
        progress = self.store.get_progress(self.source.name) if self.resume else {}
        for work in works:
            state = progress.get(work.work_id)
            if state and state.done:
                continue
            # An unfinished title restarts at its last saved page: reviews may have shifted since.
            self.queue.append((work, state.last_page if state else 1))
        self.total = len(works)
        self.position = self.total - len(self.queue)
        if self.position:
            logger.info(f"Resuming: {self.position} of {self.total} titles already finished")
        request = self.next_work_request()
        if request:
            yield request

    def page_request(self, work: WorkRef, page: int) -> scrapy.Request:
        return self.request(self.source.reviews_url(work, page), self.parse_reviews,
                            cb_kwargs={"work": work, "page": page})

    def next_work_request(self) -> scrapy.Request | None:
        if not self.queue:
            return None
        work, page = self.queue.popleft()
        self.position += 1
        return self.page_request(work, page)

    def parse_reviews(self, response: scrapy.http.Response, work: WorkRef, page: int) -> Iterator[Any]:
        try:
            result = self.source.parse_reviews(response.text, response.url, work)
        except SourceError as error:
            yield from self.request_failed(response.url, str(error))
            return
        self.store.push_reviews_to_database(result.reviews)
        done = not (result.has_next and result.reviews)
        self.store.save_progress(work.work_id, self.source.name, page, done)
        self.reviews_saved += len(result.reviews)
        self.consecutive_failures = 0
        logger.info(f"[{self.position}/{self.total}] {work.work_id} {work.name}: page {page}, "
                    f"{len(result.reviews)} reviews" + (" (last page)" if done else ""))
        yield from result.reviews
        following = self.page_request(work, page + 1) if not done else self.next_work_request()
        if following:
            yield following

    def request_failed(self, url: str, reason: str) -> Iterator[Any]:
        """Give up on the current title and move on to the next one."""
        yield from super().request_failed(url, reason)
        self.consecutive_failures += 1
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            raise self.stop("too_many_failures", f"{MAX_CONSECUTIVE_FAILURES} titles in a row failed. "
                            "Check the network or the source, then run again with --resume.")
        following = self.next_work_request()  # skip this title, keep going
        if following:
            yield following

    def closed(self, reason: str) -> None:
        logger.info(f"review_spider finished ({reason}): {self.reviews_saved} reviews saved from "
                    f"{self.position} of {self.total} titles, {self.failed} failed requests")
        super().closed(reason)
