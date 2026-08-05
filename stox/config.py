"""Configuratie laden: watchlist, instellingen en geheimen."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Projectwortel = de map boven het 'stox' package.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str
    category: str = "Overig"
    region: str = ""


@dataclass(frozen=True)
class Settings:
    tickers: list[Ticker]
    default_horizon_days: int
    model: str
    anthropic_api_key: str | None
    db_path: Path


def load_settings(watchlist_path: Path | None = None) -> Settings:
    """Lees watchlist.yaml + omgevingsvariabelen in één Settings-object."""
    path = watchlist_path or (CONFIG_DIR / "watchlist.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    tickers = [
        Ticker(
            symbol=t["symbol"],
            name=t.get("name", t["symbol"]),
            category=t.get("category", "Overig"),
            region=t.get("region", ""),
        )
        for t in raw.get("tickers", [])
    ]

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    return Settings(
        tickers=tickers,
        default_horizon_days=int(raw.get("default_horizon_days", 14)),
        model=os.environ.get("STOX_MODEL", "claude-sonnet-5"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        db_path=DATA_DIR / "stox.db",
    )
