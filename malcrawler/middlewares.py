"""Retry rate-limited and failing requests after a pause instead of immediately.

Scrapy's own RetryMiddleware re-sends a 429 or 503 right away, which only hits the limit again.
This middleware sits in front of it (priority 560 > 550, so it sees responses first), waits for the
server's Retry-After or an exponential backoff, then hands Scrapy the retry request. It uses the
same settings (RETRY_HTTP_CODES, RETRY_TIMES) and the same retry counter as Scrapy's middleware, so
the built-in one only gives up when this one has already given up.

Settings: BACKOFF_BASE_SECONDS (first wait, default 10) and BACKOFF_MAX_SECONDS (cap, default 600).
The wait pauses the whole crawl because the spiders run with CONCURRENT_REQUESTS = 1.
"""

from __future__ import annotations

import asyncio
import datetime
from email.utils import parsedate_to_datetime

from loguru import logger
from scrapy import Request
from scrapy.crawler import Crawler
from scrapy.downloadermiddlewares.retry import get_retry_request
from scrapy.http import Response

DEFAULT_BACKOFF_BASE_SECONDS = 10.0
DEFAULT_BACKOFF_MAX_SECONDS = 600.0


def retry_after_seconds(value: str | bytes | None, now: datetime.datetime | None = None) -> float | None:
    """Seconds to wait from a Retry-After header (a number of seconds or an HTTP date)."""
    if not value:
        return None
    text = value.decode("latin-1") if isinstance(value, bytes) else value
    text = text.strip()
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return max(0.0, (when - now).total_seconds())


class BackoffRetryMiddleware:
    def __init__(self, crawler: Crawler):
        settings = crawler.settings
        self.crawler = crawler
        self.retry_http_codes = {int(code) for code in settings.getlist("RETRY_HTTP_CODES")}
        self.max_retry_times = settings.getint("RETRY_TIMES")
        self.base = settings.getfloat("BACKOFF_BASE_SECONDS", DEFAULT_BACKOFF_BASE_SECONDS)
        self.cap = settings.getfloat("BACKOFF_MAX_SECONDS", DEFAULT_BACKOFF_MAX_SECONDS)

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> BackoffRetryMiddleware:
        return cls(crawler)

    def delay_for(self, response: Response, attempt: int) -> float:
        server = retry_after_seconds(response.headers.get("Retry-After"))
        wait = server if server is not None else self.base * 2 ** (attempt - 1)
        return min(wait, self.cap)

    async def process_response(self, request: Request, response: Response, spider=None) -> Request | Response:
        if request.meta.get("dont_retry") or response.status not in self.retry_http_codes:
            return response
        attempt = request.meta.get("retry_times", 0) + 1
        retry = get_retry_request(request, spider=self.crawler.spider, reason=f"HTTP {response.status}",
                                  max_retry_times=self.max_retry_times)
        if retry is None:
            request.meta["dont_retry"] = True  # already gave up; Scrapy's RetryMiddleware should not retry again
            return response
        delay = self.delay_for(response, attempt)
        logger.warning(f"HTTP {response.status} from {request.url}; waiting {delay:.0f} s "
                       f"before retry {attempt}/{self.max_retry_times}")
        await asyncio.sleep(delay)
        return retry
