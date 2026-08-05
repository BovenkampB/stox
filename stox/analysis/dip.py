"""Dip-detector: hoe ver staat een fonds onder zijn recente top?

Bedoeld voor brede indexfondsen/ETF's waarin je periodiek inlegt: een dip is
een kans om die maand wat extra te kopen. We meten de terugval (drawdown) ten
opzichte van de hoogste slotkoers in een recente periode.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import DipConfig
from ..data.prices import fetch_history


@dataclass
class DipStatus:
    symbol: str
    name: str
    last_close: float
    recent_high: float
    high_date: str
    drawdown_pct: float   # ≤ 0: hoeveel procent onder de recente top
    from_high_days: int   # hoeveel handelsdagen geleden was die top
    rsi14: float
    level: str            # 'geen' | 'licht' | 'matig' | 'stevig'
    is_dip: bool

    @property
    def depth_pct(self) -> float:
        """Positieve diepte van de dip (spiegelbeeld van drawdown)."""
        return abs(self.drawdown_pct)


def _rsi(close, window: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1]
    return float(value) if value == value else 50.0  # NaN-check


def assess_dip(symbol: str, name: str, cfg: DipConfig) -> DipStatus | None:
    """Bepaal de dip-status van één fonds; None bij onvoldoende data."""
    price = fetch_history(symbol, period="6mo")
    df = price.history
    if df.empty or len(df) < 20:
        return None

    close = df["Close"]
    last = float(close.iloc[-1])

    window = close.tail(cfg.lookback_days)
    recent_high = float(window.max())
    high_idx = window.idxmax()
    high_date = high_idx.strftime("%Y-%m-%d")
    from_high_days = int((window.index[-1] - high_idx).days)

    drawdown = (last - recent_high) / recent_high * 100 if recent_high else 0.0
    depth = -drawdown

    if depth >= cfg.significant_pct:
        level = "stevig"
    elif depth >= cfg.moderate_pct:
        level = "matig"
    elif depth >= cfg.mild_pct:
        level = "licht"
    else:
        level = "geen"

    return DipStatus(
        symbol=symbol,
        name=name,
        last_close=round(last, 2),
        recent_high=round(recent_high, 2),
        high_date=high_date,
        drawdown_pct=round(drawdown, 2),
        from_high_days=from_high_days,
        rsi14=round(_rsi(close), 1),
        level=level,
        is_dip=level != "geen",
    )


def assess_all(cfg: DipConfig, name_lookup: dict[str, str]) -> list[DipStatus]:
    results: list[DipStatus] = []
    for sym in cfg.symbols:
        status = assess_dip(sym, name_lookup.get(sym, sym), cfg)
        if status is not None:
            results.append(status)
    return results
