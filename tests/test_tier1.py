import os
import tempfile
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("TESTING", "1")


from app import create_app
from app.extensions import db
from app.models import Event, FestivalSettings, Member, Registration, Team
from app.services.registration import RegistrationError, register_individual
from app.utils import utcnow


@pytest.fixture(scope="function")
def app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["TEST_DATABASE_URL"] = "sqlite:///" + db_path
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        FestivalSettings.get()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()


@pytest.fixture
def sample_event(app):
    with app.app_context():
        now = utcnow()
        event = Event.create_event(
            title="Testathon",
            description="Test",
            category="techverse",
            starts_at=now + timedelta(hours=5),
            ends_at=now + timedelta(hours=10),
            capacity=2,
            status="published",
            registration_status="open",
            registration_mode="individual",
        )
        event.is_demo = False
        db.session.commit()
        yield event.id


def test_home_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"VibeFest" in resp.data or b"EventHub" in resp.data


def test_events_list_requires_login(client):
    resp = client.get("/events")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]
    assert "next=" in resp.headers["Location"]


def test_events_list_renders_after_login(client, app):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="opengate", email="opengate@example.com")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    resp = client.post(
        "/auth/login?next=/events",
        data={"email": "opengate@example.com", "password": "Adm@1234"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/events")
    follow = client.get(resp.headers["Location"])
    assert follow.status_code == 200


def test_login_rejects_external_next(client, app):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="nextsafe", email="nextsafe@example.com")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    resp = client.post(
        "/auth/login?next=https://evil.example/steal",
        data={"email": "nextsafe@example.com", "password": "Adm@1234"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "evil.example" not in resp.headers["Location"]


def test_login_form_shows_email_and_password(client):
    html = client.get("/auth/login").data.decode("utf-8")
    assert 'type="email"' in html
    assert 'name="email"' in html
    assert 'name="username"' not in html
    assert 'name="password"' in html
    assert "data-password-toggle" in html


def test_login_by_email_normalizes_spaces_and_case(client, app):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="casey", email="  Casey.Admin@Example.COM  ")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
        assert a.email == "casey.admin@example.com"
    resp = client.post(
        "/auth/login?next=/events",
        data={"email": "  Casey.Admin@Example.COM  ", "password": "Adm@1234"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/events")


def test_login_rejects_bad_email_or_password(client, app):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="grace", email="grace@example.com")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    bad_pw = client.post(
        "/auth/login", data={"email": "grace@example.com", "password": "nope"}
    )
    assert bad_pw.status_code == 200
    assert b"Invalid email or password." in bad_pw.data
    missing = client.post(
        "/auth/login", data={"email": "nobody@example.com", "password": "nope"}
    )
    assert missing.status_code == 200
    assert b"Invalid email or password." in missing.data
    assert client.get("/admin/").status_code == 302


def test_event_detail_renders(client, sample_event):
    resp = client.get("/events/testathon")
    assert resp.status_code == 200


def test_individual_registration_success(client, sample_event):
    resp = client.post(
        "/events/testathon/register",
        data={
            "full_name": "Alice Example",
            "email": "alice@example.com",
            "phone": "9876543210",
            "college": "Test College",
            "consent": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    with client.application.app_context():
        reg = Registration.query.filter_by(email="alice@example.com").first()
        assert reg is not None
        assert reg.normalized_email == "alice@example.com"


def test_duplicate_email_rejected(client, sample_event):
    client.post(
        "/events/testathon/register",
        data={
            "full_name": "Alice Example",
            "email": "alice@example.com",
            "phone": "9876543210",
            "consent": "on",
        },
    )
    resp = client.post(
        "/events/testathon/register",
        data={
            "full_name": "Alice Dup",
            "email": "ALICE@example.com",
            "phone": "9876543211",
            "consent": "on",
        },
    )
    assert b"already registered" in resp.data.lower()


def test_capacity_enforced_across_requests(client, sample_event):
    client.post("/events/testathon/register", data={"full_name": "A", "email": "a@test.com", "phone": "1", "consent": "on"})
    client.post("/events/testathon/register", data={"full_name": "B", "email": "b@test.com", "phone": "2", "consent": "on"})
    resp = client.post("/events/testathon/register", data={"full_name": "C", "email": "c@test.com", "phone": "3", "consent": "on"})
    assert b"full" in resp.data.lower() or b"closed" in resp.data.lower()


def test_consent_required(client, sample_event):
    resp = client.post(
        "/events/testathon/register",
        data={"full_name": "X", "email": "x@test.com", "phone": "1"},
    )
    assert b"consent" in resp.data.lower()


def test_admin_requires_login(client):
    resp = client.get("/admin/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_admin_login_and_dashboard(client, app):
    # ensure no admin; create admin directly
    from app.models import AdminUser
    with app.app_context():
        if AdminUser.query.filter_by(username="adm").first() is None:
            a = AdminUser(username="adm", email="adm@example.com")
            a.set_password("Adm@1234")
            db.session.add(a)
            db.session.commit()
    resp = client.post("/auth/login", data={"email": "adm@example.com", "password": "Adm@1234"}, follow_redirects=True)
    assert resp.status_code == 200
    resp = client.get("/admin/")
    assert resp.status_code == 200


def test_csv_requires_auth(client):
    resp = client.get("/admin/reports/export")
    assert resp.status_code == 302


def test_csv_export_auth_success(client, app, sample_event):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="adm2", email="adm2@example.com")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    client.post("/auth/login", data={"email": "adm2@example.com", "password": "Adm@1234"})
    client.post("/events/testathon/register", data={"full_name": "Z", "email": "z@test.com", "phone": "1", "consent": "on"})
    resp = client.get("/admin/reports/export")
    assert resp.status_code == 200
    assert b"reference" in resp.data


def test_public_counts_endpoint(client, sample_event):
    client.post("/events/testathon/register", data={"full_name": "M", "email": "m@test.com", "phone": "1", "consent": "on"})
    resp = client.get("/api/events/testathon/counts")
    assert resp.status_code == 200
    assert b"seats_left" in resp.data


def test_service_capacity_rejection(client, app, sample_event):
    from app.services.registration import RegistrationError, register_individual

    with app.app_context():
        event = db.session.get(Event, sample_event)

        def form_for(email):
            return {
                "full_name": email.split("@")[0],
                "email": email,
                "phone": "123",
                "college": "",
                "department": "",
                "year_of_study": "",
                "consent": True,
            }

        reg_a = register_individual(event, form_for("x@test.com"))
        reg_b = register_individual(event, form_for("y@test.com"))
        assert reg_a.reference and reg_b.reference

        with pytest.raises(RegistrationError) as exc:
            register_individual(event, form_for("z@test.com"))
        assert "full" in exc.value.message.lower()


def test_admin_pages_render(client, app):
    from app.models import AdminUser

    with app.app_context():
        a = AdminUser(username="adm3", email="adm3@example.com")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    client.post("/auth/login", data={"email": "adm3@example.com", "password": "Adm@1234"})
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/events").status_code == 200
    assert client.get("/admin/events/new").status_code == 200
    assert client.get("/admin/applicants").status_code == 200
    assert client.get("/admin/analytics").status_code == 200
    assert client.get("/admin/reports").status_code == 200
    assert client.get("/admin/settings").status_code == 200


@pytest.fixture(scope="function")
def rl_app(monkeypatch):
    from app.extensions import limiter
    from config import TestingConfig, config_by_name

    class RateLimitedTesting(TestingConfig):
        RATELIMIT_ENABLED = True

    monkeypatch.setitem(config_by_name, "testing_rl", RateLimitedTesting)
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["TEST_DATABASE_URL"] = "sqlite:///" + db_path
    app = create_app("testing_rl")
    limiter.reset()
    with app.app_context():
        db.create_all()
        FestivalSettings.get()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
    limiter.reset()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_login_page_get_requests_not_rate_limited(rl_app):
    client = rl_app.test_client()
    codes = [client.get("/auth/login").status_code for _ in range(12)]
    assert codes == [200] * 12
    assert client.get("/auth/login?next=/events").status_code == 200


def test_login_post_rate_limited_after_five(rl_app):
    client = rl_app.test_client()
    payload = {"email": "ghost@example.com", "password": "wrong-password"}
    for _ in range(5):
        resp = client.post("/auth/login", data=payload)
        assert resp.status_code == 200
    resp = client.post("/auth/login", data=payload)
    assert resp.status_code == 429
    assert b"429" in resp.data


# ------------------------------------------------------------------ members


def _signup(client, email="mira@example.com", password="Member@2026", name="Mira Member"):
    return client.post(
        "/auth/signup",
        data={
            "full_name": name,
            "email": email,
            "phone": "9876543210",
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=False,
    )


def test_signup_page_renders(client):
    resp = client.get("/auth/signup")
    assert resp.status_code == 200
    assert b"Create your account" in resp.data
    assert b'name="confirm_password"' in resp.data


def test_signup_creates_member_and_logs_in(client, app):
    resp = _signup(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/account/")
    with app.app_context():
        member = Member.query.filter_by(email="mira@example.com").first()
        assert member is not None
        assert member.email == "mira@example.com"
        assert member.role == "member"
        assert member.password_hash.startswith("scrypt:")
    # session now authenticated as a member
    assert client.get("/account/").status_code == 200


def test_signup_rejects_duplicate_email(client, app):
    _signup(client)
    client.post("/auth/logout", data={})  # CSRF disabled in testing config
    resp = _signup(client, email="MIRA@example.com")
    assert resp.status_code == 400
    assert b"already exists" in resp.data


def test_signup_rejects_short_password_and_mismatch(client):
    resp = _signup(client, password="short")
    assert resp.status_code == 400
    assert b"at least 8 characters" in resp.data
    resp = client.post(
        "/auth/signup",
        data={
            "full_name": "Bo",
            "email": "bo@example.com",
            "password": "Member@2026",
            "confirm_password": "Different@2026",
        },
    )
    assert resp.status_code == 400
    assert b"do not match" in resp.data


def test_member_login_and_lands_on_account(client, app):
    with app.app_context():
        m = Member(full_name="Lee Member", email="lee@example.com")
        m.set_password("Member@2026")
        db.session.add(m)
        db.session.commit()
    resp = client.post(
        "/auth/login",
        data={"email": "LEE@example.com", "password": "Member@2026"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/account/")
    assert client.get("/account/").status_code == 200


def test_member_cannot_reach_admin(client, app):
    with app.app_context():
        m = Member(full_name="Lee Member", email="lee@example.com")
        m.set_password("Member@2026")
        db.session.add(m)
        db.session.commit()
    client.post("/auth/login", data={"email": "lee@example.com", "password": "Member@2026"})
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_admin_cannot_reach_member_account(client, app):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="boss", email="boss@example.com")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    client.post("/auth/login", data={"email": "boss@example.com", "password": "Adm@1234"})
    resp = client.get("/account/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/" in resp.headers["Location"]


def test_member_sees_own_registration_and_can_cancel(client, app, sample_event):
    with app.app_context():
        m = Member(full_name="Mira Member", email="mira@example.com")
        m.set_password("Member@2026")
        db.session.add(m)
        db.session.commit()
        reg = register_individual(
            db.session.get(Event, sample_event),
            {"full_name": "Mira Member", "email": "mira@example.com", "phone": "1", "consent": True},
        )
        reg_id = reg.id
    client.post("/auth/login", data={"email": "mira@example.com", "password": "Member@2026"})
    page = client.get("/account/")
    assert page.status_code == 200
    assert b"Testathon" in page.data
    resp = client.post(f"/account/registrations/{reg_id}/cancel", data={})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Registration, reg_id).status == "cancelled"


def test_member_cannot_cancel_someone_elses_registration(client, app, sample_event):
    with app.app_context():
        m = Member(full_name="Mira Member", email="mira@example.com")
        m.set_password("Member@2026")
        db.session.add(m)
        db.session.commit()
        reg = register_individual(
            db.session.get(Event, sample_event),
            {"full_name": "Other Person", "email": "other@example.com", "phone": "1", "consent": True},
        )
        other_id = reg.id
    client.post("/auth/login", data={"email": "mira@example.com", "password": "Member@2026"})
    resp = client.post(f"/account/registrations/{other_id}/cancel", data={})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Registration, other_id).status == "confirmed"


def test_account_requires_login(client):
    resp = client.get("/account/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]
