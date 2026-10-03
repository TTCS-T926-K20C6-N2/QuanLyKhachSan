"""Shared, isolated Flask test setup for the Login slice."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

os.environ["APP_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-only-secret-key"

from hotel_app.app import create_app  # noqa: E402
from hotel_app.extensions import db  # noqa: E402
from hotel_app.models import User, normalize_email  # noqa: E402


DEMO_EMAIL = "demo@example.test"
DEMO_PASSWORD = "Demo1@Hotel2026"


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "login-tests.db"
    test_app = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": "test-only-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SESSION_COOKIE_SECURE": False,
        }
    )

    with test_app.app_context():
        user = User(email=normalize_email(DEMO_EMAIL))
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.commit()

    yield test_app

    with test_app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()

