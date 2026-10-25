from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import (
    CATEGORY_LABELS,
    REG_CANCELLED,
    REG_CONFIRMED,
    FestivalSettings,
    Registration,
    Team,
    TeamMember,
)
from app.utils import to_display, utcnow

member_bp = Blueprint("member", __name__, url_prefix="/account")


@member_bp.before_request
@login_required
def require_member():
    """Only attendee accounts may use these pages; admins are redirected to the console."""
    if getattr(current_user, "role", None) != "member":
        flash("That area is for member accounts.", "warning")
        return redirect(url_for("admin.dashboard"))


def _tz() -> str:
    return FestivalSettings.get().display_timezone


@member_bp.route("/")
def account():
    tz = _tz()
    email = current_user.email

    registrations = (
        Registration.query.filter(Registration.normalized_email == email)
        .options(db.joinedload(Registration.event))
        .order_by(Registration.created_at.desc())
        .all()
    )
    teams = (
        Team.query.join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.normalized_email == email)
        .options(db.joinedload(Team.event), db.joinedload(Team.members))
        .order_by(Team.created_at.desc())
        .all()
    )

    reg_rows = [
        {
            "registration": r,
            "event": r.event,
            "category_label": CATEGORY_LABELS.get(r.event.category, r.event.category)
            if r.event
            else "",
            "registered_display": to_display(r.created_at, tz),
            "cancellable": r.status == REG_CONFIRMED
            and r.event is not None
            and r.event.starts_at > utcnow(),
        }
        for r in registrations
    ]
    team_rows = [
        {
            "team": t,
            "event": t.event,
            "role": next(
                (m.role for m in t.members if m.normalized_email == email), "member"
            ),
            "registered_display": to_display(t.created_at, tz),
        }
        for t in teams
    ]

    return render_template(
        "member/account.html",
        settings=FestivalSettings.get(),
        reg_rows=reg_rows,
        team_rows=team_rows,
        member=current_user,
    )


@member_bp.route("/registrations/<int:registration_id>/cancel", methods=["POST"])
def cancel_registration(registration_id: int):
    registration = db.session.get(Registration, registration_id)
    if registration is None or registration.normalized_email != current_user.email:
        flash("We couldn't find that registration on your account.", "error")
        return redirect(url_for("member.account"))

    if registration.status == REG_CANCELLED:
        flash("That registration is already cancelled.", "warning")
        return redirect(url_for("member.account"))

    event = registration.event
    if event is not None and event.starts_at <= utcnow():
        flash("This event has already started, so it can no longer be cancelled.", "error")
        return redirect(url_for("member.account"))

    registration.status = REG_CANCELLED
    registration.cancelled_at = utcnow()
    db.session.commit()
    flash("Your registration has been cancelled.", "success")
    return redirect(url_for("member.account"))
