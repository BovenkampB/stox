"""stox command-line interface.

Commando's:
  analyze   Analyseer de watchlist en log aanbevelingen.
  evaluate  Check verstreken aanbevelingen tegen de werkelijke koers (leerlus).
  history   Toon eerdere aanbevelingen.
  report    Toon trefzekerheid / statistieken.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, datetime
from html import escape

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import DATA_DIR, load_settings
from .analysis.recommender import analyse_ticker, store_result
from .analysis.dip import assess_all, DipStatus
from .notify import load_email_config, send_email
from .logbook.store import Logbook
from .logbook.evaluator import run_evaluation, compute_accuracy

console = Console()

DISCLAIMER = (
    "[dim]stox is een analysehulpmiddel, geen beleggingsadvies. "
    "Aanbevelingen zijn benaderingen; de markt is niet betrouwbaar te voorspellen. "
    "Jij beslist zelf.[/dim]"
)

SIGNAL_STYLE = {"buy": "bold green", "sell": "bold red", "hold": "yellow"}
SIGNAL_LABEL = {"buy": "KOPEN", "sell": "VERKOPEN", "hold": "AANHOUDEN"}


def log_error(context: str, exc: BaseException) -> None:
    """Schrijf een fout met traceback naar data/stox.log (voor onzichtbare geplande runs)."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "stox.log", "a", encoding="utf-8") as fh:
            fh.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] {context}\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass  # logging mag nooit zelf de boel laten crashen


def cmd_analyze(args) -> None:
    settings = load_settings()
    book = Logbook(settings.db_path)

    if not settings.anthropic_api_key:
        console.print(
            "[yellow]Let op:[/yellow] geen ANTHROPIC_API_KEY gevonden — "
            "de app draait in regelgebaseerde modus (nieuws wordt niet meegewogen). "
            "Vul .env in voor de volledige AI-redenatie.\n"
        )

    tickers = settings.tickers
    if args.symbol:
        tickers = [t for t in tickers if t.symbol.upper() == args.symbol.upper()]
        if not tickers:
            console.print(f"[red]Ticker {args.symbol} staat niet in de watchlist.[/red]")
            return
    if args.category:
        needle = args.category.lower()
        tickers = [t for t in tickers if needle in t.category.lower()]
        if not tickers:
            cats = sorted({t.category for t in settings.tickers})
            console.print(f"[red]Geen categorie die matcht op '{args.category}'.[/red] "
                          f"Beschikbaar: {', '.join(cats)}")
            return

    current_category = None
    for ticker in tickers:
        if ticker.category != current_category:
            current_category = ticker.category
            console.rule(f"[bold]{current_category}[/bold]")
        console.print(f"Analyseren: [cyan]{ticker.name}[/cyan] ({ticker.symbol}) …")
        result = analyse_ticker(ticker, settings, book)
        if result is None:
            console.print(f"  [red]Onvoldoende koersdata voor {ticker.symbol}.[/red]")
            continue

        rec_id = store_result(result, book)
        _print_result(result, rec_id)

    console.print(DISCLAIMER)
    book.close()


def _print_result(result, rec_id: int) -> None:
    r = result.reasoning
    t = result.tech
    style = SIGNAL_STYLE.get(r.signal, "white")
    label = SIGNAL_LABEL.get(r.signal, r.signal.upper())

    body = [
        f"[{style}]{label}[/{style}]  "
        f"(zekerheid {r.confidence:.0%}, horizon {r.horizon_days} dagen, bron: {r.source})",
        "",
        f"[b]Koers:[/b] {t.last_close}  |  1w {t.change_1w_pct:+.1f}%  "
        f"1m {t.change_1m_pct:+.1f}%  3m {t.change_3m_pct:+.1f}%",
        f"[b]Grafiek:[/b] trend {t.trend}, RSI {t.rsi14} ({t.rsi_signal}), "
        f"MACD {t.macd_state}, support {t.support} / resistance {t.resistance}",
        "",
        f"[b]Redenatie:[/b] {r.rationale}",
    ]
    if r.key_factors:
        body.append("\n[b]Belangrijkste factoren:[/b]")
        body += [f"  • {f}" for f in r.key_factors]
    if r.risks:
        body.append("\n[b]Risico's:[/b]")
        body += [f"  • {f}" for f in r.risks]

    console.print(
        Panel(
            "\n".join(body),
            title=f"#{rec_id}  {result.ticker.name} ({result.ticker.symbol})",
            border_style=style.split()[-1],
        )
    )


def cmd_evaluate(args) -> None:
    settings = load_settings()
    book = Logbook(settings.db_path)
    console.print("Verstreken aanbevelingen evalueren tegen de actuele koers …\n")
    res = run_evaluation(book)
    console.print(
        f"Geëvalueerd: [b]{res.evaluated}[/b]  |  "
        f"waarvan correct: [b]{res.correct}[/b]  |  "
        f"nog niet rijp: {res.skipped_not_mature}\n"
    )
    _print_accuracy(book)
    book.close()


def cmd_report(args) -> None:
    settings = load_settings()
    book = Logbook(settings.db_path)
    _print_accuracy(book)
    book.close()


def _print_accuracy(book: Logbook) -> None:
    acc = compute_accuracy(book)
    if acc.total == 0:
        console.print("[dim]Nog geen geëvalueerde aanbevelingen. "
                      "Draai eerst 'analyze' en later 'evaluate'.[/dim]")
        return
    table = Table(title="Trefzekerheid (geëvalueerde aanbevelingen)")
    table.add_column("Signaal")
    table.add_column("Correct", justify="right")
    table.add_column("Totaal", justify="right")
    table.add_column("Percentage", justify="right")
    for sig, (c, tot) in acc.by_signal.items():
        if tot:
            table.add_row(sig, str(c), str(tot), f"{c / tot * 100:.0f}%")
    table.add_row("[b]TOTAAL[/b]", f"[b]{acc.correct}[/b]", f"[b]{acc.total}[/b]",
                  f"[b]{acc.hit_rate:.0f}%[/b]")
    console.print(table)


def _item_from_result(r) -> dict:
    """Normaliseer een AnalysisResult (verse run) naar een mail-item."""
    return {
        "symbol": r.ticker.symbol, "name": r.ticker.name, "category": r.ticker.category,
        "signal": r.reasoning.signal, "confidence": r.reasoning.confidence,
        "price": r.tech.last_close, "rationale": r.reasoning.rationale,
        "sources": [{"title": n.title, "source": n.source, "link": n.link} for n in r.news],
    }


def _item_from_rec(r, cat_of) -> dict:
    """Normaliseer een opgeslagen Recommendation (resend) naar een mail-item."""
    return {
        "symbol": r.symbol, "name": r.name, "category": cat_of.get(r.symbol, "Overig"),
        "signal": r.signal, "confidence": r.confidence, "price": r.price_at_reco,
        "rationale": r.rationale, "sources": r.sources or [],
    }


# (label, tekstkleur, achtergrond) voor de HTML-signaalbadges.
_SIG_HTML = {
    "buy": ("KOPEN", "#0a8f5b", "#e6f7ef"),
    "sell": ("VERKOPEN", "#c62828", "#fdecee"),
    "hold": ("AANHOUDEN", "#b26a00", "#fff5e6"),
}


def _badge_html(signal: str) -> str:
    label, fg, bg = _SIG_HTML.get(signal, (signal.upper(), "#555", "#eee"))
    return (f'<span style="display:inline-block;padding:2px 9px;border-radius:5px;'
            f'font-size:12px;font-weight:700;color:{fg};background:{bg};">{label}</span>')


def _logo_html() -> str:
    bars = [("#ea3943", 12), ("#16c784", 17), ("#16c784", 22)]
    spans = "".join(
        f'<span style="display:inline-block;width:5px;height:{h}px;background:{c};'
        f'margin:0 1px;vertical-align:middle;border-radius:1px;"></span>'
        for c, h in bars
    )
    return ('<span style="font-size:26px;font-weight:800;color:#e6edf3;letter-spacing:-1px;'
            f'vertical-align:middle;">Sto</span>{spans}')


def _build_daily_email(items, settings, acc, note_lines=None, subject_label="dagelijks"):
    """Bouw (onderwerp, platte tekst, HTML) voor de dagelijkse samenvattingsmail."""
    from collections import Counter

    cat_order = {c: i for i, c in enumerate(dict.fromkeys(t.category for t in settings.tickers))}
    items = sorted(items, key=lambda it: (cat_order.get(it["category"], 999), it["symbol"]))
    note_lines = note_lines or []

    counts = Counter(it["signal"] for it in items)
    buy, sell, hold = counts.get("buy", 0), counts.get("sell", 0), counts.get("hold", 0)
    datestr = date.today().strftime("%d-%m-%Y")
    subject = f"stox {subject_label}: {buy} kopen, {sell} verkopen, {hold} aanhouden ({datestr})"
    actionable = sorted((it for it in items if it["signal"] in ("buy", "sell")),
                        key=lambda it: -it["confidence"])

    def news(is_crypto):
        seen, out = set(), []
        for it in items:
            if (it["category"] == "Crypto") != is_crypto:
                continue
            for s in (it["sources"] or [])[:3]:
                link = s.get("link", "")
                if not link or link in seen:
                    continue
                seen.add(link)
                out.append((it["symbol"], s.get("title", ""), s.get("source", ""), link))
        return out

    # ---------- platte tekst (fallback) ----------
    t = [f"stox dagelijkse samenvatting — {datestr}", ""]
    t += note_lines
    if acc.total:
        t.append(f"Trefzekerheid tot nu toe: {acc.correct}/{acc.total} ({acc.hit_rate:.0f}%).")
    t.append("")
    if actionable:
        t.append("== Signalen die om aandacht vragen ==")
        for it in actionable:
            t.append(f"[{SIGNAL_LABEL.get(it['signal'], it['signal'])}] {it['name']} "
                     f"({it['symbol']}) — zekerheid {it['confidence']:.0%}, koers {it['price']}")
            if it["rationale"]:
                t.append(f"    {it['rationale']}")
            t.append("")
    t.append("== Volledig overzicht ==")
    cur = None
    for it in items:
        if it["category"] != cur:
            cur = it["category"]
            t.append(f"\n{cur}:")
        t.append(f"  {SIGNAL_LABEL.get(it['signal'], it['signal']):9s} {it['symbol']:12s} "
                 f"{it['price']:>9}  (zekerheid {it['confidence']:.0%})")
    for titel, is_crypto in [("Aandelennieuws", False), ("Cryptonieuws", True)]:
        rows = news(is_crypto)
        if rows:
            t.append(f"\n== {titel} ==")
            for sym, titl, src, link in rows:
                t.append(f"  - [{sym}] {titl} ({src}) {link}")
    t += ["", "— stox is een analysehulpmiddel, geen beleggingsadvies. "
          "De markt is niet betrouwbaar te voorspellen; jij beslist zelf."]
    text_body = "\n".join(t)

    # ---------- HTML ----------
    h = ['<div style="max-width:600px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;'
         'color:#1a1a1a;font-size:15px;line-height:1.5;">']
    h.append('<div style="background:#0d1117;padding:18px 24px;border-radius:10px 10px 0 0;">')
    h.append(_logo_html())
    h.append(f'<div style="color:#8b98a9;font-size:13px;margin-top:6px;">'
             f'Dagelijkse samenvatting · {datestr}</div></div>')
    h.append('<div style="background:#ffffff;padding:20px 24px;border:1px solid #e5e7eb;'
             'border-top:none;border-radius:0 0 10px 10px;">')
    h.append(f'<p style="margin:0 0 10px;"><b style="color:#0a8f5b;">{buy} kopen</b> · '
             f'<b style="color:#c62828;">{sell} verkopen</b> · <b>{hold} aanhouden</b></p>')
    for nl in note_lines:
        h.append(f'<p style="margin:0 0 6px;color:#555;font-size:13px;">{escape(nl)}</p>')
    if acc.total:
        h.append(f'<p style="margin:0 0 6px;color:#555;font-size:13px;">Trefzekerheid tot nu toe: '
                 f'<b>{acc.correct}/{acc.total} ({acc.hit_rate:.0f}%)</b></p>')

    if actionable:
        h.append('<h2 style="font-size:16px;margin:22px 0 10px;border-bottom:2px solid #eee;'
                 'padding-bottom:5px;">Signalen die om aandacht vragen</h2>')
        for it in actionable:
            h.append('<div style="margin:0 0 12px;padding:12px 14px;background:#fafbfc;'
                     'border:1px solid #eef0f2;border-radius:8px;">')
            h.append(f'{_badge_html(it["signal"])} <b>{escape(it["name"])}</b> '
                     f'<span style="color:#888;font-size:13px;">{escape(it["symbol"])}</span> · '
                     f'<b>zekerheid {it["confidence"]:.0%}</b> · '
                     f'<span style="color:#555;">koers {it["price"]}</span>')
            if it["rationale"]:
                h.append(f'<div style="margin-top:6px;">{escape(it["rationale"])}</div>')
            h.append('</div>')

    h.append('<h2 style="font-size:16px;margin:22px 0 10px;border-bottom:2px solid #eee;'
             'padding-bottom:5px;">Volledig overzicht</h2>')
    h.append('<table style="width:100%;border-collapse:collapse;font-size:14px;">')
    cur = None
    for it in items:
        if it["category"] != cur:
            cur = it["category"]
            h.append(f'<tr><td colspan="3" style="padding:12px 0 4px;font-weight:700;'
                     f'color:#555;">{escape(cur)}</td></tr>')
        h.append('<tr>'
                 f'<td style="padding:3px 0;white-space:nowrap;">{_badge_html(it["signal"])}</td>'
                 f'<td style="padding:3px 8px;"><b>{escape(it["symbol"])}</b> '
                 f'<span style="color:#999;">{escape(it["name"])}</span></td>'
                 f'<td style="padding:3px 0;text-align:right;color:#555;white-space:nowrap;">'
                 f'{it["confidence"]:.0%} · {it["price"]}</td></tr>')
    h.append('</table>')

    for titel, is_crypto in [("Aandelennieuws", False), ("Cryptonieuws", True)]:
        rows = news(is_crypto)
        if not rows:
            continue
        h.append(f'<h2 style="font-size:15px;margin:22px 0 8px;color:#555;">{titel}</h2>')
        h.append('<div style="font-size:12px;color:#8a8a8a;line-height:1.7;">')
        for sym, titl, src, link in rows:
            h.append(f'<div style="margin-bottom:3px;"><span style="color:#aaa;">[{escape(sym)}]</span> '
                     f'<a href="{escape(link)}" style="color:#6b7280;text-decoration:none;">{escape(titl)}</a>'
                     f' <span style="color:#bbb;">· {escape(src)}</span></div>')
        h.append('</div>')

    h.append('<p style="margin-top:24px;color:#9aa0a6;font-size:11px;border-top:1px solid #eee;'
             'padding-top:10px;">stox is een analysehulpmiddel, geen beleggingsadvies. De markt is '
             'niet betrouwbaar te voorspellen; jij beslist zelf.</p>')
    h.append('</div></div>')
    html_body = "\n".join(h)

    return subject, text_body, html_body


def _resend_today(settings) -> int:
    """Mail de samenvatting van vandaag opnieuw uit het bestaande logboek (geen her-analyse)."""
    book = Logbook(settings.db_path)
    today = date.today().isoformat()
    latest = {}
    for r in book.all(limit=5000):
        if r.created_at[:10] == today:
            latest.setdefault(r.symbol, r)  # meest recente per aandeel
    if not latest:
        console.print("[yellow]Geen aanbevelingen van vandaag in het logboek om te versturen.[/yellow]")
        book.close()
        return 0

    acc = compute_accuracy(book)
    cat_of = {t.symbol: t.category for t in settings.tickers}
    items = [_item_from_rec(r, cat_of) for r in latest.values()]
    subject, body, html = _build_daily_email(items, settings, acc)
    cfg = load_email_config()
    if not cfg.is_configured:
        console.print("[yellow]Geen SMTP-gegevens in .env — kan niet mailen.[/yellow]")
    else:
        try:
            send_email(cfg, subject, body, html=html)
            console.print(f"[green]Samenvatting opnieuw gemaild naar {cfg.recipient}[/green] "
                          f"({len(latest)} aandelen, uit bestaande bronnen).")
        except Exception as exc:
            console.print(f"[red]E-mail versturen mislukt:[/red] {exc}")
    console.print(Panel(body, title="Dagelijkse samenvatting (opnieuw verstuurd)", border_style="cyan"))
    book.close()
    return 0


def cmd_daily(args) -> int:
    settings = load_settings()
    if args.resend:
        return _resend_today(settings)
    if not settings.anthropic_api_key:
        console.print("[yellow]Let op:[/yellow] geen ANTHROPIC_API_KEY — regelgebaseerde modus.")

    tickers = settings.tickers
    if args.category:
        needle = args.category.lower()
        tickers = [t for t in tickers if needle in t.category.lower()]
        if not tickers:
            console.print(f"[red]Geen categorie die matcht op '{args.category}'.[/red]")
            return 1

    book = Logbook(settings.db_path)

    # 1. Evalueer verstreken aanbevelingen (voedt de track record voor de nieuwe ronde).
    eval_res = run_evaluation(book)

    # 2. Analyseer en log. Elk aandeel apart afgeschermd: één fout mag de hele
    #    run (en dus de mail) nooit slopen.
    results = []
    skipped = 0
    current_category = None
    for ticker in tickers:
        if ticker.category != current_category:
            current_category = ticker.category
            console.rule(f"[bold]{current_category}[/bold]")
        console.print(f"Analyseren: [cyan]{ticker.name}[/cyan] ({ticker.symbol}) …")
        try:
            result = analyse_ticker(ticker, settings, book)
            if result is None:
                console.print(f"  [red]Onvoldoende data voor {ticker.symbol}.[/red]")
                skipped += 1
                continue
            store_result(result, book)
            results.append(result)
        except Exception as exc:
            console.print(f"  [red]Overgeslagen ({ticker.symbol}): {exc}[/red]")
            log_error(f"daily: analyse mislukt voor {ticker.symbol}", exc)
            skipped += 1

    acc = compute_accuracy(book)
    note_lines = []
    if eval_res.evaluated:
        note_lines.append(f"Vandaag geëvalueerd: {eval_res.evaluated} eerdere aanbevelingen, "
                          f"waarvan {eval_res.correct} correct.")
    if skipped:
        note_lines.append(f"Let op: {skipped} ticker(s) overgeslagen door een fout (zie data/stox.log).")
    items = [_item_from_result(r) for r in results]
    label = args.category.lower() if args.category else "dagelijks"
    subject, body, html = _build_daily_email(items, settings, acc, note_lines, subject_label=label)

    # 3. Mail of toon.
    if args.email:
        cfg = load_email_config()
        if not cfg.is_configured:
            console.print("[yellow]E-mail overslaan:[/yellow] geen SMTP-gegevens in .env.")
        else:
            try:
                send_email(cfg, subject, body, html=html)
                console.print(f"[green]Samenvatting gemaild naar {cfg.recipient}.[/green]")
            except Exception as exc:
                console.print(f"[red]E-mail versturen mislukt:[/red] {exc}")

    # 4. Papertrading: handel op de verse signalen (alleen bij een volledige run).
    if not args.category:
        try:
            from .portfolio import Portfolio
            pf = Portfolio(settings.db_path)
            res = pf.run_trading(items)
            pf.close()
            console.print(f"[dim]Papertrading: {res['bought']} gekocht, {res['sold']} verkocht.[/dim]")
        except Exception as exc:
            log_error("papertrading", exc)
            console.print(f"[red]Papertrading mislukt:[/red] {exc} [dim](zie data/stox.log)[/dim]")

    console.print()
    console.print(Panel(body, title="Dagelijkse samenvatting", border_style="cyan"))
    book.close()
    return 0


DIP_STYLE = {"geen": "green", "licht": "yellow", "matig": "orange3", "stevig": "bold red"}


def _dip_email_body(dips: list[DipStatus]) -> tuple[str, str]:
    """Bouw (onderwerp, tekst) voor een dip-melding."""
    deepest = max(dips, key=lambda s: s.depth_pct)
    subject = (
        f"stox dip-signaal: {deepest.name} -{deepest.depth_pct:.1f}% "
        f"({deepest.level} dip)"
    )
    lines = ["Een of meer gevolgde fondsen staan onder hun recente top:\n"]
    for s in dips:
        lines.append(
            f"- {s.name} ({s.symbol}): {s.last_close} — "
            f"{s.depth_pct:.1f}% onder de top van {s.recent_high} "
            f"({s.high_date}). Niveau: {s.level}. RSI {s.rsi14}."
        )
    lines += [
        "",
        "Dit kan een moment zijn om je maandelijkse inleg deels extra in te zetten.",
        "",
        "— stox is een analysehulpmiddel, geen beleggingsadvies. "
        "De markt is niet betrouwbaar te voorspellen; jij beslist zelf.",
    ]
    return subject, "\n".join(lines)


def _maybe_email_dip(dips: list[DipStatus], settings) -> None:
    """Verstuur een dip-mail, met anti-spam-drempel (nieuwe of diepere dip)."""
    cfg = load_email_config()
    if not cfg.is_configured:
        console.print(
            "[yellow]E-mail overslaan:[/yellow] geen SMTP-gegevens in .env "
            "(STOX_SMTP_USER / STOX_SMTP_PASSWORD / STOX_ALERT_TO)."
        )
        return

    today = date.today().isoformat()
    book = Logbook(settings.db_path)
    to_notify = [
        s for s in dips if book.should_alert_dip(s.symbol, s.level, today)
    ]
    if not to_notify:
        console.print("[dim]Dip al eerder vandaag gemeld — geen nieuwe e-mail.[/dim]")
        book.close()
        return

    subject, body = _dip_email_body(to_notify)
    try:
        send_email(cfg, subject, body)
        for s in to_notify:
            book.record_dip_alert(s.symbol, s.level, today, s.depth_pct)
        console.print(f"[green]E-mail verstuurd naar {cfg.recipient}.[/green]")
    except Exception as exc:
        console.print(f"[red]E-mail versturen mislukt:[/red] {exc}")
    finally:
        book.close()


def _send_test_email(statuses: list[DipStatus]) -> int:
    """Verstuur één testmail met de actuele stand, ongeacht drempel/anti-spam."""
    cfg = load_email_config()
    if not cfg.is_configured:
        console.print(
            "[red]E-mail niet geconfigureerd.[/red] Zet eerst STOX_SMTP_USER, "
            "STOX_SMTP_PASSWORD en STOX_ALERT_TO in je .env (zie .env.example)."
        )
        return 1

    lines = [
        "Dit is een TESTMAIL van stox om je e-mailinstellingen te controleren.",
        "",
        "Huidige stand van je gevolgde fondsen:",
    ]
    if statuses:
        for s in statuses:
            staat = "op/bij de top" if not s.is_dip else f"{s.level} dip"
            lines.append(
                f"- {s.name} ({s.symbol}): {s.last_close} — "
                f"{s.depth_pct:.1f}% onder de top van {s.recent_high} "
                f"({s.high_date}) → {staat}."
            )
    else:
        lines.append("- (geen dip-symbolen geconfigureerd in watchlist.yaml)")
    lines += [
        "",
        "Zie je deze mail? Dan werkt de dip-melding. Je krijgt voortaan "
        "automatisch bericht zodra er een echte dip is.",
    ]
    try:
        send_email(cfg, "[TEST] stox e-mailmelding werkt", "\n".join(lines))
        console.print(f"[green]Testmail verstuurd naar {cfg.recipient}.[/green] "
                      "Check je inbox (en eventueel de spam-map).")
        return 0
    except Exception as exc:
        console.print(f"[red]Testmail versturen mislukt:[/red] {exc}")
        return 1


def cmd_dip(args) -> int:
    settings = load_settings()
    name_lookup = {t.symbol: t.name for t in settings.tickers}
    statuses = assess_all(settings.dip, name_lookup)

    if args.test_email:
        return _send_test_email(statuses)

    dips = [s for s in statuses if s.is_dip]

    if args.email and dips:
        _maybe_email_dip(dips, settings)

    # --quiet: geef alleen iets terug als er een dip is (voor cron/e-mail).
    if args.quiet and not dips:
        return 0

    if not statuses:
        console.print("[dim]Geen dip-symbolen geconfigureerd (zie 'dip_alert' in watchlist.yaml).[/dim]")
        return 0

    table = Table(title="Dip-signaal (t.o.v. recente top)")
    table.add_column("Fonds")
    table.add_column("Koers", justify="right")
    table.add_column("Recente top", justify="right")
    table.add_column("Onder top", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("Signaal")
    for s in statuses:
        style = DIP_STYLE.get(s.level, "white")
        signal = "— geen dip" if not s.is_dip else f"DIP: {s.level}"
        table.add_row(
            f"{s.name} ({s.symbol})",
            f"{s.last_close}",
            f"{s.recent_high} ({s.high_date})",
            f"[{style}]-{s.depth_pct:.1f}%[/{style}]",
            f"{s.rsi14}",
            f"[{style}]{signal}[/{style}]",
        )
    console.print(table)

    if dips:
        deepest = max(dips, key=lambda s: s.depth_pct)
        console.print(
            f"\n[bold]📉 Seintje:[/bold] {deepest.name} staat "
            f"[{DIP_STYLE.get(deepest.level)}]{deepest.depth_pct:.1f}% onder de recente top[/] "
            f"({deepest.level} dip). Overweeg je maandelijkse inleg hier deels extra in te zetten."
        )
        console.print(DISCLAIMER)
    else:
        console.print("\n[green]Geen dip op dit moment — de fondsen staan dicht bij hun recente top.[/green]")
    return 0


def cmd_sources(args) -> int:
    settings = load_settings()
    book = Logbook(settings.db_path)
    recs = book.for_symbol(args.symbol.upper(), only_evaluated=False)
    if not recs:
        console.print(f"[yellow]Geen aanbevelingen voor {args.symbol} in het logboek.[/yellow]")
        book.close()
        return 0

    for r in recs[: args.limit]:
        console.rule(
            f"#{r.id}  {r.name} ({r.symbol}) — "
            f"{SIGNAL_LABEL.get(r.signal, r.signal)} ({r.confidence:.0%}) — {r.created_at[:10]}"
        )
        if r.rationale:
            console.print(f"[b]Redenatie:[/b] {r.rationale}\n")
        if r.sources:
            console.print("[b]Gebruikte bronnen:[/b]")
            for s in r.sources:
                meta = " · ".join(x for x in [s.get("published", ""), s.get("source", "")] if x)
                console.print(f"  • [{meta}] {s.get('title', '')}")
                if s.get("link"):
                    console.print(f"    [dim]{s['link']}[/dim]")
        else:
            console.print(
                "[dim]Geen bronnen opgeslagen bij deze aanbeveling "
                "(van vóór de bron-opslag, of regelgebaseerde modus zonder nieuws).[/dim]"
            )
        console.print()
    book.close()
    return 0


def cmd_history(args) -> None:
    settings = load_settings()
    book = Logbook(settings.db_path)
    recs = book.all(limit=args.limit)
    if not recs:
        console.print("[dim]Logboek is leeg.[/dim]")
        book.close()
        return
    table = Table(title="Aanbevelingen-logboek")
    table.add_column("#", justify="right")
    table.add_column("Datum")
    table.add_column("Ticker")
    table.add_column("Signaal")
    table.add_column("Koers", justify="right")
    table.add_column("Status")
    table.add_column("Resultaat", justify="right")
    for r in recs:
        if r.evaluated:
            mark = "✓" if r.correct else "✗"
            status = f"{mark} geëvalueerd"
            outcome = f"{r.actual_return_pct:+.1f}%" if r.actual_return_pct is not None else "-"
        else:
            status = "wacht"
            outcome = "-"
        table.add_row(
            str(r.id), r.created_at[:10], r.symbol,
            SIGNAL_LABEL.get(r.signal, r.signal), f"{r.price_at_reco}", status, outcome,
        )
    console.print(table)
    book.close()


def _print_portfolio(pf, settings) -> None:
    hist = pf.history()
    total = hist[-1]["total_eur"] if hist else pf.cash()
    start = pf.start_budget()
    ret = total - start
    console.print(Panel(
        f"Startbudget : €{start:,.0f}\n"
        f"Waarde      : €{total:,.2f}   ({ret:+,.2f} / {ret / start * 100:+.2f}%)\n"
        f"Cash        : €{pf.cash():,.2f}\n"
        f"Posities    : {len(pf.positions())}",
        title="Fictief portfolio", border_style="cyan"))
    positions = pf.positions()
    if positions:
        table = Table(title="Posities (op kostprijs)")
        table.add_column("Symbool")
        table.add_column("Aandelen", justify="right")
        table.add_column("Ingelegd €", justify="right")
        for p in positions:
            table.add_row(p["symbol"], f"{p['shares']:.4f}", f"{p['cost_eur']:,.0f}")
        console.print(table)


def cmd_portfolio(args) -> int:
    from .portfolio import Portfolio
    settings = load_settings()
    pf = Portfolio(settings.db_path)
    if args.run:
        book = Logbook(settings.db_path)
        today = date.today().isoformat()
        latest = {}
        for r in book.all(limit=8000):
            if r.created_at[:10] == today:
                latest.setdefault(r.symbol, r)
        book.close()
        cat_of = {t.symbol: t.category for t in settings.tickers}
        items = [_item_from_rec(r, cat_of) for r in latest.values()]
        if not items:
            console.print("[yellow]Geen aanbevelingen van vandaag om op te handelen.[/yellow]")
        else:
            res = pf.run_trading(items)
            console.print(f"[green]Handelsronde:[/green] {res['bought']} gekocht, {res['sold']} verkocht.")
    _print_portfolio(pf, settings)
    pf.close()
    return 0


def cmd_dashboard(args) -> int:
    import threading
    import webbrowser

    from .dashboard.app import create_app

    settings = load_settings()
    app = create_app(settings)
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    local_url = f"http://{display_host}:{args.port}"
    console.print(
        f"[green]Stoxxx dashboard[/green] draait op [b]{local_url}[/b]  "
        "(read-only · Ctrl+C om te stoppen)"
    )
    if args.host not in ("127.0.0.1", "localhost"):
        console.print(
            f"[dim]Ook bereikbaar op je netwerk/Tailscale via poort {args.port} "
            f"— open bijv. http://<tailscale-ip>:{args.port} op je tablet.[/dim]"
        )
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(local_url)).start()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stox", description="Transparante aandelen-analyse.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_an = sub.add_parser("analyze", help="Analyseer de watchlist en log aanbevelingen.")
    p_an.add_argument("--symbol", help="Analyseer slechts één ticker uit de watchlist.")
    p_an.add_argument("--category", help="Analyseer alleen een categorie, bijv. 'Defensie' of 'Index'.")
    p_an.set_defaults(func=cmd_analyze)

    p_ev = sub.add_parser("evaluate", help="Evalueer verstreken aanbevelingen (leerlus).")
    p_ev.set_defaults(func=cmd_evaluate)

    p_hi = sub.add_parser("history", help="Toon het logboek.")
    p_hi.add_argument("--limit", type=int, default=30)
    p_hi.set_defaults(func=cmd_history)

    p_re = sub.add_parser("report", help="Toon trefzekerheid / statistieken.")
    p_re.set_defaults(func=cmd_report)

    p_src = sub.add_parser("sources", help="Toon de nieuwsbronnen achter aanbevelingen voor een ticker.")
    p_src.add_argument("symbol", help="Ticker, bijv. KTOS of ASML.AS")
    p_src.add_argument("--limit", type=int, default=1,
                       help="Aantal recente aanbevelingen om te tonen (standaard 1).")
    p_src.set_defaults(func=cmd_sources)

    p_pf = sub.add_parser("portfolio", help="Toon het fictieve papertrading-portfolio (of handel met --run).")
    p_pf.add_argument("--run", action="store_true",
                      help="Voer een handelsronde uit op de signalen van vandaag.")
    p_pf.set_defaults(func=cmd_portfolio)

    p_dash = sub.add_parser("dashboard", help="Start het lokale Stoxxx-webdashboard (read-only).")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8000)
    p_dash.add_argument("--no-browser", action="store_true", help="Open de browser niet automatisch.")
    p_dash.set_defaults(func=cmd_dashboard)

    p_daily = sub.add_parser("daily", help="Volledige dagroutine: evalueer + analyseer alles + mail samenvatting.")
    p_daily.add_argument("--email", action="store_true", help="Mail de dagelijkse samenvatting.")
    p_daily.add_argument("--category", help="Beperk tot een categorie (handig om te testen/kosten te sparen).")
    p_daily.add_argument("--resend", action="store_true",
                         help="Analyseer niet opnieuw; mail de samenvatting van vandaag uit het bestaande logboek.")
    p_daily.set_defaults(func=cmd_daily)

    p_dip = sub.add_parser("dip", help="Check of de index/ETF-fondsen onder hun recente top staan.")
    p_dip.add_argument("--quiet", action="store_true",
                       help="Geef alleen output als er daadwerkelijk een dip is (voor geplande taken).")
    p_dip.add_argument("--email", action="store_true",
                       help="Verstuur een e-mail bij een (nieuwe of diepere) dip.")
    p_dip.add_argument("--test-email", action="store_true",
                       help="Stuur één testmail met de actuele stand om je e-mailinstellingen te controleren.")
    p_dip.set_defaults(func=cmd_dip)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Forceer UTF-8 op Windows-consoles zodat •, … en accenten goed tonen.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except KeyboardInterrupt:
        console.print("\n[dim]Afgebroken.[/dim]")
        return 130
    except Exception as exc:
        # Vangnet: bewaar de traceback zodat onzichtbare geplande runs te debuggen zijn.
        log_error(f"onverwachte fout in commando '{getattr(args, 'command', '?')}'", exc)
        console.print(f"[red]Onverwachte fout:[/red] {exc}  [dim](zie data/stox.log)[/dim]")
        return 1
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
