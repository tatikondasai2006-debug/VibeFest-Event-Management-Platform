import os
import sys

import click
from flask import Flask
from werkzeug.security import check_password_hash

from app.db import configure_sqlite_engine
from app.extensions import csrf, db, limiter, login_manager, migrate
from app.models import AdminUser, FestivalSettings
from app.services.seed import seed_demo_data


def create_app(config_name: str | None = None) -> Flask:
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")
        if config_name == "production":
            app_config = "production"
        elif config_name == "testing":
            app_config = "testing"
        else:
            app_config = "development"
    else:
        app_config = config_name

    from config import config_by_name

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name.get(app_config, config_by_name["development"]))

    if app.config.get("TESTING") and os.environ.get("TEST_DATABASE_URL"):
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["TEST_DATABASE_URL"]

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    @login_manager.user_loader
    def _load_user(user_id):
        try:
            return db.session.get(AdminUser, int(user_id))
        except (TypeError, ValueError):
            return None

    csrf.init_app(app)
    limiter.init_app(app)
    configure_sqlite_engine(app, db)

    _register_blueprints(app)
    _register_cli(app)
    _register_security(app)
    _register_error_handlers(app)

    with app.app_context():
        _ensure_settings()

    return app


def _register_blueprints(app: Flask) -> None:
    from app.admin.routes import admin_bp
    from app.auth.routes import auth_bp
    from app.public.routes import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)


def _ensure_settings() -> None:
    try:
        FestivalSettings.get()
    except Exception:
        db.session.rollback()


def _register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    def create_admin():
        """Interactively create an administrator account."""
        username = click.prompt("Admin username").strip()
        if not username:
            click.echo("Username cannot be empty.")
            sys.exit(1)
        existing = AdminUser.query.filter_by(username=username).first()
        if existing:
            click.echo(f"An admin with username '{username}' already exists.")
            sys.exit(1)

        while True:
            password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
            if len(password) < 8:
                click.echo("Password must be at least 8 characters long.")
                continue
            if password.lower() in ("password", "12345678", "password1"):
                click.echo("That password is too common. Choose a stronger one.")
                continue
            break

        admin = AdminUser(username=username)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Administrator '{username}' created.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Seed demonstration events and registrations (never in production)."""
        if app.config.get("ENV") == "production" or app.config.get("PRODUCTION"):
            click.echo("Refusing to seed demo data in a production environment.")
            sys.exit(1)
        summary = seed_demo_data()
        click.echo(summary)

    @app.cli.command("reset-admin-password")
    @click.argument("username")
    def reset_admin_password(username):
        """Reset an existing administrator's password interactively."""
        admin = AdminUser.query.filter_by(username=username).first()
        if not admin:
            click.echo(f"No admin found with username '{username}'.")
            sys.exit(1)
        while True:
            password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
            if len(password) < 8:
                click.echo("Password must be at least 8 characters long.")
                continue
            break
        admin.set_password(password)
        db.session.commit()
        click.echo(f"Password updated for '{username}'.")


def _register_security(app: Flask) -> None:
    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        csp = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def _register_error_handlers(app: Flask) -> None:
    from flask_wtf.csrf import CSRFError
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        from flask import render_template

        if exc.code == 404:
            return render_template("errors/404.html"), 404
        if exc.code == 429:
            return render_template("errors/429.html"), 429
        if exc.code == 400 and isinstance(exc, HTTPException):
            return render_template(
                "errors/error.html",
                code=exc.code,
                title=exc.name,
                message=exc.description,
            ), exc.code
        return render_template(
            "errors/error.html",
            code=exc.code,
            title=exc.name,
            message=exc.description,
        ), exc.code

    @app.errorhandler(CSRFError)
    def handle_csrf_error(exc):
        from flask import flash, redirect, request, url_for

        flash("Your session expired. Please try again.", "error")
        return redirect(request.referrer or url_for("public.index"))

    @app.errorhandler(500)
    def handle_500(exc):
        from flask import render_template

        db.session.rollback()
        return render_template("errors/500.html"), 500
