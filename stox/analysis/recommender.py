"""Orkestratie: van ticker naar een volledige, gelogde aanbeveling."""
from __future__ import annotations

from dataclasses import dataclass

from .indicators import analyse, TechnicalSummary
from .reasoning import reason, Reasoning
from ..config import Settings, Ticker
from ..data.news import fetch_news, NewsItem
from ..data.prices import fetch_history
from ..logbook.store import Logbook, Recommendation
from ..logbook.evaluator import track_record_text


@dataclass
class AnalysisResult:
    ticker: Ticker
    tech: TechnicalSummary
    news: list[NewsItem]
    reasoning: Reasoning


def analyse_ticker(
    ticker: Ticker, settings: Settings, book: Logbook | None = None
) -> AnalysisResult | None:
    """Voer de volledige analyse uit voor één ticker (zonder op te slaan)."""
    price = fetch_history(ticker.symbol, period="6mo")
    tech = analyse(price)
    if tech is None:
        return None

    news = fetch_news(ticker.name)
    track = track_record_text(book, ticker.symbol) if book else None

    reasoning = reason(
        name=ticker.name,
        symbol=ticker.symbol,
        tech=tech,
        news=news,
        horizon_days=settings.default_horizon_days,
        api_key=settings.anthropic_api_key,
        model=settings.model,
        track_record=track,
    )
    return AnalysisResult(ticker=ticker, tech=tech, news=news, reasoning=reasoning)


def store_result(result: AnalysisResult, book: Logbook) -> int:
    """Schrijf een aanbeveling naar het logboek en geef het id terug."""
    rec = Recommendation(
        id=None,
        created_at="",
        symbol=result.ticker.symbol,
        name=result.ticker.name,
        signal=result.reasoning.signal,
        confidence=result.reasoning.confidence,
        horizon_days=result.reasoning.horizon_days,
        price_at_reco=result.tech.last_close,
        rationale=result.reasoning.rationale,
        key_factors=result.reasoning.key_factors,
        risks=result.reasoning.risks,
        source=result.reasoning.source,
        sources=[
            {"title": n.title, "source": n.source,
             "published": n.published, "link": n.link}
            for n in result.news
        ],
    )
    return book.add(rec)
