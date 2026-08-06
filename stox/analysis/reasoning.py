"""De redenatie-motor: weegt grafiek + nieuws en produceert een onderbouwd signaal.

Gebruikt de Claude API wanneer een sleutel beschikbaar is. Zonder sleutel valt
het terug op een eenvoudige regelgebaseerde heuristiek, zodat de app altijd draait.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .indicators import TechnicalSummary
from ..data.news import NewsItem

VALID_SIGNALS = {"buy", "sell", "hold"}


@dataclass
class Reasoning:
    signal: str                       # 'buy' | 'sell' | 'hold'
    confidence: float                 # 0.0 - 1.0
    horizon_days: int
    rationale: str                    # leesbare onderbouwing
    key_factors: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    source: str = "claude"            # 'claude' of 'heuristic'


SYSTEM_PROMPT = """Je bent een nuchtere beursanalist die aandelen beoordeelt voor een \
particuliere belegger. Je geeft GEEN gegarandeerde voorspellingen — de markt is niet \
exact voorspelbaar. Je weegt technische grafiek-signalen en recent nieuws af tot een \
onderbouwd, eerlijk signaal met een expliciete onzekerheid.

Belangrijk:
- Wees concreet: verwijs naar specifieke nieuwsfeiten (deals, concurrentie, \
regelgeving, cijfers) en naar de technische stand (trend, RSI, MACD, support/resistance).
- Overdrijf niet. Als het beeld gemengd is, kies 'hold' met lage confidence.
- Houd rekening met je eigen track record indien meegegeven: als een bepaald soort \
redenering eerder vaak fout zat, wees dan voorzichtiger.

Antwoord UITSLUITEND met geldige JSON in dit schema:
{
  "signal": "buy" | "sell" | "hold",
  "confidence": <getal 0..1>,
  "rationale": "<2-4 zinnen onderbouwing in het Nederlands>",
  "key_factors": ["<kort feit>", ...],
  "risks": ["<kort risico>", ...]
}"""


def _format_news(news: list[NewsItem]) -> str:
    if not news:
        return "(geen recent nieuws gevonden)"
    return "\n".join(f"- {item.as_line()}" for item in news)


def _build_user_prompt(
    name: str,
    symbol: str,
    tech: TechnicalSummary,
    news: list[NewsItem],
    track_record: str | None,
) -> str:
    parts = [
        f"Bedrijf: {name} ({symbol})",
        "",
        "TECHNISCHE STAND (grafiek):",
        json.dumps(tech.to_dict(), ensure_ascii=False, indent=2),
        "",
        "RECENT NIEUWS (nieuwste eerst):",
        _format_news(news),
    ]
    if track_record:
        parts += ["", "JOUW TRACK RECORD TOT NU TOE (leer hiervan):", track_record]
    parts += [
        "",
        "Geef nu je onderbouwde signaal als JSON volgens het schema.",
    ]
    return "\n".join(parts)


def _heuristic(tech: TechnicalSummary, horizon: int) -> Reasoning:
    """Simpele terugval zonder API: combineert trend, RSI en MACD."""
    score = 0
    factors: list[str] = []
    if tech.trend == "stijgend":
        score += 1
        factors.append("opwaartse trend (koers boven SMA20/SMA50)")
    elif tech.trend == "dalend":
        score -= 1
        factors.append("neerwaartse trend (koers onder SMA20/SMA50)")

    if tech.macd_state == "bullish":
        score += 1
        factors.append("MACD bullish")
    else:
        score -= 1
        factors.append("MACD bearish")

    if tech.rsi_signal == "oversold":
        score += 1
        factors.append(f"RSI laag ({tech.rsi14}) — mogelijk oversold")
    elif tech.rsi_signal == "overbought":
        score -= 1
        factors.append(f"RSI hoog ({tech.rsi14}) — mogelijk overbought")

    if score >= 2:
        signal = "buy"
    elif score <= -2:
        signal = "sell"
    else:
        signal = "hold"

    confidence = min(0.6, 0.3 + 0.1 * abs(score))
    return Reasoning(
        signal=signal,
        confidence=round(confidence, 2),
        horizon_days=horizon,
        rationale=(
            "Regelgebaseerde inschatting zonder AI-redenatie (geen API-sleutel actief). "
            f"Technisch beeld weegt richting '{signal}'. Nieuws is niet meegewogen."
        ),
        key_factors=factors,
        risks=["Nieuws en fundamentele context zijn niet meegewogen in deze modus."],
        source="heuristic",
    )


def reason(
    *,
    name: str,
    symbol: str,
    tech: TechnicalSummary,
    news: list[NewsItem],
    horizon_days: int,
    api_key: str | None,
    model: str,
    track_record: str | None = None,
) -> Reasoning:
    """Produceer een onderbouwd signaal via Claude, of via de heuristiek."""
    if not api_key:
        return _heuristic(tech, horizon_days)

    try:
        import anthropic
    except ImportError:
        return _heuristic(tech, horizon_days)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        user_prompt = _build_user_prompt(name, symbol, tech, news, track_record)
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        data = _extract_json(text)
        signal = str(data.get("signal", "hold")).lower()
        if signal not in VALID_SIGNALS:
            signal = "hold"
        confidence = float(data.get("confidence", 0.4))
        confidence = max(0.0, min(1.0, confidence))
        return Reasoning(
            signal=signal,
            confidence=round(confidence, 2),
            horizon_days=horizon_days,
            rationale=str(data.get("rationale", "")).strip(),
            key_factors=[str(x) for x in data.get("key_factors", [])],
            risks=[str(x) for x in data.get("risks", [])],
            source="claude",
        )
    except Exception as exc:  # netwerk-, parse- of API-fout: val netjes terug
        fallback = _heuristic(tech, horizon_days)
        fallback.rationale += f" (Claude-aanroep mislukt: {exc})"
        return fallback


def _extract_json(text: str) -> dict:
    """Haal het eerste JSON-object uit een tekst (voor het geval er extra tekst omheen staat)."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Geen JSON gevonden in antwoord: {text[:200]}")
    return json.loads(text[start : end + 1])
