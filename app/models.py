from datetime import date, datetime

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, event, func
from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import normalize_email, slugify, utcnow

CATEGORIES = [
    ("techverse", "TechVerse"),
    ("culturewave", "CultureWave"),
    ("gamezone", "GameZone"),
    ("creative_canvas", "Creative Canvas"),
    ("vibe_nights", "Vibe Nights"),
]
CATEGORY_LABELS = dict(CATEGORIES)

EVENT_STATUSES = ("draft", "published", "cancelled")
REGISTRATION_STATUSES = ("open", "closed")
REGISTRATION_MODES = ("individual", "team")
REGISTRATION_MODE_LABELS = {"individual": "Individual", "team": "Team"}
CAPACITY_UNITS = ("seats", "entries", "teams")

REG_CONFIRMED = "confirmed"
REG_CANCELLED = "cancelled"


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AdminUser(UserMixin, db.Model):
    __tablename__ = "admin_user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    role = "admin"

    @validates("email")
    def _set_email(self, key, value):
        return normalize_email(value)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        """Namespace the session id so admin and member ids never collide."""
        return f"admin:{self.id}"


class Member(UserMixin, db.Model):
    """Self-service attendee account: signs up, then views/cancels their own registrations."""

    __tablename__ = "member"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    role = "member"

    @validates("email")
    def _set_email(self, key, value):
        return normalize_email(value)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        return f"member:{self.id}"

    @property
    def registrations(self):
        return (
            Registration.query.filter(
                Registration.normalized_email == self.email
            )
            .order_by(Registration.created_at.desc())
            .all()
        )

    @property
    def teams(self):
        return (
            Team.query.join(TeamMember, TeamMember.team_id == Team.id)
            .filter(TeamMember.normalized_email == self.email)
            .order_by(Team.created_at.desc())
            .all()
        )


class FestivalSettings(db.Model):
    """Single-row settings record (id always 1)."""

    __tablename__ = "festival_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_settings_singleton"),)

    id = db.Column(db.Integer, primary_key=True)
    festival_name = db.Column(db.String(120), nullable=False, default="VibeFest 2026")
    tagline = db.Column(db.String(200), nullable=False, default="Find Your Vibe. Own the Stage.")
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    venue = db.Column(db.String(200), nullable=True)
    college_name = db.Column(db.String(200), nullable=True)
    contact_email = db.Column(db.String(200), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    display_timezone = db.Column(db.String(60), nullable=False, default="Asia/Kolkata")
    registration_instructions = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get(cls) -> "FestivalSettings":
        row = db.session.get(cls, 1)
        if row is None:
            row = cls(id=1)
            db.session.add(row)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                row = db.session.get(cls, 1)
        return row

    def festival_dates_valid(self) -> bool:
        return bool(self.start_date and self.end_date and self.end_date >= self.start_date)

    def countdown_target(self) -> datetime | None:
        """UTC naive datetime of festival start, or None when unconfigured."""
        if not self.start_date:
            return None
        return datetime.combine(self.start_date, datetime.min.time())


class Event(TimestampMixin, db.Model):
    __tablename__ = "event"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_event_slug"),
        CheckConstraint("capacity > 0", name="ck_event_capacity_positive"),
        CheckConstraint(
            "ends_at > starts_at", name="ck_event_end_after_start"
        ),
        CheckConstraint(
            "status IN ('draft','published','cancelled')", name="ck_event_status"
        ),
        CheckConstraint(
            "registration_status IN ('open','closed')", name="ck_event_reg_status"
        ),
        CheckConstraint(
            "registration_mode IN ('individual','team')", name="ck_event_mode"
        ),
        Index("ix_event_status_starts", "status", "starts_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    category = db.Column(db.String(40), nullable=False, default="techverse")
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    venue = db.Column(db.String(200), nullable=True)
    organizer = db.Column(db.String(200), nullable=True)
    registration_deadline = db.Column(db.DateTime, nullable=True)
    capacity = db.Column(db.Integer, nullable=False, default=50)
    capacity_unit = db.Column(db.String(30), nullable=False, default="seats")
    registration_mode = db.Column(db.String(20), nullable=False, default="individual")
    status = db.Column(db.String(20), nullable=False, default="draft")
    registration_status = db.Column(db.String(20), nullable=False, default="open")
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    team_min_size = db.Column(db.Integer, nullable=False, default=2)
    team_max_size = db.Column(db.Integer, nullable=False, default=5)
    custom_fields = db.Column(db.JSON, nullable=False, default=list)

    registrations = db.relationship(
        "Registration",
        backref="event",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    teams = db.relationship(
        "Team",
        backref="event",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @validates("title")
    def _validate_title(self, key, value):
        if not value or not value.strip():
            raise ValueError("Event title is required.")
        return value.strip()[:200]

    @validates("category")
    def _validate_category(self, key, value):
        if value not in CATEGORY_LABELS:
            raise ValueError("Unknown event category.")
        return value

    @validates("capacity")
    def _validate_capacity(self, key, value):
        if value is None or int(value) < 1:
            raise ValueError("Capacity must be greater than zero.")
        return int(value)

    @validates("starts_at", "ends_at")
    def _validate_times(self, key, value):
        if value is None:
            raise ValueError("Event times are required.")
        return value

    @staticmethod
    def _ensure_slug(value: str) -> str:
        base = slugify(value)
        slug = base
        n = 2
        while Event.query.filter_by(slug=slug).first() is not None:
            slug = f"{base}-{n}"
            n += 1
        return slug

    @classmethod
    def create_event(cls, **kwargs) -> "Event":
        if not kwargs.get("slug"):
            kwargs["slug"] = cls._ensure_slug(kwargs["title"])
        if kwargs["ends_at"] <= kwargs["starts_at"]:
            raise ValueError("End time must be after start time.")
        event_obj = cls(**kwargs)
        db.session.add(event_obj)
        return event_obj

    def confirmed_count(self) -> int:
        from app.models import REG_CONFIRMED

        return (
            db.session.query(func.count(Registration.id))
            .filter(
                Registration.event_id == self.id,
                Registration.status == REG_CONFIRMED,
            )
            .scalar()
            or 0
        )

    def confirmed_team_count(self) -> int:
        from app.models import REG_CONFIRMED

        return (
            db.session.query(func.count(Team.id))
            .filter(Team.event_id == self.id, Team.status == REG_CONFIRMED)
            .scalar()
            or 0
        )

    def used_capacity(self) -> int:
        if self.registration_mode == "team":
            return self.confirmed_team_count()
        return self.confirmed_count()

    def seats_left(self) -> int:
        return max(self.capacity - self.used_capacity(), 0)

    def is_full(self) -> bool:
        return self.used_capacity() >= self.capacity

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def mode_label(self) -> str:
        return REGISTRATION_MODE_LABELS.get(self.registration_mode, self.registration_mode)

    def is_registration_allowed(self, now: datetime | None = None) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        now = now or utcnow()
        if self.status == "draft":
            return False, "This event is not yet published."
        if self.status == "cancelled":
            return False, "This event has been cancelled."
        if self.registration_status != "open":
            return False, "Registration is currently closed."
        if self.registration_deadline and now > self.registration_deadline:
            return False, "The registration deadline has passed."
        if now >= self.starts_at:
            return False, "This event has already started."
        if self.is_full():
            return False, "This event is full."
        return True, ""

    def ensure_capacity_for(self, new_capacity: int) -> None:
        used = self.used_capacity()
        if new_capacity < used:
            raise ValueError(
                f"Capacity cannot be reduced below current registrations ({used})."
            )

    def publish(self) -> None:
        self.status = "published"

    def close_registration(self) -> None:
        self.registration_status = "closed"

    def reopen_registration(self) -> None:
        if self.status == "cancelled":
            raise ValueError("A cancelled event cannot reopen registration.")
        if self.is_full():
            raise ValueError("Event is at full capacity; increase capacity first.")
        if self.registration_deadline and utcnow() > self.registration_deadline:
            raise ValueError("Registration deadline has passed; clear or extend it first.")
        if utcnow() >= self.starts_at:
            raise ValueError("Event has already started; registration cannot reopen.")
        self.registration_status = "open"

    def cancel(self) -> None:
        self.status = "cancelled"
        self.registration_status = "closed"


class Registration(TimestampMixin, db.Model):
    __tablename__ = "registration"
    __table_args__ = (
        UniqueConstraint("event_id", "normalized_email", name="uq_reg_event_email"),
        CheckConstraint(
            "status IN ('confirmed','cancelled')", name="ck_reg_status"
        ),
        Index("ix_reg_event_status", "event_id", "status"),
        Index("ix_reg_created", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)
    event_id = db.Column(
        db.Integer, db.ForeignKey("event.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    normalized_email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    college = db.Column(db.String(200), nullable=True)
    department = db.Column(db.String(120), nullable=True)
    year_of_study = db.Column(db.String(30), nullable=True)
    consent = db.Column(db.Boolean, nullable=False, default=False)
    consent_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=REG_CONFIRMED)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    answers = db.relationship(
        "RegistrationAnswer",
        backref="registration",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @validates("normalized_email")
    def _set_normalized(self, key, value):
        return normalize_email(value)

    @property
    def event_title(self) -> str:
        return self.event.title if self.event else ""


class Team(TimestampMixin, db.Model):
    __tablename__ = "team"
    __table_args__ = (
        CheckConstraint("status IN ('confirmed','cancelled')", name="ck_team_status"),
        Index("ix_team_event_status", "event_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)
    event_id = db.Column(
        db.Integer, db.ForeignKey("event.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_name = db.Column(db.String(120), nullable=False)
    leader_name = db.Column(db.String(120), nullable=False)
    leader_normalized_email = db.Column(db.String(200), nullable=False)
    leader_phone = db.Column(db.String(30), nullable=True)
    leader_college = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=REG_CONFIRMED)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    members = db.relationship(
        "TeamMember",
        backref="team",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TeamMember.role.desc()",
    )
    answers = db.relationship(
        "RegistrationAnswer",
        backref="team",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TeamMember(db.Model):
    __tablename__ = "team_member"
    __table_args__ = (
        UniqueConstraint("event_id", "normalized_email", name="uq_member_event_email"),
        CheckConstraint("role IN ('leader','member')", name="ck_member_role"),
        Index(
            "uq_team_one_leader",
            "team_id",
            unique=True,
            sqlite_where=db.text("role = 'leader'"),
            postgresql_where=db.text("role = 'leader'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id = db.Column(
        db.Integer, db.ForeignKey("event.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    normalized_email = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="member")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @validates("normalized_email")
    def _set_normalized(self, key, value):
        return normalize_email(value)


class RegistrationAnswer(db.Model):
    __tablename__ = "registration_answer"
    __table_args__ = (
        UniqueConstraint("registration_id", "field_key", name="uq_answer_reg_field"),
        UniqueConstraint("team_id", "field_key", name="uq_answer_team_field"),
    )

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(
        db.Integer,
        db.ForeignKey("registration.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("team.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    field_key = db.Column(db.String(80), nullable=False)
    field_label = db.Column(db.String(200), nullable=False)
    field_type = db.Column(db.String(20), nullable=False)
    value_text = db.Column(db.String(500), nullable=True)
    value_bool = db.Column(db.Boolean, nullable=True)
