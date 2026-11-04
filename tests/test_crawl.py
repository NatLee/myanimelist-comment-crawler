"""Whole runs of the three scripts against a local fake site (no internet needed)."""

from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys

import pytest

from tests.conftest import ROOT
from tests.fake_site import FakeSite

FMAB_PATH = "/anime/5114/Fullmetal_Alchemist__Brotherhood"
REVIEWS_QUERY = "/reviews?sort=newest&filter_check=&filter_hide=&preliminary=on&spoiler=on&p="
EDGE_REVIEWS = "/v1/anime/5114/reviews?page={page}&preliminary=true&spoilers=true"


@pytest.fixture
def site():
    fake = FakeSite()
    yield fake
    fake.close()


@pytest.fixture
def workdir(tmp_path, site):
    (tmp_path / "setting.ini").write_text(site.setting_ini(), encoding="utf-8")
    return tmp_path


def run(workdir, script: str, *args: str) -> subprocess.CompletedProcess:
    result = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=workdir, capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    assert "Traceback" not in result.stderr, result.stderr
    assert "DeprecationWarning" not in result.stderr, result.stderr  # keep up with Scrapy's API changes
    return result


def query(workdir, sql: str) -> list[tuple]:
    with sqlite3.connect(workdir / "anime.db") as conn:
        return conn.execute(sql).fetchall()


def test_html_source_end_to_end(site, workdir):
    site.add("/robots.txt", "User-agent: *\nAllow: /\n")
    site.add_fixture("/topanime.php?limit=0", "html/topanime_limit0.html")
    site.add_fixture("/topanime.php?limit=50", "html/topanime_empty.html")
    site.add_fixture(FMAB_PATH, "html/anime_5114.html")  # the other two titles answer 404
    site.add_fixture(FMAB_PATH + REVIEWS_QUERY + "1", "html/reviews_5114_p1.html")
    site.add_fixture(FMAB_PATH + REVIEWS_QUERY + "2", "html/reviews_5114_p2.html")

    info = run(workdir, "info_spider.py", "--source", "html", "--delay", "0")
    assert info.returncode == 0
    assert "1 saved" in info.stderr and "HTTP 404" in info.stderr
    titles = [path for path in site.requests if path.startswith("/anime/")]
    assert titles == ["/anime/52991/Sousou_no_Frieren", FMAB_PATH,  # ranking order, then the next ranking page
                      "/anime/61316/Re_Zero_kara_Hajimeru_Isekai_Seikatsu_4th_Season"]
    assert site.requests.index(titles[-1]) < site.requests.index("/topanime.php?limit=50")
    assert query(workdir, "SELECT workId, source, members FROM animeList") == [(5114, "Manga", "3,752,360")]
    saved = json.loads((workdir / "tmp/info/005114.json").read_text(encoding="utf-8"))
    assert saved["engName"] == "Fullmetal Alchemist: Brotherhood"

    reviews = run(workdir, "review_spider.py", "--source", "html", "--delay", "0")
    assert reviews.returncode == 0
    assert query(workdir, "SELECT COUNT(*) FROM reviews") == [(4,)]
    # Regression: after the last page the old spider still asked for the next (empty) page.
    assert FMAB_PATH + REVIEWS_QUERY + "3" not in site.requests
    assert query(workdir, "SELECT lastPage, done FROM crawlProgress") == [(2, 1)]

    export = run(workdir, "db_to_kaggle.py")
    assert export.returncode == 0
    with open(workdir / "reviews.csv", encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 4


def test_robots_txt_that_blocks_scrapy_stops_the_crawl_with_a_hint(site, workdir):
    site.add("/robots.txt", "User-agent: Scrapy\nDisallow: /\n")  # what myanimelist.net says (2026-11-04)
    site.add_fixture("/topanime.php?limit=0", "html/topanime_limit0.html")

    result = run(workdir, "info_spider.py", "--source", "html", "--delay", "0")
    assert result.returncode == 1
    assert "robots.txt does not allow" in result.stderr and "--source jikan-edge" in result.stderr
    assert site.requests == ["/robots.txt"]


def test_jikan_edge_is_the_default_source(site, workdir):
    # Owner's decision of 2026-11-04: html stays available, but MAL's robots.txt blocks it.
    site.add_fixture("/v1/anime/5114", "jikan_edge/anime_5114.json")
    result = run(workdir, "info_spider.py", "--ids", "5114", "--delay", "0")
    assert result.returncode == 0 and "source jikan-edge" in result.stderr
    assert site.requests == ["/v1/anime/5114"]
    assert "(default: jikan-edge)" in run(workdir, "info_spider.py", "--help").stdout


def test_jikan_edge_source_end_to_end_with_resume(site, workdir):
    site.add("/robots.txt", "User-agent: *\nDisallow: /v1/\n")  # aimed at search engines; see jikan_edge.py
    site.add_fixture("/v1/anime/5114", "jikan_edge/anime_5114.json")
    site.add_fixture(EDGE_REVIEWS.format(page=1), "jikan_edge/reviews_5114_p1.json")
    site.add_fixture(EDGE_REVIEWS.format(page=2), "jikan_edge/reviews_5114_p2.json")

    assert run(workdir, "info_spider.py", "--source", "jikan-edge", "--ids", "5114", "--delay", "0").returncode == 0
    assert query(workdir, "SELECT workId, allRank FROM animeList") == [(5114, "#2")]

    first = run(workdir, "review_spider.py", "--source", "jikan-edge", "--delay", "0")
    assert first.returncode == 0 and "(last page)" in first.stderr
    assert query(workdir, "SELECT COUNT(*), MIN(workName) FROM reviews") == [(4, "Fullmetal_Alchemist__Brotherhood")]

    asked = len(site.requests)
    again = run(workdir, "review_spider.py", "--source", "jikan-edge", "--delay", "0", "--resume")
    assert "1 of 1 titles already finished" in again.stderr
    assert len(site.requests) == asked  # nothing fetched again


def test_rate_limit_is_retried_after_the_servers_pause(site, workdir):
    site.add("/v1/anime/5114", '{"error": {"code": "RATE_LIMITED"}}', status=429, headers={"Retry-After": "1"})
    site.add_fixture("/v1/anime/5114", "jikan_edge/anime_5114.json")

    result = run(workdir, "info_spider.py", "--source", "jikan-edge", "--ids", "5114", "--delay", "0")
    assert "HTTP 429" in result.stderr and "waiting 1 s" in result.stderr
    assert site.requests.count("/v1/anime/5114") == 2
    assert query(workdir, "SELECT COUNT(*) FROM animeList") == [(1,)]


def test_scrapy_runspider_command_still_works(site, workdir):
    site.add_fixture("/v1/anime/5114", "jikan_edge/anime_5114.json")
    result = subprocess.run(  # no -a source=...: the old command picks up the new default too
        [sys.executable, "-m", "scrapy", "runspider", str(ROOT / "info_spider.py"), "--nolog",
         "-a", "ids=5114", "-s", "DOWNLOAD_DELAY=0"],
        cwd=workdir, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    assert "DeprecationWarning" not in result.stderr, result.stderr
    assert query(workdir, "SELECT workId FROM animeList") == [(5114,)]


def test_reviews_before_info_explains_what_to_run(site, workdir):
    result = run(workdir, "review_spider.py", "--source", "jikan-edge")
    assert result.returncode == 1
    assert "Run info_spider first" in result.stderr
    assert site.requests == []


@pytest.mark.parametrize(("args", "delay"), [
    (["--source", "html"], "4.0"),  # the 2023 review spider's pace
    (["--source", "jikan-edge"], "2.0"),  # half of Jikan-Edge's published limit
    (["--source", "html", "--delay", "0.5"], "0.5"),
])
def test_each_source_keeps_its_own_pace_unless_told_otherwise(workdir, args, delay):
    result = run(workdir, "review_spider.py", *args, "--verbose")
    assert f"'DOWNLOAD_DELAY': {delay}" in result.stderr


def test_unknown_source_is_rejected(workdir):
    result = run(workdir, "info_spider.py", "--source", "nope")
    assert result.returncode == 2 and "invalid choice" in result.stderr
