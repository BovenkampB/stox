"""Flask-app voor het Stoxxx-dashboard (lokaal, read-only)."""
from __future__ import annotations

from flask import Flask, abort, jsonify, render_template, request

from ..config import load_settings, Settings
from ..logbook.store import Logbook
from . import service


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config["STOX_SETTINGS"] = settings

    def book() -> Logbook:
        return Logbook(settings.db_path)

    @app.context_processor
    def inject_globals():
        return {"model": settings.model, "nav_categories": service.categories(settings)}

    @app.route("/")
    def index():
        category = request.args.get("category") or None
        b = book()
        try:
            rows = service.overview_rows(settings, b, category)
        finally:
            b.close()
        return render_template(
            "overview.html", rows=rows, categories=service.categories(settings),
            active_category=category,
        )

    @app.route("/stock/<path:symbol>")
    def stock(symbol: str):
        b = book()
        try:
            detail = service.stock_detail(settings, b, symbol)
        finally:
            b.close()
        if detail is None:
            abort(404)
        return render_template("detail.html", d=detail)

    @app.route("/news")
    def news():
        symbol = request.args.get("symbol") or None
        b = book()
        try:
            items = service.news_feed(b, symbol)
        finally:
            b.close()
        return render_template("news.html", items=items, symbol=symbol)

    @app.route("/report")
    def report():
        b = book()
        try:
            data = service.report_data(settings, b)
        finally:
            b.close()
        return render_template("report.html", r=data)

    @app.route("/logbook")
    def logbook():
        b = book()
        try:
            rows = service.logbook_rows(b)
        finally:
            b.close()
        return render_template("logbook.html", rows=rows)

    @app.route("/api/prices/<path:symbol>")
    def api_prices(symbol: str):
        period = request.args.get("range", "6mo")
        return jsonify(service.price_series(symbol, period))

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("not_found.html"), 404

    return app
