# stox

Een transparante aandelen-analyse en aanbevelingstool. `stox` bekijkt de
koersgrafiek én recent nieuws, en geeft per aandeel een onderbouwd signaal
(**kopen / verkopen / aanhouden**) mét redenatie. Elke aanbeveling gaat in een
logboek en wordt na verloop van tijd automatisch getoetst aan de werkelijke
koers — zo bouwt stox een track record op en leert het van eerdere inschattingen.

> ⚠️ **Geen beleggingsadvies.** stox is een hulpmiddel dat je helpt beter en
> sneller na te denken. De markt is niet betrouwbaar te voorspellen; aanbevelingen
> zijn benaderingen. Jij neemt altijd zelf de beslissing om te kopen of verkopen.

## Wat het doet (fase 1)

- **Koersdata** ophalen via Yahoo Finance (gratis, geen sleutel nodig).
- **Grafiek-analyse**: trend, RSI, MACD, volatiliteit, support/resistance, volume.
- **Nieuws** verzamelen via Google News RSS (gratis).
- **AI-redenatie** met de Claude API: weegt nieuws + grafiek af tot een signaal
  met een leesbare onderbouwing, kernfactoren en risico's.
- **Logboek** (SQLite): elke aanbeveling wordt vastgelegd met koers en tijdstip.
- **Leerlus**: `evaluate` toetst verstreken aanbevelingen aan de echte koers en
  berekent je trefzekerheid; die track record voedt de volgende redenaties.

Zonder API-sleutel draait stox in een **regelgebaseerde terugvalmodus** (alleen
technische analyse), zodat je het meteen kunt uitproberen.

## Installatie

```bash
python -m pip install -r requirements.txt
cp .env.example .env      # en vul je ANTHROPIC_API_KEY in
```

## Gebruik

```bash
# Analyseer de hele watchlist en log de aanbevelingen
python -m stox analyze

# Analyseer één aandeel
python -m stox analyze --symbol ASML.AS

# Toets verstreken aanbevelingen aan de werkelijke koers (draai periodiek)
python -m stox evaluate

# Bekijk het logboek
python -m stox history

# Bekijk je trefzekerheid
python -m stox report
```

De watchlist pas je aan in [`config/watchlist.yaml`](config/watchlist.yaml).

## Roadmap

- **Fase 1 (nu):** data + grafiek-analyse + nieuws-redenatie + logboek + leerlus.
- **Fase 2:** rijkere leerlus (patronen per aandeel/sector), betere nieuwsbronnen,
  eventueel een webdashboard met grafieken.
- **Fase 3:** papertrading — een nep-portefeuille die de aanbevelingen volgt, zodat
  je zonder risico ziet hoe een strategie het doet.
- **Fase 4:** optionele koppeling met een echte broker, met harde veiligheidsgrenzen
  (max bedrag, stop-loss, altijd handmatige bevestiging). Pas ná bewezen resultaten.

## Projectstructuur

```
stox/
├── config/watchlist.yaml        # welke aandelen je volgt
├── stox/
│   ├── config.py                # instellingen + geheimen laden
│   ├── data/prices.py           # koersdata (yfinance)
│   ├── data/news.py             # nieuws (Google News RSS)
│   ├── analysis/indicators.py   # technische grafiek-analyse
│   ├── analysis/reasoning.py    # Claude-redenatie (+ heuristische terugval)
│   ├── analysis/recommender.py  # orkestratie
│   ├── logbook/store.py         # SQLite-logboek
│   ├── logbook/evaluator.py     # leerlus / trefzekerheid
│   └── cli.py                   # command-line interface
└── data/stox.db                 # logboek (wordt automatisch aangemaakt)
```
