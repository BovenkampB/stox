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


def _daily_summary(results, eval_res, acc, skipped: int = 0) -> tuple[str, str]:
    """Bouw (onderwerp, tekst) voor de dagelijkse samenvattingsmail."""
    from collections import Counter

    counts = Counter(r.reasoning.signal for r in results)
    buy, sell, hold = counts.get("buy", 0), counts.get("sell", 0), counts.get("hold", 0)
    datestr = date.today().strftime("%d-%m-%Y")
    subject = f"stox dagelijks: {buy} kopen, {sell} verkopen, {hold} aanhouden ({datestr})"

    lines = [f"stox dagelijkse samenvatting — {datestr}", ""]
    if eval_res.evaluated:
        lines.append(
            f"Vandaag geëvalueerd: {eval_res.evaluated} eerdere aanbevelingen, "
            f"waarvan {eval_res.correct} correct."
        )
    if acc.total:
        lines.append(
            f"Trefzekerheid tot nu toe: {acc.correct}/{acc.total} ({acc.hit_rate:.0f}%)."
        )
    if skipped:
        lines.append(f"Let op: {skipped} ticker(s) overgeslagen door een fout (zie data/stox.log).")
    lines.append("")

    actionable = [r for r in results if r.reasoning.signal in ("buy", "sell")]
    if actionable:
        lines.append("== Signalen die om aandacht vragen ==")
        for r in sorted(actionable, key=lambda r: -r.reasoning.confidence):
            lab = SIGNAL_LABEL[r.reasoning.signal]
            lines.append(
                f"[{lab}] {r.ticker.name} ({r.ticker.symbol}) — "
                f"zekerheid {r.reasoning.confidence:.0%}, koers {r.tech.last_close}"
            )
            if r.reasoning.rationale:
                lines.append(f"    {r.reasoning.rationale}")
            if r.news:
                lines.append("    Bronnen:")
                for n in r.news[:4]:
                    lines.append(f"      - {n.title} ({n.source}) {n.link}")
            lines.append("")

    lines.append("== Volledig overzicht ==")
    current = None
    for r in results:
        if r.ticker.category != current:
            current = r.ticker.category
            lines.append(f"\n{current}:")
        lab = SIGNAL_LABEL[r.reasoning.signal]
        lines.append(
            f"  {lab:9s} {r.ticker.symbol:10s} {r.tech.last_close:>9}  "
            f"(zekerheid {r.reasoning.confidence:.0%})"
        )

    lines += [
        "",
        "— stox is een analysehulpmiddel, geen beleggingsadvies. "
        "De markt is niet betrouwbaar te voorspellen; jij beslist zelf.",
    ]
    return subject, "\n".join(lines)


def cmd_daily(args) -> int:
    settings = load_settings()
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
    subject, body = _daily_summary(results, eval_res, acc, skipped)

    # 3. Mail of toon.
    if args.email:
        cfg = load_email_config()
        if not cfg.is_configured:
            console.print("[yellow]E-mail overslaan:[/yellow] geen SMTP-gegevens in .env.")
        else:
            try:
                send_email(cfg, subject, body)
                console.print(f"[green]Samenvatting gemaild naar {cfg.recipient}.[/green]")
            except Exception as exc:
                console.print(f"[red]E-mail versturen mislukt:[/red] {exc}")

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

    p_dash = sub.add_parser("dashboard", help="Start het lokale Stoxxx-webdashboard (read-only).")
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=8000)
    p_dash.add_argument("--no-browser", action="store_true", help="Open de browser niet automatisch.")
    p_dash.set_defaults(func=cmd_dashboard)

    p_daily = sub.add_parser("daily", help="Volledige dagroutine: evalueer + analyseer alles + mail samenvatting.")
    p_daily.add_argument("--email", action="store_true", help="Mail de dagelijkse samenvatting.")
    p_daily.add_argument("--category", help="Beperk tot een categorie (handig om te testen/kosten te sparen).")
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
