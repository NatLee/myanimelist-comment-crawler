"""Crawl the reviews of the titles already in the database (run info_spider.py first).

    python review_spider.py --help
    scrapy runspider review_spider.py --nolog -a source=jikan-edge -a resume=1
"""

from malcrawler import cli, spiders


class ReviewSpider(spiders.ReviewSpider):
    """Declared in this file so that ``scrapy runspider review_spider.py`` finds it."""


if __name__ == "__main__":
    cli.run_crawl(ReviewSpider)
