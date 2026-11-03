"""Settings from ``setting.ini``.

The file and its first three sections are the same as in 2023, so old ``setting.ini`` files keep
working. Every key has a default, so sections added later are optional.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

import scrapy

CONFIG_FILE = "setting.ini"
PROJECT_URL = "https://github.com/NatLee/myanimelist-comment-crawler"

# Say who we are, including that this is a Scrapy crawler, so site owners' robots.txt rules for
# Scrapy apply to us exactly as they intend.
USER_AGENT = f"myanimelist-comment-crawler (+{PROJECT_URL}) Scrapy/{scrapy.__version__}"


@dataclass(frozen=True)
class Settings:
    rank_increment: int = 50
    temp_info_folder: Path = Path("tmp/info")
    database_name: str = "anime.db"
    mal_base_url: str = "https://myanimelist.net"
    jikan_edge_base_url: str = "https://jikan.lucashdo.com/v1"


def load_settings(path: str | Path = CONFIG_FILE) -> Settings:
    """Read ``path``; a missing file or key falls back to the defaults above."""
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    default = Settings()
    return Settings(
        rank_increment=parser.getint("SETTING", "RankIncrement", fallback=default.rank_increment),
        temp_info_folder=Path(parser.get("PATH", "TempWorkInfoFolder", fallback=str(default.temp_info_folder))),
        database_name=parser.get("DATABASE", "DatabaseName", fallback=default.database_name),
        mal_base_url=parser.get("MAL", "BaseUrl", fallback=default.mal_base_url).rstrip("/"),
        jikan_edge_base_url=parser.get("JIKAN_EDGE", "BaseUrl", fallback=default.jikan_edge_base_url).rstrip("/"),
    )
