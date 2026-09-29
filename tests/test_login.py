"""Acceptance tests for SCRUM-21 / PB-01 / FR-AUTH-001."""

from __future__ import annotations

import re

from hotel_app.app import (
    DEVELOPMENT_DEMO_EMAIL,
    DEVELOPMENT_DEMO_PASSWORD,
    INVALID_CREDENTIAL_MESSAGE,
    create_app,
)
from hotel_app.extensions import db
from hotel_app.models import User, normalize_email

from conftest import DEMO_EMAIL, DEMO_PASSWORD


def _csrf_token(client) -> str:
    response = client.get("/login")
    assert response.status_code == 200
    match = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"', response.get_data(as_text=True)
    )
    assert match is not None
    return match.group(1)


def _login(client, email: str, password: str):
    return client.post(
        "/login",
        data={
            "csrf_token": _csrf_token(client),
            "email": email,
            "password": password,
        },
        follow_redirects=False,
    )


def test_valid_credentials_create_session_and_redirect_home(client):
    response = _login(client, DEMO_EMAIL, DEMO_PASSWORD)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as stored_session:
        assert isinstance(stored_session["user_id"], int)

    home = client.get("/")
    assert home.status_code == 200
    assert "Đăng nhập thành công" in home.get_data(as_text=True)


def test_wrong_password_returns_generic_error_without_auth_session(client):
    response = _login(client, DEMO_EMAIL, "wrong-password")

    assert response.status_code == 200
    assert INVALID_CREDENTIAL_MESSAGE in response.get_data(as_text=True)
    with client.session_transaction() as stored_session:
        assert "user_id" not in stored_session


def test_unknown_email_uses_same_generic_error(client):
    response = _login(client, "unknown@example.test", DEMO_PASSWORD)

    assert response.status_code == 200
    assert INVALID_CREDENTIAL_MESSAGE in response.get_data(as_text=True)
    with client.session_transaction() as stored_session:
        assert "user_id" not in stored_session


def test_email_leading_and_trailing_whitespace_is_trimmed(client):
    response = _login(client, f"  {DEMO_EMAIL}  ", DEMO_PASSWORD)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_email_comparison_is_case_insensitive(client):
    response = _login(client, DEMO_EMAIL.upper(), DEMO_PASSWORD)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_home_redirects_unauthenticated_user_to_login(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_database_contains_scrypt_hash_not_plaintext(app):
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == normalize_email(DEMO_EMAIL))
        ).scalar_one()

        assert user.password_hash != DEMO_PASSWORD
        assert user.password_hash.startswith("scrypt:")
        assert user.check_password(DEMO_PASSWORD)


def test_authenticated_session_contains_no_password_data(client):
    response = _login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 302

    with client.session_transaction() as stored_session:
        assert "user_id" in stored_session
        assert "email" not in stored_session
        assert "password" not in stored_session
        assert "password_hash" not in stored_session
        assert set(stored_session).issubset({"user_id", "csrf_token", "_permanent"})


def test_user_persists_when_application_is_recreated(tmp_path):
    database_path = tmp_path / "persistent-user.db"
    config = {
        "APP_ENV": "testing",
        "TESTING": True,
        "SECRET_KEY": "persistence-test-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        "SESSION_COOKIE_SECURE": False,
    }

    first_app = create_app(config)
    with first_app.app_context():
        user = User(email=normalize_email(DEMO_EMAIL))
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.commit()
        db.session.remove()
        db.engine.dispose()

    restarted_app = create_app(config)
    with restarted_app.app_context():
        persisted_user = db.session.execute(
            db.select(User).where(User.email == normalize_email(DEMO_EMAIL))
        ).scalar_one()
        assert persisted_user.check_password(DEMO_PASSWORD)
        db.session.remove()
        db.engine.dispose()


def test_fresh_development_database_creates_default_demo_user(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "fresh-development.db"
    for variable_name in (
        "SEED_DEMO_USER",
        "DEMO_USER_EMAIL",
        "DEMO_USER_PASSWORD",
    ):
        monkeypatch.delenv(variable_name, raising=False)

    development_app = create_app(
        {
            "APP_ENV": "development",
            "TESTING": True,
            "SECRET_KEY": "fresh-development-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SESSION_COOKIE_SECURE": False,
        }
    )

    with development_app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEVELOPMENT_DEMO_EMAIL)
        ).scalar_one()

        assert database_path.exists()
        assert user.email == "demo@example.test"
        assert user.password_hash != DEVELOPMENT_DEMO_PASSWORD
        assert user.password_hash.startswith("scrypt:")
        assert user.check_password("Demo1@Hotel2026")
        db.session.remove()
        db.engine.dispose()


def test_development_seed_is_idempotent(tmp_path, monkeypatch):
    database_path = tmp_path / "demo-seed.db"
    for variable_name in (
        "SEED_DEMO_USER",
        "DEMO_USER_EMAIL",
        "DEMO_USER_PASSWORD",
    ):
        monkeypatch.delenv(variable_name, raising=False)

    config = {
        "APP_ENV": "development",
        "TESTING": True,
        "SECRET_KEY": "demo-seed-test-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        "SESSION_COOKIE_SECURE": False,
    }

    seeded_apps = [create_app(config) for _ in range(10)]

    with seeded_apps[-1].app_context():
        users = db.session.execute(db.select(User)).scalars().all()
        assert len(users) == 1
        assert users[0].email == DEVELOPMENT_DEMO_EMAIL
        assert users[0].check_password(DEVELOPMENT_DEMO_PASSWORD)

    for seeded_app in seeded_apps:
        with seeded_app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_testing_environment_does_not_seed_demo_user(tmp_path, monkeypatch):
    database_path = tmp_path / "testing-without-seed.db"
    monkeypatch.setenv("SEED_DEMO_USER", "true")
    monkeypatch.setenv("DEMO_USER_EMAIL", DEVELOPMENT_DEMO_EMAIL)
    monkeypatch.setenv("DEMO_USER_PASSWORD", DEVELOPMENT_DEMO_PASSWORD)

    testing_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "testing-no-seed-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SESSION_COOKIE_SECURE": False,
        }
    )

    with testing_app.app_context():
        assert testing_app.config["SEED_DEMO_USER"] is True
        users = db.session.execute(db.select(User)).scalars().all()
        assert users == []
        db.session.remove()
        db.engine.dispose()


def test_development_demo_seed_can_be_disabled(tmp_path):
    database_path = tmp_path / "development-seed-disabled.db"
    development_app = create_app(
        {
            "APP_ENV": "development",
            "TESTING": True,
            "SECRET_KEY": "development-seed-disabled-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SESSION_COOKIE_SECURE": False,
            "SEED_DEMO_USER": False,
        }
    )

    with development_app.app_context():
        users = db.session.execute(db.select(User)).scalars().all()
        assert users == []
        db.session.remove()
        db.engine.dispose()


def test_login_post_requires_csrf_token(client):
    response = client.post(
        "/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )

    assert response.status_code == 400
    assert "Phiên biểu mẫu không hợp lệ" in response.get_data(as_text=True)
