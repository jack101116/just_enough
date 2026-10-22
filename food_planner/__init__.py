"""Just Enough: smart event food planning and surplus donation platform."""
import hmac
import secrets
import sqlite3

from flask import Flask, abort, render_template, request, session

import config as app_config
from . import db as database
from .utils import formatting


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=False,
                template_folder="../templates", static_folder="../static")
    app.config.update(app_config.build_config())
    if test_config:
        app.config.update(test_config)
    app.config["DEBUG"] = app.config.get("DEBUG_MODE", False)

    database.init_schema(database.connect(app.config["DATABASE"]))
    app.teardown_appcontext(database.close_db)

    for name in ("kg", "num", "pct", "fmt_date", "fmt_datetime", "status_label", "diet_label"):
        app.add_template_filter(getattr(formatting, name), name)

    def csrf_token():
        token = session.get("_csrf")
        if not token:
            token = secrets.token_hex(16)
            session["_csrf"] = token
        return token

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect_from_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
            expected = session.get("_csrf", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, description="Your session expired or the form was invalid. Please go back, refresh and try again.")

    @app.context_processor
    def inject_globals():
        from .services.donations import STATUSES
        ep = (request.endpoint or "").split(".")[-1]
        if ep in ("index", "dashboard"):
            nav = ep
        elif ep.startswith("event") or ep in ("planner", "risk", "risk_apply", "preview"):
            nav = "events"
        elif ep.startswith("dish"):
            nav = "dishes"
        elif ep.startswith("donation"):
            nav = "donations"
        elif ep.startswith("ngo"):
            nav = "ngos"
        elif ep.startswith("report"):
            nav = "reports"
        else:
            nav = ""
        return {"currency": app.config["CURRENCY_SYMBOL"], "active": ep, "nav": nav,
                "donation_statuses": STATUSES}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; "
            "form-action 'self'; frame-ancestors 'none'")
        return resp

    def error_page(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return error_page(400, "Request could not be processed", getattr(e, "description", "Bad request."))

    @app.errorhandler(404)
    def not_found(_e):
        return error_page(404, "Page not found", "We could not find what you were looking for.")

    @app.errorhandler(405)
    def not_allowed(_e):
        return error_page(405, "Method not allowed", "That action is not allowed on this page.")

    @app.errorhandler(sqlite3.Error)
    def db_error(e):
        app.logger.exception("Database error: %s", e)
        return error_page(500, "Database problem", "The database could not complete that action. Your data was not changed.")

    @app.errorhandler(500)
    def server_error(_e):
        return error_page(500, "Something went wrong", "An unexpected error occurred. Please try again.")

    from .routes import bp
    app.register_blueprint(bp)
    return app
