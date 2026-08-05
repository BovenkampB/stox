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

# Volledige dagroutine: evalueer + analyseer alles + toon/mail een samenvatting
python -m stox daily

# Toon de nieuwsbronnen achter de laatste aanbeveling voor een ticker
python -m stox sources KTOS

# Start het lokale webdashboard (opent vanzelf in je browser)
python -m stox dashboard
```

## Dashboard

`python -m stox dashboard` start een lokaal, **read-only** webdashboard op
`http://127.0.0.1:8000` (opent automatisch je browser). Het toont alle data uit
het logboek — het draait geen nieuwe analyses en kost dus geen API-credits.

- **Overzicht** — alle getrackte aandelen, gesorteerd op koopadvies, met een
  sparkline per aandeel en een **Instapkans**-kolom (hoe ver onder de recente
  top: lichte/flinke/grote terugval — objectief, los van het koop/verkoopsignaal);
  filter op categorie.
- **Crypto** — dezelfde weergave voor de populairste cryptomunten (BTC, ETH, …),
  die via dezelfde pijplijn worden geanalyseerd.
- **Detail** (klik een aandeel) — de volledige redenatie, de gebruikte bronnen,
  een candlestick-grafiek (rood/groen, met SMA20/SMA50/SMA200) met een
  range-filter (1D, 5D, 1M, 6M, YTD, 1J — 1D/5D tonen intraday) en toggle-bare
  indicatoren (**Bollinger Banden** als overlay, **RSI** en **MACD** in eigen
  panes eronder — standaard uit), doorklik-links naar TradingView en DEGIRO,
  plus de adviezenhistorie.
- **Nieuws** — alle bronartikelen gesorteerd op de datum waarop ze zijn meegewogen.
- **Rapport** — trefzekerheid per signaal, categorie en horizon (vult zich zodra
  er evaluaties zijn).
- **Logboek** — alle aanbevelingen.

Opties: `--port`, `--host`, `--no-browser`. Draait op de Flask dev-server; voor
een permanente opstelling (bijv. Raspberry Pi) kun je later een WSGI-server zoals
waitress gebruiken.

### Bekijken op je tablet/telefoon (via Tailscale)

Het dashboard is responsive en werkt prima op een tablet. Om het vanaf een ander
apparaat te bekijken, bied je het aan binnen je eigen Tailscale-netwerk (tailnet) —
versleuteld en alleen bereikbaar voor je eigen apparaten.

**Optie A — binden aan je Tailscale-IP (simpel):**

```bash
python -m stox dashboard --host <tailscale-ip-van-je-pc>
```

Open daarna op je tablet `http://<tailscale-ip-van-je-pc>:8000`. Door aan het
Tailscale-IP te binden (i.p.v. `0.0.0.0`) is het dashboard alléén via je tailnet
bereikbaar, niet via je gewone wifi/LAN.

**Optie B — Tailscale Serve met HTTPS (netter):** laat het dashboard op localhost
draaien en zet er Tailscale voor:

```bash
tailscale serve --bg 8000
```

Je bereikt het dan op `https://<pc-naam>.<jouw-tailnet>.ts.net` — met een geldig
certificaat en zonder firewall-aanpassingen. Stoppen: `tailscale serve --https=443 off`.

> Windows-firewall kan de eerste keer om toestemming vragen om Python via het
> netwerk te laten communiceren — sta dat toe (privé netwerk).

## Dagelijkse samenvatting

`stox daily` doet de volledige dagroutine in één keer:

1. **Evalueert** eerder gedane aanbevelingen waarvan de horizon verstreken is
   (dit voedt de track record die de nieuwe redenaties meekrijgen).
2. **Analyseert** de hele watchlist opnieuw en logt de aanbevelingen.
3. **Mailt** (met `--email`) een samenvatting: actie-signalen bovenaan, dan het
   volledige overzicht per categorie plus je trefzekerheid tot nu toe.

Met `--category` beperk je de run (handig om te testen of kosten te sparen).
Plan `python -m stox daily --email` bijvoorbeeld elke werkdag om 08:00 in met
Windows Taakplanner.

De watchlist pas je aan in [`config/watchlist.yaml`](config/watchlist.yaml).

## Herkomst van aanbevelingen (bronnen)

Elke aanbeveling slaat de gebruikte nieuwsartikelen op (titel, uitgever, datum,
link), zodat je achteraf altijd kunt zien waaróp een advies stoelde — ook als
dat nieuws later is weggezakt. Bekijk ze met `python -m stox sources <TICKER>`
(bijv. `sources KTOS`). In de dagelijkse mail staan de bronnen onder elk
koop-/verkoopsignaal.

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
