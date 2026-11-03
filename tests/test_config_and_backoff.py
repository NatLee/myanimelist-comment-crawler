from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scrapy.http import Response
from scrapy.settings import Settings as ScrapySettings

from malcrawler.config import Settings, load_settings
from malcrawler.middlewares import BackoffRetryMiddleware, retry_after_seconds
from malcrawler.spiders import parse_ids

SETTING_INI_2023 = ("[SETTING]\nRankIncrement = 50\n"
                    "[PATH]\nTempWorkInfoFolder = tmp/info\n"
                    "[DATABASE]\nDatabaseName = x.db\n")


def test_a_2023_setting_ini_still_loads(tmp_path):
    path = tmp_path / "setting.ini"
    path.write_text(SETTING_INI_2023, encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.database_name == "x.db"
    assert loaded.temp_info_folder == Path("tmp/info")
    assert loaded.jikan_edge_base_url == Settings().jikan_edge_base_url


def test_missing_setting_ini_uses_defaults(tmp_path):
    assert load_settings(tmp_path / "missing.ini") == Settings()


def test_repo_setting_ini_matches_the_defaults():
    assert load_settings(Path(__file__).resolve().parents[1] / "setting.ini") == Settings()


@pytest.mark.parametrize(("raw", "expected"), [("5114", [5114]), ("5114, 11979", [5114, 11979]), (None, None)])
def test_parse_ids(raw, expected):
    assert parse_ids(raw) == expected


def test_parse_ids_rejects_words():
    with pytest.raises(ValueError, match="comma-separated numbers"):
        parse_ids("fmab")


@pytest.mark.parametrize(("header", "expected"), [("30", 30.0), (b"10", 10.0), ("soon", None), (None, None)])
def test_retry_after_seconds(header, expected):
    assert retry_after_seconds(header) == expected


def test_retry_after_http_date():
    now = datetime.datetime(2026, 11, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
    assert retry_after_seconds("Wed, 04 Nov 2026 12:01:00 GMT", now=now) == 60.0


def middleware(**settings):
    scrapy_settings = ScrapySettings({"RETRY_HTTP_CODES": [429, 503], "RETRY_TIMES": 4, **settings})
    return BackoffRetryMiddleware(SimpleNamespace(settings=scrapy_settings, spider=None))


def test_backoff_doubles_and_is_capped():
    mw = middleware(BACKOFF_BASE_SECONDS=5, BACKOFF_MAX_SECONDS=30)
    response = Response("https://example.test", status=429)
    assert [mw.delay_for(response, attempt) for attempt in (1, 2, 3, 4)] == [5, 10, 20, 30]


def test_server_retry_after_wins_over_backoff():
    mw = middleware(BACKOFF_BASE_SECONDS=5)
    response = Response("https://example.test", status=429, headers={"Retry-After": "60"})
    assert mw.delay_for(response, 1) == 60
