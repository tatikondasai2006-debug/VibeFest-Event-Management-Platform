import os
import tempfile
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("TESTING", "1")


from app import create_app
from app.extensions import db
from app.models import Event, FestivalSettings, Registration, Team
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


def test_events_list_renders(client):
    resp = client.get("/events")
    assert resp.status_code == 200


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
            a = AdminUser(username="adm")
            a.set_password("Adm@1234")
            db.session.add(a)
            db.session.commit()
    resp = client.post("/auth/login", data={"username": "adm", "password": "Adm@1234"}, follow_redirects=True)
    assert resp.status_code == 200
    resp = client.get("/admin/")
    assert resp.status_code == 200


def test_csv_requires_auth(client):
    resp = client.get("/admin/reports/export")
    assert resp.status_code == 302


def test_csv_export_auth_success(client, app, sample_event):
    from app.models import AdminUser
    with app.app_context():
        a = AdminUser(username="adm2")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    client.post("/auth/login", data={"username": "adm2", "password": "Adm@1234"})
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
        a = AdminUser(username="adm3")
        a.set_password("Adm@1234")
        db.session.add(a)
        db.session.commit()
    client.post("/auth/login", data={"username": "adm3", "password": "Adm@1234"})
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/events").status_code == 200
    assert client.get("/admin/events/new").status_code == 200
    assert client.get("/admin/applicants").status_code == 200
    assert client.get("/admin/analytics").status_code == 200
    assert client.get("/admin/reports").status_code == 200
    assert client.get("/admin/settings").status_code == 200

