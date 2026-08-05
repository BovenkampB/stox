"""Koersdata ophalen via yfinance (gratis)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf


@dataclass
class PriceData:
    symbol: str
    history: pd.DataFrame  # kolommen: Open, High, Low, Close, Volume (index = datum)

    @property
    def last_close(self) -> float:
        return float(self.history["Close"].iloc[-1])

    @property
    def is_empty(self) -> bool:
        return self.history.empty


def fetch_history(symbol: str, period: str = "6mo", interval: str = "1d") -> PriceData:
    """Haal historische koersen op.

    period: bijv. '1mo', '3mo', '6mo', '1y', '2y'
    interval: bijv. '1d', '1h'
    """
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, interval=interval, auto_adjust=True)
    # Verwijder tijdzone-info voor eenvoudige opslag/vergelijking.
    if not hist.empty and hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)
    return PriceData(symbol=symbol, history=hist)


def current_price(symbol: str) -> float | None:
    """Meest recente slotkoers (of None als onbekend)."""
    data = fetch_history(symbol, period="5d", interval="1d")
    if data.is_empty:
        return None
    return data.last_close
