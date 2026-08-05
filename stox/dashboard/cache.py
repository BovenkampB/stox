"""Kleine in-memory TTL-cache rond koersdata, zodat het dashboard snel blijft
en yfinance niet bij elke pageload wordt geraakt."""
from __future__ import annotations

import time

from ..data.prices import fetch_history, PriceData

_TTL_SECONDS = 15 * 60
_cache: dict[str, tuple[float, PriceData]] = {}


def get_history(symbol: str, period: str = "6mo") -> PriceData:
    key = f"{symbol}:{period}"
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _TTL_SECONDS:
        return hit[1]
    data = fetch_history(symbol, period=period)
    _cache[key] = (now, data)
    return data
