"""Secure CSV export with whitelisted columns and formula-injection guards."""

import csv
import io

from app.extensions import db
from app.models import REG_CONFIRMED, Event, Registration, Team, TeamMember
from app.utils import csv_safe, to_display

EXPORT_COLUMNS = [
    "reference",
    "event",
    "category",
    "full_name",
    "email",
    "phone",
    "college",
    "department",
    "year_of_study",
    "status",
    "registered_at",
    "is_demo",
]

TEAM_EXPORT_COLUMNS = [
    "reference",
    "event",
    "team_name",
    "leader_name",
    "leader_email",
    "leader_phone",
    "leader_college",
    "member_count",
    "status",
    "registered_at",
    "is_demo",
]


def export_registrations_csv(
    event_id: int | None = None,
    status: str | None = None,
    tz_name: str = "Asia/Kolkata",
    include_demo: bool = True,
) -> str:
    q = db.session.query(Registration, Event).join(Event, Event.id == Registration.event_id)
    if event_id:
        q = q.filter(Registration.event_id == event_id)
    if status:
        q = q.filter(Registration.status == status)
    if not include_demo:
        q = q.filter(Registration.is_demo.is_(False))
    rows = q.order_by(Registration.created_at.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for reg, event in rows:
        writer.writerow(
            [
                csv_safe(reg.reference),
                csv_safe(event.title),
                csv_safe(event.category),
                csv_safe(reg.full_name),
                csv_safe(reg.email),
                csv_safe(reg.phone),
                csv_safe(reg.college or ""),
                csv_safe(reg.department or ""),
                csv_safe(reg.year_of_study or ""),
                csv_safe(reg.status),
                csv_safe(to_display(reg.created_at, tz_name).isoformat() if reg.created_at else ""),
                "yes" if reg.is_demo else "no",
            ]
        )
    return buffer.getvalue()


def export_teams_csv(
    event_id: int | None = None,
    status: str | None = None,
    tz_name: str = "Asia/Kolkata",
    include_demo: bool = True,
) -> str:
    q = db.session.query(Team, Event).join(Event, Event.id == Team.event_id)
    if event_id:
        q = q.filter(Team.event_id == event_id)
    if status:
        q = q.filter(Team.status == status)
    if not include_demo:
        q = q.filter(Team.is_demo.is_(False))
    rows = q.order_by(Team.created_at.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEAM_EXPORT_COLUMNS)
    for team, event in rows:
        member_count = (
            db.session.query(TeamMember)
            .filter(TeamMember.team_id == team.id)
            .count()
        )
        writer.writerow(
            [
                csv_safe(team.reference),
                csv_safe(event.title),
                csv_safe(team.team_name),
                csv_safe(team.leader_name),
                csv_safe(team.leader_normalized_email),
                csv_safe(team.leader_phone or ""),
                csv_safe(team.leader_college or ""),
                member_count,
                csv_safe(team.status),
                csv_safe(to_display(team.created_at, tz_name).isoformat() if team.created_at else ""),
                "yes" if team.is_demo else "no",
            ]
        )
    return buffer.getvalue()
