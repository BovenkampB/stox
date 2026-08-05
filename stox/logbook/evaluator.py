"""De leerlus: check achteraf of aanbevelingen uitkwamen en meet trefzekerheid."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .store import Logbook, Recommendation
from ..data.prices import current_price

# Een 'hold' rekenen we als 'correct' wanneer de koers binnen deze band bleef.
HOLD_BAND_PCT = 3.0


def _age_days(created_at: str) -> float:
    try:
        created = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - created).total_seconds() / 86400


def _judge(signal: str, return_pct: float) -> int:
    """Bepaal of een signaal achteraf klopte."""
    if signal == "buy":
        return 1 if return_pct > 0 else 0
    if signal == "sell":
        return 1 if return_pct < 0 else 0
    # hold
    return 1 if abs(return_pct) <= HOLD_BAND_PCT else 0


@dataclass
class EvalResult:
    evaluated: int
    correct: int
    skipped_not_mature: int


def run_evaluation(book: Logbook) -> EvalResult:
    """Evalueer alle aanbevelingen waarvan de horizon verstreken is."""
    evaluated = correct = skipped = 0
    for rec in book.pending_evaluation():
        if _age_days(rec.created_at) < rec.horizon_days:
            skipped += 1
            continue
        price_now = current_price(rec.symbol)
        if price_now is None or rec.price_at_reco == 0:
            skipped += 1
            continue
        ret = (price_now - rec.price_at_reco) / rec.price_at_reco * 100
        is_correct = _judge(rec.signal, ret)
        book.mark_evaluated(rec.id, round(price_now, 2), round(ret, 2), is_correct)
        evaluated += 1
        correct += is_correct
    return EvalResult(evaluated=evaluated, correct=correct, skipped_not_mature=skipped)


@dataclass
class Accuracy:
    total: int
    correct: int
    by_signal: dict[str, tuple[int, int]]  # signal -> (correct, total)

    @property
    def hit_rate(self) -> float:
        return (self.correct / self.total * 100) if self.total else 0.0


def compute_accuracy(book: Logbook, symbol: str | None = None) -> Accuracy:
    recs = (
        book.for_symbol(symbol, only_evaluated=True)
        if symbol
        else [r for r in book.all(limit=1000) if r.evaluated]
    )
    by_signal: dict[str, list[int]] = {"buy": [0, 0], "sell": [0, 0], "hold": [0, 0]}
    correct = 0
    for r in recs:
        by_signal.setdefault(r.signal, [0, 0])
        by_signal[r.signal][1] += 1
        if r.correct:
            by_signal[r.signal][0] += 1
            correct += 1
    return Accuracy(
        total=len(recs),
        correct=correct,
        by_signal={k: (v[0], v[1]) for k, v in by_signal.items()},
    )


def track_record_text(book: Logbook, symbol: str) -> str | None:
    """Vat de historische trefzekerheid samen als context voor de AI-redenatie."""
    acc = compute_accuracy(book, symbol)
    if acc.total == 0:
        return None
    lines = [
        f"Voor {symbol}: {acc.correct}/{acc.total} eerdere aanbevelingen klopten "
        f"({acc.hit_rate:.0f}%)."
    ]
    for sig, (c, t) in acc.by_signal.items():
        if t:
            lines.append(f"  - '{sig}': {c}/{t} correct")
    return "\n".join(lines)
