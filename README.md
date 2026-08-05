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

# Check of de index/ETF-fondsen onder hun recente top staan (dip-signaal)
python -m stox dip
```

De watchlist pas je aan in [`config/watchlist.yaml`](config/watchlist.yaml).

## Dip-signaal met e-mail

`stox dip` meet hoe ver je index/ETF-fondsen onder hun recente top staan
(licht ≥3%, matig ≥5%, stevig ≥8%). Handig om je maandelijkse inleg extra in
te zetten op een terugval. Configureer de fondsen en drempels in het
`dip_alert`-blok van [`config/watchlist.yaml`](config/watchlist.yaml).

Voor automatische e-mailmeldingen:

1. Zet de SMTP-gegevens in je `.env` (zie [`.env.example`](.env.example)).
   Voor Gmail heb je een **app-wachtwoord** nodig
   (https://myaccount.google.com/apppasswords).
2. Draai `python -m stox dip --quiet --email`. Met `--quiet` gebeurt er niets
   op het scherm als er geen dip is; `--email` stuurt een mail bij een **nieuwe
   of diepere** dip (er zit een anti-spam-drempel op, dus geen dubbele mails).
3. Plan dit commando in met Windows Taakplanner om automatisch te checken
   (bijv. 3× per handelsdag: 09:30, 13:00 en 17:00).

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
