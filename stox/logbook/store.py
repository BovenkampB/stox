"""Het logboek: elke aanbeveling wordt hier vastgelegd en later geëvalueerd."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Recommendation:
    id: int | None
    created_at: str
    symbol: str
    name: str
    signal: str
    confidence: float
    horizon_days: int
    price_at_reco: float
    rationale: str
    key_factors: list[str]
    risks: list[str]
    source: str
    # Evaluatievelden (leeg tot de horizon verstreken is):
    evaluated: int = 0
    evaluated_at: str | None = None
    price_at_eval: float | None = None
    actual_return_pct: float | None = None
    correct: int | None = None  # 1 = klopte, 0 = klopte niet, None = n.v.t.


SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    signal TEXT NOT NULL,
    confidence REAL NOT NULL,
    horizon_days INTEGER NOT NULL,
    price_at_reco REAL NOT NULL,
    rationale TEXT,
    key_factors TEXT,
    risks TEXT,
    source TEXT,
    evaluated INTEGER DEFAULT 0,
    evaluated_at TEXT,
    price_at_eval REAL,
    actual_return_pct REAL,
    correct INTEGER
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Logbook:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- schrijven --------------------------------------------------------
    def add(self, rec: Recommendation) -> int:
        cur = self.conn.execute(
            """INSERT INTO recommendations
               (created_at, symbol, name, signal, confidence, horizon_days,
                price_at_reco, rationale, key_factors, risks, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.created_at or _now(),
                rec.symbol,
                rec.name,
                rec.signal,
                rec.confidence,
                rec.horizon_days,
                rec.price_at_reco,
                rec.rationale,
                json.dumps(rec.key_factors, ensure_ascii=False),
                json.dumps(rec.risks, ensure_ascii=False),
                rec.source,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def mark_evaluated(
        self, rec_id: int, price_at_eval: float, actual_return_pct: float, correct: int
    ) -> None:
        self.conn.execute(
            """UPDATE recommendations
               SET evaluated=1, evaluated_at=?, price_at_eval=?,
                   actual_return_pct=?, correct=?
               WHERE id=?""",
            (_now(), price_at_eval, actual_return_pct, correct, rec_id),
        )
        self.conn.commit()

    # -- lezen ------------------------------------------------------------
    def _row_to_rec(self, row: sqlite3.Row) -> Recommendation:
        return Recommendation(
            id=row["id"],
            created_at=row["created_at"],
            symbol=row["symbol"],
            name=row["name"],
            signal=row["signal"],
            confidence=row["confidence"],
            horizon_days=row["horizon_days"],
            price_at_reco=row["price_at_reco"],
            rationale=row["rationale"] or "",
            key_factors=json.loads(row["key_factors"] or "[]"),
            risks=json.loads(row["risks"] or "[]"),
            source=row["source"] or "",
            evaluated=row["evaluated"],
            evaluated_at=row["evaluated_at"],
            price_at_eval=row["price_at_eval"],
            actual_return_pct=row["actual_return_pct"],
            correct=row["correct"],
        )

    def all(self, limit: int = 100) -> list[Recommendation]:
        rows = self.conn.execute(
            "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_rec(r) for r in rows]

    def pending_evaluation(self) -> list[Recommendation]:
        rows = self.conn.execute(
            "SELECT * FROM recommendations WHERE evaluated=0"
        ).fetchall()
        return [self._row_to_rec(r) for r in rows]

    def for_symbol(self, symbol: str, only_evaluated: bool = True) -> list[Recommendation]:
        q = "SELECT * FROM recommendations WHERE symbol=?"
        if only_evaluated:
            q += " AND evaluated=1"
        q += " ORDER BY created_at DESC"
        rows = self.conn.execute(q, (symbol,)).fetchall()
        return [self._row_to_rec(r) for r in rows]
