"""Idempotent demo seeding, clearly marked and never mixed with production records."""

from datetime import datetime, timedelta

from app.extensions import db
from app.models import (
    REG_CONFIRMED,
    CATEGORIES,
    Event,
    FestivalSettings,
    Registration,
)
from app.utils import make_reference, utcnow


def seed_demo_data() -> str:
    """Create demo events and registrations if no demo data exists yet."""
    existing = Event.query.filter_by(is_demo=True).first()
    if existing:
        return "Demo data already present. Nothing to do."

    now = utcnow()
    settings = FestivalSettings.get()
    base_day = settings.start_date or now.date()
    cat_keys = [c[0] for c in CATEGORIES]

    demo_events = [
        Event(
            slug="demo-hackathon",
            title="Hackathon Sprint",
            description="Build a working prototype in one intensive day. Open to all skill levels.",
            category=cat_keys[0],
            starts_at=datetime.combine(base_day, datetime.min.time()) + timedelta(hours=10),
            ends_at=datetime.combine(base_day, datetime.min.time()) + timedelta(hours=22),
            venue="Innovation Lab",
            organizer="Tech Committee",
            capacity=60,
            capacity_unit="seats",
            status="published",
            registration_status="open",
            is_demo=True,
        ),
        Event(
            slug="demo-dance-night",
            title="Dance Face-Off",
            description="Cross-campus dance battle. Solo and duo entries welcome.",
            category=cat_keys[1],
            starts_at=datetime.combine(base_day + timedelta(days=1), datetime.min.time()) + timedelta(hours=18),
            ends_at=datetime.combine(base_day + timedelta(days=1), datetime.min.time()) + timedelta(hours=21),
            venue="Open Air Amphitheatre",
            organizer="Cultural Committee",
            capacity=40,
            status="published",
            registration_status="open",
            is_demo=True,
        ),
        Event(
            slug="demo-esports-arena",
            title="Esports Arena",
            description="Team-based esports tournament with group stages and finals.",
            category=cat_keys[2],
            starts_at=datetime.combine(base_day + timedelta(days=2), datetime.min.time()) + timedelta(hours=14),
            ends_at=datetime.combine(base_day + timedelta(days=2), datetime.min.time()) + timedelta(hours=20),
            venue="Sports Complex Hall",
            organizer="Gaming Club",
            capacity=32,
            capacity_unit="teams",
            registration_mode="team",
            team_min_size=2,
            team_max_size=5,
            status="published",
            registration_status="open",
            is_demo=True,
        ),
        Event(
            slug="demo-art-expo",
            title="Canvas & Craft Expo",
            description="Live art installations, craft stalls and a juried showcase.",
            category=cat_keys[3],
            starts_at=datetime.combine(base_day + timedelta(days=3), datetime.min.time()) + timedelta(hours=11),
            ends_at=datetime.combine(base_day + timedelta(days=3), datetime.min.time()) + timedelta(hours=17),
            venue="Art Block",
            organizer="Arts Society",
            capacity=80,
            status="published",
            registration_status="open",
            is_demo=True,
        ),
        Event(
            slug="demo-cosplay-carnival",
            title="Cosplay Carnival",
            description="Costume parade and photography contest with themed zones.",
            category=cat_keys[4],
            starts_at=datetime.combine(base_day + timedelta(days=4), datetime.min.time()) + timedelta(hours=16),
            ends_at=datetime.combine(base_day + timedelta(days=4), datetime.min.time()) + timedelta(hours=20),
            venue="Main Quad",
            organizer="Vibe Nights Crew",
            capacity=100,
            status="published",
            registration_status="open",
            is_demo=True,
        ),
        Event(
            slug="demo-draft-workshop",
            title="Draft Workshop: Intro to Robotics",
            description="A draft event that is not yet published.",
            category=cat_keys[0],
            starts_at=now + timedelta(days=30),
            ends_at=now + timedelta(days=30, hours=3),
            venue="Robotics Lab",
            capacity=25,
            status="draft",
            registration_status="open",
            is_demo=True,
        ),
    ]

    for event in demo_events:
        db.session.add(event)
    db.session.flush()

    first_names = ["Aarav", "Diya", "Kabir", "Ananya", "Rohan", "Isha", "Vikram", "Meera", "Arjun", "Sara"]
    last_names = ["Sharma", "Patel", "Reddy", "Nair", "Iyer", "Gupta", "Singh", "Das", "Khan", "Bose"]
    colleges = ["State University", "City Institute of Technology", "National College", "Regional Polytechnic"]

    counter = 0
    for event in demo_events[:2] + demo_events[3:5]:
        take = min(event.capacity // 3, 12)
        for i in range(take):
            counter += 1
            first = first_names[counter % len(first_names)]
            last = last_names[counter % len(last_names)]
            reg_time = now - timedelta(days=counter % 10, hours=counter % 6)
            db.session.add(
                Registration(
                    reference=make_reference("EH-"),
                    event_id=event.id,
                    full_name=f"{first} {last}",
                    email=f"demo{counter}@example.com",
                    normalized_email=f"demo{counter}@example.com",
                    phone=f"98{counter:08d}",
                    college=colleges[counter % len(colleges)],
                    department="Computer Science",
                    year_of_study=str((counter % 4) + 1),
                    consent=True,
                    consent_at=reg_time,
                    status=REG_CONFIRMED,
                    is_demo=True,
                    created_at=reg_time,
                )
            )

    db.session.commit()
    return (
        f"Seeded {len(demo_events)} demo events and {counter} demo registrations. "
        "All demo records are marked is_demo=True."
    )
