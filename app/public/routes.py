from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import login_required

from app.extensions import db, limiter
from app.models import (
    CATEGORIES,
    REG_CONFIRMED,
    CATEGORY_LABELS,
    Event,
    FestivalSettings,
    Registration,
    Team,
)
from app.services.registration import RegistrationError, register_individual, register_team
from app.utils import to_display, utcnow

public_bp = Blueprint("public", __name__)


def _visible_events_query():
    return Event.query.filter(Event.status == "published").order_by(Event.starts_at.asc())


def _event_card_context(event: Event, tz_name: str) -> dict:
    allowed, reason = event.is_registration_allowed()
    used = event.used_capacity()
    return {
        "event": event,
        "category_label": CATEGORY_LABELS.get(event.category, event.category),
        "starts_display": to_display(event.starts_at, tz_name),
        "ends_display": to_display(event.ends_at, tz_name),
        "used": used,
        "seats_left": max(event.capacity - used, 0),
        "registration_open": allowed,
        "closed_reason": reason,
    }


@public_bp.route("/")
def index():
    settings = FestivalSettings.get()
    tz = settings.display_timezone
    events = _visible_events_query().all()
    featured = [e for e in events if e.registration_status == "open"][:6]

    total_confirmed = (
        db.session.query(db.func.count(Registration.id))
        .filter(Registration.status == REG_CONFIRMED)
        .scalar()
        or 0
    )
    total_teams = (
        db.session.query(db.func.count(Team.id)).filter(Team.status == REG_CONFIRMED).scalar()
        or 0
    )

    category_cards = []
    for key, label in CATEGORIES:
        count = len([e for e in events if e.category == key])
        category_cards.append({"key": key, "label": label, "count": count})

    return render_template(
        "public/index.html",
        settings=settings,
        category_cards=category_cards,
        featured=[_event_card_context(e, tz) for e in featured],
        total_confirmed=total_confirmed,
        total_teams=total_teams,
        total_events=len(events),
    )


@public_bp.route("/events")
@login_required
def events():
    settings = FestivalSettings.get()
    tz = settings.display_timezone
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    availability = (request.args.get("availability") or "").strip()

    query = _visible_events_query()
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Event.title.ilike(like),
                Event.description.ilike(like),
                Event.venue.ilike(like),
            )
        )
    if category in CATEGORY_LABELS:
        query = query.filter(Event.category == category)

    all_cards = [_event_card_context(e, tz) for e in query.all()]
    if availability == "open":
        all_cards = [c for c in all_cards if c["registration_open"]]
    elif availability == "full":
        all_cards = [c for c in all_cards if c["seats_left"] == 0]

    return render_template(
        "public/events.html",
        settings=settings,
        cards=all_cards,
        categories=CATEGORIES,
        selected_category=category,
        selected_availability=availability,
        search_query=q,
    )


@public_bp.route("/events/<slug>")
def event_detail(slug: str):
    event = Event.query.filter_by(slug=slug).first_or_404()
    if event.status == "draft":
        abort(404)
    settings = FestivalSettings.get()
    tz = settings.display_timezone
    allowed, reason = event.is_registration_allowed()
    ctx = _event_card_context(event, tz)
    ctx.update(
        {
            "settings": settings,
            "registration_allowed": allowed,
            "closed_reason": reason,
            "custom_fields": event.custom_fields or [],
        }
    )
    return render_template("public/event_detail.html", **ctx)


@public_bp.route("/events/<slug>/register", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def event_register(slug: str):
    event = Event.query.filter_by(slug=slug).first_or_404()
    if event.status == "draft":
        abort(404)
    settings = FestivalSettings.get()
    tz = settings.display_timezone
    allowed, reason = event.is_registration_allowed()

    if request.method == "POST":
        if not allowed:
            return (
                render_template(
                    "public/register.html",
                    event=event,
                    settings=settings,
                    registration_allowed=False,
                    closed_reason=reason,
                    errors={"form": reason},
                    form_values=request.form,
                    custom_fields=event.custom_fields or [],
                    starts_display=to_display(event.starts_at, tz),
                    category_label=CATEGORY_LABELS.get(event.category, event.category),
                ),
                400,
            )
        try:
            if event.registration_mode == "team":
                team = register_team(event, request.form)
                return render_template(
                    "public/confirmation.html",
                    settings=settings,
                    reference=team.reference,
                    event=event,
                    kind="team",
                    team=team,
                )
            registration = register_individual(event, request.form)
            return render_template(
                "public/confirmation.html",
                settings=settings,
                reference=registration.reference,
                event=event,
                kind="individual",
                registration=registration,
            )
        except RegistrationError as exc:
            return (
                render_template(
                    "public/register.html",
                    event=event,
                    settings=settings,
                    registration_allowed=True,
                    closed_reason="",
                    errors={"form": exc.message},
                    form_values=request.form,
                    custom_fields=event.custom_fields or [],
                    starts_display=to_display(event.starts_at, tz),
                    category_label=CATEGORY_LABELS.get(event.category, event.category),
                ),
                400,
            )

    if not allowed:
        return (
            render_template(
                "public/register.html",
                event=event,
                settings=settings,
                registration_allowed=False,
                closed_reason=reason,
                errors={},
                form_values={},
                custom_fields=event.custom_fields or [],
                starts_display=to_display(event.starts_at, tz),
                category_label=CATEGORY_LABELS.get(event.category, event.category),
            ),
            403,
        )

    return render_template(
        "public/register.html",
        event=event,
        settings=settings,
        registration_allowed=True,
        closed_reason="",
        errors={},
        form_values={},
        custom_fields=event.custom_fields or [],
        starts_display=to_display(event.starts_at, tz),
        category_label=CATEGORY_LABELS.get(event.category, event.category),
    )


@public_bp.route("/registration/<reference>/confirmed")
def registration_confirmed(reference: str):
    registration = Registration.query.filter_by(reference=reference).first_or_404()
    settings = FestivalSettings.get()
    tz = settings.display_timezone
    return render_template(
        "public/confirmation_page.html",
        settings=settings,
        registration=registration,
        event=registration.event,
        registered_display=to_display(registration.created_at, tz),
    )


@public_bp.route("/team/<reference>/confirmed")
def team_confirmed(reference: str):
    team = Team.query.filter_by(reference=reference).first_or_404()
    settings = FestivalSettings.get()
    tz = settings.display_timezone
    return render_template(
        "public/team_confirmation_page.html",
        settings=settings,
        team=team,
        event=team.event,
        registered_display=to_display(team.created_at, tz),
    )


@public_bp.route("/about")
def about():
    settings = FestivalSettings.get()
    return render_template("public/about.html", settings=settings)


@public_bp.route("/contact")
def contact():
    settings = FestivalSettings.get()
    return render_template("public/contact.html", settings=settings)


@public_bp.route("/api/events/<slug>/counts")
def event_counts(slug: str):
    """Aggregate-only public counts endpoint. Never returns personal data."""
    event = Event.query.filter_by(slug=slug).first_or_404()
    if event.status == "draft":
        abort(404)
    allowed, _ = event.is_registration_allowed()
    used = event.used_capacity()
    return jsonify(
        registered=used,
        capacity=event.capacity,
        seats_left=max(event.capacity - used, 0),
        registration_open=allowed,
    )


@public_bp.route("/api/summary")
def festival_summary():
    """Aggregate festival-wide counts for the live summary strip."""
    total_confirmed = (
        db.session.query(db.func.count(Registration.id))
        .filter(Registration.status == REG_CONFIRMED)
        .scalar()
        or 0
    )
    total_teams = (
        db.session.query(db.func.count(Team.id)).filter(Team.status == REG_CONFIRMED).scalar()
        or 0
    )
    total_events = Event.query.filter(Event.status == "published").count()
    return jsonify(
        registrations=total_confirmed,
        teams=total_teams,
        events=total_events,
    )
