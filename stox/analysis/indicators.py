"""Technische analyse van de koersgrafiek.

Berekent indicatoren die de AI-redenatie meekrijgt zodat de grafiek
nauwkeurig wordt meegewogen: trend, momentum (RSI/MACD), volatiliteit,
en support/resistance-niveaus.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from ..data.prices import PriceData


@dataclass
class TechnicalSummary:
    symbol: str
    last_close: float
    change_1w_pct: float
    change_1m_pct: float
    change_3m_pct: float
    sma20: float
    sma50: float
    trend: str            # 'stijgend', 'dalend', 'zijwaarts'
    rsi14: float
    rsi_signal: str       # 'overbought', 'oversold', 'neutraal'
    macd: float
    macd_signal_line: float
    macd_state: str       # 'bullish', 'bearish'
    volatility_pct: float  # jaarlijkse volatiliteit, indicatief
    support: float
    resistance: float
    volume_trend: str      # 'toenemend', 'afnemend', 'stabiel'

    def to_dict(self) -> dict:
        return asdict(self)


def _rsi(close: pd.Series, window: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1]
    return float(value) if pd.notna(value) else 50.0


def _macd(close: pd.Series) -> tuple[float, float]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(signal.iloc[-1])


def _pct_change(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return 0.0
    old = close.iloc[-days - 1]
    new = close.iloc[-1]
    if old == 0:
        return 0.0
    return float((new - old) / old * 100)


def analyse(price: PriceData) -> TechnicalSummary | None:
    """Bereken een technische samenvatting; None bij te weinig data."""
    df = price.history
    if df.empty or len(df) < 30:
        return None

    close = df["Close"]
    last = float(close.iloc[-1])

    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20

    if last > sma20 > sma50:
        trend = "stijgend"
    elif last < sma20 < sma50:
        trend = "dalend"
    else:
        trend = "zijwaarts"

    rsi = _rsi(close)
    if rsi >= 70:
        rsi_signal = "overbought"
    elif rsi <= 30:
        rsi_signal = "oversold"
    else:
        rsi_signal = "neutraal"

    macd, macd_signal = _macd(close)
    macd_state = "bullish" if macd > macd_signal else "bearish"

    daily_returns = close.pct_change().dropna()
    volatility = float(daily_returns.std() * (252 ** 0.5) * 100) if not daily_returns.empty else 0.0

    recent = close.tail(60)
    support = float(recent.min())
    resistance = float(recent.max())

    vol = df["Volume"]
    vol_recent = float(vol.tail(10).mean())
    vol_prev = float(vol.tail(40).head(30).mean()) if len(vol) >= 40 else vol_recent
    if vol_recent > vol_prev * 1.15:
        volume_trend = "toenemend"
    elif vol_recent < vol_prev * 0.85:
        volume_trend = "afnemend"
    else:
        volume_trend = "stabiel"

    return TechnicalSummary(
        symbol=price.symbol,
        last_close=round(last, 2),
        change_1w_pct=round(_pct_change(close, 5), 2),
        change_1m_pct=round(_pct_change(close, 21), 2),
        change_3m_pct=round(_pct_change(close, 63), 2),
        sma20=round(sma20, 2),
        sma50=round(sma50, 2),
        trend=trend,
        rsi14=round(rsi, 1),
        rsi_signal=rsi_signal,
        macd=round(macd, 3),
        macd_signal_line=round(macd_signal, 3),
        macd_state=macd_state,
        volatility_pct=round(volatility, 1),
        support=round(support, 2),
        resistance=round(resistance, 2),
        volume_trend=volume_trend,
    )
