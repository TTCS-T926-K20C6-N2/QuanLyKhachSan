"""Focused tests for password recovery routes, tokens, mail, and migration."""

from __future__ import annotations

import re
import smtplib
import sqlite3
from email.message import EmailMessage

import pytest
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import timed as itsdangerous_timed
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from hotel_app import auth_recovery
from hotel_app.app import (
    FORGOT_PASSWORD_MESSAGE,
    INVALID_RESET_TOKEN_MESSAGE,
    create_app,
)
from hotel_app.extensions import db
from hotel_app.models import User, normalize_email


RESET_PASSWORD = "NewPassword123"
DEMO_EMAIL = "demo@example.test"
DEMO_PASSWORD = "Demo1@Hotel2026"


def _csrf_token(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match is not None
    return match.group(1)


def _post_forgot(client, email: str):
    return client.post(
        "/forgot-password",
        data={"csrf_token": _csrf_token(client, "/forgot-password"), "email": email},
        follow_redirects=True,
    )


def _post_reset(client, token: str, password: str, confirmation: str):
    path = f"/reset-password/{token}"
    return client.post(
        path,
        data={
            "csrf_token": _csrf_token(client, path),
            "new_password": password,
            "confirm_password": confirmation,
        },
        follow_redirects=False,
    )


def _new_token(app, email: str = DEMO_EMAIL) -> str:
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == normalize_email(email))
        ).scalar_one()
        return auth_recovery.generate_password_reset_token(
            user, app.config["SECRET_KEY"]
        )


def test_forgot_password_page_and_login_link_render(client):
    forgot = client.get("/forgot-password")
    assert forgot.status_code == 200
    html = forgot.get_data(as_text=True)
    assert 'name="email"' in html
    assert 'autocomplete="email"' in html
    assert 'name="csrf_token"' in html
    assert "Gửi liên kết đặt lại mật khẩu" in html
    assert "Quay lại đăng nhập" in html

    login = client.get("/login").get_data(as_text=True)
    assert 'href="/forgot-password"' in login
    assert 'href="/register"' in login
    assert 'autocomplete="username"' in login
    assert 'autocomplete="current-password"' in login


def test_known_email_is_normalized_versioned_and_mailed(app, client, monkeypatch):
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr("hotel_app.app.send_password_reset_email", fake_send)
    response = _post_forgot(client, f"  {DEMO_EMAIL.upper()}  ")
    assert FORGOT_PASSWORD_MESSAGE in response.get_data(as_text=True)
    assert len(sent) == 1
    assert sent[0]["recipient"] == DEMO_EMAIL
    assert sent[0]["token"]
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        assert user.password_reset_version == 1


def test_known_and_unknown_addresses_have_same_public_response(
    client, monkeypatch
):
    sent = []
    monkeypatch.setattr(
        "hotel_app.app.send_password_reset_email",
        lambda **kwargs: sent.append(kwargs) or True,
    )
    known = _post_forgot(client, DEMO_EMAIL)
    unknown = _post_forgot(client, "not.registered@example.test")
    assert known.status_code == unknown.status_code == 200
    assert known.get_data(as_text=True) == unknown.get_data(as_text=True)
    assert FORGOT_PASSWORD_MESSAGE in known.get_data(as_text=True)
    assert len(sent) == 1


def test_forgot_password_post_requires_csrf(client):
    response = client.post("/forgot-password", data={"email": DEMO_EMAIL})
    assert response.status_code == 400


def test_token_accepts_current_user_and_rejects_tampered_malformed_unknown_and_old(
    app, client
):
    token = _new_token(app)
    valid = client.get(f"/reset-password/{token}")
    assert valid.status_code == 200
    html = valid.get_data(as_text=True)
    assert 'name="new_password"' in html
    assert html.count('autocomplete="new-password"') == 2

    signature_parts = token.split(".")
    first_signature_char = signature_parts[-1][0]
    signature_parts[-1] = (
        ("A" if first_signature_char != "A" else "B")
        + signature_parts[-1][1:]
    )
    tampered_token = ".".join(signature_parts)
    for invalid in (tampered_token, "not-a-token"):
        response = client.get(f"/reset-password/{invalid}")
        assert response.status_code == 400
        assert INVALID_RESET_TOKEN_MESSAGE in response.get_data(as_text=True)

    unknown = URLSafeTimedSerializer(
        app.config["SECRET_KEY"], salt=auth_recovery.RESET_TOKEN_SALT
    ).dumps(
        {"user_id": 999999, "reset_version": 0, "purpose": "password-reset"}
    )
    assert client.get(f"/reset-password/{unknown}").status_code == 400
    malformed_payload = URLSafeTimedSerializer(
        app.config["SECRET_KEY"], salt=auth_recovery.RESET_TOKEN_SALT
    ).dumps({"user_id": 1, "purpose": "password-reset"})
    malformed_response = client.get(
        f"/reset-password/{malformed_payload}"
    )
    assert malformed_response.status_code == 400
    assert INVALID_RESET_TOKEN_MESSAGE in malformed_response.get_data(as_text=True)

    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        user.password_reset_version += 1
        db.session.commit()
    assert client.get(f"/reset-password/{token}").status_code == 400


def test_expired_token_is_rejected_without_waiting(app, client, monkeypatch):
    token = _new_token(app)
    real_time = itsdangerous_timed.time.time
    monkeypatch.setattr(
        itsdangerous_timed.time, "time", lambda: real_time() + 901
    )
    response = client.get(f"/reset-password/{token}")
    assert response.status_code == 400
    assert INVALID_RESET_TOKEN_MESSAGE in response.get_data(as_text=True)


def test_new_reset_request_invalidates_previous_token(
    app, client, monkeypatch
):
    sent = []
    monkeypatch.setattr(
        "hotel_app.app.send_password_reset_email",
        lambda **kwargs: sent.append(kwargs) or True,
    )
    _post_forgot(client, DEMO_EMAIL)
    token_a = sent[-1]["token"]
    _post_forgot(client, DEMO_EMAIL)
    token_b = sent[-1]["token"]
    assert token_a != token_b
    assert client.get(f"/reset-password/{token_a}").status_code == 400
    assert client.get(f"/reset-password/{token_b}").status_code == 200


def test_reset_updates_hash_invalidates_token_and_does_not_auto_login(
    app, client
):
    token = _new_token(app)
    response = _post_reset(client, token, RESET_PASSWORD, RESET_PASSWORD)
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as stored_session:
        assert "user_id" not in stored_session

    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        assert user.password_reset_version == 1
        assert user.password_hash != RESET_PASSWORD
        assert user.password_hash.startswith("scrypt:")
        assert user.check_password(RESET_PASSWORD)

    assert client.get(f"/reset-password/{token}").status_code == 400
    old_login = client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client, "/login"),
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
        },
    )
    assert old_login.status_code == 200
    new_login = client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client, "/login"),
            "email": DEMO_EMAIL,
            "password": RESET_PASSWORD,
        },
    )
    assert new_login.status_code == 302


@pytest.mark.parametrize(
    ("password", "confirmation", "expected_error"),
    [
        ("", "", "Vui lòng nhập mật khẩu mới."),
        ("short", "short", "Mật khẩu phải có ít nhất 8 ký tự."),
        (RESET_PASSWORD, "DifferentPassword", "Mật khẩu xác nhận không khớp."),
    ],
)
def test_reset_validation_does_not_change_password_or_version(
    app, client, password, confirmation, expected_error
):
    token = _new_token(app)
    response = _post_reset(client, token, password, confirmation)
    assert response.status_code == 200
    assert expected_error in response.get_data(as_text=True)
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        assert user.password_reset_version == 0
        assert user.check_password(DEMO_PASSWORD)


def test_reset_post_requires_csrf(client, app):
    token = _new_token(app)
    response = client.post(
        f"/reset-password/{token}",
        data={"new_password": RESET_PASSWORD, "confirm_password": RESET_PASSWORD},
    )
    assert response.status_code == 400


def test_reset_database_failure_rolls_back_password_and_version(
    app, client, monkeypatch
):
    token = _new_token(app)

    def fail_commit():
        raise SQLAlchemyError("injected failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = _post_reset(client, token, RESET_PASSWORD, RESET_PASSWORD)
    assert response.status_code == 503
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        assert user.password_reset_version == 0
        assert user.check_password(DEMO_PASSWORD)


def test_mail_helper_uses_configured_gmail_and_plaintext_content(monkeypatch):
    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.gmail.com"
            assert port == 587
            assert timeout > 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self, context):
            assert context is not None

        def login(self, username, password):
            assert username == "sender@example.test"
            assert password == "fake-test-secret"

        def send_message(self, message: EmailMessage):
            assert message["To"] == "recipient@school.example"
            assert message["Subject"] == "Đặt lại mật khẩu - Hotel Management"
            body = message.get_content()
            assert "15 phút" in body
            assert "http://127.0.0.1:5000/reset-password/" in body
            assert "ignore" not in body.casefold() or "bỏ qua" in body
            assert RESET_PASSWORD not in body

    monkeypatch.setattr(auth_recovery.smtplib, "SMTP", FakeSMTP)
    assert auth_recovery.send_password_reset_email(
        recipient="recipient@school.example",
        token="signed-token",
        config={
            "MAIL_SERVER": "smtp.gmail.com",
            "MAIL_PORT": 587,
            "MAIL_USE_TLS": True,
            "MAIL_USERNAME": "sender@example.test",
            "MAIL_PASSWORD": "fake-test-secret",
            "MAIL_FROM": "sender@example.test",
            "APP_BASE_URL": "http://127.0.0.1:5000",
        },
    )


def test_reset_url_normalizes_base_slashes_and_rejects_unsafe_parts():
    assert auth_recovery._reset_url(
        "signed-token", "https://example.test/hotel///"
    ) == "https://example.test/hotel/reset-password/signed-token"
    for base_url in (
        "https://example.test/path?next=/other",
        "https://example.test/path#fragment",
        "https://user:password@example.test",
        "//example.test/path",
    ):
        with pytest.raises(ValueError):
            auth_recovery._reset_url("signed-token", base_url)


def test_smtp_failure_keeps_generic_response_and_does_not_crash(
    app, client, monkeypatch, caplog
):
    app.config.update(
        MAIL_USERNAME="sender@example.test",
        MAIL_PASSWORD="do-not-log-this-secret",
        MAIL_FROM="sender@example.test",
    )

    def fail_smtp(*_args, **_kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"authentication failed")

    monkeypatch.setattr(auth_recovery.smtplib, "SMTP", fail_smtp)
    known = _post_forgot(client, DEMO_EMAIL)
    unknown = _post_forgot(client, "missing@example.test")
    known_html = known.get_data(as_text=True)
    unknown_html = unknown.get_data(as_text=True)
    assert known.status_code == unknown.status_code == 200
    assert known_html == unknown_html
    assert FORGOT_PASSWORD_MESSAGE in known_html
    assert "do-not-log-this-secret" not in caplog.text
    assert "signed-token" not in caplog.text


def test_missing_mail_credentials_keep_app_and_forgot_flow_available(
    app, client
):
    app.config.update(MAIL_USERNAME="", MAIL_PASSWORD="", MAIL_FROM="")
    response = _post_forgot(client, DEMO_EMAIL)
    assert response.status_code == 200
    assert FORGOT_PASSWORD_MESSAGE in response.get_data(as_text=True)
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        assert user.password_reset_version == 1


def test_mail_failure_keeps_committed_version_and_invalidates_prior_token(
    app, client, monkeypatch
):
    old_token = _new_token(app)
    monkeypatch.setattr(
        "hotel_app.app.send_password_reset_email",
        lambda **_kwargs: False,
    )
    response = _post_forgot(client, DEMO_EMAIL)
    assert FORGOT_PASSWORD_MESSAGE in response.get_data(as_text=True)
    assert client.get(f"/reset-password/{old_token}").status_code == 400
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        assert user.password_reset_version == 1


def test_reset_storage_has_version_but_no_token_field(app):
    with app.app_context():
        columns = {
            column["name"] for column in inspect(db.engine).get_columns("users")
        }
        assert "password_reset_version" in columns
        assert "reset_token" not in columns
        assert "password" not in columns


def test_existing_sqlite_users_are_preserved_and_receive_version_zero(tmp_path):
    database_path = tmp_path / "legacy-auth.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE, "
            "password_hash VARCHAR(255) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
            (41, "legacy@example.test", "scrypt$preserved-hash"),
        )

    legacy_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "legacy-migration-test-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SESSION_COOKIE_SECURE": False,
        }
    )
    with legacy_app.app_context():
        user = db.session.get(User, 41)
        assert user is not None
        assert user.email == "legacy@example.test"
        assert user.password_hash == "scrypt$preserved-hash"
        assert user.password_reset_version == 0
        db.session.remove()
        db.engine.dispose()

    restarted_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "legacy-migration-test-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SESSION_COOKIE_SECURE": False,
        }
    )
    with restarted_app.app_context():
        assert db.session.get(User, 41).password_reset_version == 0
        db.session.remove()
        db.engine.dispose()
