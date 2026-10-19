import re
import secrets
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def utcnow():
    """Naive UTC timestamp used for all stored datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(email) and len(email) <= 200 and EMAIL_RE.match(email.strip()) is not None


def is_valid_phone(phone: str) -> bool:
    return bool(phone) and PHONE_RE.match(phone.strip()) is not None


def make_reference(prefix: str = "EH-") -> str:
    return prefix + "".join(secrets.choice(REF_ALPHABET) for _ in range(8))


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    return slug[:100] or "event"


def to_display(dt: datetime | None, tz_name: str) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))


def parse_local_datetime(value: str, tz_name: str) -> datetime:
    """Parse a datetime-local input value (festival timezone) to naive UTC."""
    naive = datetime.fromisoformat(value.strip())
    return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc).replace(tzinfo=None)


def local_day_start_utc(day: date, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=tz)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection for exported cell values."""
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
