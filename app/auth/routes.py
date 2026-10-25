from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.models import AdminUser, FestivalSettings, Member
from app.utils import is_valid_email, is_valid_phone, normalize_email

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

MIN_PASSWORD_LENGTH = 8


def _is_safe_next(target):
    """Allow only same-site absolute-path redirects (blocks //host, scheme and backslash tricks)."""
    if not target or not target.startswith("/") or "\\" in target:
        return False
    parts = urlparse(target)
    return not parts.scheme and not parts.netloc and not target.startswith("//")


def _default_landing():
    """Admins land in the admin console; members land on their account page."""
    if getattr(current_user, "role", None) == "member":
        return url_for("member.account")
    return url_for("admin.dashboard")


def _resolve_login(email, password):
    """Find the account matching an email, whichever table it lives in."""
    admin = AdminUser.query.filter_by(email=email).first()
    if admin and admin.check_password(password):
        return admin
    member = Member.query.filter_by(email=email).first()
    if member and member.check_password(password):
        return member
    return None


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_default_landing())

    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""
        user = _resolve_login(email, password) if is_valid_email(email) else None
        if user is not None:
            login_user(user)
            if _is_safe_next(request.args.get("next")):
                return redirect(request.args.get("next"))
            return redirect(_default_landing())
        flash("Invalid email or password.", "error")

    return render_template("auth/login.html", settings=FestivalSettings.get())


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(_default_landing())

    form_values = request.form
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = normalize_email(request.form.get("email"))
        phone = (request.form.get("phone") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        errors = {}
        if not full_name or len(full_name) > 120:
            errors["full_name"] = "Please provide your full name (max 120 characters)."
        if not is_valid_email(email):
            errors["email"] = "Please provide a valid email address."
        if phone and not is_valid_phone(phone):
            errors["phone"] = "Please provide a valid phone number."
        if len(password) < MIN_PASSWORD_LENGTH:
            errors["password"] = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        elif password != confirm:
            errors["confirm_password"] = "Passwords do not match."

        if not errors:
            taken = (
                Member.query.filter_by(email=email).first()
                or AdminUser.query.filter_by(email=email).first()
            )
            if taken:
                errors["email"] = "An account with this email already exists."

        if not errors:
            member = Member(full_name=full_name, email=email, phone=phone or None)
            member.set_password(password)
            db.session.add(member)
            db.session.commit()
            login_user(member)
            flash("Welcome to EventHub! Your account is ready.", "success")
            return redirect(url_for("member.account"))

        return (
            render_template(
                "auth/signup.html",
                settings=FestivalSettings.get(),
                errors=errors,
                form_values=form_values,
            ),
            400,
        )

    return render_template(
        "auth/signup.html", settings=FestivalSettings.get(), errors={}, form_values={}
    )


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("public.index"))
