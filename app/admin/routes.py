import json
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.models import (
    CATEGORIES,
    CATEGORY_LABELS,
    REG_CANCELLED,
    REG_CONFIRMED,
    REGISTRATION_MODE_LABELS,
    AdminUser,
    Event,
    FestivalSettings,
    Registration,
    Team,
    TeamMember,
)
from app.services import analytics, csv_export
from app.services.custom_fields import validate_custom_fields
from app.utils import (
    is_valid_email,
    is_valid_phone,
    make_reference,
    normalize_email,
    parse_local_datetime,
    to_display,
    utcnow,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@login_required
def require_admin():
    """Only administrator accounts may use the admin console."""
    if getattr(current_user, "role", None) != "admin":
        abort(403)


def _tz() -> str:
    return FestivalSettings.get().display_timezone


# ---------------------------------------------------------------- dashboard


@admin_bp.route("/")
def dashboard():
    include_demo = request.args.get("demo", "1") == "1"
    tz = _tz()
    metrics = analytics.dashboard_metrics(tz, include_demo=include_demo)
    over_time = analytics.registrations_over_time(tz, include_demo=include_demo)
    by_event = analytics.registrations_by_event(include_demo=include_demo)
    by_category = analytics.registrations_by_category(include_demo=include_demo)
    utilisation = analytics.capacity_utilization_by_event(include_demo=include_demo)
    recent = (
        Registration.query.filter(Registration.status == REG_CONFIRMED)
        .order_by(Registration.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "admin/dashboard.html",
        metrics=metrics,
        over_time=json.dumps(over_time),
        by_event=json.dumps(by_event),
        by_category=json.dumps(by_category),
        utilisation=json.dumps(utilisation),
        recent=recent,
        include_demo=include_demo,
        tz=tz,
    )


# ---------------------------------------------------------------- events


@admin_bp.route("/events")
def events_list():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    query = Event.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Event.title.ilike(like), Event.slug.ilike(like)))
    if status in ("draft", "published", "cancelled"):
        query = query.filter(Event.status == status)
    events = query.order_by(Event.starts_at.desc()).all()
    tz = _tz()
    rows = []
    for event in events:
        used = event.used_capacity()
        rows.append(
            {
                "event": event,
                "used": used,
                "seats_left": max(event.capacity - used, 0),
                "starts_display": to_display(event.starts_at, tz),
                "category_label": CATEGORY_LABELS.get(event.category, event.category),
            }
        )
    return render_template(
        "admin/events_list.html",
        rows=rows,
        search_query=q,
        selected_status=status,
    )


def _parse_event_form(form) -> tuple[dict | None, dict[str, str]]:
    errors: dict[str, str] = {}
    title = (form.get("title") or "").strip()
    description = (form.get("description") or "").strip()
    category = (form.get("category") or "").strip()
    venue = (form.get("venue") or "").strip() or None
    organizer = (form.get("organizer") or "").strip() or None
    capacity_unit = (form.get("capacity_unit") or "seats").strip()
    registration_mode = (form.get("registration_mode") or "individual").strip()
    status = (form.get("status") or "draft").strip()
    registration_status = (form.get("registration_status") or "open").strip()

    tz = _tz()
    starts_raw = (form.get("starts_at") or "").strip()
    ends_raw = (form.get("ends_at") or "").strip()
    deadline_raw = (form.get("registration_deadline") or "").strip()

    if not title:
        errors["title"] = "Title is required."
    if category not in CATEGORY_LABELS:
        errors["category"] = "Choose a valid category."
    if registration_mode not in REGISTRATION_MODE_LABELS:
        errors["registration_mode"] = "Choose a valid registration mode."
    if status not in ("draft", "published", "cancelled"):
        errors["status"] = "Choose a valid status."
    if registration_status not in ("open", "closed"):
        errors["registration_status"] = "Choose a valid registration status."

    try:
        capacity = int(form.get("capacity") or 0)
        if capacity < 1:
            raise ValueError
    except (ValueError, TypeError):
        errors["capacity"] = "Capacity must be a positive whole number."
        capacity = None

    starts_at = ends_at = deadline = None
    if not starts_raw:
        errors["starts_at"] = "Start time is required."
    else:
        try:
            starts_at = parse_local_datetime(starts_raw, tz)
        except ValueError:
            errors["starts_at"] = "Enter a valid start date and time."
    if not ends_raw:
        errors["ends_at"] = "End time is required."
    else:
        try:
            ends_at = parse_local_datetime(ends_raw, tz)
        except ValueError:
            errors["ends_at"] = "Enter a valid end date and time."
    if starts_at and ends_at and ends_at <= starts_at:
        errors["ends_at"] = "End time must be after the start time."
    if deadline_raw:
        try:
            deadline = parse_local_datetime(deadline_raw, tz)
        except ValueError:
            errors["registration_deadline"] = "Enter a valid deadline."

    team_min = int(form.get("team_min_size") or 2)
    team_max = int(form.get("team_max_size") or 5)
    if registration_mode == "team":
        if team_min < 1 or team_max < team_min:
            errors["team_max_size"] = "Team size limits are invalid."

    custom_raw = (form.get("custom_fields_json") or "").strip()
    custom_fields: list = []
    if custom_raw:
        try:
            custom_fields = validate_custom_fields(json.loads(custom_raw))
        except (json.JSONDecodeError, ValueError) as exc:
            errors["custom_fields_json"] = str(exc)

    if errors:
        return None, errors

    data = {
        "title": title,
        "description": description,
        "category": category,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "registration_deadline": deadline,
        "venue": venue,
        "organizer": organizer,
        "capacity": capacity,
        "capacity_unit": capacity_unit,
        "registration_mode": registration_mode,
        "status": status,
        "registration_status": registration_status,
        "team_min_size": team_min,
        "team_max_size": team_max,
        "custom_fields": custom_fields,
    }
    return data, {}


@admin_bp.route("/events/new", methods=["GET", "POST"])
def event_new():
    if request.method == "POST":
        data, errors = _parse_event_form(request.form)
        if errors:
            return render_template(
                "admin/event_form.html",
                event=None,
                errors=errors,
                form_values=request.form,
                categories=CATEGORIES,
                modes=list(REGISTRATION_MODE_LABELS.items()),
            ), 400
        event = Event.create_event(**data)
        event.is_demo = False
        db.session.commit()
        flash(f"Event '{event.title}' created.", "success")
        return redirect(url_for("admin.event_detail", event_id=event.id))
    return render_template(
        "admin/event_form.html",
        event=None,
        errors={},
        form_values={},
        categories=CATEGORIES,
        modes=list(REGISTRATION_MODE_LABELS.items()),
    )


@admin_bp.route("/events/<int:event_id>")
def event_detail(event_id: int):
    event = db.get_or_404(Event, event_id)
    tz = _tz()
    used = event.used_capacity()
    registrations = (
        Registration.query.filter_by(event_id=event.id)
        .order_by(Registration.created_at.desc())
        .limit(50)
        .all()
    )
    teams = []
    if event.registration_mode == "team":
        teams = (
            Team.query.filter_by(event_id=event.id)
            .order_by(Team.created_at.desc())
            .limit(50)
            .all()
        )
    return render_template(
        "admin/event_detail.html",
        event=event,
        used=used,
        seats_left=max(event.capacity - used, 0),
        starts_display=to_display(event.starts_at, tz),
        ends_display=to_display(event.ends_at, tz),
        deadline_display=to_display(event.registration_deadline, tz)
        if event.registration_deadline
        else None,
        category_label=CATEGORY_LABELS.get(event.category, event.category),
        registrations=registrations,
        teams=teams,
    )


@admin_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def event_edit(event_id: int):
    event = db.get_or_404(Event, event_id)
    if request.method == "POST":
        data, errors = _parse_event_form(request.form)
        if errors:
            return render_template(
                "admin/event_form.html",
                event=event,
                errors=errors,
                form_values=request.form,
                categories=CATEGORIES,
                modes=list(REGISTRATION_MODE_LABELS.items()),
            ), 400
        if (
            data["registration_mode"] != event.registration_mode
            and event.used_capacity() > 0
        ):
            errors["registration_mode"] = (
                "Registration mode cannot change once registrations exist."
            )
            return render_template(
                "admin/event_form.html",
                event=event,
                errors=errors,
                form_values=request.form,
                categories=CATEGORIES,
                modes=list(REGISTRATION_MODE_LABELS.items()),
            ), 400
        try:
            if data["capacity"] < event.capacity:
                event.ensure_capacity_for(data["capacity"])
        except ValueError as exc:
            errors["capacity"] = str(exc)
            return render_template(
                "admin/event_form.html",
                event=event,
                errors=errors,
                form_values=request.form,
                categories=CATEGORIES,
                modes=list(REGISTRATION_MODE_LABELS.items()),
            ), 400
        for key, value in data.items():
            setattr(event, key, value)
        db.session.commit()
        flash(f"Event '{event.title}' updated.", "success")
        return redirect(url_for("admin.event_detail", event_id=event.id))

    tz = _tz()
    return render_template(
        "admin/event_form.html",
        event=event,
        errors={},
        form_values={},
        categories=CATEGORIES,
        modes=list(REGISTRATION_MODE_LABELS.items()),
        starts_value=to_display(event.starts_at, tz).strftime("%Y-%m-%dT%H:%M"),
        ends_value=to_display(event.ends_at, tz).strftime("%Y-%m-%dT%H:%M"),
        deadline_value=to_display(event.registration_deadline, tz).strftime(
            "%Y-%m-%dT%H:%M"
        )
        if event.registration_deadline
        else "",
        custom_fields_json=json.dumps(event.custom_fields or [], indent=2),
    )


@admin_bp.route("/events/<int:event_id>/publish", methods=["POST"])
def event_publish(event_id: int):
    event = db.get_or_404(Event, event_id)
    if event.status == "cancelled":
        flash("A cancelled event cannot be published.", "error")
    else:
        event.publish()
        db.session.commit()
        flash(f"'{event.title}' published.", "success")
    return redirect(url_for("admin.event_detail", event_id=event.id))


@admin_bp.route("/events/<int:event_id>/close-registration", methods=["POST"])
def event_close(event_id: int):
    event = db.get_or_404(Event, event_id)
    event.close_registration()
    db.session.commit()
    flash(f"Registration closed for '{event.title}'.", "success")
    return redirect(url_for("admin.event_detail", event_id=event.id))


@admin_bp.route("/events/<int:event_id>/reopen-registration", methods=["POST"])
def event_reopen(event_id: int):
    event = db.get_or_404(Event, event_id)
    try:
        event.reopen_registration()
        db.session.commit()
        flash(f"Registration reopened for '{event.title}'.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("admin.event_detail", event_id=event.id))


@admin_bp.route("/events/<int:event_id>/cancel", methods=["POST"])
def event_cancel(event_id: int):
    event = db.get_or_404(Event, event_id)
    confirm = (request.form.get("confirm_title") or "").strip()
    if confirm != event.title:
        flash("Type the exact event title to confirm cancellation.", "error")
        return redirect(url_for("admin.event_detail", event_id=event.id))
    event.cancel()
    db.session.commit()
    flash(f"'{event.title}' cancelled. Registrations are retained for history.", "success")
    return redirect(url_for("admin.event_detail", event_id=event.id))


# ---------------------------------------------------------------- applicants


@admin_bp.route("/applicants")
def applicants():
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    event_id = request.args.get("event_id", type=int)
    status = (request.args.get("status") or "").strip()
    include_demo = request.args.get("demo", "1") == "1"

    query = Registration.query
    if not include_demo:
        query = query.filter(Registration.is_demo.is_(False))
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Registration.full_name.ilike(like),
                Registration.email.ilike(like),
                Registration.normalized_email.ilike(normalize_email(q)),
            )
        )
    if event_id:
        query = query.filter(Registration.event_id == event_id)
    if status in (REG_CONFIRMED, REG_CANCELLED):
        query = query.filter(Registration.status == status)

    pagination = query.order_by(Registration.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    tz = _tz()
    events = Event.query.order_by(Event.starts_at.desc()).all()
    return render_template(
        "admin/applicants.html",
        pagination=pagination,
        registrations=pagination.items,
        events=events,
        search_query=q,
        selected_event=event_id,
        selected_status=status,
        include_demo=include_demo,
        to_display=to_display,
        tz=tz,
    )


@admin_bp.route("/applicants/<int:reg_id>")
def applicant_detail(reg_id: int):
    registration = db.get_or_404(Registration, reg_id)
    tz = _tz()
    return render_template(
        "admin/applicant_detail.html",
        registration=registration,
        event=registration.event,
        registered_display=to_display(registration.created_at, tz),
        consent_display=to_display(registration.consent_at, tz)
        if registration.consent_at
        else None,
    )


@admin_bp.route("/teams/<int:team_id>")
def team_detail(team_id: int):
    team = db.get_or_404(Team, team_id)
    tz = _tz()
    members = TeamMember.query.filter_by(team_id=team.id).all()
    return render_template(
        "admin/team_detail.html",
        team=team,
        event=team.event,
        members=members,
        registered_display=to_display(team.created_at, tz),
    )


@admin_bp.route("/registrations/<int:reg_id>/cancel", methods=["POST"])
def registration_cancel(reg_id: int):
    registration = db.get_or_404(Registration, reg_id)
    if registration.status == REG_CANCELLED:
        flash("This registration is already cancelled.", "warning")
    else:
        registration.status = REG_CANCELLED
        registration.cancelled_at = utcnow()
        db.session.commit()
        flash(f"Registration {registration.reference} cancelled.", "success")
    return redirect(url_for("admin.applicant_detail", reg_id=reg_id))


@admin_bp.route("/teams/<int:team_id>/cancel", methods=["POST"])
def team_cancel(team_id: int):
    team = db.get_or_404(Team, team_id)
    if team.status == REG_CANCELLED:
        flash("This team is already cancelled.", "warning")
    else:
        team.status = REG_CANCELLED
        team.cancelled_at = utcnow()
        db.session.commit()
        flash(f"Team {team.reference} cancelled.", "success")
    return redirect(url_for("admin.team_detail", team_id=team_id))


# ---------------------------------------------------------------- analytics / reports


@admin_bp.route("/analytics")
def analytics_page():
    include_demo = request.args.get("demo", "1") == "1"
    tz = _tz()
    metrics = analytics.dashboard_metrics(tz, include_demo=include_demo)
    over_time = analytics.registrations_over_time(tz, include_demo=include_demo)
    by_event = analytics.registrations_by_event(include_demo=include_demo)
    by_category = analytics.registrations_by_category(include_demo=include_demo)
    utilisation = analytics.capacity_utilization_by_event(include_demo=include_demo)
    return render_template(
        "admin/analytics.html",
        metrics=metrics,
        over_time=json.dumps(over_time),
        by_event=json.dumps(by_event),
        by_category=json.dumps(by_category),
        utilisation=json.dumps(utilisation),
        include_demo=include_demo,
        tz=tz,
    )


@admin_bp.route("/reports")
def reports():
    events = Event.query.order_by(Event.starts_at.desc()).all()
    return render_template("admin/reports.html", events=events)


@admin_bp.route("/reports/export")
@login_required
def reports_export():
    kind = request.args.get("kind", "registrations")
    event_id = request.args.get("event_id", type=int)
    status = (request.args.get("status") or "").strip() or None
    include_demo = request.args.get("demo", "1") == "1"
    tz = _tz()

    if kind == "teams":
        content = csv_export.export_teams_csv(
            event_id=event_id, status=status, tz_name=tz, include_demo=include_demo
        )
        filename = "vibefest-teams.csv"
    else:
        content = csv_export.export_registrations_csv(
            event_id=event_id, status=status, tz_name=tz, include_demo=include_demo
        )
        filename = "vibefest-registrations.csv"

    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------- settings


@admin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    row = FestivalSettings.get()
    if request.method == "POST":
        name = (request.form.get("festival_name") or "").strip()
        tagline = (request.form.get("tagline") or "").strip()
        venue = (request.form.get("venue") or "").strip() or None
        college = (request.form.get("college_name") or "").strip() or None
        email = (request.form.get("contact_email") or "").strip() or None
        phone = (request.form.get("contact_phone") or "").strip() or None
        tz_name = (request.form.get("display_timezone") or "Asia/Kolkata").strip()
        instructions = (request.form.get("registration_instructions") or "").strip() or None
        start_raw = (request.form.get("start_date") or "").strip()
        end_raw = (request.form.get("end_date") or "").strip()

        errors = []
        if not name:
            errors.append("Festival name is required.")
        if email and not is_valid_email(email):
            errors.append("Contact email is invalid.")
        if phone and not is_valid_phone(phone):
            errors.append("Contact phone is invalid.")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz_name)
        except Exception:
            errors.append("Display timezone must be a valid IANA timezone.")

        start_date = end_date = None
        if start_raw:
            try:
                start_date = datetime.fromisoformat(start_raw).date()
            except ValueError:
                errors.append("Start date is invalid.")
        if end_raw:
            try:
                end_date = datetime.fromisoformat(end_raw).date()
            except ValueError:
                errors.append("End date is invalid.")
        if start_date and end_date and end_date < start_date:
            errors.append("End date cannot be before the start date.")

        if errors:
            for msg in errors:
                flash(msg, "error")
        else:
            row.festival_name = name
            row.tagline = tagline
            row.venue = venue
            row.college_name = college
            row.contact_email = email
            row.contact_phone = phone
            row.display_timezone = tz_name
            row.registration_instructions = instructions
            row.start_date = start_date
            row.end_date = end_date
            db.session.commit()
            flash("Festival settings saved.", "success")
            return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", settings=row)


@admin_bp.route("/settings/password", methods=["POST"])
@limiter.limit("5 per minute")
def change_password():
    current = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    if not current_user.check_password(current):
        flash("Current password is incorrect.", "error")
    elif len(new_password) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new_password != confirm:
        flash("New passwords do not match.", "error")
    else:
        current_user.set_password(new_password)
        db.session.commit()
        flash("Password updated.", "success")
    return redirect(url_for("admin.settings"))
