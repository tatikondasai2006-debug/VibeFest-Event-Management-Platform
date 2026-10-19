"""Dashboard analytics computed strictly from database records."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.extensions import db
from app.models import (
    CATEGORIES,
    REG_CANCELLED,
    REG_CONFIRMED,
    Event,
    Registration,
    Team,
)
from app.utils import local_day_start_utc


def _confirmed_regs(event_id=None):
    q = db.session.query(Registration).filter(Registration.status == REG_CONFIRMED)
    if event_id:
        q = q.filter(Registration.event_id == event_id)
    return q


def _published_events():
    return db.session.query(Event).filter(Event.status == "published")


def _event_capacity_used(event: Event) -> tuple[int, int]:
    if event.registration_mode == "team":
        used = (
            db.session.query(func.count(Team.id))
            .filter(Team.event_id == event.id, Team.status == REG_CONFIRMED)
            .scalar()
            or 0
        )
    else:
        used = (
            db.session.query(func.count(Registration.id))
            .filter(
                Registration.event_id == event.id,
                Registration.status == REG_CONFIRMED,
            )
            .scalar()
            or 0
        )
    return used, event.capacity


def dashboard_metrics(tz_name: str, include_demo: bool = True) -> dict:
    now = utc = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = local_day_start_utc(date.today(), tz_name)

    reg_q = db.session.query(func.count(Registration.id)).filter(
        Registration.status == REG_CONFIRMED
    )
    team_q = db.session.query(func.count(Team.id)).filter(Team.status == REG_CONFIRMED)
    if not include_demo:
        reg_q = reg_q.filter(Registration.is_demo.is_(False))
        team_q = team_q.filter(Team.is_demo.is_(False))

    total_individual = reg_q.scalar() or 0
    total_teams = team_q.scalar() or 0

    today_q = reg_q.filter(Registration.created_at >= today_start)
    today_individual = today_q.scalar() or 0
    today_team_q = team_q.filter(Team.created_at >= today_start)
    today_teams = today_team_q.scalar() or 0

    events = _published_events().all()
    upcoming = [e for e in events if e.starts_at > now]

    total_capacity = 0
    total_used = 0
    for event in events:
        used, cap = _event_capacity_used(event)
        total_capacity += cap
        total_used += used

    utilization = (total_used / total_capacity * 100) if total_capacity else 0.0

    return {
        "total_individual": total_individual,
        "total_teams": total_teams,
        "total_combined": total_individual + total_teams,
        "today_individual": today_individual,
        "today_teams": today_teams,
        "today_combined": today_individual + today_teams,
        "published_events": len(events),
        "upcoming_events": len(upcoming),
        "total_capacity": total_capacity,
        "total_used": total_used,
        "utilization": round(utilization, 1),
    }


def registrations_over_time(tz_name: str, days: int = 14, include_demo: bool = True):
    """Daily confirmed individual registrations for the last N days (display tz)."""
    today = date.today()
    start_day = today - timedelta(days=days - 1)
    start_utc = local_day_start_utc(start_day, tz_name)

    q = db.session.query(
        func.count(Registration.id), func.date(Registration.created_at)
    ).filter(
        Registration.status == REG_CONFIRMED,
        Registration.created_at >= start_utc,
    )
    if not include_demo:
        q = q.filter(Registration.is_demo.is_(False))
    rows = q.group_by(func.date(Registration.created_at)).all()

    by_day = {str(day): count for count, day in rows}
    labels = []
    values = []
    cursor = start_day
    while cursor <= today:
        key_iso = cursor.isoformat()
        labels.append(cursor.strftime("%b %d"))
        values.append(by_day.get(key_iso, 0))
        cursor += timedelta(days=1)
    return {"labels": labels, "values": values}


def registrations_by_event(include_demo: bool = True):
    q = (
        db.session.query(Event.title, func.count(Registration.id))
        .join(Registration, Registration.event_id == Event.id)
        .filter(Registration.status == REG_CONFIRMED)
        .group_by(Event.title)
        .order_by(func.count(Registration.id).desc())
    )
    if not include_demo:
        q = q.filter(Registration.is_demo.is_(False))
    rows = q.limit(12).all()
    return {"labels": [r[0] for r in rows], "values": [r[1] for r in rows]}


def registrations_by_category(include_demo: bool = True):
    q = (
        db.session.query(Event.category, func.count(Registration.id))
        .join(Registration, Registration.event_id == Event.id)
        .filter(Registration.status == REG_CONFIRMED)
        .group_by(Event.category)
    )
    if not include_demo:
        q = q.filter(Registration.is_demo.is_(False))
    rows = q.all()
    label_map = dict(CATEGORIES)
    return {
        "labels": [label_map.get(r[0], r[0]) for r in rows],
        "values": [r[1] for r in rows],
    }


def capacity_utilization_by_event(include_demo: bool = True):
    events = _published_events().order_by(Event.starts_at.asc()).all()
    labels, used_vals, capacity_vals, pcts = [], [], [], []
    for event in events:
        used, cap = _event_capacity_used(event)
        if not include_demo and event.is_demo:
            continue
        labels.append(event.title)
        used_vals.append(used)
        capacity_vals.append(cap)
        pcts.append(round((used / cap * 100) if cap else 0, 1))
    return {
        "labels": labels,
        "used": used_vals,
        "capacity": capacity_vals,
        "pcts": pcts,
    }
