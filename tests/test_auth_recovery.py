"""Focused OTP recovery, migration, and mocked Brevo tests."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.request import Request

import pytest
from sqlalchemy import inspect

from hotel_app import app as app_module
from hotel_app import auth_recovery
from hotel_app.app import FORGOT_PASSWORD_MESSAGE, create_app
from hotel_app.extensions import db
from hotel_app.models import PasswordResetChallenge, Room, RoomRental, RoomType, User


DEMO_EMAIL = "demo@example.test"
DEMO_PASSWORD = "Demo1@Hotel2026"
NEW_PASSWORD = "NewPassword123"


def _csrf(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.get_data(as_text=True))
    assert match
    return match.group(1)


def _post(client, path: str, data: dict | None = None, follow_redirects=True):
    values = dict(data or {})
    csrf_path = "/verify-reset-code" if path == "/resend-reset-code" else path
    values["csrf_token"] = _csrf(client, csrf_path)
    return client.post(path, data=values, follow_redirects=follow_redirects)


@pytest.fixture
def sent_messages(monkeypatch):
    messages = []

    def fake_send(recipient, otp, config):
        messages.append((recipient, otp))
        return True

    monkeypatch.setattr("hotel_app.app.send_password_reset_otp", fake_send)
    return messages


def _request_code(client, email=DEMO_EMAIL):
    return _post(client, "/forgot-password", {"email": email})


def _verify(client, code):
    return _post(client, "/verify-reset-code", {"otp": code}, False)


def _challenge(app, client):
    with client.session_transaction() as stored:
        challenge_id = stored.get("password_reset_challenge_id")
    if challenge_id is None:
        return None
    with app.app_context():
        return db.session.get(PasswordResetChallenge, challenge_id)


def _reset(client, password=NEW_PASSWORD, confirmation=NEW_PASSWORD):
    return _post(
        client,
        "/reset-password",
        {"new_password": password, "confirm_password": confirmation},
        False,
    )


def _verified(client, messages):
    _request_code(client)
    assert messages
    return _verify(client, messages[-1][1])


def test_forgot_login_verify_ui_and_no_legacy_route(client):
    forgot = client.get("/forgot-password")
    assert forgot.status_code == 200
    assert "Gửi mã xác nhận" in forgot.get_data(as_text=True)
    login = client.get("/login").get_data(as_text=True)
    assert 'href="/forgot-password"' in login
    assert client.get("/verify-reset-code").status_code == 200
    assert client.get("/reset-password/anything").status_code == 404


def test_forgot_post_requires_csrf(client):
    assert client.post("/forgot-password", data={"email": DEMO_EMAIL}).status_code == 400


def test_known_email_normalizes_and_issues_otp(app, client, sent_messages):
    response = _request_code(client, f"  {DEMO_EMAIL.upper()}  ")
    assert response.status_code == 200
    assert FORGOT_PASSWORD_MESSAGE in response.get_data(as_text=True)
    assert sent_messages[0][0] == DEMO_EMAIL
    assert re.fullmatch(r"[0-9]{6}", sent_messages[0][1])
    challenge = _challenge(app, client)
    assert challenge.delivery_status == "sent"
    assert sent_messages[0][1] not in challenge.otp_digest
    with app.app_context():
        user = db.session.execute(db.select(User).where(User.email == DEMO_EMAIL)).scalar_one()
        assert user.password_reset_version == 1


def test_known_unknown_and_cooldown_public_flow_equivalent(client, sent_messages):
    known = _request_code(client, DEMO_EMAIL)
    unknown = _request_code(client, "nobody@example.test")
    assert known.status_code == unknown.status_code == 200
    assert "verify-reset-code" in known.request.path
    assert known.get_data(as_text=True) == unknown.get_data(as_text=True)
    assert len(sent_messages) == 1


def test_unknown_creates_no_challenge_or_provider_call(app, client, sent_messages):
    _request_code(client, "missing@example.test")
    assert sent_messages == []
    with app.app_context():
        assert db.session.execute(db.select(PasswordResetChallenge)).scalars().all() == []


@pytest.mark.parametrize("value", [1, 41928, 999999])
def test_secure_generator_formats_six_digits(monkeypatch, value):
    monkeypatch.setattr(auth_recovery.secrets, "randbelow", lambda upper: value)
    assert auth_recovery.generate_otp() == f"{value:06d}"


def test_hmac_digest_binds_challenge_user_and_generation():
    digest = auth_recovery.otp_digest("secret", 2, 5, 8, "000001")
    assert auth_recovery.otp_matches(digest, "secret", 2, 5, 8, "000001")
    assert not auth_recovery.otp_matches(digest, "secret", 3, 5, 8, "000001")
    assert not auth_recovery.otp_matches(digest, "secret", 2, 6, 8, "000001")
    assert not auth_recovery.otp_matches(digest, "secret", 2, 5, 9, "000001")


def test_leading_zero_code_verifies(app, client, sent_messages, monkeypatch):
    monkeypatch.setattr(auth_recovery.secrets, "randbelow", lambda _upper: 1)
    _request_code(client)
    assert sent_messages[-1][1] == "000001"
    assert _verify(client, "000001").status_code == 303
    assert client.get("/reset-password").status_code == 200


def test_wrong_code_counts_and_fifth_locks(app, client, sent_messages):
    _request_code(client)
    for attempt in range(1, 6):
        response = _verify(client, "999999")
        assert response.status_code == 200
        assert "không hợp lệ hoặc đã hết hạn" in response.get_data(as_text=True)
        assert _challenge(app, client).failed_attempts == attempt
    assert _verify(client, sent_messages[-1][1]).status_code == 200


def test_malformed_code_counts_as_wrong(app, client, sent_messages):
    _request_code(client)
    _verify(client, "١٢٣٤٥٦")
    assert _challenge(app, client).failed_attempts == 1


def test_otp_expiry_and_authorization_expiry(app, client, sent_messages, monkeypatch):
    now = app_module._utc_now()
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now)
    _request_code(client)
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now + timedelta(minutes=5))
    assert _verify(client, sent_messages[-1][1]).status_code == 200
    assert client.get("/reset-password").status_code == 303

    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now)
    _request_code(client)
    _verify(client, sent_messages[-1][1])
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now + timedelta(minutes=10))
    assert client.get("/reset-password").status_code == 303


def test_new_challenge_invalidates_older_generation(app, client, sent_messages, monkeypatch):
    _request_code(client)
    old_code = sent_messages[-1][1]
    later = app_module._utc_now() + timedelta(seconds=61)
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: later)
    _request_code(client)
    assert len(sent_messages) == 2
    assert _verify(client, old_code).status_code == 200
    assert _challenge(app, client).reset_version == 2


def test_cooldown_and_send_limit_include_failed_delivery(app, client, monkeypatch):
    sends = []
    monkeypatch.setattr("hotel_app.app.send_password_reset_otp", lambda *_args: sends.append(1) or False)
    now = app_module._utc_now()
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now)
    for _ in range(5):
        _request_code(client)
        monkeypatch.setattr("hotel_app.app._utc_now", lambda now=now: now + timedelta(seconds=61))
        now += timedelta(seconds=61)
    assert len(sends) == 5
    _request_code(client)
    assert len(sends) == 5
    with app.app_context():
        assert len(db.session.execute(db.select(PasswordResetChallenge)).scalars().all()) == 5


def test_exact_cooldown_and_15_minute_boundary_are_allowed(
    app, client, monkeypatch
):
    sends = []
    monkeypatch.setattr(
        "hotel_app.app.send_password_reset_otp",
        lambda *_args: sends.append(1) or False,
    )
    now = app_module._utc_now()
    first_attempt_at = now
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now)
    for _ in range(5):
        _request_code(client)
        now += timedelta(seconds=60)
        monkeypatch.setattr("hotel_app.app._utc_now", lambda now=now: now)
    assert len(sends) == 5
    now = first_attempt_at + timedelta(minutes=15)
    monkeypatch.setattr("hotel_app.app._utc_now", lambda: now)
    _request_code(client)
    assert len(sends) == 6


def test_provider_failure_persists_failed_and_is_not_usable(app, client, monkeypatch):
    monkeypatch.setattr("hotel_app.app.send_password_reset_otp", lambda *_args: False)
    response = _request_code(client)
    assert response.status_code == 200
    challenge = _challenge(app, client)
    assert challenge.delivery_status == "failed"
    assert _verify(client, "123456").status_code == 200
    assert _challenge(app, client).failed_attempts == 0


def test_verify_requires_csrf(client, sent_messages):
    _request_code(client)
    assert client.post("/verify-reset-code", data={"otp": "123456"}).status_code == 400


def test_success_verification_is_one_time_and_otp_not_in_session(app, client, sent_messages):
    _request_code(client)
    code = sent_messages[-1][1]
    assert _verify(client, code).status_code == 303
    with client.session_transaction() as stored:
        assert isinstance(stored["password_reset_challenge_id"], int)
        assert code not in repr(dict(stored))
    assert _challenge(app, client).verified_at is not None
    assert _verify(client, code).status_code == 200


def test_reset_requires_verification_and_csrf(client):
    assert client.get("/reset-password").status_code == 303
    assert client.post("/reset-password", data={}).status_code == 400


def test_password_validation_and_success_reset(app, client, sent_messages):
    _verified(client, sent_messages)
    assert _reset(client, "short", "short").status_code == 200
    assert _reset(client, NEW_PASSWORD, "different").status_code == 200
    success = _reset(client)
    assert success.status_code == 303
    assert success.headers["Location"].endswith("/login")
    with client.session_transaction() as stored:
        assert "user_id" not in stored
        assert "password_reset_challenge_id" not in stored
    with app.app_context():
        user = db.session.execute(db.select(User).where(User.email == DEMO_EMAIL)).scalar_one()
        assert user.check_password(NEW_PASSWORD)
        assert not user.check_password(DEMO_PASSWORD)
        challenge = db.session.execute(db.select(PasswordResetChallenge)).scalar_one()
        assert challenge.consumed_at is not None
        assert user.password_reset_version == 2


def test_reset_db_failure_rolls_back_password_and_consumption(app, client, sent_messages, monkeypatch):
    _verified(client, sent_messages)
    original_commit = db.session.commit
    calls = 0

    def fail_commit():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise app_module.SQLAlchemyError("hidden database detail")
        return original_commit()

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = _reset(client)
    assert response.status_code == 503
    with app.app_context():
        user = db.session.execute(db.select(User).where(User.email == DEMO_EMAIL)).scalar_one()
        challenge = db.session.execute(db.select(PasswordResetChallenge)).scalar_one()
        assert user.check_password(DEMO_PASSWORD)
        assert challenge.consumed_at is None


def test_resend_csrf_cooldown_and_generic_redirect(app, client, sent_messages):
    _request_code(client)
    before = len(sent_messages)
    response = _post(client, "/resend-reset-code", follow_redirects=True)
    assert response.status_code == 200
    assert len(sent_messages) == before
    assert FORGOT_PASSWORD_MESSAGE in response.get_data(as_text=True)
    assert client.post("/resend-reset-code").status_code == 400


def test_brevo_adapter_endpoint_headers_sender_and_body(monkeypatch):
    captured = {}

    class Response:
        status = 201
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(auth_recovery, "urlopen", fake_urlopen)
    assert auth_recovery.send_password_reset_otp("user@school.example", "000123", {
        "EMAIL_PROVIDER": "brevo", "BREVO_API_KEY": "fake-test-key",
        "MAIL_FROM": "verified@example.test", "MAIL_FROM_NAME": "Hotel Management",
    })
    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == "https://api.brevo.com/v3/smtp/email"
    assert request.get_header("Api-key") == "fake-test-key"
    payload = json.loads(request.data)
    assert payload["sender"]["email"] == "verified@example.test"
    assert payload["to"] == [{"email": "user@school.example"}]
    assert "000123" in payload["textContent"]
    assert captured["timeout"] > 0


def test_brevo_error_is_safe_and_does_not_log_secrets(monkeypatch, caplog):
    def fail(*_args, **_kwargs):
        raise OSError("fake-test-key secret response body")
    monkeypatch.setattr(auth_recovery, "urlopen", fail)
    assert not auth_recovery.send_password_reset_otp("user@example.test", "654321", {
        "EMAIL_PROVIDER": "brevo", "BREVO_API_KEY": "fake-test-key",
        "MAIL_FROM": "sender@example.test",
    })
    assert "fake-test-key" not in caplog.text
    assert "654321" not in caplog.text
    assert "secret response body" not in caplog.text


def test_additive_migration_preserves_legacy_users(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL)")
        connection.execute("INSERT INTO users (id,email,password_hash) VALUES (17,'old@example.test','preserved-hash')")
    migrated = create_app({
        "APP_ENV": "testing", "TESTING": True, "SECRET_KEY": "migration-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path.as_posix()}",
        "SESSION_COOKIE_SECURE": False,
    })
    with migrated.app_context():
        user = db.session.get(User, 17)
        assert user.email == "old@example.test"
        assert user.password_hash == "preserved-hash"
        assert user.password_reset_version == 0
        assert "password_reset_challenges" in inspect(db.engine).get_table_names()
        room = Room(number="990", floor="Test", type="Legacy", status="Occupied")
        db.session.add(room)
        db.session.add(RoomType(name="Legacy", price=1))
        db.session.commit()
        db.session.add(RoomRental(
            room_id=room.id,
            room_number=room.number,
            rented_at=datetime.now(timezone.utc).replace(tzinfo=None),
            expected_checkout=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
            duration_minutes=1440,
            nightly_rate=1,
            total_price=1,
        ))
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
    restarted = create_app({
        "APP_ENV": "testing", "TESTING": True, "SECRET_KEY": "migration-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path.as_posix()}",
        "SESSION_COOKIE_SECURE": False,
    })
    with restarted.app_context():
        assert db.session.get(User, 17).password_hash == "preserved-hash"
        preserved_room = db.session.execute(db.select(Room).where(Room.number == "990")).scalar_one()
        assert preserved_room.number == "990"
        assert preserved_room.status == "Occupied"
        assert db.session.execute(db.select(RoomType).where(RoomType.name == "Legacy")).scalar_one().name == "Legacy"
        assert db.session.execute(db.select(RoomRental).where(RoomRental.room_number == "990")).scalar_one().total_price == 1
        db.session.remove()
        db.engine.dispose()


def test_example_config_has_no_credentials_and_no_legacy_settings():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    example = (root / ".env.example").read_text(encoding="utf-8")
    assert "EMAIL_PROVIDER=brevo" in example
    assert "BREVO_API_KEY=" in example
    assert "APP_BASE_URL" not in example
    assert "MAIL_PASSWORD" not in example
