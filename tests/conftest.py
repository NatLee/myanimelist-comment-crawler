from __future__ import annotations

from pathlib import Path

import pytest

from malcrawler.config import Settings
from malcrawler.sources import WorkRef

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

FMAB = WorkRef(5114, "https://myanimelist.net/anime/5114/Fullmetal_Alchemist__Brotherhood", "64")


def read_fixture(relative: str) -> str:
    return (FIXTURES / relative).read_text(encoding="utf-8")


@pytest.fixture
def settings() -> Settings:
    return Settings()
