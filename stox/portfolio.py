"""Fictief papertrading-portfolio dat handelt op stox' eigen signalen.

Start met een fictief budget en volgt de strategie: koop bij een KOPEN-signaal
met voldoende zekerheid, verkoop bij een VERKOPEN-signaal, houd anders aan.
Alle bedragen in euro's; koersen in vreemde valuta worden omgerekend. Elke
koop/verkoop kost een vaste transactievergoeding. Puur fictief — geen echte handel.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import yfinance as yf

# --- strategie-instellingen (makkelijk bij te stellen) ---
START_BUDGET_EUR = 100_000.0
FEE_EUR = 3.50                 # kosten per koop/verkoop
TARGET_POSITION_EUR = 6_000.0  # streefbedrag per nieuwe positie (~16 posities max)
MIN_CONFIDENCE = 0.55          # alleen handelen bij signalen met minstens deze zekerheid
MIN_BUY_EUR = 100.0            # koop niet voor een schijntje

# --- valuta ---
_CUR_SUFFIX = {".AS": "EUR", ".DE": "EUR", ".MI": "EUR", ".PA": "EUR",
               ".BR": "EUR", ".ST": "SEK", ".L": "GBP", ".SW": "CHF"}
_fx_cache: dict[str, float] = {}


def currency_of(symbol: str) -> str:
    for suffix, cur in _CUR_SUFFIX.items():
        if symbol.endswith(suffix):
            return cur
    return "USD"  # VS-aandelen en crypto (<munt>-USD)


def fx_to_eur(currency: str) -> float:
    """Wisselkoers: hoeveel euro is 1 eenheid van 'currency' waard."""
    if currency == "EUR":
        return 1.0
    if currency in _fx_cache:
        return _fx_cache[currency]
    rate = 1.0
    try:
        hist = yf.Ticker(f"{currency}EUR=X").history(period="5d")
        if not hist.empty:
            rate = float(hist["Close"].dropna().iloc[-1])
    except Exception:
        pass
    _fx_cache[currency] = rate
    return rate


def price_in_eur(symbol: str, native_price: float) -> float:
    return float(native_price) * fx_to_eur(currency_of(symbol))


SCHEMA = """
CREATE TABLE IF NOT EXISTS pf_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pf_positions (
    symbol TEXT PRIMARY KEY, name TEXT, shares REAL, cost_eur REAL, opened_at TEXT
);
CREATE TABLE IF NOT EXISTS pf_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, name TEXT,
    action TEXT, shares REAL, price_eur REAL, amount_eur REAL, fee_eur REAL, cash_after REAL
);
CREATE TABLE IF NOT EXISTS pf_history (
    date TEXT PRIMARY KEY, total_eur REAL, cash_eur REAL, invested_eur REAL
);
"""


class Portfolio:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        if self._meta("cash") is None:
            self._set_meta("cash", START_BUDGET_EUR)
            self._set_meta("start_budget", START_BUDGET_EUR)
            self._set_meta("started_at", datetime.now().strftime("%Y-%m-%d"))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- meta / cash --------------------------------------------------------
    def _meta(self, key: str):
        row = self.conn.execute("SELECT value FROM pf_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO pf_meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def cash(self) -> float:
        return float(self._meta("cash") or 0.0)

    def start_budget(self) -> float:
        return float(self._meta("start_budget") or START_BUDGET_EUR)

    def started_at(self) -> str:
        return self._meta("started_at") or ""

    def _set_cash(self, value: float) -> None:
        self._set_meta("cash", round(value, 2))

    # -- posities / trades --------------------------------------------------
    def positions(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM pf_positions ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]

    def position(self, symbol: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM pf_positions WHERE symbol=?", (symbol,)).fetchone()
        return dict(row) if row else None

    def trades(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM pf_trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def history(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM pf_history ORDER BY date").fetchall()
        return [dict(r) for r in rows]

    def _log_trade(self, ts, symbol, name, action, shares, price_eur, amount, fee) -> None:
        self.conn.execute(
            "INSERT INTO pf_trades (ts,symbol,name,action,shares,price_eur,amount_eur,fee_eur,cash_after)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, symbol, name, action, round(shares, 6), round(price_eur, 4),
             round(amount, 2), fee, round(self.cash(), 2)))

    # -- handelen -----------------------------------------------------------
    def _buy(self, symbol, name, price_eur, ts) -> bool:
        cash = self.cash()
        amount = min(TARGET_POSITION_EUR, cash - FEE_EUR)
        if amount < MIN_BUY_EUR or price_eur <= 0:
            return False
        shares = amount / price_eur
        self._set_cash(cash - amount - FEE_EUR)
        self.conn.execute(
            "INSERT INTO pf_positions (symbol,name,shares,cost_eur,opened_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET shares=shares+excluded.shares, cost_eur=cost_eur+excluded.cost_eur",
            (symbol, name, shares, amount, ts[:10]))
        self._log_trade(ts, symbol, name, "buy", shares, price_eur, amount, FEE_EUR)
        return True

    def _sell(self, symbol, name, price_eur, ts) -> bool:
        pos = self.position(symbol)
        if not pos or price_eur <= 0:
            return False
        shares = pos["shares"]
        proceeds = shares * price_eur
        self._set_cash(self.cash() + proceeds - FEE_EUR)
        self.conn.execute("DELETE FROM pf_positions WHERE symbol=?", (symbol,))
        self._log_trade(ts, symbol, pos["name"], "sell", shares, price_eur, proceeds, FEE_EUR)
        return True

    def run_trading(self, items: list[dict], now: datetime | None = None) -> dict:
        """Voer één handelsronde uit op de gegeven signalen en leg een dagwaarde vast.

        items: [{symbol, name, signal, confidence, price (native valuta)}]
        """
        now = now or datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        price_eur = {}
        for it in items:
            if it.get("price") is not None:
                price_eur[it["symbol"]] = price_in_eur(it["symbol"], it["price"])

        bought = sold = 0
        # 1. verkopen (maakt cash vrij)
        for it in items:
            if (it["signal"] == "sell" and it["confidence"] >= MIN_CONFIDENCE
                    and self.position(it["symbol"]) and it["symbol"] in price_eur):
                sold += self._sell(it["symbol"], it["name"], price_eur[it["symbol"]], ts)
        # 2. kopen (hoogste zekerheid eerst)
        held = {p["symbol"] for p in self.positions()}
        buys = sorted(
            (it for it in items if it["signal"] == "buy" and it["confidence"] >= MIN_CONFIDENCE
             and it["symbol"] not in held and it["symbol"] in price_eur),
            key=lambda it: -it["confidence"])
        for it in buys:
            bought += self._buy(it["symbol"], it["name"], price_eur[it["symbol"]], ts)

        self._snapshot(price_eur, now.strftime("%Y-%m-%d"))
        self.conn.commit()
        return {"bought": bought, "sold": sold}

    def _snapshot(self, price_eur: dict, day: str) -> None:
        pos_value = 0.0
        invested = 0.0
        for pos in self.positions():
            invested += pos["cost_eur"]
            pe = price_eur.get(pos["symbol"])
            if pe is None:  # geen verse koers → terugvallen op kostprijs
                pe = pos["cost_eur"] / pos["shares"] if pos["shares"] else 0.0
            pos_value += pos["shares"] * pe
        total = self.cash() + pos_value
        self.conn.execute(
            "INSERT INTO pf_history (date,total_eur,cash_eur,invested_eur) VALUES (?,?,?,?)"
            " ON CONFLICT(date) DO UPDATE SET total_eur=excluded.total_eur, "
            "cash_eur=excluded.cash_eur, invested_eur=excluded.invested_eur",
            (day, round(total, 2), round(self.cash(), 2), round(invested, 2)))
