"""Bouwt view-model data voor het dashboard uit het logboek + config.

Puur lezen: geen nieuwe analyses, geen schrijfacties, geen API-kosten.
"""
from __future__ import annotations

import re

import pandas as pd
import yfinance as yf

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


# ---------------------------------------------------- fictief portfolio ---
def portfolio_view(settings: Settings) -> dict:
    """Huidige stand van het papertrading-portfolio, met live koersen in euro."""
    from ..portfolio import Portfolio, price_in_eur, FEE_EUR

    pf = Portfolio(settings.db_path)
    name_of = {t.symbol: t.name for t in settings.tickers}
    positions, holdings_value = [], 0.0
    for p in pf.positions():
        df = cache.get_history(p["symbol"], period="5d").history
        native = float(df["Close"].iloc[-1]) if not df.empty else None
        cur_eur = price_in_eur(p["symbol"], native) if native is not None else (
            p["cost_eur"] / p["shares"] if p["shares"] else 0.0)
        value = p["shares"] * cur_eur
        holdings_value += value
        cost = p["cost_eur"]
        positions.append({
            "symbol": p["symbol"], "name": name_of.get(p["symbol"], p["name"]),
            "shares": p["shares"], "cost_eur": cost, "value_eur": value,
            "pnl_eur": value - cost, "pnl_pct": ((value - cost) / cost * 100) if cost else 0.0,
            "opened_at": p["opened_at"],
        })
    positions.sort(key=lambda x: -x["value_eur"])

    cash = pf.cash()
    start = pf.start_budget()
    total = cash + holdings_value
    trades = pf.trades(100)
    history = pf.history()
    started = pf.started_at()
    pf.close()

    return {
        "start_budget": start, "cash": cash, "holdings_value": holdings_value,
        "total": total, "return_eur": total - start,
        "return_pct": ((total - start) / start * 100) if start else 0.0,
        "positions": positions, "trades": trades, "history": history,
        "started_at": started, "fee": FEE_EUR,
    }


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


# ------------------------------------------------------- indicatorreeksen ---
_GREEN, _RED = "#16c784", "#ea3943"


def _bollinger(close, window: int = 20, k: float = 2.0):
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return mid + k * std, mid, mid - k * std


def _rsi_series(close, window: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _macd_series(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def _fmt_line(series, keyfn, mask=None, nd: int = 2):
    if mask is not None:
        series = series[mask]
    s = series.dropna()
    return [{"time": keyfn(t), "value": round(float(v), nd)} for t, v in s.items()]


def _fmt_hist(series, keyfn, mask=None, nd: int = 4):
    if mask is not None:
        series = series[mask]
    s = series.dropna()
    return [{"time": keyfn(t), "value": round(float(v), nd),
             "color": _GREEN if v >= 0 else _RED} for t, v in s.items()]


def _indicators(close, keyfn, mask=None) -> dict:
    bb_u, bb_m, bb_l = _bollinger(close)
    macd_l, macd_s, macd_h = _macd_series(close)
    return {
        "bb_upper": _fmt_line(bb_u, keyfn, mask), "bb_middle": _fmt_line(bb_m, keyfn, mask),
        "bb_lower": _fmt_line(bb_l, keyfn, mask),
        "rsi": _fmt_line(_rsi_series(close), keyfn, mask, nd=1),
        "macd": _fmt_line(macd_l, keyfn, mask, nd=4),
        "macd_signal": _fmt_line(macd_s, keyfn, mask, nd=4),
        "macd_hist": _fmt_hist(macd_h, keyfn, mask, nd=4),
    }


# ------------------------------------------------------------- prijsreeks ---
_RANGE_DAILY_DAYS = {"1mo": 31, "6mo": 190, "1y": 370}   # zichtbaar venster in dagen
_RANGE_INTRADAY = {"1d": ("1d", "5m"), "5d": ("5d", "30m")}
_EMPTY_INDICATORS = {k: [] for k in
                     ("bb_upper", "bb_middle", "bb_lower", "rsi", "macd", "macd_signal", "macd_hist")}


def _empty_series() -> dict:
    return {"candles": [], "sma20": [], "sma50": [], "sma200": [], "last_close": None,
            "entry": {"level": "none", "depth_pct": 0.0, "drawdown_pct": 0.0},
            **_EMPTY_INDICATORS}


def _daily_series(symbol: str, rng: str) -> dict:
    # Ruime historie (2j) zodat SMA200 ook op korte zichtvensters gevuld is.
    df = cache.get_history(symbol, period="2y").history.dropna(subset=["Close"])
    if df.empty:
        return _empty_series()
    close = df["Close"]
    sma20, sma50, sma200 = (close.rolling(w).mean() for w in (20, 50, 200))

    last_date = df.index[-1]
    if rng == "ytd":
        start = pd.Timestamp(year=last_date.year, month=1, day=1)
    else:
        start = last_date - pd.Timedelta(days=_RANGE_DAILY_DAYS.get(rng, 190))
    mask = df.index >= start
    key = lambda t: t.strftime("%Y-%m-%d")  # noqa: E731

    vis = df[mask]
    candles = [
        {"time": key(t),
         "open": round(float(row.Open), 2), "high": round(float(row.High), 2),
         "low": round(float(row.Low), 2), "close": round(float(row.Close), 2)}
        for t, row in vis.iterrows()
    ]
    return {"candles": candles,
            "sma20": _fmt_line(sma20, key, mask), "sma50": _fmt_line(sma50, key, mask),
            "sma200": _fmt_line(sma200, key, mask),
            "last_close": round(float(close.iloc[-1]), 2), "entry": _entry_status(close),
            **_indicators(close, key, mask)}


def _intraday_series(symbol: str, rng: str) -> dict:
    period, interval = _RANGE_INTRADAY[rng]
    hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        return {"candles": [], "sma20": [], "sma50": [], "sma200": [],
                "last_close": None, "entry": None, **_EMPTY_INDICATORS}
    key = lambda t: int(t.timestamp())  # noqa: E731  (UTC-seconden, tz-correct)
    candles = [
        {"time": int(row.Index.timestamp()),
         "open": round(float(row.Open), 2), "high": round(float(row.High), 2),
         "low": round(float(row.Low), 2), "close": round(float(row.Close), 2)}
        for row in hist.itertuples()
    ]
    return {"candles": candles, "sma20": [], "sma50": [], "sma200": [],
            "last_close": round(float(hist["Close"].iloc[-1]), 2), "entry": None,
            **_indicators(hist["Close"], key)}


def price_series(symbol: str, rng: str = "6mo") -> dict:
    """Koersdata voor de grafiek: candles + SMA's + Bollinger/RSI/MACD (+ instapkans).

    Dagbereiken (1mo/6mo/ytd/1y) tonen dag-SMA's; intraday (1d/5d) alleen candles.
    Bollinger/RSI/MACD worden voor alle bereiken meegeleverd (frontend toont ze op verzoek).
    """
    if rng in _RANGE_INTRADAY:
        return _intraday_series(symbol, rng)
    return _daily_series(symbol, rng)
