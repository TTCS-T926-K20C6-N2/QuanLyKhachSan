"""Tests for the approved Register feature and Login integration."""

from __future__ import annotations

import re

import pytest

from hotel_app.app import REGISTER_SUCCESS_MESSAGE, create_app
from hotel_app.extensions import db
from hotel_app.models import User, normalize_email

from conftest import DEMO_EMAIL, DEMO_PASSWORD


REGISTER_PASSWORD = "Register123"


def _csrf_token(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match is not None
    return match.group(1)


def _register(
    client,
    email: str,
    password: str = REGISTER_PASSWORD,
    confirm_password: str = REGISTER_PASSWORD,
    *,
    follow_redirects: bool = False,
):
    return client.post(
        "/register",
        data={
            "csrf_token": _csrf_token(client, "/register"),
            "email": email,
            "password": password,
            "confirm_password": confirm_password,
        },
        follow_redirects=follow_redirects,
    )


def _login(client, email: str, password: str):
    return client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client, "/login"),
            "email": email,
            "password": password,
        },
        follow_redirects=False,
    )


def test_register_get_returns_form(client):
    response = client.get("/register")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="email"' in html
    assert 'name="password"' in html
    assert 'name="confirm_password"' in html
    assert "Đã có tài khoản?" in html


def test_valid_register_creates_user_and_redirects_to_login(app, client):
    email = "new.user@example.test"
    response = _register(client, email, follow_redirects=True)

    assert response.status_code == 200
    assert REGISTER_SUCCESS_MESSAGE in response.get_data(as_text=True)
    with client.session_transaction() as stored_session:
        assert "user_id" not in stored_session
        assert "password" not in stored_session
        assert "confirm_password" not in stored_session
        assert "password_hash" not in stored_session

    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == email)
        ).scalar_one()
        assert user.email == email


def test_newly_registered_user_can_login_with_existing_flow(client):
    email = "login.after.register@example.test"
    register_response = _register(client, email)
    assert register_response.status_code == 302
    assert register_response.headers["Location"].endswith("/login")

    login_response = _login(client, email, REGISTER_PASSWORD)
    assert login_response.status_code == 302
    assert login_response.headers["Location"].endswith("/")


def test_duplicate_email_is_rejected(app, client):
    response = _register(client, DEMO_EMAIL, DEMO_PASSWORD, DEMO_PASSWORD)

    assert response.status_code == 200
    assert "Email đã được sử dụng" in response.get_data(as_text=True)
    with app.app_context():
        users = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalars().all()
        assert len(users) == 1


def test_case_insensitive_duplicate_email_is_rejected(app, client):
    response = _register(
        client,
        f"  {DEMO_EMAIL.upper()}  ",
        DEMO_PASSWORD,
        DEMO_PASSWORD,
    )

    assert response.status_code == 200
    assert "Email đã được sử dụng" in response.get_data(as_text=True)
    with app.app_context():
        users = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalars().all()
        assert len(users) == 1


def test_register_normalizes_email_whitespace_and_case(app, client):
    response = _register(client, "  New.Account@Example.TEST  ")
    assert response.status_code == 302

    with app.app_context():
        user = db.session.execute(
            db.select(User).where(
                User.email == normalize_email("New.Account@Example.TEST")
            )
        ).scalar_one()
        assert user.email == "new.account@example.test"


def test_register_rejects_password_shorter_than_eight_characters(app, client):
    email = "short.password@example.test"
    response = _register(client, email, "short7", "short7")

    assert response.status_code == 200
    assert "Mật khẩu phải có ít nhất 8 ký tự" in response.get_data(as_text=True)
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == email)
        ).scalar_one_or_none()
        assert user is None


def test_register_rejects_mismatched_password_confirmation(app, client):
    email = "password.mismatch@example.test"
    response = _register(client, email, REGISTER_PASSWORD, "Different123")

    assert response.status_code == 200
    assert "Mật khẩu xác nhận không khớp" in response.get_data(as_text=True)
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == email)
        ).scalar_one_or_none()
        assert user is None


def test_register_stores_scrypt_hash_not_plaintext(app, client):
    email = "hashed.password@example.test"
    response = _register(client, email)
    assert response.status_code == 302

    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == email)
        ).scalar_one()
        assert user.password_hash != REGISTER_PASSWORD
        assert user.password_hash.startswith("scrypt:")
        assert user.check_password(REGISTER_PASSWORD)


@pytest.mark.parametrize("csrf_token", [None, "invalid-token"])
def test_register_rejects_missing_or_invalid_csrf(app, client, csrf_token):
    email = "csrf.rejected@example.test"
    data = {
        "email": email,
        "password": REGISTER_PASSWORD,
        "confirm_password": REGISTER_PASSWORD,
    }
    if csrf_token is not None:
        data["csrf_token"] = csrf_token

    response = client.post("/register", data=data)

    assert response.status_code == 400
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == email)
        ).scalar_one_or_none()
        assert user is None


def test_registered_user_persists_after_application_restart(tmp_path):
    database_path = tmp_path / "register-persistence.db"
    config = {
        "APP_ENV": "testing",
        "TESTING": True,
        "SECRET_KEY": "register-persistence-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        "SESSION_COOKIE_SECURE": False,
    }
    email = "persistent.register@example.test"

    first_app = create_app(config)
    first_client = first_app.test_client()
    response = _register(first_client, email)
    assert response.status_code == 302

    with first_app.app_context():
        db.session.remove()
        db.engine.dispose()

    restarted_app = create_app(config)
    with restarted_app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == email)
        ).scalar_one()
        assert user.check_password(REGISTER_PASSWORD)
        db.session.remove()
        db.engine.dispose()
