"""Bouwt view-model data voor het dashboard uit het logboek + config.

Puur lezen: geen nieuwe analyses, geen schrijfacties, geen API-kosten.
"""
from __future__ import annotations

import re

from ..config import Settings, Ticker
from ..logbook.store import Logbook, Recommendation
from ..logbook.evaluator import compute_accuracy, HOLD_BAND_PCT
from . import cache

SIGNAL_LABEL = {"buy": "KOPEN", "sell": "VERKOPEN", "hold": "AANHOUDEN", "none": "—"}
SIGNAL_RANK = {"buy": 0, "hold": 1, "sell": 2, "none": 3}
CRYPTO_CATEGORY = "Crypto"


# ---------------------------------------------------------------- helpers ---
def latest_by_symbol(book: Logbook) -> dict[str, Recommendation]:
    """Meest recente aanbeveling per symbool (book.all is aflopend op datum)."""
    latest: dict[str, Recommendation] = {}
    for rec in book.all(limit=5000):
        latest.setdefault(rec.symbol, rec)
    return latest


def _rec_row(rec: Recommendation) -> dict:
    return {
        "id": rec.id,
        "created_at": rec.created_at,
        "signal": rec.signal,
        "signal_label": SIGNAL_LABEL.get(rec.signal, rec.signal),
        "confidence": rec.confidence,
        "price": rec.price_at_reco,
        "horizon_days": rec.horizon_days,
        "evaluated": bool(rec.evaluated),
        "correct": rec.correct,
        "actual_return_pct": rec.actual_return_pct,
    }


# --------------------------------------------------------------- overview ---
def overview_rows(settings: Settings, book: Logbook, category: str | None = None,
                  exclude: list[str] | None = None) -> list[dict]:
    latest = latest_by_symbol(book)
    excluded = set(exclude or [])
    rows: list[dict] = []
    for t in settings.tickers:
        if category and t.category != category:
            continue
        if t.category in excluded:
            continue
        rec = latest.get(t.symbol)
        signal = rec.signal if rec else "none"
        rows.append({
            "symbol": t.symbol,
            "name": t.name,
            "category": t.category,
            "signal": signal,
            "signal_label": SIGNAL_LABEL.get(signal, signal),
            "confidence": rec.confidence if rec else None,
            "price": rec.price_at_reco if rec else None,
            "created_at": rec.created_at if rec else None,
            "has_rec": rec is not None,
        })
    rows.sort(key=lambda r: (SIGNAL_RANK.get(r["signal"], 9), -(r["confidence"] or 0)))
    return rows


def categories(settings: Settings, exclude: list[str] | None = None) -> list[str]:
    excluded = set(exclude or [])
    seen: list[str] = []
    for t in settings.tickers:
        if t.category in excluded:
            continue
        if t.category not in seen:
            seen.append(t.category)
    return seen


# ----------------------------------------------------------------- detail ---
def _ticker_for(settings: Settings, symbol: str) -> Ticker | None:
    for t in settings.tickers:
        if t.symbol == symbol:
            return t
    return None


def stock_detail(settings: Settings, book: Logbook, symbol: str) -> dict | None:
    ticker = _ticker_for(settings, symbol)
    history = book.for_symbol(symbol, only_evaluated=False)
    if ticker is None and not history:
        return None

    latest = history[0] if history else None
    return {
        "symbol": symbol,
        "name": ticker.name if ticker else (latest.name if latest else symbol),
        "category": ticker.category if ticker else "",
        "latest": {
            **_rec_row(latest),
            "rationale": latest.rationale,
            "key_factors": latest.key_factors,
            "risks": latest.risks,
            "sources": latest.sources,
            "source": latest.source,
        } if latest else None,
        "history": [_rec_row(r) for r in history],
        "links": external_links(symbol),
    }


# ------------------------------------------------------------------- news ---
def news_feed(book: Logbook, symbol: str | None = None) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for rec in book.all(limit=5000):
        if symbol and rec.symbol != symbol:
            continue
        analysis_date = rec.created_at[:10]
        for s in rec.sources or []:
            link = s.get("link", "")
            key = (analysis_date, rec.symbol, link)
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "analysis_date": rec.created_at,
                "symbol": rec.symbol,
                "name": rec.name,
                "signal": rec.signal,
                "signal_label": SIGNAL_LABEL.get(rec.signal, rec.signal),
                "title": s.get("title", ""),
                "publisher": s.get("source", ""),
                "published": s.get("published", ""),
                "link": link,
            })
    items.sort(key=lambda i: (i["analysis_date"], i["published"]), reverse=True)
    return items


# ----------------------------------------------------------------- report ---
def report_data(settings: Settings, book: Logbook) -> dict:
    cat_of = {t.symbol: t.category for t in settings.tickers}
    evaluated = [r for r in book.all(limit=5000) if r.evaluated]

    overall = compute_accuracy(book)

    by_category: dict[str, list[int]] = {}
    by_horizon: dict[int, list[int]] = {}
    for r in evaluated:
        cat = cat_of.get(r.symbol, "Overig")
        by_category.setdefault(cat, [0, 0])
        by_category[cat][1] += 1
        by_category[cat][0] += 1 if r.correct else 0
        by_horizon.setdefault(r.horizon_days, [0, 0])
        by_horizon[r.horizon_days][1] += 1
        by_horizon[r.horizon_days][0] += 1 if r.correct else 0

    evaluated_rows = sorted(
        ({**_rec_row(r), "symbol": r.symbol, "name": r.name} for r in evaluated),
        key=lambda r: r["created_at"], reverse=True,
    )

    return {
        "total": overall.total,
        "correct": overall.correct,
        "hit_rate": overall.hit_rate,
        "by_signal": {SIGNAL_LABEL.get(k, k): v for k, v in overall.by_signal.items()},
        "by_category": by_category,
        "by_horizon": dict(sorted(by_horizon.items())),
        "evaluated_rows": evaluated_rows,
        "hold_band_pct": HOLD_BAND_PCT,
    }


def logbook_rows(book: Logbook, limit: int = 500) -> list[dict]:
    return [
        {**_rec_row(r), "symbol": r.symbol, "name": r.name}
        for r in book.all(limit=limit)
    ]


# ------------------------------------------------------------ extern/links ---
_TV_PREFIX = {".AS": "EURONEXT", ".DE": "XETR", ".MI": "MIL", ".ST": "OMXSTO"}


def external_links(symbol: str) -> list[dict]:
    """Doorklik-links per aandeel/munt (label + url)."""
    if symbol.endswith("-USD"):  # crypto — DEGIRO doet geen crypto
        # Yahoo gebruikt soms een cijfercode (SUI20947-USD); strip die voor TradingView.
        base = re.sub(r"\d+$", "", symbol[:-4])
        return [
            {"label": "TradingView", "url": f"https://www.tradingview.com/chart/?symbol={base}USD"},
            {"label": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{symbol}"},
        ]
    base = symbol
    prefix = None
    for suffix, pfx in _TV_PREFIX.items():
        if symbol.endswith(suffix):
            base = symbol[: -len(suffix)]
            prefix = pfx
            break
    tv_symbol = f"{prefix}:{base.replace('-', '_')}" if prefix else base
    return [
        {"label": "TradingView", "url": f"https://www.tradingview.com/chart/?symbol={tv_symbol}"},
        {"label": "DEGIRO", "url": "https://trader.degiro.nl/"},
    ]


# ------------------------------------------------- instapkans (drawdown) ---
# Ruimere drempels dan de ETF-dip: losse aandelen/crypto zijn volatieler.
ENTRY_LOOKBACK = 90                                   # ~top van de afgelopen maanden
ENTRY_THRESHOLDS = [(25, "groot"), (15, "flink"), (8, "klein")]


def _entry_status(close) -> dict:
    """Hoe ver staat de koers onder zijn recente top? (objectief, geen advies)"""
    if close.empty:
        return {"level": "none", "depth_pct": 0.0, "drawdown_pct": 0.0}
    window = close.tail(ENTRY_LOOKBACK)
    high = float(window.max())
    last = float(close.iloc[-1])
    drawdown = (last - high) / high * 100 if high else 0.0
    depth = -drawdown
    level = "none"
    for thr, name in ENTRY_THRESHOLDS:
        if depth >= thr:
            level = name
            break
    return {"level": level, "depth_pct": round(depth, 1), "drawdown_pct": round(drawdown, 1)}


# ------------------------------------------------------------- prijsreeks ---
def price_series(symbol: str, period: str = "6mo") -> dict:
    """OHLC + SMA20/SMA50 + instapkans voor de grafiek/overzicht (via de TTL-cache)."""
    data = cache.get_history(symbol, period=period)
    df = data.history.dropna(subset=["Close"])  # lege rijen (bv. lopende dag) weglaten
    if df.empty:
        return {"candles": [], "sma20": [], "sma50": [], "last_close": None,
                "entry": {"level": "none", "depth_pct": 0.0, "drawdown_pct": 0.0}}

    def _line(series):
        s = series.dropna()
        return [{"time": t.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
                for t, v in s.items()]

    candles = [
        {"time": t.strftime("%Y-%m-%d"),
         "open": round(float(row.Open), 2), "high": round(float(row.High), 2),
         "low": round(float(row.Low), 2), "close": round(float(row.Close), 2)}
        for t, row in df.iterrows()
    ]
    close = df["Close"]
    return {
        "candles": candles,
        "sma20": _line(close.rolling(20).mean()),
        "sma50": _line(close.rolling(50).mean()),
        "last_close": round(float(close.iloc[-1]), 2),
        "entry": _entry_status(close),
    }
