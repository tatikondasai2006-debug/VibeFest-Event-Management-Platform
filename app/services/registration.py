"""Transactional registration services with capacity and duplicate enforcement."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    REG_CONFIRMED,
    Event,
    Registration,
    RegistrationAnswer,
    Team,
    TeamMember,
)
from app.utils import make_reference, normalize_email, utcnow


class RegistrationError(Exception):
    """Business-rule rejection with a user-friendly message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _validate_common(name, email, phone, consent):
    errors = {}
    if not name or not name.strip() or len(name.strip()) > 120:
        errors["full_name"] = "Please provide your full name (max 120 characters)."
    if not email or "@" not in email or len(email) > 200:
        errors["email"] = "Please provide a valid email address."
    if not phone or not phone.strip() or len(phone.strip()) > 30:
        errors["phone"] = "Please provide a phone number."
    if not consent:
        errors["consent"] = "You must consent to the privacy notice to register."
    return errors


def _validate_custom_answers(event: Event, form) -> dict:
    """Validate answers against event.custom_fields definitions."""
    errors: dict[str, str] = {}
    definitions = event.custom_fields or []
    for field in definitions:
        key = field.get("key")
        ftype = field.get("type", "text")
        label = field.get("label", key)
        required = bool(field.get("required"))
        if ftype == "checkbox":
            value = form.get(f"cf_{key}") == "on"
            if required and not value:
                errors[key] = f"'{label}' is required."
        else:
            value = (form.get(f"cf_{key}") or "").strip()
            max_len = int(field.get("max_length", 200) or 200)
            if required and not value:
                errors[key] = f"'{label}' is required."
            elif value and len(value) > max_len:
                errors[key] = f"'{label}' must be at most {max_len} characters."
            elif value and ftype == "select":
                options = field.get("options") or []
                if options and value not in options:
                    errors[key] = f"Invalid option for '{label}'."
    return errors


def _save_answers(registration: Registration, event: Event, form) -> None:
    for field in event.custom_fields or []:
        key = field.get("key")
        ftype = field.get("type", "text")
        label = field.get("label", key)
        if ftype == "checkbox":
            value_bool = form.get(f"cf_{key}") == "on"
            answer = RegistrationAnswer(
                registration_id=registration.id,
                field_key=key,
                field_label=label,
                field_type=ftype,
                value_bool=value_bool,
                value_text="yes" if value_bool else "no",
            )
        else:
            value_text = (form.get(f"cf_{key}") or "").strip()
            answer = RegistrationAnswer(
                registration_id=registration.id,
                field_key=key,
                field_label=label,
                field_type=ftype,
                value_text=value_text,
            )
        db.session.add(answer)


def register_individual(event: Event, form, is_demo: bool = False) -> Registration:
    """Create one individual registration inside a guarded transaction."""
    name = (form.get("full_name") or "").strip()
    email_raw = (form.get("email") or "").strip()
    phone = (form.get("phone") or "").strip()
    college = (form.get("college") or "").strip()
    department = (form.get("department") or "").strip()
    year = (form.get("year_of_study") or "").strip()
    consent = form.get("consent") in ("on", "true", "1", True)

    errors = _validate_common(name, email_raw, phone, consent)
    errors.update(_validate_custom_answers(event, form))
    if errors:
        raise RegistrationError(next(iter(errors.values())))

    normalized = normalize_email(email_raw)
    now = utcnow()

    try:
        event_locked = db.session.execute(
            select(Event).where(Event.id == event.id).with_for_update()
        ).scalar_one_or_none()
        if event_locked is None:
            raise RegistrationError("This event no longer exists.")

        allowed, reason = event_locked.is_registration_allowed(now)
        if not allowed:
            raise RegistrationError(reason)

        existing = db.session.execute(
            select(Registration.id).where(
                Registration.event_id == event_locked.id,
                Registration.normalized_email == normalized,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise RegistrationError(
                "You have already registered for this event with this email."
            )

        used = event_locked.used_capacity()
        if used >= event_locked.capacity:
            raise RegistrationError("This event is full.")

        reference = make_reference("EH-")
        registration = Registration(
            reference=reference,
            event_id=event_locked.id,
            full_name=name,
            email=email_raw,
            normalized_email=normalized,
            phone=phone,
            college=college or None,
            department=department or None,
            year_of_study=year or None,
            consent=True,
            consent_at=now,
            status=REG_CONFIRMED,
            is_demo=is_demo,
        )
        db.session.add(registration)
        db.session.flush()
        _save_answers(registration, event_locked, form)
        db.session.commit()
        return registration
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError(
            "You have already registered for this event with this email."
        )
    except RegistrationError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise


def _validate_member_names(members: list[dict]) -> dict[str, str]:
    errors = {}
    for idx, member in enumerate(members, start=1):
        if not (member.get("name") or "").strip():
            errors[f"member_{idx}_name"] = f"Member {idx}: name is required."
            continue
        email = (member.get("email") or "").strip()
        if "@" not in email or len(email) > 200:
            errors[f"member_{idx}_email"] = f"Member {idx}: a valid email is required."
    return errors


def _save_team_answers(team: Team, event: Event, form) -> None:
    for field in event.custom_fields or []:
        key = field.get("key")
        ftype = field.get("type", "text")
        label = field.get("label", key)
        if ftype == "checkbox":
            value_bool = form.get(f"cf_{key}") == "on"
            answer = RegistrationAnswer(
                team_id=team.id,
                field_key=key,
                field_label=label,
                field_type=ftype,
                value_bool=value_bool,
                value_text="yes" if value_bool else "no",
            )
        else:
            value_text = (form.get(f"cf_{key}") or "").strip()
            answer = RegistrationAnswer(
                team_id=team.id,
                field_key=key,
                field_label=label,
                field_type=ftype,
                value_text=value_text,
            )
        db.session.add(answer)


def register_team(event: Event, form, is_demo: bool = False) -> Team:
    """Create a team (leader + members) inside a guarded transaction."""
    if event.registration_mode != "team":
        raise RegistrationError("This event does not accept team registrations.")

    team_name = (form.get("team_name") or "").strip()
    leader_name = (form.get("full_name") or "").strip()
    leader_email = (form.get("email") or "").strip()
    phone = (form.get("phone") or "").strip()
    college = (form.get("college") or "").strip()
    consent = form.get("consent") in ("on", "true", "1", True)

    errors = _validate_common(leader_name, leader_email, phone, consent)
    if not team_name or len(team_name) > 120:
        errors["team_name"] = "Please provide a team name (max 120 characters)."

    member_entries: list[dict] = []
    raw_members = form.getlist("member_json") if hasattr(form, "getlist") else []
    import json

    for raw in raw_members:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            member_entries.append(
                {
                    "name": (data.get("name") or "").strip(),
                    "email": (data.get("email") or "").strip(),
                }
            )

    member_entries = [m for m in member_entries if m["name"] or m["email"]]
    errors.update(_validate_member_names(member_entries))

    min_size = max(event.team_min_size, 1)
    max_size = max(event.team_max_size, min_size)
    total_members = 1 + len(member_entries)
    if total_members < min_size:
        errors["members"] = f"A team needs at least {min_size} member(s) including the leader."
    if total_members > max_size:
        errors["members"] = f"A team can have at most {max_size} members including the leader."

    leader_norm = normalize_email(leader_email)
    seen_emails = {leader_norm}
    for member in member_entries:
        norm = normalize_email(member["email"])
        if norm in seen_emails:
            errors["members"] = "Each team member must use a unique email address."
            break
        seen_emails.add(norm)

    errors.update(_validate_custom_answers(event, form))
    if errors:
        raise RegistrationError(next(iter(errors.values())))

    now = utcnow()
    try:
        event_locked = db.session.execute(
            select(Event).where(Event.id == event.id).with_for_update()
        ).scalar_one_or_none()
        if event_locked is None:
            raise RegistrationError("This event no longer exists.")

        allowed, reason = event_locked.is_registration_allowed(now)
        if not allowed:
            raise RegistrationError(reason)

        dup_leader = db.session.execute(
            select(Team.id).where(
                Team.event_id == event_locked.id,
                Team.leader_normalized_email == leader_norm,
            )
        ).scalar_one_or_none()
        if dup_leader is not None:
            raise RegistrationError(
                "This team leader email is already registered for this event."
            )
        dup_member = db.session.execute(
            select(TeamMember.id).where(
                TeamMember.event_id == event_locked.id,
                TeamMember.normalized_email == leader_norm,
            )
        ).scalar_one_or_none()
        if dup_member is not None:
            raise RegistrationError(
                "A team member email is already registered for this event."
            )

        used = event_locked.used_capacity()
        if used >= event_locked.capacity:
            raise RegistrationError("This event is full.")

        team = Team(
            reference=make_reference("TM-"),
            event_id=event_locked.id,
            team_name=team_name,
            leader_name=leader_name,
            leader_normalized_email=leader_norm,
            leader_phone=phone,
            leader_college=college or None,
            status=REG_CONFIRMED,
            is_demo=is_demo,
        )
        db.session.add(team)
        db.session.flush()

        db.session.add(
            TeamMember(
                team_id=team.id,
                event_id=event_locked.id,
                full_name=leader_name,
                email=leader_email,
                normalized_email=leader_norm,
                role="leader",
            )
        )
        for member in member_entries:
            db.session.add(
                TeamMember(
                    team_id=team.id,
                    event_id=event_locked.id,
                    full_name=member["name"],
                    email=member["email"],
                    normalized_email=normalize_email(member["email"]),
                    role="member",
                )
            )

        _save_team_answers(team, event_locked, form)

        db.session.commit()
        return team
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError(
            "A team member email is already registered for this event."
        )
    except RegistrationError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise
