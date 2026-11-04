"""Command-line options for ``info_spider.py``, ``review_spider.py`` and ``db_to_kaggle.py``.

``scrapy runspider info_spider.py -a source=jikan-edge`` keeps working; running the scripts with
``python`` adds ``--help``, readable progress output and option checking on top of the same spiders.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings as ScrapySettings

from .config import CONFIG_FILE, load_settings
from .export import export_to_csv
from .sources import DEFAULT_SOURCE, SOURCES
from .spiders import InfoSpider, ReviewSpider, parse_ids


def configure_logging(verbose: bool) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO",
               format="<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> {message}")


def _ids(value: str) -> str:
    try:
        parse_ids(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None
    return value


def _config(value: str) -> str:
    if value != CONFIG_FILE and not Path(value).is_file():
        raise argparse.ArgumentTypeError(f"settings file {value!r} not found")
    return value


def crawl_parser(spider_cls: type[InfoSpider] | type[ReviewSpider]) -> argparse.ArgumentParser:
    reviews = issubclass(spider_cls, ReviewSpider)
    script = "review_spider.py" if reviews else "info_spider.py"
    what = ("reviews of the titles saved by info_spider.py" if reviews
            else "anime information from the all-time ranking (or only --ids)")
    sources = "\n".join(f"  {name:<11} {cls.description}" for name, cls in SOURCES.items())
    example_ids = "11979" if reviews else "5114,11979"
    parser = argparse.ArgumentParser(
        prog=f"python {script}",
        description=f"Crawl {what} into the SQLite database named in setting.ini.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"sources:\n{sources}\n\nexample:\n  python {script} --ids {example_ids}",
    )
    parser.add_argument("--source", choices=list(SOURCES), default=DEFAULT_SOURCE,
                        help=f"where to read from (default: {DEFAULT_SOURCE})")
    parser.add_argument("--ids", type=_ids, metavar="ID,ID",
                        help="only these MyAnimeList IDs, e.g. 5114,11979 (default: all)")
    if reviews:
        parser.add_argument("--resume", action="store_true",
                            help="skip titles finished in an earlier run and continue unfinished ones")
    parser.add_argument("--delay", type=float, metavar="SECONDS",
                        help="seconds between requests (default: the source's polite pace)")
    parser.add_argument("--config", type=_config, default=CONFIG_FILE,
                        help=f"settings file (default: {CONFIG_FILE})")
    parser.add_argument("-v", "--verbose", action="store_true", help="also show Scrapy's own log")
    return parser


def run_crawl(spider_cls: type[InfoSpider] | type[ReviewSpider], argv: list[str] | None = None) -> None:
    args = crawl_parser(spider_cls).parse_args(argv)
    configure_logging(args.verbose)
    settings = ScrapySettings()
    settings.set("LOG_LEVEL", "INFO" if args.verbose else "WARNING", priority="cmdline")
    if args.delay is not None:
        settings.set("DOWNLOAD_DELAY", args.delay, priority="cmdline")
    spider_args = {"source": args.source, "ids": args.ids, "config": args.config}
    if issubclass(spider_cls, ReviewSpider):
        spider_args["resume"] = args.resume
    process = CrawlerProcess(settings)
    crawler = process.create_crawler(spider_cls)
    process.crawl(crawler, **spider_args)
    process.start()
    if crawler.spider is not None and crawler.spider.problem:
        raise SystemExit(1)  # the reason was already logged


def run_export(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python db_to_kaggle.py",
        description="Export the database to anime_list.csv and reviews.csv (the Kaggle dataset layout).")
    parser.add_argument("--config", type=_config, default=CONFIG_FILE, help=f"settings file (default: {CONFIG_FILE})")
    parser.add_argument("--out-dir", default=".", help="folder for the CSV files (default: current folder)")
    args = parser.parse_args(argv)
    configure_logging(verbose=False)
    database = load_settings(args.config).database_name
    try:
        paths = export_to_csv(database, args.out_dir)
    except FileNotFoundError as error:
        logger.error(str(error))
        raise SystemExit(1) from None
    for path in paths:
        logger.info(f"wrote {path}")
