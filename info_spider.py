"""Crawl anime information into the database.

    python info_spider.py --help
    scrapy runspider info_spider.py --nolog -a source=jikan-edge -a ids=5114
"""

from malcrawler import cli, spiders


class InfoSpider(spiders.InfoSpider):
    """Declared in this file so that ``scrapy runspider info_spider.py`` finds it."""


if __name__ == "__main__":
    cli.run_crawl(InfoSpider)
